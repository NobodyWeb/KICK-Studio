"""Small shared helpers for Kick Studio.

The application is intentionally dependency-light: the only required third-party
packages are ``pywebview`` (desktop shell) and ``requests`` (Kick API calls).
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_NAME = "Kick Studio"
APP_VERSION = "3.0.0"


def _app_root() -> Path:
    """Folder that holds runtime data: next to the exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _bundle_root() -> Path:
    """Folder that holds bundled read-only resources (web UI, icons)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", _app_root()))
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
BUNDLE_DIR = _bundle_root()
WEB_DIR = BUNDLE_DIR / "web"
ICON_PATH = BUNDLE_DIR / "assets" / "icon.ico"
DATA_DIR = ROOT / "Data"
LOG_DIR = ROOT / "Logs"
TEMP_DIR = ROOT / ".tmp"
DOWNLOAD_DIR = ROOT / "Recordings"
RUNTIME_DIR = ROOT / "Runtime"

for _p in (DATA_DIR, LOG_DIR, TEMP_DIR, DOWNLOAD_DIR, RUNTIME_DIR):
    _p.mkdir(parents=True, exist_ok=True)

_BAD_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def now() -> float:
    return time.time()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_filename(value: str, fallback: str = "Kick", max_len: int = 100) -> str:
    text = _BAD_FILENAME.sub("_", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = text.strip()
    if not text:
        text = fallback
    if text.upper() in _RESERVED:
        text = f"_{text}"
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")
    return text or fallback


def unique_path(path: Path) -> Path:
    """Return *path* or a suffix-numbered alternative if it already exists."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


def channel_slug(raw: str) -> str | None:
    """Accept a Kick channel URL, a bare slug, or ``kick.com/slug``."""
    value = (raw or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    try:
        uri = urlparse(value)
    except Exception:
        return None
    if uri.scheme not in ("http", "https"):
        return None
    host = (uri.netloc or "").lower().split(":")[0]
    if host not in ("kick.com", "www.kick.com", "m.kick.com"):
        return None
    parts = [p for p in uri.path.split("/") if p]
    if not parts:
        return None
    first = parts[0].lower()
    if first in {"video", "videos", "categories", "clips", "search", "auth", "dashboard"}:
        return None
    slug = re.sub(r"[^A-Za-z0-9_-]", "", parts[0])
    return slug or None


VOD_PATH_RE = re.compile(r"/videos/([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})")
VOD_OLD_RE = re.compile(r"/video/([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})")
CLIP_RE = re.compile(r"(clip_[A-Za-z0-9_-]+)")
UUID_RE = re.compile(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})")


def classify_url(raw: str) -> dict:
    """Classify a user supplied URL.

    Returns ``{"type": "channel"|"vod"|"clip"|"direct", ...}``.
    Unknown http(s) URLs are treated as direct media links, which lets the user
    paste any HLS/MP4 URL that FFmpeg can open.
    """
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        return {"type": "invalid", "reason": "empty"}

    # A bare channel name is convenient for the live/auto pages.
    if "://" not in value and "/" not in value and " " not in value and not value.lower().startswith(("http", "rtmp")):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            return {"type": "channel", "slug": value.lower()}

    if "://" not in value:
        value = "https://" + value

    try:
        uri = urlparse(value)
    except Exception:
        return {"type": "invalid", "reason": "bad_url"}

    host = (uri.netloc or "").lower().split(":")[0]
    path = uri.path or ""
    lower_path = path.lower()

    if lower_path.endswith((".m3u8", ".mp4", ".ts", ".mkv", ".flv", ".webm")):
        return {"type": "direct", "url": value}

    if host not in ("kick.com", "www.kick.com", "m.kick.com"):
        return {"type": "direct", "url": value}

    query = parse_qs(uri.query or "")
    clip_candidates = []
    for key in ("clip", "clip_id", "clipId"):
        clip_candidates.extend(query.get(key, []))
    clip_candidates.append(path)
    for candidate in clip_candidates:
        match = CLIP_RE.search(candidate or "")
        if match:
            return {"type": "clip", "id": match.group(1), "url": value}

    match = VOD_PATH_RE.search(path) or VOD_OLD_RE.search(path)
    if match:
        slug = None
        parts = [p for p in path.split("/") if p]
        if parts and parts[0].lower() not in ("video", "videos"):
            slug = parts[0]
        return {"type": "vod", "id": match.group(1).lower(), "slug": slug, "url": value}

    slug = channel_slug(value)
    if slug:
        return {"type": "channel", "slug": slug.lower(), "url": value}

    return {"type": "invalid", "reason": "unsupported_kick_url"}


def format_bytes(num: float | int | None) -> str:
    if not num or num < 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def format_seconds(seconds: float | int | None) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_clock(ts: float | int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")


def parse_iso_ts(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        try:
            return datetime.fromisoformat(text.replace(" ", "T")).timestamp()
        except Exception:
            return None


def split_lines(text: str) -> list[str]:
    return [line.strip() for line in re.split(r"[\r\n]+", text or "") if line.strip()]


class LogBus:
    """Thread-safe in-memory log ring plus a persistent text log."""

    def __init__(self, log_dir: Path, maxlen: int = 3000):
        self._entries: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.RLock()
        self._seq = 0
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / "app.log"

    def add(self, level: str, message: str, source: str = "app") -> dict:
        message = str(message).replace("\r", "")
        if len(message) > 4000:
            message = message[:4000] + "…"
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": time.time(),
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": (level or "info").lower(),
                "source": source,
                "message": message,
            }
            self._entries.append(entry)
            try:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"[{entry['level'].upper()}] [{source}] {message}\n"
                    )
            except Exception:
                pass
        return entry

    def info(self, message: str, source: str = "app") -> dict:
        return self.add("info", message, source)

    def warn(self, message: str, source: str = "app") -> dict:
        return self.add("warn", message, source)

    def error(self, message: str, source: str = "app") -> dict:
        return self.add("error", message, source)

    def success(self, message: str, source: str = "app") -> dict:
        return self.add("success", message, source)

    def tail(self, limit: int = 300, after: int = 0, level: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit or 300), 2000))
        with self._lock:
            items = [e for e in self._entries if e["seq"] > int(after or 0)]
        if level and level != "all":
            items = [e for e in items if e["level"] == level]
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def print_console(self, entry: dict) -> None:
        try:
            print(f"[{entry['time']}] [{entry['level'].upper()}] {entry['message']}")
            sys.stdout.flush()
        except Exception:
            pass
