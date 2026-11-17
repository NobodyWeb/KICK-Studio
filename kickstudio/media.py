"""HLS parsing, variant selection and FFmpeg command construction."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

from .config import normalize_output, normalize_source
from .util import TEMP_DIR, format_bytes

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
KICK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
KICK_HEADERS = {
    "User-Agent": KICK_UA,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://kick.com/",
    "Origin": "https://kick.com",
}


def _int(value, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_attrs(value: str) -> dict:
    """Parse an HLS attribute list (``A=1,B="text",C=...``)."""
    attrs: dict[str, str] = {}
    buf = []
    in_quote = False
    parts = []
    for char in value:
        if char == '"':
            in_quote = not in_quote
            buf.append(char)
        elif char == "," and not in_quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    if buf:
        parts.append("".join(buf))
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        attrs[key.strip().upper()] = val.strip().strip('"')
    return attrs


def parse_master(text: str, base_url: str) -> list[dict]:
    """Return the video variants found in an HLS master playlist."""
    if not text:
        return []
    text = text.lstrip("\ufeff")
    lines = [line.strip().lstrip("\ufeff") for line in text.replace("\r", "").split("\n")]
    variants: list[dict] = []
    seen: set[str] = set()
    pending: dict | None = None

    def add(url: str, attrs: dict) -> None:
        url = (url or "").strip()
        if not url:
            return
        absolute = urljoin(base_url, url)
        if absolute in seen:
            return
        seen.add(absolute)
        width = height = 0
        resolution = attrs.get("RESOLUTION", "")
        if "x" in resolution.lower():
            try:
                w, h = resolution.lower().split("x", 1)
                width, height = int(w), int(h)
            except ValueError:
                pass
        bandwidth = _int(attrs.get("BANDWIDTH") or attrs.get("AVERAGE-BANDWIDTH"))
        fps = _float(attrs.get("FRAME-RATE"))
        codecs = attrs.get("CODECS", "")
        video_codec = "h264"
        if "hvc1" in codecs or "hev1" in codecs:
            video_codec = "hevc"
        elif "av01" in codecs:
            video_codec = "av1"
        elif "vp09" in codecs:
            video_codec = "vp9"
        name = attrs.get("VIDEO") or ""
        if not name:
            if height:
                name = f"{height}p"
                if fps and int(fps) >= 50:
                    name += "60"
            else:
                name = f"منبع {len(variants) + 1}"
        variant_id = f"{height or 0}x{int(round(fps))}@{bandwidth}"
        variants.append(
            {
                "id": variant_id,
                "url": absolute,
                "name": name,
                "width": width,
                "height": height,
                "fps": fps,
                "bandwidth": bandwidth,
                "codec": video_codec,
                "codecs": codecs,
                "label": _variant_label(height, fps, bandwidth),
            }
        )

    for line in lines:
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = parse_attrs(line.split(":", 1)[1])
            pending = attrs
            inline = attrs.get("URI")
            if inline:
                add(inline, attrs)
                pending = None
            continue
        if line.startswith("#"):
            continue
        if pending is not None:
            add(line, pending)
            pending = None
    variants.sort(key=lambda v: (v["height"], v["bandwidth"]), reverse=True)
    return variants


def _variant_label(height: int, fps: float, bandwidth: int) -> str:
    parts = []
    if height:
        parts.append(f"{height}p")
    else:
        parts.append("منبع")
    if fps:
        parts.append(str(int(round(fps))))
    if bandwidth:
        parts.append(f"{bandwidth / 1_000_000:.1f} Mbps")
    return " · ".join(parts)


def select_variant(variants: list[dict], source: dict | None) -> dict | None:
    if not variants:
        return None
    source = normalize_source(source)
    mode = source["mode"]
    if mode == "variant" and source.get("variant_id"):
        for variant in variants:
            if variant.get("id") == source["variant_id"]:
                return variant
    if mode == "worst":
        return min(variants, key=lambda v: (v.get("bandwidth") or 0, v.get("height") or 0))
    if mode in {"height", "variant"} and source.get("height"):
        cap = int(source["height"])
        candidates = [v for v in variants if (v.get("height") or 0) <= cap]
        pool = candidates or variants
        # Prefer the highest resolution under the cap, then the highest bitrate.
        return max(pool, key=lambda v: ((v.get("height") or 0), (v.get("bandwidth") or 0)))
    if mode == "auto":
        # "auto" means the best available, which matches what Kick's player uses.
        return max(variants, key=lambda v: ((v.get("height") or 0), (v.get("bandwidth") or 0)))
    return max(variants, key=lambda v: ((v.get("height") or 0), (v.get("bandwidth") or 0)))


def source_from_variant(variant: dict | None) -> dict:
    if not variant:
        return normalize_source({"mode": "auto"})
    return normalize_source(
        {
            "mode": "variant",
            "height": variant.get("height") or 0,
            "bandwidth": variant.get("bandwidth") or 0,
            "variant_id": variant.get("id") or "",
        }
    )


def candidate_variant_urls(master_url: str, variants: list[dict], chosen: dict | None) -> list[str]:
    urls: list[str] = []
    if chosen and chosen.get("url"):
        urls.append(chosen["url"])
    # If the requested quality cannot be followed because the signature expires,
    # retrying with the highest variant is often enough. FFmpeg itself will also
    # retry network reads.
    if not urls:
        urls.extend(v.get("url") for v in variants if v.get("url"))
    if master_url and master_url not in urls:
        urls.append(master_url)
    return [u for u in urls if u]


def _encoder_available(encoder: str) -> bool:
    return encoder in {"libx264", "h264_nvenc", "h264_qsv", "h264_amf"}


def resolve_encoder(profile: dict, available: set[str] | None = None) -> str:
    requested = (profile.get("encoder") or "auto").lower()
    available = available or set()
    if requested != "auto" and (not available or requested in available):
        return requested
    for encoder in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf"):
        if not available or encoder in available:
            return encoder
    return "libx264"


def build_output_args(profile: dict, available_encoders: set[str] | None = None) -> list[str]:
    profile = normalize_output(profile)
    if profile["mode"] == "copy":
        return ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", "copy", "-sn", "-dn"]

    encoder = resolve_encoder(profile, available_encoders)
    args = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", encoder]

    filters = []
    if profile["max_height"]:
        filters.append(f"scale=-2:min(ih\\,{int(profile['max_height'])}):flags=lanczos")
    if profile["fps"]:
        filters.append(f"fps=fps={int(profile['fps'])}")
    if filters:
        args += ["-vf", ",".join(filters)]

    if encoder == "libx264":
        args += ["-preset", profile["preset"]]
        if profile["video_bitrate"] > 0:
            bitrate = profile["video_bitrate"]
            args += [
                "-b:v", f"{bitrate}k",
                "-maxrate", f"{bitrate}k",
                "-bufsize", f"{max(bitrate * 2, 1000)}k",
            ]
        else:
            args += ["-crf", str(profile["crf"])]
    else:
        # Hardware encoders are excellent at constant quality/bitrate, but their
        # quality flags differ. A target bitrate keeps the command portable.
        if profile["video_bitrate"] > 0:
            bitrate = profile["video_bitrate"]
        else:
            bitrate = {2160: 14_000, 1440: 10_000, 1080: 6_000, 720: 3_500, 480: 1_500, 360: 900}.get(
                profile["max_height"] or 1080, 4_000
            )
        args += ["-b:v", f"{bitrate}k", "-maxrate", f"{bitrate}k", "-bufsize", f"{max(bitrate * 2, 1000)}k"]
        if encoder == "h264_nvenc":
            args += ["-rc", "vbr"]
        elif encoder == "h264_qsv":
            args += ["-look_ahead", "1"]

    args += ["-pix_fmt", "yuv420p"]
    if profile["audio_bitrate"] > 0:
        args += ["-c:a", "aac", "-b:a", f"{int(profile['audio_bitrate'])}k"]
    else:
        args += ["-c:a", "copy"]
    args += ["-sn", "-dn"]
    extra = (profile.get("extra_args") or "").strip()
    if extra:
        try:
            args += shlex.split(extra, posix=False)
        except Exception:
            pass
    return args


def build_input_args(
    url: str,
    live: bool = False,
    from_start: bool = False,
    hls_options: set[str] | None = None,
) -> list[str]:
    args = [
        "-hide_banner",
        "-loglevel", "info",
        "-stats_period", "1",
        "-progress", "pipe:1",
        "-nostats",
        "-user_agent", KICK_UA,
        "-referer", "https://kick.com/",
        "-headers", "Origin: https://kick.com\r\nAccept-Language: en-US,en;q=0.9\r\n",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
        "-allowed_extensions", "ALL",
        "-max_reload", "30",
    ]
    if "extension_picky" in (hls_options or set()):
        # Newer FFmpeg builds (7.1+) reject extensionless HLS segments such as
        # Kick's VOD playlists. Disabling the picky check restores playback.
        args += ["-extension_picky", "0"]
    if live:
        args += [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "15",
            "-live_start_index", "0" if from_start else "-3",
        ]
    return args


def build_record_command(
    ffmpeg: str,
    input_url: str,
    temp_path: Path,
    profile: dict,
    available_encoders: set[str] | None = None,
    live: bool = False,
    from_start: bool = False,
    seek_seconds: float = 0,
    hls_options: set[str] | None = None,
) -> list[str]:
    args = [ffmpeg] + build_input_args(
        input_url, live=live, from_start=from_start, hls_options=hls_options
    )
    if seek_seconds and seek_seconds > 0.5:
        # Input seeking on an EVENT/DVR playlist lets a reconnected part resume
        # where the previous part stopped without duplicating the whole stream.
        args += ["-ss", f"{seek_seconds:.3f}"]
    args += ["-i", input_url]
    args += build_output_args(profile, available_encoders)
    container = "matroska" if Path(temp_path).suffix.lower() == ".mkv" else "mpegts"
    args += [
        "-max_muxing_queue_size", "4096",
        "-f", container,
        "-y", str(temp_path),
    ]
    return args


def _creation_flags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def run_ffmpeg(args: list[str], timeout: float = 3600) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=_creation_flags(),
        )
        err = proc.stderr.decode("utf-8", errors="replace")
        return proc.returncode, err
    except subprocess.TimeoutExpired:
        return -9, "FFmpeg timed out."
    except FileNotFoundError:
        return -1, "ffmpeg executable was not found."
    except Exception as exc:  # pragma: no cover - platform specific
        return -1, str(exc)


def finalize_file(ffmpeg: str, temp_path: Path | str, output_path: Path | str, log=None) -> tuple[bool, str]:
    temp_path = Path(temp_path)
    output_path = Path(output_path)
    if not temp_path.exists() or temp_path.stat().st_size <= 0:
        return False, "فایل موقت خالی است."
    output_path.parent.mkdir(parents=True, exist_ok=True)

    common = ["-hide_banner", "-loglevel", "warning", "-y", "-i", str(temp_path)]
    tail = ["-map", "0:v:0", "-map", "0:a:0?", "-movflags", "+faststart", "-f", "mp4", str(output_path)]
    attempts = [
        common + ["-c", "copy"] + tail,
        common + ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k"] + tail,
        common + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k"] + tail,
    ]
    last_err = ""
    for index, args in enumerate(attempts, 1):
        args = [ffmpeg] + args
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            pass
        code, err = run_ffmpeg(args, timeout=7200)
        last_err = err
        if code == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return True, ""
        if log:
            log.warn(f"MP4 remux attempt {index} failed (code {code}).", "ffmpeg")
    return False, last_err[-4000:]


def concat_parts(ffmpeg: str, parts: list[Path | str], output_path: Path | str, log=None) -> tuple[bool, str]:
    parts = [Path(p) for p in parts if Path(p).exists() and Path(p).stat().st_size > 0]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not parts:
        return False, "هیچ بخش قابل استفاده‌ای برای ترکیب پیدا نشد."
    if len(parts) == 1:
        return finalize_file(ffmpeg, parts[0], output_path, log)

    list_path = output_path.with_suffix(".concat.txt")
    try:
        lines = []
        for part in parts:
            text = part.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{text}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        return False, str(exc)

    common = [
        "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
    ]
    tail = ["-map", "0:v:0", "-map", "0:a:0?", "-fflags", "+genpts", "-movflags", "+faststart", "-f", "mp4", str(output_path)]
    attempts = [
        common + ["-c", "copy"] + tail,
        common + ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k"] + tail,
        common + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k"] + tail,
    ]
    last_err = ""
    for index, args in enumerate(attempts, 1):
        args = [ffmpeg] + args
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            pass
        code, err = run_ffmpeg(args, timeout=7200)
        last_err = err
        if code == 0 and output_path.exists() and output_path.stat().st_size > 0:
            try:
                list_path.unlink()
            except OSError:
                pass
            return True, ""
        if log:
            log.warn(f"Part concatenation attempt {index} failed (code {code}).", "ffmpeg")
    return False, last_err[-4000:]


def ffprobe_duration(ffprobe: str | None, path: Path | str, timeout: float = 30) -> float:
    if not ffprobe:
        return 0.0
    args = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=_creation_flags(),
        )
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        return max(0.0, float(text))
    except Exception:
        return 0.0


def parse_progress_line(line: str) -> tuple[str, str] | None:
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()


def progress_seconds(value: str) -> float:
    """Parse FFmpeg progress ``out_time`` / ``out_time_ms`` values."""
    text = (value or "").strip()
    if not text:
        return 0.0
    if ":" in text:
        try:
            parts = text.split(":")
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except ValueError:
            return 0.0
    try:
        # out_time_ms is actually microseconds in FFmpeg.
        return float(text) / 1_000_000.0
    except ValueError:
        return 0.0


def summary_profile(profile: dict) -> str:
    profile = normalize_output(profile)
    if profile["mode"] == "copy":
        return "کپی مستقیم (کیفیت اصلی)"
    bits = ["H.264"]
    if profile["max_height"]:
        bits.append(f"{profile['max_height']}p")
    if profile["video_bitrate"]:
        bits.append(f"{profile['video_bitrate'] / 1000:.1f} Mbps")
    else:
        bits.append(f"CRF {profile['crf']}")
    if profile["audio_bitrate"]:
        bits.append(f"AAC {profile['audio_bitrate']}k")
    else:
        bits.append("صوت کپی")
    return " · ".join(bits)


def ensure_temp_dir(name: str) -> Path:
    path = TEMP_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def free_space(path: Path | str = TEMP_DIR) -> int:
    try:
        return int(os.statvfs(path).f_bavail * os.statvfs(path).f_frsize)  # type: ignore[attr-defined]
    except Exception:
        try:
            import shutil
            return int(shutil.disk_usage(str(path)).free)
        except Exception:
            return 0


def describe_size(path: Path | str) -> str:
    try:
        return format_bytes(Path(path).stat().st_size)
    except OSError:
        return "0 B"
