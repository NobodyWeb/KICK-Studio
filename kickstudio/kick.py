"""Unofficial Kick.com API client used by the desktop app.

Kick does not publish a stable public API for this use case.  The endpoints below
are the same ones used by Kick's web player and are intentionally isolated here so
that they can be adjusted if Kick changes them.
"""

from __future__ import annotations

import html
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from .config import AppConfig, normalize_source
from .media import (
    KICK_HEADERS,
    KICK_UA,
    candidate_variant_urls,
    parse_master,
    select_variant,
    source_from_variant,
)
from .util import channel_slug, classify_url, format_seconds, parse_iso_ts

API_V2 = "https://kick.com/api/v2"
WEB_V1 = "https://web.kick.com/api/v1"

try:  # Optional: helps with Cloudflare in some regions.
    from curl_cffi import requests as cffi_requests  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cffi_requests = None


class KickError(Exception):
    def __init__(self, message: str, code: str = "kick_error", status: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text).strip()


class KickClient:
    def __init__(self, config: AppConfig, log):
        self.config = config
        self.log = log
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, object]] = {}
        self._cffi = None
        if cffi_requests is not None:
            try:
                self._cffi = cffi_requests.Session(impersonate="chrome")
            except Exception:
                self._cffi = None
        self._last_request = 0.0

    # ------------------------------------------------------------------ HTTP
    def _headers(self, accept: str = "application/json") -> dict:
        headers = dict(KICK_HEADERS)
        headers["Accept"] = accept
        cookie = str(self.config.get("kick_cookie") or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _request(self, method: str, url: str, *, json_body=None, timeout=(10, 30), accept="application/json"):
        headers = self._headers(accept)
        last_error = ""
        for attempt in range(3):
            try:
                with self._lock:
                    # Keep a tiny gap between calls; Kick occasionally rate-limits bursts.
                    gap = 0.15 - (time.time() - self._last_request)
                    if gap > 0:
                        time.sleep(gap)
                    self._last_request = time.time()
                    if self._cffi is not None:
                        response = self._cffi.request(
                            method, url,
                            headers=headers,
                            json=json_body,
                            timeout=timeout,
                            impersonate="chrome",
                        )
                    else:
                        if json_body is not None:
                            response = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
                        else:
                            response = requests.request(method, url, headers=headers, timeout=timeout)
                status = int(response.status_code)
                if status == 403:
                    text = (response.text or "")[:400]
                    if "cloudflare" in text.lower() or "just a moment" in text.lower():
                        raise KickError(
                            "Kick دسترسی این برنامه را موقتاً محدود کرده است. چند دقیقه بعد دوباره تلاش کنید.",
                            "cloudflare", status,
                        )
                    raise KickError("Kick درخواست را رد کرد (403).", "forbidden", status)
                if status == 404:
                    raise KickError("این آیتم در Kick پیدا نشد (404).", "not_found", status)
                if status == 429:
                    last_error = "Kick rate limit (429)"
                    time.sleep(1.2 * (attempt + 1))
                    continue
                if status >= 500:
                    last_error = f"Kick server error ({status})"
                    time.sleep(0.8 * (attempt + 1))
                    continue
                if status >= 400:
                    raise KickError(f"Kick returned HTTP {status}.", "http_error", status)
                return response
            except KickError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt < 2:
                    time.sleep(0.6 * (attempt + 1))
                    continue
        raise KickError(f"ارتباط با Kick برقرار نشد: {last_error}", "network_error")

    def _get_json(self, url: str, *, timeout=(10, 30)):
        response = self._request("GET", url, timeout=timeout)
        try:
            return response.json()
        except Exception:
            text = (response.text or "").strip()
            raise KickError(f"پاسخ Kick قابل خواندن نبود: {text[:200]}", "bad_json")

    def _post_json(self, url: str, body: dict, *, timeout=(10, 30)):
        response = self._request("POST", url, json_body=body, timeout=timeout)
        try:
            return response.json()
        except Exception:
            text = (response.text or "").strip()
            raise KickError(f"پاسخ Kick قابل خواندن نبود: {text[:200]}", "bad_json")

    def get_text(self, url: str, *, timeout=(10, 30), accept: str = "application/vnd.apple.mpegurl, application/x-mpegURL, */*") -> str:
        response = self._request("GET", url, timeout=timeout, accept=accept)
        text = response.text or ""
        return text.lstrip("\ufeff")

    def _cache_get(self, key: str):
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            expires, value = item
            if expires < time.time():
                self._cache.pop(key, None)
                return None
            return value

    def _cache_set(self, key: str, value, ttl: float):
        with self._lock:
            self._cache[key] = (time.time() + ttl, value)

    # --------------------------------------------------------------- channels
    def channel(self, slug: str, *, fresh: bool = False) -> dict:
        slug = (slug or "").strip().lower()
        if not slug:
            raise KickError("نام کانال خالی است.", "bad_channel")
        cache_key = f"channel:{slug}"
        if not fresh:
            cached = self._cache_get(cache_key)
            if cached:
                return dict(cached)  # type: ignore[arg-type]
        try:
            data = self._get_json(f"{API_V2}/channels/{quote(slug)}")
        except KickError as exc:
            if exc.status == 404:
                raise KickError(f"کانال «{slug}» در Kick پیدا نشد.", "channel_not_found", 404) from exc
            raise
        if not isinstance(data, dict) or not data.get("id"):
            raise KickError(f"اطلاعات کانال «{slug}» در دسترس نیست.", "channel_not_found")
        result = self._normalize_channel(data, slug)
        self._cache_set(cache_key, result, 8 if not fresh else 2)
        return result

    def _normalize_channel(self, data: dict, slug: str) -> dict:
        live = data.get("livestream") if isinstance(data.get("livestream"), dict) else None
        is_live = bool(live and (live.get("is_live", True)))
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        categories = []
        if live:
            for category in live.get("categories") or []:
                if isinstance(category, dict) and category.get("name"):
                    categories.append(_clean_text(category["name"]))
        thumbnail = ""
        if live:
            thumb = live.get("thumbnail")
            if isinstance(thumb, dict):
                thumbnail = str(thumb.get("url") or "")
            elif isinstance(thumb, str):
                thumbnail = thumb
        return {
            "id": data.get("id"),
            "slug": str(data.get("slug") or slug).lower(),
            "username": _clean_text(user.get("username") or user.get("name") or slug),
            "avatar": str(user.get("profile_pic") or user.get("profile_picture") or ""),
            "verified": bool(data.get("verified") or user.get("verified")),
            "followers": int(data.get("followers_count") or 0),
            "live": is_live,
            "session_id": str(live.get("id") or "") if live else "",
            "title": _clean_text(live.get("session_title")) if live else "",
            "viewers": int(live.get("viewer_count") or 0) if live else 0,
            "started_at": str(live.get("start_time") or live.get("created_at") or "") if live else "",
            "started_ts": parse_iso_ts(live.get("start_time") or live.get("created_at")) if live else None,
            "thumbnail": thumbnail,
            "categories": categories,
            "language": str(live.get("language") or "") if live else "",
            "playback_live": str(data.get("playback_url") or "") if is_live else "",
            "is_banned": bool(data.get("is_banned")),
        }

    # ------------------------------------------------------------ live / DVR
    def channel_videos(self, channel_id, *, fresh: bool = False, timeout=(10, 30)) -> list[dict]:
        key = f"videos:{channel_id}"
        if not fresh:
            cached = self._cache_get(key)
            if cached is not None:
                return list(cached)  # type: ignore[arg-type]
        data = self._get_json(f"{WEB_V1}/channels/{channel_id}/videos", timeout=timeout)
        videos = data.get("data") if isinstance(data, dict) else None
        if not isinstance(videos, list):
            videos = []
        self._cache_set(key, videos, 8)
        return videos

    def playback(self, video_id: str, *, fresh: bool = True) -> dict:
        video_id = str(video_id or "").strip()
        if not video_id:
            raise KickError("شناسه ویدیو خالی است.", "bad_video")
        body = {
            "video_player": {"player": {}},
            "video_session": {},
            "user_session": {"non_personalised_ads": True},
        }
        data = self._post_json(f"{WEB_V1}/stream/{quote(video_id)}/playback", body)
        playback = data.get("playback_url") if isinstance(data, dict) else None
        if not isinstance(playback, dict):
            playback = {}
        result = {
            "dvr": str(playback.get("dvr") or ""),
            "live": str(playback.get("live") or ""),
            "vod": str(playback.get("vod") or ""),
            "raw": data,
        }
        if not any(result[k] for k in ("dvr", "live", "vod")):
            raise KickError("Kick برای این ویدیو لینک پخش برنگرداند.", "no_playback")
        return result

    def live_media(self, slug: str, *, fresh: bool = True) -> dict:
        channel = self.channel(slug, fresh=fresh)
        if not channel.get("live"):
            raise KickError(f"کانال «{channel.get('username') or slug}» در حال حاضر لایو نیست.", "offline")
        videos = self.channel_videos(channel["id"], fresh=fresh)
        live_vod = None
        for video in videos:
            if isinstance(video, dict) and video.get("is_live"):
                live_vod = video
                break
        dvr = ""
        live = str(channel.get("playback_live") or "")
        vod_id = ""
        if live_vod:
            vod_id = str(live_vod.get("id") or "")
            try:
                playback = self.playback(vod_id)
                dvr = playback.get("dvr") or ""
                live = playback.get("live") or live
            except KickError as exc:
                self.log.warn(f"DVR playback lookup failed for {slug}: {exc.message}", "kick")
        if not live and not dvr:
            raise KickError("لینک پخش زنده در دسترس نیست. کمی بعد دوباره تلاش کنید.", "no_live_playback")
        return {
            "dvr": dvr,
            "live": live,
            "vod_id": vod_id,
            "session_id": channel.get("session_id") or "",
            "started_at": channel.get("started_at") or "",
            "started_ts": channel.get("started_ts"),
            "channel": channel,
            "has_dvr": bool(dvr),
        }

    # ------------------------------------------------------------------ VODs
    def list_vods(self, slug: str, limit: int = 60) -> list[dict]:
        channel = self.channel(channel_slug(slug) or slug)
        videos = self.channel_videos(channel["id"], fresh=True)
        result = []
        for video in videos:
            if not isinstance(video, dict):
                continue
            video_id = str(video.get("id") or "")
            if not video_id:
                continue
            thumb = video.get("thumbnail")
            if isinstance(thumb, dict):
                thumb_url = str(thumb.get("src") or thumb.get("url") or "")
            else:
                thumb_url = str(thumb or "")
            result.append(
                {
                    "id": video_id,
                    "title": _clean_text(video.get("title")) or f"VOD {video_id[:8]}",
                    "duration": int(video.get("duration") or 0),
                    "duration_text": format_seconds(video.get("duration")),
                    "thumbnail": thumb_url,
                    "views": int(video.get("viewer_count") or video.get("views") or 0),
                    "created_at": str(video.get("created_at") or video.get("start_time") or ""),
                    "is_live": bool(video.get("is_live")),
                    "status": str(video.get("status") or ""),
                    "channel": channel["slug"],
                    "channel_name": channel["username"],
                    "url": f"https://kick.com/{channel['slug']}/videos/{video_id}",
                }
            )
            if len(result) >= max(1, min(limit, 200)):
                break
        return result

    def vod_media(self, video_id: str, slug: str | None = None) -> dict:
        playback = self.playback(video_id)
        # For a finished VOD the "vod" manifest is the right one.  For an
        # in-progress recording Kick may expose a DVR playlist instead.
        url = playback.get("vod") or playback.get("dvr") or playback.get("live")
        if not url:
            raise KickError("لینک پخش این ویدیو در دسترس نیست.", "no_vod_playback")
        title = f"Kick VOD {str(video_id)[:8]}"
        channel = None
        duration = 0
        thumbnail = ""
        if slug:
            try:
                channel = self.channel(slug)
                videos = self.channel_videos(channel["id"], fresh=True)
                for video in videos:
                    if str(video.get("id")) == str(video_id):
                        title = _clean_text(video.get("title")) or title
                        duration = int(video.get("duration") or 0)
                        thumb = video.get("thumbnail")
                        thumbnail = str(thumb.get("src") or thumb.get("url") or "") if isinstance(thumb, dict) else str(thumb or "")
                        break
            except KickError:
                pass
        return {
            "url": url,
            "title": title,
            "duration": duration,
            "thumbnail": thumbnail,
            "channel": channel,
            "kind": "vod",
            "is_live_vod": bool(playback.get("dvr") and not playback.get("vod")),
            "playback": playback,
        }

    # ----------------------------------------------------------------- clips
    def list_clips(self, slug: str, sort: str = "date", time_range: str = "week", pages: int = 2) -> list[dict]:
        channel = self.channel(channel_slug(slug) or slug)
        sort = "views" if str(sort).lower() in {"views", "view", "popular"} else "date"
        time_range = str(time_range or "week").lower()
        if time_range not in {"day", "week", "month", "all"}:
            time_range = "week"
        pages = max(1, min(int(pages or 2), 6))
        result = []
        cursor = None
        seen = set()
        for page in range(pages):
            params = f"?sort={sort}&time={time_range}"
            if cursor:
                params += f"&cursor={quote(str(cursor))}"
            data = self._get_json(f"{WEB_V1}/channels/{channel['id']}/clips{params}")
            payload = data.get("data") if isinstance(data, dict) else None
            clips = payload.get("clips") if isinstance(payload, dict) else None
            if not isinstance(clips, list):
                break
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                clip_id = str(clip.get("id") or "")
                if not clip_id or clip_id in seen:
                    continue
                seen.add(clip_id)
                category = clip.get("category") if isinstance(clip.get("category"), dict) else {}
                creator = clip.get("creator") if isinstance(clip.get("creator"), dict) else {}
                result.append(
                    {
                        "id": clip_id,
                        "title": _clean_text(clip.get("title")) or "کلیپ Kick",
                        "duration": int(clip.get("duration") or 0),
                        "duration_text": format_seconds(clip.get("duration")),
                        "thumbnail": str(clip.get("thumbnail_url") or ""),
                        "views": int(clip.get("views_count") or clip.get("views") or 0),
                        "created_at": str(clip.get("created_at") or ""),
                        "category": _clean_text(category.get("name")),
                        "creator": _clean_text(creator.get("username")),
                        "channel": channel["slug"],
                        "channel_name": channel["username"],
                        "url": f"https://kick.com/{channel['slug']}/clips/{clip_id}",
                        "playback_url": str(clip.get("playback_url") or ""),
                    }
                )
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if not cursor:
                break
        return result

    def clip(self, clip_id: str) -> dict:
        clip_id = str(clip_id or "").strip()
        if not clip_id:
            raise KickError("شناسه کلیپ خالی است.", "bad_clip")
        data = self._get_json(f"{API_V2}/clips/{quote(clip_id)}")
        clip = data.get("clip") if isinstance(data, dict) else None
        if not isinstance(clip, dict):
            raise KickError("اطلاعات کلیپ در دسترس نیست.", "clip_not_found")
        channel = clip.get("channel") if isinstance(clip.get("channel"), dict) else {}
        category = clip.get("category") if isinstance(clip.get("category"), dict) else {}
        url = str(clip.get("playback_url") or clip.get("clip_url") or clip.get("video_url") or "")
        if not url:
            raise KickError("لینک پخش این کلیپ در دسترس نیست.", "no_clip_playback")
        return {
            "id": str(clip.get("id") or clip_id),
            "url": url,
            "title": _clean_text(clip.get("title")) or "کلیپ Kick",
            "duration": int(clip.get("duration") or 0),
            "thumbnail": str(clip.get("thumbnail_url") or ""),
            "views": int(clip.get("views_count") or clip.get("views") or 0),
            "created_at": str(clip.get("created_at") or ""),
            "category": _clean_text(category.get("name")),
            "creator": _clean_text((clip.get("creator") or {}).get("username")) if isinstance(clip.get("creator"), dict) else "",
            "channel": str(channel.get("slug") or "").lower(),
            "channel_name": _clean_text(channel.get("username")),
            "kind": "clip",
        }

    # ------------------------------------------------------------------ probe
    def probe(self, raw_url: str) -> dict:
        info = classify_url(raw_url)
        kind = info.get("type")
        if kind == "invalid":
            raise KickError("لینک معتبر نیست. یک لینک Kick، HLS یا MP4 وارد کنید.", "bad_url")

        if kind == "channel":
            channel = self.channel(info["slug"], fresh=True)
            if not channel.get("live"):
                return {
                    "type": "channel",
                    "live": False,
                    "title": channel.get("username") or info["slug"],
                    "channel": channel,
                    "variants": [],
                    "message": "این کانال الان لایو نیست.",
                }
            media = self.live_media(info["slug"], fresh=True)
            playlist = media.get("dvr") or media.get("live")
            variants = self._variants_for(playlist)
            return {
                "type": "channel",
                "live": True,
                "title": channel.get("title") or channel.get("username"),
                "channel": channel,
                "variants": variants,
                "has_dvr": bool(media.get("dvr")),
                "playlist_kind": "dvr" if media.get("dvr") else "live",
                "media": {
                    "dvr": bool(media.get("dvr")),
                    "live": bool(media.get("live")),
                    "session_id": media.get("session_id"),
                    "started_at": media.get("started_at"),
                },
            }

        if kind == "vod":
            slug = info.get("slug")
            media = self.vod_media(info["id"], slug)
            variants = self._variants_for(media["url"])
            channel = media.get("channel")
            return {
                "type": "vod",
                "live": False,
                "title": media["title"],
                "channel": channel,
                "variants": variants,
                "duration": media.get("duration") or 0,
                "duration_text": format_seconds(media.get("duration")),
                "thumbnail": media.get("thumbnail") or "",
                "media": {"id": info["id"]},
                "url": info.get("url") or "",
            }

        if kind == "clip":
            clip = self.clip(info["id"])
            variants = self._variants_for(clip["url"])
            return {
                "type": "clip",
                "live": False,
                "title": clip["title"],
                "channel": {
                    "slug": clip.get("channel") or "",
                    "username": clip.get("channel_name") or "",
                    "avatar": "",
                    "live": False,
                },
                "variants": variants,
                "duration": clip.get("duration") or 0,
                "duration_text": format_seconds(clip.get("duration")),
                "thumbnail": clip.get("thumbnail") or "",
                "media": {"id": clip["id"]},
                "url": info.get("url") or "",
            }

        # Direct HLS/MP4 link
        url = info.get("url") or raw_url
        variants = self._variants_for(url)
        name = Path(urlparse(url).path).name or "لینک مستقیم"
        return {
            "type": "direct",
            "live": False,
            "title": name,
            "channel": None,
            "variants": variants,
            "duration": 0,
            "duration_text": "",
            "thumbnail": "",
            "media": {"url": url},
            "url": url,
        }

    def _variants_for(self, playlist_url: str) -> list[dict]:
        if not playlist_url:
            return []
        text = self.get_text(playlist_url)
        variants = parse_master(text, playlist_url)
        return variants

    # -------------------------------------------------------------- downloads
    def resolve_download(self, raw_url: str, source: dict | None = None) -> dict:
        info = classify_url(raw_url)
        kind = info.get("type")
        if kind == "invalid":
            raise KickError("لینک دانلود معتبر نیست.", "bad_url")
        if kind == "channel":
            channel = self.channel(info["slug"], fresh=True)
            if channel.get("live"):
                raise KickError(
                    "این آدرس یک کانال زنده است. برای ضبط زنده از صفحه «ضبط زنده» استفاده کنید.",
                    "channel_is_live",
                )
            raise KickError(
                "برای دانلود، لینک مستقیم یک VOD یا کلیپ را وارد کنید (یا از فهرست کانال انتخاب کنید).",
                "need_media_url",
            )

        if kind == "vod":
            media = self.vod_media(info["id"], info.get("slug"))
            title = media["title"]
            channel = media.get("channel")
            master_url = media["url"]
            variants = self._variants_for(master_url)
            chosen = select_variant(variants, source)
            return {
                "kind": "vod",
                "title": title,
                "channel": channel,
                "master_url": master_url,
                "input_url": chosen["url"] if chosen else master_url,
                "variants": variants,
                "source": source_from_variant(chosen),
                "duration": media.get("duration") or 0,
                "thumbnail": media.get("thumbnail") or "",
                "original_url": raw_url,
            }

        if kind == "clip":
            clip = self.clip(info["id"])
            master_url = clip["url"]
            variants = self._variants_for(master_url)
            chosen = select_variant(variants, source)
            return {
                "kind": "clip",
                "title": clip["title"],
                "channel": {
                    "slug": clip.get("channel") or "",
                    "username": clip.get("channel_name") or "",
                },
                "master_url": master_url,
                "input_url": chosen["url"] if chosen else master_url,
                "variants": variants,
                "source": source_from_variant(chosen),
                "duration": clip.get("duration") or 0,
                "thumbnail": clip.get("thumbnail") or "",
                "original_url": raw_url,
            }

        url = info.get("url") or raw_url
        variants = self._variants_for(url)
        chosen = select_variant(variants, source)
        name = Path(urlparse(url).path).name or "media"
        return {
            "kind": "direct",
            "title": name,
            "channel": None,
            "master_url": url,
            "input_url": chosen["url"] if chosen else url,
            "variants": variants,
            "source": source_from_variant(chosen),
            "duration": 0,
            "thumbnail": "",
            "original_url": raw_url,
        }

    # ------------------------------------------------------------- utilities
    def choose_playback_url(self, media: dict, from_start: bool) -> tuple[str, bool]:
        """Return (playlist_url, is_from_start)."""
        dvr = str(media.get("dvr") or "")
        live = str(media.get("live") or "")
        if from_start and dvr:
            return dvr, True
        if live:
            return live, False
        return dvr, bool(dvr)

    def choose_input(self, media: dict, source: dict | None, from_start: bool) -> dict:
        playlist, is_from_start = self.choose_playback_url(media, from_start)
        variants = self._variants_for(playlist)
        chosen = select_variant(variants, source)
        return {
            "playlist": playlist,
            "input_url": chosen["url"] if chosen else playlist,
            "variant": chosen,
            "variants": variants,
            "from_start": is_from_start,
        }

    def candidate_urls(self, media: dict, source: dict | None, from_start: bool) -> list[str]:
        playlist, _ = self.choose_playback_url(media, from_start)
        variants = self._variants_for(playlist)
        chosen = select_variant(variants, source)
        return candidate_variant_urls(playlist, variants, chosen)
