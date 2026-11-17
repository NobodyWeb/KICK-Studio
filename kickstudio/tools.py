"""FFmpeg discovery and optional first-run download (Windows)."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import requests

from .config import AppConfig
from .util import RUNTIME_DIR, format_bytes

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_SHA_URL = FFMPEG_URL + ".sha256"
KNOWN_ENCODERS = ("libx264", "h264_nvenc", "h264_qsv", "h264_amf")


class Toolchain:
    def __init__(self, config: AppConfig, log):
        self.config = config
        self.log = log
        self._lock = threading.RLock()
        self.ffmpeg: str = ""
        self.ffprobe: str = ""
        self.version: str = ""
        self.encoders: set[str] = set()
        self.hls_options: set[str] = set()
        self.error: str = ""
        self.installing: bool = False
        self.install_progress: float = 0.0
        self.install_message: str = ""
        self.refresh()

    def _candidates(self) -> list[str]:
        candidates = []
        configured = str(self.config.get("ffmpeg_path") or "").strip()
        if configured:
            candidates.append(configured)
        for name in ("ffmpeg.exe", "ffmpeg"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
        for root in (RUNTIME_DIR, Path("C:/ffmpeg"), Path("C:/FFmpeg")):
            try:
                for path in root.rglob("ffmpeg.exe" if os.name == "nt" else "ffmpeg"):
                    candidates.append(str(path))
            except OSError:
                pass
        return candidates

    def refresh(self) -> dict:
        with self._lock:
            self.error = ""
            ffmpeg = ""
            for candidate in self._candidates():
                path = Path(candidate)
                if path.exists() and path.is_file():
                    ffmpeg = str(path)
                    break
            if not ffmpeg:
                self.ffmpeg = ""
                self.ffprobe = ""
                self.version = ""
                self.encoders = set()
                self.hls_options = set()
                self.error = "FFmpeg پیدا نشد."
                return self.snapshot()

            self.ffmpeg = ffmpeg
            sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
            configured_probe = str(self.config.get("ffprobe_path") or "").strip()
            if configured_probe and Path(configured_probe).exists():
                self.ffprobe = configured_probe
            elif sibling.exists():
                self.ffprobe = str(sibling)
            else:
                found = shutil.which("ffprobe.exe" if os.name == "nt" else "ffprobe")
                self.ffprobe = found or ""

            try:
                proc = subprocess.run(
                    [ffmpeg, "-hide_banner", "-version"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=15, creationflags=CREATE_NO_WINDOW,
                )
                text = proc.stdout.decode("utf-8", errors="replace")
                self.version = text.splitlines()[0].strip() if text else "FFmpeg"
            except Exception as exc:
                self.version = "FFmpeg"
                self.error = str(exc)

            try:
                proc = subprocess.run(
                    [ffmpeg, "-hide_banner", "-encoders"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=30, creationflags=CREATE_NO_WINDOW,
                )
                text = proc.stdout.decode("utf-8", errors="replace")
                self.encoders = {name for name in KNOWN_ENCODERS if name in text}
            except Exception:
                self.encoders = set()

            try:
                proc = subprocess.run(
                    [ffmpeg, "-hide_banner", "-h", "demuxer=hls"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=15, creationflags=CREATE_NO_WINDOW,
                )
                text = proc.stdout.decode("utf-8", errors="replace")
                self.hls_options = {
                    name
                    for name in ("extension_picky", "allowed_segment_extensions")
                    if name in text
                }
            except Exception:
                self.hls_options = set()

            if not ffmpeg:
                self.error = "FFmpeg پیدا نشد."
            return self.snapshot()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "ok": bool(self.ffmpeg),
                "ffmpeg": self.ffmpeg,
                "ffprobe": self.ffprobe,
                "version": self.version,
                "encoders": sorted(self.encoders),
                "hls_options": sorted(self.hls_options),
                "libx264": "libx264" in self.encoders,
                "error": self.error,
                "installing": self.installing,
                "install_progress": round(self.install_progress, 1),
                "install_message": self.install_message,
            }

    def ffmpeg_path(self) -> str:
        with self._lock:
            return self.ffmpeg

    def ffprobe_path(self) -> str:
        with self._lock:
            return self.ffprobe

    def hls_caps(self) -> set[str]:
        with self._lock:
            return set(self.hls_options)

    def install_async(self) -> dict:
        with self._lock:
            if self.installing:
                return self.snapshot()
            if self.ffmpeg:
                return self.snapshot()
            self.installing = True
            self.install_progress = 0.0
            self.install_message = "شروع دانلود FFmpeg…"
        self.log.info("Downloading portable FFmpeg from gyan.dev…", "setup")
        threading.Thread(target=self._install_worker, daemon=True, name="ffmpeg-install").start()
        return self.snapshot()

    def _install_worker(self) -> None:
        zip_path = RUNTIME_DIR / "ffmpeg-release-essentials.zip"
        try:
            self._set_progress(2, "دریافت امضای SHA-256 از منبع رسمی…")
            sha_text = requests.get(FFMPEG_SHA_URL, timeout=30).text
            expected = ""
            for token in sha_text.replace("\n", " ").split():
                if len(token) == 64 and all(c in "0123456789abcdefABCDEF" for c in token):
                    expected = token.lower()
                    break
            self._set_progress(5, "دانلود FFmpeg (حدود ۹۰ مگابایت)…")
            response = requests.get(FFMPEG_URL, stream=True, timeout=60)
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with zip_path.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    pct = 5 + (done / total * 80 if total else 40)
                    self._set_progress(pct, f"دانلود FFmpeg… {format_bytes(done)}")
            if expected:
                self._set_progress(88, "بررسی SHA-256…")
                import hashlib
                digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
                if digest != expected:
                    raise RuntimeError("SHA-256 فایل FFmpeg با مقدار رسمی مطابقت ندارد.")
            self._set_progress(90, "استخراج فایل‌ها…")
            target = RUNTIME_DIR / "ffmpeg"
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(target)
            try:
                zip_path.unlink()
            except OSError:
                pass
            self._set_progress(97, "جست‌وجوی ffmpeg.exe…")
            found = next(target.rglob("ffmpeg.exe"), None)
            if not found:
                raise RuntimeError("ffmpeg.exe در آرشیو پیدا نشد.")
            self.config.update({"ffmpeg_path": str(found)})
            self._set_progress(100, "FFmpeg آماده است.")
            self.log.success(f"FFmpeg installed: {found}", "setup")
            self.refresh()
        except Exception as exc:
            self.log.error(f"FFmpeg install failed: {exc}", "setup")
            with self._lock:
                self.error = str(exc)
                self.install_message = f"نصب ناموفق: {exc}"
        finally:
            with self._lock:
                self.installing = False

    def _set_progress(self, value: float, message: str) -> None:
        with self._lock:
            self.install_progress = max(0.0, min(100.0, float(value)))
            self.install_message = message
