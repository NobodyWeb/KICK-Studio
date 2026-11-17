"""Automatic live recording scheduler."""

from __future__ import annotations

import threading
import time
import uuid

from .config import AppConfig, normalize_output, normalize_source
from .kick import KickClient, KickError
from .recorder import SessionManager
from .util import classify_url, format_seconds


class AutoRecorder:
    def __init__(self, config: AppConfig, kick: KickClient, sessions: SessionManager, log):
        self.config = config
        self.kick = kick
        self.sessions = sessions
        self.log = log
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._status: dict[str, dict] = {}
        self._last_start: dict[str, float] = {}
        self._dismissed: dict[str, str] = {}
        self.last_scan: float = 0.0
        self.next_scan: float = 0.0
        self.scanning: bool = False
        self.error: str = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auto-recorder")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.config.get("auto_enabled", True):
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            try:
                self._scan_once()
            except Exception as exc:
                self.error = getattr(exc, "message", str(exc))
                self.log.error(f"Auto recorder scan failed: {self.error}", "auto")
            interval = max(10, int(self.config.get("poll_interval") or 25))
            self.next_scan = time.time() + interval
            self._wake.wait(interval)
            self._wake.clear()

    def _scan_once(self) -> None:
        self.scanning = True
        self.error = ""
        streamers = [s for s in self.config.get("auto_streamers", []) if s.get("enabled")]
        try:
            for streamer in streamers:
                if self._stop.is_set():
                    return
                self._check_streamer(streamer)
        finally:
            self.last_scan = time.time()
            self.scanning = False
            self._wake.clear()

    def _check_streamer(self, streamer: dict) -> None:
        auto_id = str(streamer.get("id") or streamer.get("slug"))
        slug = str(streamer.get("slug") or "").lower()
        if not slug:
            return
        status = {
            "checked_at": time.time(),
            "live": False,
            "title": "",
            "viewers": 0,
            "error": "",
            "session_state": "",
            "session_id": "",
            "recording": False,
        }
        try:
            channel = self.kick.channel(slug, fresh=True)
            status.update(
                {
                    "live": bool(channel.get("live")),
                    "title": channel.get("title") or "",
                    "viewers": int(channel.get("viewers") or 0),
                    "session_id": channel.get("session_id") or "",
                    "avatar": channel.get("avatar") or streamer.get("avatar") or "",
                    "name": channel.get("username") or streamer.get("name") or slug,
                    "started_at": channel.get("started_at") or "",
                    "started_ts": channel.get("started_ts"),
                }
            )
            active = self.sessions.active_for_auto(auto_id)
            current_key = str(channel.get("session_id") or channel.get("started_at") or "")
            if active:
                status["recording"] = active.state in {"resolving", "recording", "waiting", "finalizing"}
                status["session_state"] = active.state
                status["session_id"] = active.id
                if channel.get("live"):
                    active.note_live(channel)
                    if active.session_key and current_key and current_key != active.session_key:
                        self.log.info(
                            f"New live session detected for {slug}; closing previous recording.",
                            "auto",
                        )
                        self.sessions.stop(active.id)
                    else:
                        status["recording"] = True
                else:
                    status["recording"] = active.state in {"recording", "waiting"}
            elif not channel.get("live"):
                # The stream ended, so a future broadcast may be recorded even
                # if the user had stopped the previous session manually.
                self._dismissed.pop(auto_id, None)
            elif channel.get("live"):
                if current_key and self._dismissed.get(auto_id) == current_key:
                    status["dismissed"] = True
                    return
                max_active = max(1, int(self.config.get("max_auto_recordings") or 3))
                if self.sessions.count_active(auto_only=True) >= max_active:
                    status["waiting_slot"] = True
                    return
                last_start = self._last_start.get(auto_id, 0)
                if time.time() - last_start < 12:
                    return
                self._last_start[auto_id] = time.time()
                folder = str(streamer.get("folder") or "").strip() or str(self.config.get("download_dir") or "")
                self.log.info(f"Auto recording started: {slug}", "auto")
                try:
                    session = self.sessions.start_live(
                        slug,
                        source=streamer.get("source") or self.config.get("default_source"),
                        profile=streamer.get("output") or self.config.get("default_output"),
                        folder=folder,
                        from_start=True,
                        auto_id=auto_id,
                        session_key=str(channel.get("session_id") or channel.get("started_at") or ""),
                        title=channel.get("title") or "",
                    )
                    status["recording"] = True
                    status["session_state"] = session.get("state", "")
                    status["session_id"] = session.get("id", "")
                    self._dismissed.pop(auto_id, None)
                except KickError as exc:
                    status["error"] = exc.message
                    self.log.warn(f"Auto start failed for {slug}: {exc.message}", "auto")
                except Exception as exc:
                    status["error"] = str(exc)
                    self.log.error(f"Auto start failed for {slug}: {exc}", "auto")
        except KickError as exc:
            status["error"] = exc.message
            if exc.code not in {"network_error"}:
                self.log.warn(f"Auto check failed for {slug}: {exc.message}", "auto")
        except Exception as exc:
            status["error"] = str(exc)
            self.log.error(f"Auto check failed for {slug}: {exc}", "auto")
        finally:
            with self._lock:
                self._status[auto_id] = status

    def add(self, url: str, *, source: dict, output: dict, folder: str = "") -> dict:
        info = classify_url(url)
        if info.get("type") != "channel":
            raise KickError("برای ضبط خودکار یک لینک کانال Kick وارد کنید.", "bad_channel")
        slug = info["slug"]
        streamers = self.config.get("auto_streamers", [])
        if any(str(s.get("slug")).lower() == slug for s in streamers):
            raise KickError(f"کانال «{slug}» قبلاً به فهرست اضافه شده است.", "duplicate")
        channel = self.kick.channel(slug, fresh=True)
        item = {
            "id": uuid.uuid4().hex[:10],
            "slug": slug,
            "name": channel.get("username") or slug,
            "avatar": channel.get("avatar") or "",
            "enabled": True,
            "source": normalize_source(source),
            "output": normalize_output(output),
            "folder": str(folder or "").strip(),
            "added_at": time.time(),
        }
        streamers.append(item)
        self.config.set_streamers(streamers)
        self.log.success(f"Added to auto recorder: {item['name']} ({slug})", "auto")
        self.wake()
        return item

    def update(self, auto_id: str, patch: dict) -> dict:
        streamers = self.config.get("auto_streamers", [])
        found = None
        for streamer in streamers:
            if str(streamer.get("id")) == str(auto_id):
                found = streamer
                break
        if not found:
            raise KickError("استریمر در فهرست پیدا نشد.", "not_found")
        if "enabled" in patch:
            found["enabled"] = bool(patch["enabled"])
        if "source" in patch:
            found["source"] = normalize_source(patch["source"])
        if "output" in patch:
            found["output"] = normalize_output(patch["output"])
        if "folder" in patch:
            found["folder"] = str(patch.get("folder") or "").strip()
        if "name" in patch and patch.get("name"):
            found["name"] = str(patch["name"])
        self.config.set_streamers(streamers)
        if not found.get("enabled", True):
            self.sessions.stop_auto(auto_id)
        self.wake()
        return found

    def remove(self, auto_id: str) -> None:
        self.sessions.stop_auto(auto_id)
        streamers = [s for s in self.config.get("auto_streamers", []) if str(s.get("id")) != str(auto_id)]
        self.config.set_streamers(streamers)
        with self._lock:
            self._status.pop(auto_id, None)
        self.log.info(f"Removed auto recorder entry: {auto_id}", "auto")
        self.wake()

    def set_enabled(self, enabled: bool) -> None:
        self.config.update({"auto_enabled": bool(enabled)})
        self.log.info(f"Auto recorder {'enabled' if enabled else 'disabled'}.", "auto")
        self.wake()

    def dismiss(self, auto_id: str, session_key: str = "") -> None:
        """Remember a manually stopped session so auto mode does not restart it."""
        if not auto_id:
            return
        with self._lock:
            self._dismissed[str(auto_id)] = str(session_key or "")
        self._last_start.pop(str(auto_id), None)

    def restart(self, auto_id: str) -> None:
        """Forget a manual stop so the next check records the stream again from the start."""
        auto_id = str(auto_id or "")
        if not auto_id:
            raise KickError("شناسه استریمر نامعتبر است.", "bad_request")
        streamers = self.config.get("auto_streamers", [])
        if not any(str(s.get("id")) == auto_id for s in streamers):
            raise KickError("استریمر در فهرست پیدا نشد.", "not_found")
        with self._lock:
            self._dismissed.pop(auto_id, None)
            self._status.pop(auto_id, None)
        self._last_start.pop(auto_id, None)
        self.log.info(f"Auto recording restarted by request: {auto_id}", "auto")
        self.wake()

    def check_now(self) -> None:
        self.wake()

    def snapshot(self) -> dict:
        streamers = self.config.get("auto_streamers", [])
        with self._lock:
            statuses = dict(self._status)
        items = []
        for streamer in streamers:
            auto_id = str(streamer.get("id"))
            status = dict(statuses.get(auto_id, {}))
            active = self.sessions.active_for_auto(auto_id)
            if active:
                status["recording"] = active.state in {"resolving", "recording", "waiting"}
                status["session_state"] = active.state
                status["session_id"] = active.id
                status["media_seconds"] = active.total_media_seconds
            items.append(
                {
                    **streamer,
                    "status": status,
                }
            )
        enabled = self.config.get("auto_enabled", True)
        return {
            "enabled": bool(enabled),
            "running": bool(self._thread and self._thread.is_alive()),
            "scanning": self.scanning,
            "last_scan": self.last_scan,
            "next_scan": self.next_scan,
            "error": self.error,
            "active": self.sessions.count_active(auto_only=True),
            "max_active": int(self.config.get("max_auto_recordings") or 3),
            "poll_interval": int(self.config.get("poll_interval") or 25),
            "session_gap": int(self.config.get("session_gap") or 90),
            "streamers": items,
            "activity": _recent_activity(self.log),
        }


def _recent_activity(log, limit: int = 30) -> list[dict]:
    entries = log.tail(300)
    return [e for e in entries if e.get("source", "").startswith("auto")][-limit:]
