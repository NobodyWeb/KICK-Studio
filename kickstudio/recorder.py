"""Recording sessions and download jobs."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from .config import AppConfig, normalize_output, normalize_source
from .kick import KickClient, KickError
from .media import (
    build_record_command,
    concat_parts,
    ffprobe_duration,
    finalize_file,
    parse_progress_line,
    progress_seconds,
    summary_profile,
)
from .tools import Toolchain
from .util import (
    TEMP_DIR,
    classify_url,
    format_bytes,
    format_seconds,
    safe_filename,
    unique_path,
)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
ACTIVE_SESSION_STATES = {"resolving", "recording", "waiting", "finalizing"}
ACTIVE_DOWNLOAD_STATES = {"queued", "resolving", "running", "stopping", "finalizing"}


class FfmpegRunner:
    """Run one FFmpeg process and expose progress in a thread-safe way."""

    def __init__(self, args: list[str], temp_path: Path | str, log, source: str = "ffmpeg"):
        self.args = list(args)
        self.temp_path = Path(temp_path)
        self.log = log
        self.source = source
        self.proc: subprocess.Popen | None = None
        self.returncode: int | None = None
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.stderr_tail: deque[str] = deque(maxlen=60)
        self.progress: dict = {
            "media_seconds": 0.0,
            "size": 0,
            "total_size": 0,
            "bitrate": "",
            "speed": "",
            "fps": "",
            "frame": "",
            "out_time": "",
        }
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._stop_requested = False
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._waiter_thread: threading.Thread | None = None
        self._stdin = None
        self._log_counter = 0

    def start(self) -> None:
        self.started_at = time.time()
        self.temp_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.proc = subprocess.Popen(
                self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            self.returncode = -1
            self._done.set()
            raise RuntimeError("ffmpeg executable was not found.") from exc
        self._stdin = self.proc.stdin
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True, name="ffmpeg-stdout")
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True, name="ffmpeg-stderr")
        self._waiter_thread = threading.Thread(target=self._wait_worker, daemon=True, name="ffmpeg-waiter")
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._waiter_thread.start()

    def _read_stdout(self) -> None:
        stream = self.proc.stdout if self.proc else None
        if not stream:
            return
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                parsed = parse_progress_line(line)
                if not parsed:
                    continue
                key, value = parsed
                with self._lock:
                    if key == "out_time":
                        self.progress["out_time"] = value
                        seconds = progress_seconds(value)
                        if seconds > 0:
                            self.progress["media_seconds"] = max(self.progress["media_seconds"], seconds)
                    elif key in ("out_time_ms", "out_time_us"):
                        try:
                            seconds = float(value) / 1_000_000.0
                            if seconds > 0:
                                self.progress["media_seconds"] = max(self.progress["media_seconds"], seconds)
                        except ValueError:
                            pass
                    elif key in ("total_size", "size"):
                        try:
                            self.progress["total_size"] = int(value)
                        except ValueError:
                            pass
                    elif key in ("bitrate", "speed", "fps", "frame"):
                        self.progress[key] = value
        except Exception:
            pass

    def _read_stderr(self) -> None:
        stream = self.proc.stderr if self.proc else None
        if not stream:
            return
        started = time.time()
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                with self._lock:
                    self.stderr_tail.append(line)
                    self._log_counter += 1
                    should_log = self._log_counter <= 20 or self._log_counter % 80 == 0
                lowered = line.lower()
                if any(word in lowered for word in ("error", "failed", "forbidden", "404", "403", "invalid")):
                    self.log.warn(line[:500], self.source)
                elif should_log and time.time() - started < 20:
                    self.log.info(line[:500], self.source)
        except Exception:
            pass

    def _wait_worker(self) -> None:
        if self.proc:
            try:
                self.returncode = self.proc.wait()
            except Exception:
                self.returncode = -1
        self.ended_at = time.time()
        if self._stdout_thread:
            self._stdout_thread.join(timeout=3)
        if self._stderr_thread:
            self._stderr_thread.join(timeout=3)
        with self._lock:
            try:
                if self.temp_path.exists():
                    self.progress["size"] = self.temp_path.stat().st_size
            except OSError:
                pass
        self._done.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def stop(self, grace: float = 12.0) -> None:
        with self._lock:
            self._stop_requested = True
        proc = self.proc
        if not proc:
            return
        try:
            if proc.poll() is None and self._stdin:
                try:
                    self._stdin.write(b"q\n")
                    self._stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=grace)
                    return
                except subprocess.TimeoutExpired:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                    return
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            self._done.wait(timeout=3)

    def snapshot(self) -> dict:
        with self._lock:
            progress = dict(self.progress)
            stderr = list(self.stderr_tail)[-8:]
            stop_requested = self._stop_requested
        try:
            file_size = self.temp_path.stat().st_size if self.temp_path.exists() else 0
        except OSError:
            file_size = 0
        if file_size:
            progress["size"] = file_size
        return {
            "media_seconds": progress.get("media_seconds", 0),
            "size": progress.get("size", 0),
            "total_size": progress.get("total_size", 0),
            "bitrate": progress.get("bitrate", ""),
            "speed": progress.get("speed", ""),
            "fps": progress.get("fps", ""),
            "frame": progress.get("frame", ""),
            "elapsed": max(0.0, (self.ended_at or time.time()) - (self.started_at or time.time())),
            "running": bool(self.proc and self.proc.poll() is None),
            "returncode": self.returncode,
            "stop_requested": stop_requested,
            "stderr": stderr,
        }


class DownloadJob:
    def __init__(self, job_id: str, url: str, *, source: dict, profile: dict, folder: str, title: str = "", kind: str = ""):
        self.id = job_id
        self.url = url.strip()
        self.source = normalize_source(source)
        self.profile = normalize_output(profile)
        self.folder = Path(folder)
        self.requested_title = title.strip()
        self.requested_kind = kind
        self.kind = kind or "media"
        self.title = title or self.url
        self.channel = ""
        self.state = "queued"
        self.error = ""
        self.created_at = time.time()
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.runner: FfmpegRunner | None = None
        self.stop_requested = False
        self.output_path: Path | None = None
        self.temp_path: Path | None = None
        self.resolved: dict | None = None
        self.log_tail: deque[str] = deque(maxlen=40)
        self.logger = None
        self._lock = threading.RLock()

    def add_log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self.log_tail.append(f"{time.strftime('%H:%M:%S')} {message}")
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message, f"download:{self.kind}")

    def snapshot(self) -> dict:
        with self._lock:
            runner = self.runner.snapshot() if self.runner else {}
            state = self.state
            elapsed = max(0.0, (self.ended_at or time.time()) - (self.started_at or self.created_at))
            return {
                "id": self.id,
                "kind": self.kind,
                "title": self.title,
                "channel": self.channel,
                "url": self.url,
                "state": state,
                "error": self.error,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "elapsed": elapsed,
                "media_seconds": runner.get("media_seconds", 0),
                "size": runner.get("size", 0),
                "duration": int((self.resolved or {}).get("duration") or 0),
                "bitrate": runner.get("bitrate", ""),
                "speed": runner.get("speed", ""),
                "output_path": str(self.output_path or ""),
                "temp_path": str(self.temp_path or ""),
                "profile_label": summary_profile(self.profile),
                "source": self.source,
                "logs": list(self.log_tail)[-10:],
            }


class DownloadManager:
    def __init__(self, config: AppConfig, kick: KickClient, tools: Toolchain, log):
        self.config = config
        self.kick = kick
        self.tools = tools
        self.log = log
        self._jobs: dict[str, DownloadJob] = {}
        self._queue: deque[str] = deque()
        self._active = 0
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._stop = False
        self._dispatcher: threading.Thread | None = None

    def start(self) -> None:
        if self._dispatcher and self._dispatcher.is_alive():
            return
        self._stop = False
        self._dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True, name="download-dispatcher")
        self._dispatcher.start()

    def submit(self, items: list[dict], *, source: dict, profile: dict, folder: str) -> list[dict]:
        submitted = []
        with self._cond:
            for item in items:
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                job_id = uuid.uuid4().hex[:12]
                job = DownloadJob(
                    job_id, url,
                    source=source, profile=profile, folder=folder,
                    title=str(item.get("title") or ""),
                    kind=str(item.get("kind") or ""),
                )
                job.logger = self.log
                self._jobs[job_id] = job
                self._queue.append(job_id)
                submitted.append(job.snapshot())
                self.log.info(f"Queued download: {job.title or url}", "download")
            self._cond.notify_all()
        return submitted

    def _dispatch_loop(self) -> None:
        while not self._stop:
            with self._cond:
                while not self._stop:
                    max_concurrent = max(1, int(self.config.get("max_downloads") or 2))
                    if self._queue and self._active < max_concurrent:
                        job_id = self._queue.popleft()
                        job = self._jobs.get(job_id)
                        if job and job.state == "queued" and not job.stop_requested:
                            self._active += 1
                            threading.Thread(
                                target=self._run_job, args=(job,), daemon=True,
                                name=f"download-{job_id}",
                            ).start()
                            continue
                    self._cond.wait(timeout=0.8)
        for job in list(self._jobs.values()):
            if job.state in ACTIVE_DOWNLOAD_STATES:
                job.stop_requested = True
                if job.runner:
                    job.runner.stop()

    def _run_job(self, job: DownloadJob) -> None:
        try:
            job.started_at = time.time()
            job.state = "resolving"
            job.add_log("در حال بررسی لینک و کیفیت‌ها…")
            if not self.tools.ffmpeg_path():
                raise RuntimeError("FFmpeg در دسترس نیست.")
            resolved = self.kick.resolve_download(job.url, job.source)
            job.resolved = resolved
            job.kind = resolved.get("kind") or job.kind or "media"
            job.title = job.requested_title or resolved.get("title") or job.title
            channel = resolved.get("channel") or {}
            job.channel = str(channel.get("slug") or "")
            prefix = f"{job.channel or 'Kick'}_{job.kind}"
            base = safe_filename(f"{prefix}_{job.title}", fallback=f"Kick_{job.kind}", max_len=85)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            job.folder.mkdir(parents=True, exist_ok=True)
            job.output_path = unique_path(job.folder / f"{base}_{stamp}.mp4")
            temp_dir = TEMP_DIR / "downloads"
            temp_dir.mkdir(parents=True, exist_ok=True)
            job.temp_path = temp_dir / f"{job.id}.mkv"
            try:
                job.temp_path.unlink()
            except OSError:
                pass

            args = build_record_command(
                self.tools.ffmpeg_path(),
                resolved["input_url"],
                job.temp_path,
                job.profile,
                self.tools.encoders,
                live=False,
                from_start=False,
                hls_options=self.tools.hls_caps(),
            )
            job.runner = FfmpegRunner(args, job.temp_path, self.log, f"download:{job.kind}")
            if job.stop_requested:
                job.state = "canceled"
                return
            job.state = "running"
            job.add_log(f"دانلود آغاز شد: {job.title}")
            job.runner.start()
            job.runner.wait()
            if job.stop_requested:
                job.state = "stopping"

            media_seconds = (job.runner.progress or {}).get("media_seconds", 0)
            if not job.temp_path.exists() or job.temp_path.stat().st_size <= 0:
                raise RuntimeError("FFmpeg هیچ فایلی تولید نکرد. لینک یا کیفیت را بررسی کنید.")

            job.state = "finalizing"
            job.add_log("ساخت فایل MP4…")
            ok, error = finalize_file(self.tools.ffmpeg_path(), job.temp_path, job.output_path, self.log)
            if ok:
                job.state = "completed"
                job.error = ""
                job.add_log(f"دانلود کامل شد: {job.output_path}")
                self.log.success(f"Download completed: {job.output_path}", "download")
                if not self.config.get("keep_parts"):
                    try:
                        job.temp_path.unlink()
                    except OSError:
                        pass
            else:
                job.state = "error"
                job.error = "ساخت MP4 ناموفق بود. فایل موقت حفظ شد."
                job.add_log(f"ساخت MP4 ناموفق بود: {error[-500:] if error else ''}", "error")
                self.log.error(f"MP4 finalize failed for {job.output_path}: {error[-800:]}", "download")
            if job.stop_requested:
                job.state = "stopped" if ok else job.state
                job.add_log("دانلود توسط کاربر متوقف شد.")
        except Exception as exc:
            job.state = "error"
            job.error = getattr(exc, "message", str(exc))
            job.add_log(f"خطا: {job.error}", "error")
            self.log.error(f"Download failed ({job.url}): {job.error}", "download")
        finally:
            job.ended_at = time.time()
            job.runner = job.runner if job.runner else None
            with self._cond:
                self._active = max(0, self._active - 1)
                self._cond.notify_all()

    def stop(self, job_id: str) -> dict:
        with self._cond:
            job = self._jobs.get(job_id)
            if not job:
                return {"ok": False, "error": "job_not_found"}
            job.stop_requested = True
            if job.state == "queued":
                job.state = "canceled"
                job.ended_at = time.time()
                self._cond.notify_all()
                return {"ok": True, "job": job.snapshot()}
            if job.runner:
                threading.Thread(target=job.runner.stop, daemon=True, name=f"stop-{job_id}").start()
            return {"ok": True, "job": job.snapshot()}

    def stop_all(self) -> None:
        with self._cond:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.state in ACTIVE_DOWNLOAD_STATES:
                self.stop(job.id)

    def clear_history(self) -> None:
        with self._cond:
            for job_id, job in list(self._jobs.items()):
                if job.state not in ACTIVE_DOWNLOAD_STATES:
                    self._jobs.pop(job_id, None)

    def snapshot(self, limit: int = 80) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [job.snapshot() for job in jobs[:limit]]

    def shutdown(self) -> None:
        self._stop = True
        self.stop_all()
        with self._cond:
            self._cond.notify_all()


class LiveSession:
    def __init__(
        self,
        session_id: str,
        slug: str,
        *,
        source: dict,
        profile: dict,
        folder: str,
        from_start: bool,
        kick: KickClient,
        tools: Toolchain,
        config: AppConfig,
        log,
        auto_id: str = "",
        session_key: str = "",
        title: str = "",
    ):
        self.id = session_id
        self.slug = slug.lower()
        self.source = normalize_source(source)
        self.profile = normalize_output(profile)
        self.folder = Path(folder)
        self.from_start = bool(from_start)
        self.kick = kick
        self.tools = tools
        self.config = config
        self.log = log
        self.auto_id = auto_id
        self.session_key = session_key
        self.title = title or slug
        self.channel: dict = {}
        self.state = "resolving"
        self.error = ""
        self.created_at = time.time()
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.parts: list[dict] = []
        self.stop_requested = False
        self.final_path: Path | None = None
        self.folder.mkdir(parents=True, exist_ok=True)
        self.output_target: Path = unique_path(
            self.folder / f"{safe_filename(self.slug, max_len=60)}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        )
        self.temp_dir = TEMP_DIR / "sessions" / session_id
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.total_media_seconds = 0.0
        self.has_dvr = False
        self.used_from_start = False
        self.source_label = "خودکار"
        self.log_tail: deque[str] = deque(maxlen=60)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._current_runner: FfmpegRunner | None = None
        self._consecutive_failures = 0
        self._finalized = False

    def add_log(self, message: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            self.log_tail.append(f"{stamp} {message}")
        getattr(self.log, level, self.log.info)(message, f"live:{self.slug}")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"live-{self.slug}")
        self._thread.start()

    def stop(self) -> None:
        self.stop_requested = True
        runner = self._current_runner
        if runner:
            threading.Thread(target=runner.stop, daemon=True, name=f"stop-live-{self.slug}").start()
        self.add_log("درخواست توقف ثبت شد؛ در حال نهایی‌سازی…", "warn")

    def _run(self) -> None:
        part_index = 0
        try:
            self.state = "resolving"
            self.add_log("در حال دریافت لینک پخش زنده…")
            media = self.kick.live_media(self.slug, fresh=True)
            self.channel = media.get("channel") or {}
            self.title = self.channel.get("title") or self.channel.get("username") or self.slug
            if not self.session_key:
                self.session_key = str(media.get("session_id") or media.get("started_at") or "")
            self.has_dvr = bool(media.get("dvr"))
            self.add_log(
                f"کانال لایو است. DVR: {'در دسترس' if self.has_dvr else 'در دسترس نیست'}",
                "success",
            )
            self.started_at = time.time()

            while not self.stop_requested:
                try:
                    if part_index == 0:
                        chosen_media = media
                        use_from_start = bool(self.from_start and media.get("dvr"))
                        seek = 0.0
                    else:
                        chosen_media = self.kick.live_media(self.slug, fresh=True)
                        new_key = str(chosen_media.get("session_id") or chosen_media.get("started_at") or "")
                        if new_key and self.session_key and new_key != self.session_key:
                            self.add_log("یک پخش زنده جدید شروع شده؛ این جلسه بسته می‌شود.", "warn")
                            self.stop_requested = True
                            break
                        use_from_start = bool(
                            self.from_start and self.used_from_start and chosen_media.get("dvr")
                        )
                        # The DVR playlist starts at the broadcast start, so seek to
                        # the duration already captured.  A "from now" session (or one
                        # without DVR) simply resumes at the live edge.
                        seek = (self.total_media_seconds + 0.2) if use_from_start else 0.0
                        self.channel = chosen_media.get("channel") or self.channel

                    self.has_dvr = self.has_dvr or bool(chosen_media.get("dvr"))
                    selection = self.kick.choose_input(chosen_media, self.source, use_from_start)
                    used_from_start = bool(selection["from_start"])
                    self.used_from_start = self.used_from_start or used_from_start
                    variant = selection.get("variant") or {}
                    if variant.get("label"):
                        self.source_label = variant["label"]
                    part_index += 1
                    part_path = self.temp_dir / f"part_{part_index:03d}.mkv"
                    part = {
                        "index": part_index,
                        "path": str(part_path),
                        "state": "starting",
                        "media_seconds": 0.0,
                        "started_at": time.time(),
                        "ended_at": None,
                        "seek": seek,
                        "from_start": used_from_start,
                    }
                    with self._lock:
                        self.parts.append(part)
                    args = build_record_command(
                        self.tools.ffmpeg_path(),
                        selection["input_url"],
                        part_path,
                        self.profile,
                        self.tools.encoders,
                        live=True,
                        from_start=used_from_start,
                        seek_seconds=seek,
                        hls_options=self.tools.hls_caps(),
                    )
                    runner = FfmpegRunner(args, part_path, self.log, f"live:{self.slug}")
                    self._current_runner = runner
                    self.state = "recording"
                    part["state"] = "recording"
                    self.add_log(
                        f"بخش {part_index} آغاز شد"
                        f"{' (از ابتدای پخش)' if used_from_start and seek == 0 else ''}"
                        f"{f' (ادامه از {format_seconds(seek)})' if seek else ''}"
                    )
                    runner.start()
                    runner.wait()
                    self._current_runner = None
                    media_seconds = float((runner.progress or {}).get("media_seconds", 0))
                    if media_seconds < 1 and self.tools.ffprobe_path():
                        media_seconds = ffprobe_duration(self.tools.ffprobe_path(), part_path)
                    part["media_seconds"] = media_seconds
                    part["ended_at"] = time.time()
                    part["state"] = "done" if media_seconds > 0 else "failed"
                    self.total_media_seconds += max(0.0, media_seconds)
                    if self.stop_requested:
                        break
                    if media_seconds < 2:
                        self._consecutive_failures += 1
                        self.add_log(
                            f"بخش {part_index} کوتاه بود (کد خروج {runner.returncode}). تلاش دوباره…",
                            "warn",
                        )
                        if self._consecutive_failures >= 5:
                            raise RuntimeError("اتصال به استریم چند بار پشت سر هم قطع شد.")
                        time.sleep(min(10, 2 * self._consecutive_failures))
                    else:
                        self._consecutive_failures = 0

                    # Stay in the same live session while the channel is online.
                    self.state = "waiting"
                    if not self._wait_until_live():
                        self.add_log("استریم برای مدت تعیین‌شده قطع بود؛ پایان جلسه.", "warn")
                        break
                except KickError as exc:
                    if exc.code == "offline":
                        self.state = "waiting"
                        if not self._wait_until_live():
                            break
                        continue
                    self._consecutive_failures += 1
                    self.add_log(f"خطای Kick: {exc.message}", "error")
                    if self._consecutive_failures >= 4:
                        raise
                    time.sleep(4)
            self._finalize()
        except Exception as exc:
            self.error = getattr(exc, "message", str(exc))
            self.add_log(f"خطا: {self.error}", "error")
            self._finalize(failed=True)

    def _wait_until_live(self) -> bool:
        gap = max(10, int(self.config.get("session_gap") or 90))
        started = time.time()
        announced = False
        while not self.stop_requested:
            try:
                channel = self.kick.channel(self.slug, fresh=True)
                if channel.get("live"):
                    if announced:
                        self.add_log("کانال دوباره لایو شد؛ ادامه ضبط.", "success")
                    return True
            except KickError as exc:
                if exc.code not in {"network_error", "cloudflare"}:
                    self.add_log(f"بررسی وضعیت: {exc.message}", "warn")
            if not announced:
                self.add_log(f"استریم قطع شده؛ تا {gap} ثانیه منتظر بازگشت می‌مانم…", "warn")
                announced = True
            if time.time() - started >= gap:
                return False
            for _ in range(10):
                if self.stop_requested:
                    return False
                time.sleep(0.5)
        return False

    def _finalize(self, failed: bool = False) -> None:
        with self._lock:
            if self._finalized:
                return
            self._finalized = True
        self.state = "finalizing"
        runner = self._current_runner
        if runner:
            runner.stop(grace=6)
            self._current_runner = None
        parts = [Path(p["path"]) for p in self.parts if Path(p["path"]).exists() and Path(p["path"]).stat().st_size > 0]
        if not parts:
            self.state = "error" if failed or not self.stop_requested else "stopped"
            self.error = self.error or "هیچ داده‌ای ضبط نشد."
            self.ended_at = time.time()
            self.add_log("هیچ فایل قابل استفاده‌ای تولید نشد.", "error")
            return
        self.add_log(f"ترکیب {len(parts)} بخش و ساخت MP4…")
        ok, error = concat_parts(self.tools.ffmpeg_path(), parts, self.output_target, self.log)
        if ok:
            self.final_path = self.output_target
            self.state = "completed"
            self.error = ""
            self.add_log(f"ضبط کامل شد: {self.output_target}", "success")
            self.log.success(f"Live recording saved: {self.output_target}", "live")
            if not self.config.get("keep_parts"):
                for part in parts:
                    try:
                        part.unlink()
                    except OSError:
                        pass
                try:
                    self.temp_dir.rmdir()
                except OSError:
                    pass
        else:
            self.state = "error"
            self.error = "ترکیب/ساخت MP4 ناموفق بود؛ فایل‌های موقت حفظ شدند."
            self.add_log(f"ساخت MP4 ناموفق بود: {error[-500:] if error else ''}", "error")
            self.log.error(f"Live finalize failed for {self.slug}: {error[-800:]}", "live")
        self.ended_at = time.time()

    def note_live(self, channel: dict) -> None:
        if channel:
            self.channel = channel
            self.title = channel.get("title") or self.title

    def snapshot(self) -> dict:
        with self._lock:
            runner = self._current_runner.snapshot() if self._current_runner else {}
            parts = list(self.parts)
            total_size = 0
            for part in parts:
                try:
                    total_size += Path(part["path"]).stat().st_size
                except OSError:
                    pass
            elapsed = max(0.0, (self.ended_at or time.time()) - (self.created_at or time.time()))
            final_size = 0
            if self.final_path:
                try:
                    final_size = Path(self.final_path).stat().st_size
                except OSError:
                    pass
            return {
                "id": self.id,
                "kind": "live",
                "slug": self.slug,
                "title": self.title,
                "channel": self.channel,
                "state": self.state,
                "error": self.error,
                "auto_id": self.auto_id,
                "session_key": self.session_key,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "elapsed": elapsed,
                "media_seconds": self.total_media_seconds + float(runner.get("media_seconds", 0) or 0),
                "size": max(total_size, final_size),
                "parts": len(parts),
                "output_path": str(self.final_path or getattr(self, "output_target", "") or ""),
                "folder": str(self.folder),
                "profile_label": summary_profile(self.profile),
                "source_label": self.source_label,
                "has_dvr": self.has_dvr,
                "from_start": self.from_start and self.used_from_start,
                "progress": runner,
                "logs": list(self.log_tail)[-12:],
            }


class SessionManager:
    def __init__(self, config: AppConfig, kick: KickClient, tools: Toolchain, log):
        self.config = config
        self.kick = kick
        self.tools = tools
        self.log = log
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.RLock()

    def start_live(
        self,
        url_or_slug: str,
        *,
        source: dict,
        profile: dict,
        folder: str,
        from_start: bool = True,
        auto_id: str = "",
        session_key: str = "",
        title: str = "",
    ) -> dict:
        info = classify_url(url_or_slug)
        if info.get("type") != "channel":
            raise KickError("برای ضبط زنده یک لینک کانال Kick وارد کنید.", "bad_channel")
        slug = info["slug"]
        with self._lock:
            for session in self._sessions.values():
                if session.slug == slug and session.state in ACTIVE_SESSION_STATES and not auto_id:
                    raise KickError(f"برای «{slug}» یک ضبط فعال وجود دارد.", "already_recording")
            if auto_id:
                for session in self._sessions.values():
                    if session.auto_id == auto_id and session.state in ACTIVE_SESSION_STATES:
                        return session.snapshot()
            session_id = uuid.uuid4().hex[:12]
            session = LiveSession(
                session_id, slug,
                source=source, profile=profile, folder=folder,
                from_start=from_start, kick=self.kick, tools=self.tools,
                config=self.config, log=self.log, auto_id=auto_id,
                session_key=session_key, title=title,
            )
            self._sessions[session_id] = session
        session.start()
        return session.snapshot()

    def stop(self, session_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return {"ok": False, "error": "session_not_found"}
        session.stop()
        return {"ok": True, "session": session.snapshot()}

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.state in ACTIVE_SESSION_STATES:
                session.stop()

    def active_auto_keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return [
                (s.auto_id, s.session_key)
                for s in self._sessions.values()
                if s.auto_id and s.state in ACTIVE_SESSION_STATES
            ]

    def stop_auto(self, auto_id: str) -> None:
        with self._lock:
            sessions = [s for s in self._sessions.values() if s.auto_id == auto_id]
        for session in sessions:
            if session.state in ACTIVE_SESSION_STATES:
                session.stop()

    def active_for_auto(self, auto_id: str) -> LiveSession | None:
        with self._lock:
            for session in self._sessions.values():
                if session.auto_id == auto_id and session.state in ACTIVE_SESSION_STATES:
                    return session
        return None

    def active_for_slug(self, slug: str) -> LiveSession | None:
        with self._lock:
            for session in self._sessions.values():
                if session.slug == slug and session.state in ACTIVE_SESSION_STATES:
                    return session
        return None

    def count_active(self, auto_only: bool = False) -> int:
        with self._lock:
            return sum(
                1 for s in self._sessions.values()
                if s.state in ACTIVE_SESSION_STATES and (not auto_only or s.auto_id)
            )

    def clear_history(self) -> None:
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.state not in ACTIVE_SESSION_STATES:
                    self._sessions.pop(session_id, None)

    def snapshot(self, limit: int = 50) -> list[dict]:
        with self._lock:
            sessions = sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)
            return [session.snapshot() for session in sessions[:limit]]

    def wait_all(self, timeout: float = 12.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                active = [s for s in self._sessions.values() if s.state in ACTIVE_SESSION_STATES]
            if not active:
                return
            time.sleep(0.3)

    def shutdown(self) -> None:
        self.stop_all()
        self.wait_all(12)
        with self._lock:
            for session in self._sessions.values():
                runner = getattr(session, "_current_runner", None)
                if runner and runner.proc and runner.proc.poll() is None:
                    try:
                        runner.proc.kill()
                    except Exception:
                        pass
