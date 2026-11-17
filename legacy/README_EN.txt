KICK STUDIO — WINDOWS SERVER v2.6
=================================

Kick Studio is a Windows desktop utility for:
- Recording a live Kick broadcast from the earliest segment available in Kick's in-progress DVR playlist.
- Downloading channel VODs.
- Downloading channel clips.
- Saving outputs as MP4, with selectable source-copy or H.264 compression profiles.

No Docker, WSL, Python, or administrator rights are required. The first run downloads portable Go and FFmpeg, builds the local Kick API proxy, and binds that proxy to 127.0.0.1 only.

QUICK START
-----------
1. Extract the ZIP to a writable folder on Windows Server (Desktop Experience).
2. Run Run-KickDVRRecorder.bat.
3. On first run, allow the application to download and build its portable components.
4. Enter a channel URL such as https://kick.com/channelname.
5. Choose a task:
   - LIVE DVR: choose a stream rendition and output/compression profile, then click START LIVE DVR.
   - VOD LIBRARY: click LOAD CHANNEL VODS, select a VOD, then click DOWNLOAD SELECTED VOD.
   - CLIP LIBRARY: click LOAD CHANNEL CLIPS, select a clip, then click DOWNLOAD SELECTED CLIP.
6. Files are saved to the selected folder. The default folder is Recordings.

OUTPUT PROFILES
---------------
- Original (copy): no video re-encoding; preserves the source bitrate and quality. This is the fastest option and creates the largest files.
- Balanced (720p): H.264, maximum output height 720p, veryfast preset, approximately 2.8 Mbps video cap plus 128 kbps AAC audio.
- Compact (720p): H.264, maximum output height 720p, approximately 1.8 Mbps video cap plus 96 kbps AAC audio. This is the default.
- Compact (480p): H.264, maximum output height 480p, approximately 1 Mbps video cap plus 80 kbps AAC audio.

The output profile selector is shared across all three tabs. The default source rendition for Live DVR is 720p60 when available.

The compact profiles trade some image detail for smaller files and require CPU time for encoding. They reduce the saved MP4 size, not the amount of HLS data downloaded from Kick. To reduce network traffic, select a lower source rendition in the Live DVR tab (for example 480p or 360p). If the bundled FFmpeg build does not expose libx264, use Original (copy) or inspect the FFmpeg error log.

WHY A DVR FILE CAN GROW VERY QUICKLY
------------------------------------
The DVR playlist may contain the earlier portion of the current broadcast, not only the seconds elapsed since you pressed Start. FFmpeg can backfill those older segments faster than real time. For example, 500 MB written in 30 seconds may represent many minutes of previously broadcast video being downloaded quickly. The UI therefore reports both, along with the average output bitrate when FFmpeg progress is available:
- Media captured: the duration represented by the downloaded media.
- Wall time: the real time elapsed since the task started.

To reduce disk usage, choose Compact (720p) or Compact (480p). Original (copy) intentionally preserves the source bitrate. The application removes its temporary TS/MKV file after a successful MP4 remux unless “Keep the temporary source file” is checked.

VOD AND CLIP DOWNLOADS
----------------------
VOD and clip lists are loaded from the channel URL entered at the top of the application. The app uses the local UnofficialKickApp proxy endpoints:
- /streams/vods/{channel}
- /streams/vods/{channel}/{vodID}
- /streams/clips/{channel}
- /streams/clip/{channel}/{clipID}

The proxy is local-only and is not exposed on the server's public interfaces.

LIVE DVR LIMITATIONS
--------------------
Full rewind capture is possible only when Kick exposes an in-progress recording for that channel and the returned playlist contains the required earlier segments. Kick may delay creating or exposing this recording. A channel being live does not guarantee that DVR is available.

FIRST-RUN COMPONENTS
--------------------
- Portable Go toolchain (or a compatible system Go installation).
- FFmpeg Essentials for Windows.
- UnofficialKickApp source pinned to commit 0e647c4a334d14f3e910cd46ace58832f27f2e19.

RUNTIME FOLDERS
---------------
Runtime\       Portable Go and FFmpeg
Backend\       Downloaded source and locally built API executable
Recordings\    MP4 downloads and recordings
Logs\          Setup, proxy, and FFmpeg logs

TROUBLESHOOTING
---------------
- Setup failed: inspect Logs\setup.log, Logs\build.stderr.log, and Logs\build.stdout.log.
- DVR unavailable: Kick has not exposed an in-progress recording for the channel yet. Retry later or download its VOD once it appears.
- VOD/clip list is empty: verify the channel URL and check Logs\proxy.stderr.log.
- FFmpeg exits: inspect the matching *.ffmpeg.stderr.log file.
- MP4 finalization fails: the temporary TS/MKV file is retained for recovery.
- Port 18081 is busy: stop the other process using that local port.

SECURITY AND COMPLIANCE
-----------------------
- The local API proxy binds to 127.0.0.1 only.
- The application does not request a Kick password or Telegram token.
- Kick endpoints used by the upstream project are unofficial and may change.
- Only download and retain content you are authorized to access, and follow Kick's terms and applicable copyright law.

Upstream project: https://github.com/orkunevran/UnofficialKickApp
Upstream license: MIT
