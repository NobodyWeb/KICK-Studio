"""Local-only HTTP API and static file server for the web UI."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests

from .auto import AutoRecorder
from .config import AppConfig, normalize_output, normalize_source
from .kick import KickClient, KickError
from .media import free_space, summary_profile
from .recorder import DownloadManager, SessionManager
from .tools import Toolchain
from .util import (
    APP_NAME,
    APP_VERSION,
    DOWNLOAD_DIR,
    ROOT,
    WEB_DIR,
    format_bytes,
    split_lines,
)

IMAGE_CACHE: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()
IMAGE_CACHE_LOCK = threading.RLock()
IMAGE_CACHE_MAX = 160
IMAGE_CACHE_TTL = 3600


class ApiServer:
    def __init__(
        self,
        config: AppConfig,
        log,
        tools: Toolchain,
        kick: KickClient,
        sessions: SessionManager,
        downloads: DownloadManager,
        auto: AutoRecorder,
        token: str,
        host: str = "127.0.0.1",
        port: int = 0,
    ):
        self.config = config
        self.log = log
        self.tools = tools
        self.kick = kick
        self.sessions = sessions
        self.downloads = downloads
        self.auto = auto
        self.token = token
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        server = self

        class Handler(ApiHandler):
            pass

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self._httpd.app = server  # type: ignore[attr-defined]
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="ui-server")
        self._thread.start()
        self.log.info(f"UI server listening on http://{self.host}:{self.port}", "server")
        return self.host, self.port

    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?token={self.token}"

    def shutdown(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "KickStudio/3.0"

    @property
    def app(self) -> ApiServer:
        return self.server.app  # type: ignore[attr-defined]

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):
        return

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _error(self, code: int, message: str, error_code: str = "error") -> None:
        self._json(code, {"ok": False, "error": message, "code": error_code})

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 4 * 1024 * 1024:
            raise ValueError("request body too large")
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        try:
            parsed = json.loads(data.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _token_ok(self, query: dict | None = None) -> bool:
        token = self.headers.get("X-Token") or self.headers.get("X-Kick-Token") or ""
        if not token and query:
            token = (query.get("token") or [""])[0]
        return bool(token) and token == self.app.token

    def _require_token(self, query: dict | None = None) -> bool:
        if self._token_ok(query):
            return True
        self._error(401, "توکن دسترسی معتبر نیست. برنامه را از نو اجرا کنید.", "unauthorized")
        return False

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/state":
                if not self._require_token(query):
                    return
                return self._json(200, self._state_payload())
            if path == "/api/logs":
                if not self._require_token(query):
                    return
                return self._logs(query)
            if path == "/api/tools":
                if not self._require_token(query):
                    return
                return self._json(200, {"ok": True, "tools": self.app.tools.snapshot()})
            if path == "/api/image":
                return self._image(query)
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/api/"):
                return self._error(404, "API endpoint not found", "not_found")
            return self._static(path.lstrip("/"))
        except BrokenPipeError:
            return
        except Exception as exc:
            self.app.log.error(f"GET {path} failed: {exc}", "server")
            return self._error(500, str(exc), "server_error")

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if not path.startswith("/api/"):
                return self._error(404, "Not found", "not_found")
            if not self._require_token(query):
                return
            body = self._body()
            if path == "/api/probe":
                return self._probe(body)
            if path == "/api/live/start":
                return self._live_start(body)
            if path == "/api/live/stop":
                return self._live_stop(body)
            if path == "/api/live/stop-all":
                auto_keys = self.app.sessions.active_auto_keys()
                self.app.sessions.stop_all()
                for auto_id, session_key in auto_keys:
                    self.app.auto.dismiss(auto_id, session_key)
                return self._json(200, {"ok": True})
            if path == "/api/downloads/start":
                return self._downloads_start(body)
            if path == "/api/downloads/stop":
                result = self.app.downloads.stop(str(body.get("id") or ""))
                return self._json(200 if result.get("ok") else 404, result)
            if path == "/api/downloads/stop-all":
                self.app.downloads.stop_all()
                return self._json(200, {"ok": True})
            if path == "/api/downloads/clear":
                self.app.downloads.clear_history()
                return self._json(200, {"ok": True})
            if path == "/api/live/clear":
                self.app.sessions.clear_history()
                return self._json(200, {"ok": True})
            if path == "/api/channel/vods":
                return self._channel_vods(body)
            if path == "/api/channel/clips":
                return self._channel_clips(body)
            if path == "/api/auto/add":
                return self._auto_add(body)
            if path == "/api/auto/update":
                return self._auto_update(body)
            if path == "/api/auto/remove":
                return self._auto_remove(body)
            if path == "/api/auto/enabled":
                self.app.auto.set_enabled(bool(body.get("enabled")))
                return self._json(200, {"ok": True, "auto": self.app.auto.snapshot()})
            if path == "/api/auto/check":
                self.app.auto.check_now()
                return self._json(200, {"ok": True})
            if path == "/api/auto/restart":
                self.app.auto.restart(str(body.get("id") or ""))
                return self._json(200, {"ok": True, "auto": self.app.auto.snapshot()})
            if path == "/api/settings":
                return self._settings(body)
            if path == "/api/logs/clear":
                self.app.log.clear()
                return self._json(200, {"ok": True})
            if path == "/api/tools/install-ffmpeg":
                return self._json(200, {"ok": True, "tools": self.app.tools.install_async()})
            if path == "/api/open":
                return self._open(body)
            return self._error(404, "API endpoint not found", "not_found")
        except KickError as exc:
            self.app.log.warn(f"{path}: {exc.message}", "ui")
            return self._json(400, {"ok": False, "error": exc.message, "code": exc.code})
        except ValueError as exc:
            return self._error(400, str(exc), "bad_request")
        except BrokenPipeError:
            return
        except Exception as exc:
            self.app.log.error(f"POST {path} failed: {exc}", "server")
            return self._error(500, str(exc), "server_error")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------- payloads
    def _state_payload(self) -> dict:
        config = self.app.config
        tools = self.app.tools.snapshot()
        settings = config.public()
        return {
            "ok": True,
            "app": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "root": str(ROOT),
                "server_time": time.time(),
            },
            "settings": settings,
            "tools": tools,
            "sessions": self.app.sessions.snapshot(50),
            "downloads": self.app.downloads.snapshot(80),
            "auto": self.app.auto.snapshot(),
            "logs": self.app.log.tail(70),
            "stats": {
                "download_dir": str(config.get("download_dir") or DOWNLOAD_DIR),
                "free_space": free_space(config.get("download_dir") or DOWNLOAD_DIR),
                "free_space_text": format_bytes(free_space(config.get("download_dir") or DOWNLOAD_DIR)),
                "active_sessions": self.app.sessions.count_active(),
                "active_auto": self.app.sessions.count_active(auto_only=True),
            },
        }

    def _logs(self, query: dict) -> None:
        try:
            limit = int((query.get("limit") or ["400"])[0])
        except ValueError:
            limit = 400
        try:
            after = int((query.get("after") or ["0"])[0])
        except ValueError:
            after = 0
        level = (query.get("level") or ["all"])[0]
        entries = self.app.log.tail(limit=limit, after=after, level=level)
        self._json(200, {"ok": True, "logs": entries, "last": entries[-1]["seq"] if entries else after})

    # ---------------------------------------------------------------- probe
    def _probe(self, body: dict) -> None:
        url = str(body.get("url") or "").strip()
        if not url:
            raise ValueError("لینک را وارد کنید.")
        result = self.app.kick.probe(url)
        result["ok"] = True
        self._json(200, result)

    # ------------------------------------------------------------- live/DVR
    def _validate_media_options(self, body: dict) -> tuple[dict, dict, str]:
        source = normalize_source(body.get("source"))
        output = normalize_output(body.get("output"))
        folder = str(body.get("folder") or "").strip() or str(self.app.config.get("download_dir") or "")
        folder = str(Path(folder).expanduser())
        Path(folder).mkdir(parents=True, exist_ok=True)
        tools = self.app.tools.snapshot()
        if not tools.get("ok"):
            raise ValueError("FFmpeg در دسترس نیست. از صفحه تنظیمات آن را نصب کنید.")
        if output["mode"] == "encode":
            encoders = set(tools.get("encoders") or [])
            if encoders and not (encoders & {"libx264", "h264_nvenc", "h264_qsv", "h264_amf"}):
                raise ValueError("هیچ انکودر H.264 در FFmpeg پیدا نشد. حالت «کپی مستقیم» را انتخاب کنید.")
        return source, output, folder

    def _live_start(self, body: dict) -> None:
        url = str(body.get("url") or "").strip()
        if not url:
            raise ValueError("لینک کانال را وارد کنید.")
        source, output, folder = self._validate_media_options(body)
        from_start = bool(body.get("from_start", True))
        session = self.app.sessions.start_live(
            url,
            source=source,
            profile=output,
            folder=folder,
            from_start=from_start,
        )
        self._json(200, {"ok": True, "session": session})

    def _live_stop(self, body: dict) -> None:
        session_id = str(body.get("id") or "")
        if not session_id:
            raise ValueError("شناسه جلسه خالی است.")
        result = self.app.sessions.stop(session_id)
        if result.get("ok"):
            session = result.get("session") or {}
            if session.get("auto_id"):
                self.app.auto.dismiss(session["auto_id"], session.get("session_key") or "")
        self._json(200 if result.get("ok") else 404, result)

    # ------------------------------------------------------------ downloads
    def _downloads_start(self, body: dict) -> None:
        source, output, folder = self._validate_media_options(body)
        items = body.get("items")
        if not isinstance(items, list) or not items:
            urls = body.get("urls")
            if isinstance(urls, str):
                urls = split_lines(urls)
            if isinstance(urls, list):
                items = [{"url": str(u).strip()} for u in urls if str(u).strip()]
        if not isinstance(items, list) or not items:
            raise ValueError("حداقل یک لینک برای دانلود وارد کنید.")
        if len(items) > 100:
            raise ValueError("حداکثر ۱۰۰ لینک در هر درخواست مجاز است.")
        clean = []
        for item in items:
            if isinstance(item, str):
                clean.append({"url": item.strip()})
            elif isinstance(item, dict) and str(item.get("url") or "").strip():
                clean.append(item)
        if not clean:
            raise ValueError("لینک معتبری پیدا نشد.")
        submitted = self.app.downloads.submit(clean, source=source, profile=output, folder=folder)
        self._json(200, {"ok": True, "jobs": submitted})

    def _channel_vods(self, body: dict) -> None:
        url = str(body.get("url") or "").strip()
        if not url:
            raise ValueError("لینک کانال را وارد کنید.")
        limit = int(body.get("limit") or 60)
        items = self.app.kick.list_vods(url, limit=limit)
        self._json(200, {"ok": True, "items": items})

    def _channel_clips(self, body: dict) -> None:
        url = str(body.get("url") or "").strip()
        if not url:
            raise ValueError("لینک کانال را وارد کنید.")
        items = self.app.kick.list_clips(
            url,
            sort=str(body.get("sort") or "date"),
            time_range=str(body.get("range") or "week"),
            pages=int(body.get("pages") or 2),
        )
        self._json(200, {"ok": True, "items": items})

    # ----------------------------------------------------------------- auto
    def _auto_add(self, body: dict) -> None:
        url = str(body.get("url") or "").strip()
        if not url:
            raise ValueError("لینک کانال را وارد کنید.")
        source = normalize_source(body.get("source") or self.app.config.get("default_source"))
        output = normalize_output(body.get("output") or self.app.config.get("default_output"))
        folder = str(body.get("folder") or "").strip()
        item = self.app.auto.add(url, source=source, output=output, folder=folder)
        self._json(200, {"ok": True, "item": item, "auto": self.app.auto.snapshot()})

    def _auto_update(self, body: dict) -> None:
        auto_id = str(body.get("id") or "")
        if not auto_id:
            raise ValueError("شناسه استریمر خالی است.")
        patch = {k: body[k] for k in ("enabled", "source", "output", "folder", "name") if k in body}
        item = self.app.auto.update(auto_id, patch)
        self._json(200, {"ok": True, "item": item, "auto": self.app.auto.snapshot()})

    def _auto_remove(self, body: dict) -> None:
        auto_id = str(body.get("id") or "")
        if not auto_id:
            raise ValueError("شناسه استریمر خالی است.")
        self.app.auto.remove(auto_id)
        self._json(200, {"ok": True, "auto": self.app.auto.snapshot()})

    # ------------------------------------------------------------- settings
    def _settings(self, body: dict) -> None:
        allowed = {
            "download_dir", "poll_interval", "session_gap", "max_downloads",
            "max_auto_recordings", "keep_parts", "auto_enabled",
            "default_output", "default_source", "ffmpeg_path", "ffprobe_path",
            "kick_cookie", "language",
        }
        patch = {k: body[k] for k in allowed if k in body}
        if "download_dir" in patch:
            folder = str(Path(str(patch["download_dir"])).expanduser())
            Path(folder).mkdir(parents=True, exist_ok=True)
            patch["download_dir"] = folder
        if "default_output" in patch:
            patch["default_output"] = normalize_output(patch["default_output"])
        if "default_source" in patch:
            patch["default_source"] = normalize_source(patch["default_source"])
        old_ffmpeg = self.app.config.get("ffmpeg_path")
        self.app.config.update(patch)
        if "ffmpeg_path" in patch or "ffprobe_path" in patch:
            if patch.get("ffmpeg_path") != old_ffmpeg or patch.get("ffprobe_path"):
                self.app.tools.refresh()
        if "auto_enabled" in patch:
            self.app.auto.set_enabled(bool(patch["auto_enabled"]))
        self.app.auto.wake()
        self._json(200, {
            "ok": True,
            "settings": self.app.config.public(),
            "tools": self.app.tools.snapshot(),
        })

    # ------------------------------------------------------------- open path
    def _open(self, body: dict) -> None:
        target = str(body.get("path") or "").strip()
        if not target:
            target = str(self.app.config.get("download_dir") or DOWNLOAD_DIR)
        path = Path(target).expanduser()
        if not path.exists():
            raise ValueError("مسیر مورد نظر وجود ندارد.")
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif os.name == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            raise ValueError(f"باز کردن مسیر ناموفق بود: {exc}")
        self._json(200, {"ok": True})

    # --------------------------------------------------------------- static
    def _static(self, relative: str) -> None:
        relative = unquote(relative or "index.html")
        if relative in ("", "/"):
            relative = "index.html"
        candidate = (WEB_DIR / relative).resolve()
        try:
            candidate.relative_to(WEB_DIR.resolve())
        except ValueError:
            return self._error(403, "Forbidden", "forbidden")
        if not candidate.exists() or not candidate.is_file():
            # SPA fallback for unknown paths.
            if "." not in Path(relative).name:
                candidate = WEB_DIR / "index.html"
            else:
                return self._error(404, "File not found", "not_found")
        try:
            data = candidate.read_bytes()
        except OSError:
            return self._error(404, "File not found", "not_found")
        content_type, _ = mimetypes.guess_type(str(candidate))
        if candidate.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif candidate.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif candidate.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif candidate.suffix == ".svg":
            content_type = "image/svg+xml"
        content_type = content_type or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if candidate.suffix in (".css", ".js", ".svg", ".png", ".webp"):
            self.send_header("Cache-Control", "public, max-age=120")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    # --------------------------------------------------------- image proxy
    def _image(self, query: dict) -> None:
        if not self._token_ok(query):
            return self._error(401, "unauthorized", "unauthorized")
        url = (query.get("url") or [""])[0]
        if not url:
            return self._error(400, "missing url", "bad_request")
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().split(":")[0]
        if parsed.scheme not in ("http", "https") or not (host == "kick.com" or host.endswith(".kick.com")):
            return self._error(403, "host not allowed", "forbidden")
        with IMAGE_CACHE_LOCK:
            cached = IMAGE_CACHE.get(url)
            if cached and time.time() - cached[0] < IMAGE_CACHE_TTL:
                IMAGE_CACHE.move_to_end(url)
                data, content_type = cached[1], cached[2]
                self._send_image(data, content_type)
                return
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                    "Referer": "https://kick.com/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
                timeout=(8, 20),
            )
            response.raise_for_status()
            data = response.content
            if len(data) > 8 * 1024 * 1024:
                return self._error(413, "image too large", "too_large")
            content_type = response.headers.get("Content-Type") or "image/jpeg"
            with IMAGE_CACHE_LOCK:
                IMAGE_CACHE[url] = (time.time(), data, content_type)
                while len(IMAGE_CACHE) > IMAGE_CACHE_MAX:
                    IMAGE_CACHE.popitem(last=False)
            self._send_image(data, content_type)
        except Exception:
            self._error(404, "image unavailable", "not_found")

    def _send_image(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass
