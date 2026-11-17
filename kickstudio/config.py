"""Persistent application configuration (JSON, no external dependencies)."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

from .util import DATA_DIR, DOWNLOAD_DIR


DEFAULT_OUTPUT = {
    "mode": "copy",
    "encoder": "auto",
    "max_height": 0,
    "video_bitrate": 0,
    "crf": 20,
    "audio_bitrate": 160,
    "fps": 0,
    "preset": "veryfast",
    "extra_args": "",
}

DEFAULT_SOURCE = {
    "mode": "auto",
    "height": 0,
    "bandwidth": 0,
    "variant_id": "",
}

DEFAULTS: dict[str, Any] = {
    "download_dir": str(DOWNLOAD_DIR),
    "ffmpeg_path": "",
    "ffprobe_path": "",
    "poll_interval": 25,
    "session_gap": 90,
    "max_downloads": 2,
    "max_auto_recordings": 3,
    "keep_parts": False,
    "auto_enabled": True,
    "default_output": dict(DEFAULT_OUTPUT),
    "default_source": dict(DEFAULT_SOURCE),
    "auto_streamers": [],
    "language": "fa",
    "kick_cookie": "",
    "window": {"width": 1360, "height": 860},
}


def _merge(base: dict, incoming: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def normalize_output(raw: Any) -> dict:
    data = _merge(DEFAULT_OUTPUT, raw if isinstance(raw, dict) else {})
    mode = str(data.get("mode") or "copy").lower()
    data["mode"] = "encode" if mode == "encode" else "copy"
    encoder = str(data.get("encoder") or "auto").lower()
    data["encoder"] = encoder if encoder in {"auto", "libx264", "h264_nvenc", "h264_qsv", "h264_amf"} else "auto"

    heights = {0, 2160, 1440, 1080, 900, 720, 600, 540, 480, 360, 240, 160}
    try:
        height = int(data.get("max_height") or 0)
    except (TypeError, ValueError):
        height = 0
    data["max_height"] = height if height in heights else 0

    data["video_bitrate"] = _clamp(data.get("video_bitrate"), 0, 100_000, 0)
    data["crf"] = _clamp(data.get("crf"), 0, 51, 20)
    data["audio_bitrate"] = _clamp(data.get("audio_bitrate"), 0, 512, 160)
    fps = _clamp(data.get("fps"), 0, 240, 0)
    data["fps"] = fps if fps in {0, 24, 25, 30, 48, 50, 60, 120, 144} else 0
    preset = str(data.get("preset") or "veryfast").lower()
    allowed = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}
    data["preset"] = preset if preset in allowed else "veryfast"
    data["extra_args"] = str(data.get("extra_args") or "")[:2000]
    return data


def normalize_source(raw: Any) -> dict:
    data = _merge(DEFAULT_SOURCE, raw if isinstance(raw, dict) else {})
    mode = str(data.get("mode") or "auto").lower()
    if mode not in {"auto", "best", "worst", "height", "variant"}:
        mode = "auto"
    data["mode"] = mode
    data["height"] = _clamp(data.get("height"), 0, 4320, 0)
    data["bandwidth"] = _clamp(data.get("bandwidth"), 0, 200_000_000, 0)
    data["variant_id"] = str(data.get("variant_id") or "")[:120]
    return data


class AppConfig:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or (DATA_DIR / "settings.json"))
        self._lock = threading.RLock()
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> dict:
        with self._lock:
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self.data = _merge(DEFAULTS, loaded)
                except Exception:
                    self.data = copy.deepcopy(DEFAULTS)
            self._sanitize()
            return copy.deepcopy(self.data)

    def _sanitize(self) -> None:
        data = self.data
        data["download_dir"] = str(data.get("download_dir") or DOWNLOAD_DIR)
        data["ffmpeg_path"] = str(data.get("ffmpeg_path") or "")
        data["ffprobe_path"] = str(data.get("ffprobe_path") or "")
        data["poll_interval"] = _clamp(data.get("poll_interval"), 10, 600, 25)
        data["session_gap"] = _clamp(data.get("session_gap"), 10, 1800, 90)
        data["max_downloads"] = _clamp(data.get("max_downloads"), 1, 8, 2)
        data["max_auto_recordings"] = _clamp(data.get("max_auto_recordings"), 1, 20, 3)
        data["keep_parts"] = bool(data.get("keep_parts"))
        data["auto_enabled"] = bool(data.get("auto_enabled", True))
        language = str(data.get("language") or "fa").strip().lower()
        data["language"] = "en" if language in {"en", "english"} else "fa"
        data["default_output"] = normalize_output(data.get("default_output"))
        data["default_source"] = normalize_source(data.get("default_source"))
        data["kick_cookie"] = str(data.get("kick_cookie") or "")[:8000]
        streamers = data.get("auto_streamers")
        if not isinstance(streamers, list):
            streamers = []
        cleaned = []
        seen = set()
        for item in streamers:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip().lower()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            cleaned.append(
                {
                    "id": str(item.get("id") or slug),
                    "slug": slug,
                    "name": str(item.get("name") or slug),
                    "avatar": str(item.get("avatar") or ""),
                    "enabled": bool(item.get("enabled", True)),
                    "source": normalize_source(item.get("source")),
                    "output": normalize_output(item.get("output")),
                    "folder": str(item.get("folder") or ""),
                    "added_at": item.get("added_at") or 0,
                }
            )
        data["auto_streamers"] = cleaned
        window = data.get("window")
        if not isinstance(window, dict):
            window = {}
        window["width"] = _clamp(window.get("width"), 900, 4000, 1360)
        window["height"] = _clamp(window.get("height"), 600, 3000, 860)
        data["window"] = window
        Path(data["download_dir"]).mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        with self._lock:
            self._sanitize()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self.data.get(key, default))

    def update(self, patch: dict) -> dict:
        with self._lock:
            self.data = _merge(self.data, patch or {})
            self.save()
            return copy.deepcopy(self.data)

    def set_streamers(self, streamers: list[dict]) -> None:
        with self._lock:
            self.data["auto_streamers"] = streamers
            self.save()

    def public(self) -> dict:
        with self._lock:
            data = copy.deepcopy(self.data)
        data.pop("kick_cookie", None)
        data["kick_cookie_set"] = bool(self.data.get("kick_cookie"))
        return data
