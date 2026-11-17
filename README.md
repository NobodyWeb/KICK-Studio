# Kick Studio 3.0

A desktop recorder and downloader for [Kick](https://kick.com), built with Python,
a local HTTP API and a native WebView2 window (pywebview). The interface ships in
**Persian and English** and can be switched at any time from the sidebar.

> Only record or download content you have the right to keep. Respect Kick's terms
> of service and the streamer's permissions.

## Features

- **Live recording** with two explicit modes:
  - **From the start** — when DVR is available, recording begins at the first
    moment of the broadcast and runs until the stream ends.
  - **From now** — recording starts immediately and continues until the stream ends.
- **Auto recorder** — add streamers once; they are recorded from the beginning of
  each live broadcast. A stopped recording can be restarted by hand with
  **Re-record** (the dismissal is cleared and recording starts from the start again).
- **Adaptive quality** — pick the source quality, or let Kick Studio choose the
  best/worst available variant. Every live broadcast is stored in its own file,
  even across reconnects and DVR jumps.
- **Output control** — direct copy (no re-encode) or H.264 encoding with either
  **CRF (constant quality)** or a **target bitrate** in kbps, plus max height,
  audio bitrate, FPS limit, preset and extra FFmpeg arguments.
- **VOD & clip downloads** — paste direct links or load a channel list, select
  items and download several at once.
- **FFmpeg helper** — automatic install (gyan.dev builds, SHA-256 verified) and
  encoder detection (x264, NVENC, QSV, AMF).
- **Logs, stats and persistent settings.**

### Language

The sidebar footer has a **FA / EN** switch. The choice is stored in
`localStorage` and in `Data/settings.json`, so the app reopens in the same
language. English mode also flips the layout to LTR.

### Bitrate modes

The advanced panel exposes two rate-control modes:

| Mode | What it does |
| --- | --- |
| CRF (quality) | Constant quality; file size depends on the scene. Lower = better. |
| Target bitrate | Fixed video bitrate in kbps (200–80000). Predictable size. |

Only the active field is shown, the value is validated and clamped, and a summary
line shows the effective output (`copy`, `NVENC · 1080p · 6000 kbps`, …).
Switching to CRF clears the target bitrate (and vice versa), so the two modes can
never fight each other.

## Run from source

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

`run.bat` does the same thing on Windows. Requirements: Python 3.10+ and the
WebView2 runtime (pre-installed on Windows 10/11).

### Options

```powershell
python app.py                 # normal window
python app.py --browser       # open the UI in your default browser
python app.py --no-window     # serve the UI only
python app.py --debug         # enable WebView dev tools
python app.py --port 8765     # fixed local port (development)
```

## Build the Windows executable

The executable is built by GitHub Actions (`.github/workflows/build.yml`) on
`windows-latest`:

- every push to `main`/`master` (and every pull request) uploads
  `KickStudio-windows.zip` as a workflow artifact;
- pushing a tag such as `v3.0.0` also publishes a GitHub release with the zip.

Local build:

```powershell
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean KickStudio.spec
# -> dist\KickStudio\KickStudio.exe
```

The spec bundles `web/` and `assets/` and uses `assets/icon.ico` as the executable
icon. In frozen mode the app keeps `Data/`, `Logs/`, `Recordings/`, `Runtime/` and
`.tmp/` next to the executable, while the read-only UI files are loaded from the
PyInstaller bundle.

## FFmpeg

Kick Studio looks for FFmpeg on `PATH`, in `C:\FFmpeg`, in `Runtime/` and in the
path saved in settings. If it is missing:

1. Open **Settings**.
2. Press **Auto install** to download a verified build, or
3. point **FFmpeg path** at your own `ffmpeg.exe`.

Encoded output needs an H.264 encoder (`libx264`, NVENC, QSV or AMF). Direct copy
needs no encoder at all.

## Folders

| Folder | Contents |
| --- | --- |
| `Recordings/` | Finished MP4 files |
| `Data/` | Settings and the WebView profile |
| `Logs/` | Application log |
| `Runtime/` | Installed FFmpeg and tool cache |
| `.tmp/` | Temporary fragments and build helpers |
| `assets/` | App icon (`icon.ico`, `icon.png`) |
| `legacy/` | Old PowerShell recorder (reference only) |

## Notes

- **Source quality** is what Kick sends; the output profile can shrink the file
  but not the bandwidth used.
- **DVR** is required for "from the start"; without DVR the app falls back to
  recording from now.
- **403 / Cloudflare**: set the `kick_cookie` in Settings if Kick starts blocking
  requests. `pip install curl_cffi` improves compatibility.
- **Several sessions**: each live broadcast is a separate file; the recording
  continues automatically after short drops.

## Project layout

```text
app.py                 entry point + WebView window
kickstudio/
  kick.py              Kick API, VOD/DVR/clip metadata
  media.py             HLS parsing and FFmpeg arguments
  recorder.py          live sessions and downloads
  auto.py              auto-recorder scheduler
  server.py            local JSON API and static file server
  config.py            persistent settings
  tools.py             FFmpeg discovery/install
web/
  index.html           UI shell
  styles.css           design system (RTL + LTR)
  i18n.js              Persian → English dictionary and DOM translator
  app.js               UI controller
assets/                application icons
KickStudio.spec        PyInstaller build definition
.github/workflows/     Windows build + release
```

---

## راهنمای فارسی

- دو حالت ضبط: **از ابتدا تا انتها** (نیازمند DVR) و **فقط از زمان حال**.
- اگر ضبط خودکار را دستی متوقف کنید، دکمه **ضبط مجدد** روی کارت استریمر ظاهر
  می‌شود و ضبط از ابتدا دوباره شروع می‌شود.
- در بخش پیشرفته می‌توانید بین **CRF (کیفیت ثابت)** و **بیت‌ریت ثابت (kbps)**
  انتخاب کنید؛ فقط فیلد فعال نمایش داده می‌شود و مقدار آن اعتبارسنجی می‌شود.
- تغییر زبان از پایین نوار کناری (**FA / EN**) انجام می‌شود و ذخیره می‌ماند.
- ساخت نسخه ویندوز به‌صورت خودکار در GitHub Actions انجام می‌شود و فایل
  `KickStudio-windows.zip` در Artifacts (و در Release برای تگ‌ها) قرار می‌گیرد.
