"""Kick Studio — desktop entry point.

Run with:
    python app.py

The UI is a local web page rendered inside a native WebView2 window.  The Python
process owns FFmpeg, the auto-recording scheduler and the local HTTP bridge.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from kickstudio.auto import AutoRecorder
from kickstudio.config import AppConfig
from kickstudio.kick import KickClient
from kickstudio.recorder import DownloadManager, SessionManager
from kickstudio.server import ApiServer
from kickstudio.tools import Toolchain
from kickstudio.util import APP_NAME, APP_VERSION, DATA_DIR, ICON_PATH, LOG_DIR, ROOT, LogBus


class Bridge:
    """Small native helpers exposed to JavaScript by pywebview."""

    def __init__(self, log):
        self._window = None
        self._log = log

    def _attach(self, window) -> None:
        self._window = window

    def choose_folder(self):
        try:
            import webview
            if not self._window:
                return None
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return None
            if isinstance(result, (list, tuple)):
                return str(result[0])
            return str(result)
        except Exception as exc:
            self._log.warn(f"Folder dialog failed: {exc}", "ui")
            return None

    def open_path(self, path: str):
        try:
            target = str(path or "")
            if not target:
                return False
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            elif os.name == "darwin":
                os.system(f'open "{target}"')
            else:
                os.system(f'xdg-open "{target}"')
            return True
        except Exception as exc:
            self._log.warn(f"Open path failed: {exc}", "ui")
            return False

    def info(self):
        return {"name": APP_NAME, "version": APP_VERSION, "root": str(ROOT)}


def build_services(config: AppConfig):
    log = LogBus(LOG_DIR)
    log.info(f"Starting {APP_NAME} {APP_VERSION}", "app")
    tools = Toolchain(config, log)
    if tools.ffmpeg:
        log.info(f"FFmpeg: {tools.version} | encoders: {', '.join(sorted(tools.encoders)) or 'unknown'}", "app")
    else:
        log.warn("FFmpeg was not found. Use the Settings page to install it.", "app")
    kick = KickClient(config, log)
    sessions = SessionManager(config, kick, tools, log)
    downloads = DownloadManager(config, kick, tools, log)
    downloads.start()
    auto = AutoRecorder(config, kick, sessions, log)
    auto.start()
    token = secrets.token_urlsafe(24)
    server = ApiServer(
        config, log, tools, kick, sessions, downloads, auto,
        token=token, host="127.0.0.1", port=0,
    )
    host, port = server.start()
    return {
        "log": log,
        "tools": tools,
        "kick": kick,
        "sessions": sessions,
        "downloads": downloads,
        "auto": auto,
        "server": server,
        "url": f"http://{host}:{port}/?token={token}",
    }


def run_no_window(services, keep_alive: bool = True):
    url = services["url"]
    print("\nKick Studio is running.")
    print(f"UI: {url}\n")
    try:
        if keep_alive:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping…")


def set_window_icon(title: str) -> None:
    """Give the Win32 window (and taskbar button) the app icon."""
    if os.name != "nt" or not ICON_PATH.exists():
        return

    def worker() -> None:
        try:
            import ctypes

            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.FindWindowW.restype = wintypes.HWND
            image_icon, load_from_file, load_default_size = 1, 0x10, 0x40
            wm_seticon, icon_small, icon_big = 0x0080, 0, 1
            for _ in range(50):
                hwnd = user32.FindWindowW(None, title)
                if hwnd:
                    for kind in (icon_small, icon_big):
                        size = 32 if kind == icon_small else 0
                        hicon = user32.LoadImageW(
                            None, str(ICON_PATH), image_icon, size, size,
                            load_from_file | (load_default_size if not size else 0),
                        )
                        if hicon:
                            user32.SendMessageW(hwnd, wm_seticon, kind, hicon)
                    return
                time.sleep(0.12)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _window_size(config: AppConfig) -> tuple[int, int]:
    width = int(config.get("window", {}).get("width", 1360) or 1360)
    height = int(config.get("window", {}).get("height", 860) or 860)
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            # SPI_GETWORKAREA excludes the taskbar, so the window always fits.
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                available_w = int(rect.right - rect.left)
                available_h = int(rect.bottom - rect.top)
                if available_w > 0 and available_h > 0:
                    width = min(width, available_w - 80)
                    height = min(height, available_h - 60)
        except Exception:
            pass
    return max(1000, width), max(600, height)


def main() -> int:
    parser = argparse.ArgumentParser(description="Kick Studio")
    parser.add_argument("--no-window", action="store_true", help="Serve the UI without opening a WebView window")
    parser.add_argument("--browser", action="store_true", help="Open the UI in the default browser instead of a WebView")
    parser.add_argument("--debug", action="store_true", help="Enable WebView debugging")
    parser.add_argument("--port", type=int, default=0, help="Local HTTP port (0 = random)")
    args = parser.parse_args()

    # Keep the app loopback-only.  The token is defense in depth, not a network
    # exposure mechanism.
    if args.port:
        # Rebuild the server with the requested port after services are created.
        pass

    services = None
    try:
        config = AppConfig()
        services = build_services(config)
        if args.port:
            # build_services already bound a random port.  This option is mostly
            # for development; restart the local server on the requested port.
            services["server"].shutdown()
            new_server = ApiServer(
                config, services["log"], services["tools"], services["kick"],
                services["sessions"], services["downloads"], services["auto"],
                token=services["server"].token, host="127.0.0.1", port=args.port,
            )
            host, port = new_server.start()
            services["server"] = new_server
            services["url"] = f"http://{host}:{port}/?token={new_server.token}"

        url = services["url"]
        print(f"\n{APP_NAME} {APP_VERSION}")
        print(f"Local UI: {url}")
        print("Close the window to stop the application.\n")

        if args.no_window:
            run_no_window(services)
            return 0

        try:
            import webview
        except Exception as exc:
            services["log"].error(f"pywebview is not available: {exc}", "app")
            print("pywebview is not installed. Opening the UI in your browser instead.")
            webbrowser.open(url)
            run_no_window(services)
            return 0

        bridge = Bridge(services["log"])
        win_width, win_height = _window_size(config)
        title = f"{APP_NAME} — Studio"
        window = webview.create_window(
            title,
            url,
            js_api=bridge,
            width=win_width,
            height=win_height,
            min_size=(1000, 600),
            background_color="#080b10",
            text_select=True,
            confirm_close=True,
        )
        bridge._attach(window)
        closing_done = {"value": False}

        def on_closing():
            if closing_done["value"]:
                return True
            closing_done["value"] = True
            services["log"].info("Window closing; stopping active tasks…", "app")
            try:
                services["auto"].stop()
                services["sessions"].stop_all()
                services["downloads"].stop_all()
                services["sessions"].wait_all(14)
                services["downloads"].shutdown()
            except Exception as exc:
                services["log"].warn(f"Cleanup warning: {exc}", "app")
            try:
                services["server"].shutdown()
            except Exception:
                pass
            services["log"].info("Shutdown complete.", "app")
            return True

        window.events.closing += on_closing
        set_window_icon(title)
        try:
            webview.start(
                debug=bool(args.debug),
                private_mode=False,
                storage_path=str(DATA_DIR / "webview"),
                icon=str(ICON_PATH) if ICON_PATH.exists() else None,
            )
        except Exception as exc:
            services["log"].error(f"WebView failed: {exc}", "app")
            print("WebView could not be started; opening the UI in your browser instead.")
            webbrowser.open(url)
            run_no_window(services)
        return 0
    except Exception as exc:
        print(f"{APP_NAME} failed to start: {exc}")
        traceback.print_exc()
        if services:
            try:
                services["log"].error(f"Fatal error: {exc}", "app")
                services["server"].shutdown()
            except Exception:
                pass
        return 1
    finally:
        if services:
            try:
                services["auto"].stop()
                services["sessions"].stop_all()
                services["downloads"].shutdown()
                services["server"].shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
