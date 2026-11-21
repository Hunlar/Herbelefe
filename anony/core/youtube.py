# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.

import asyncio
import re
import random
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import aiohttp
import yt_dlp
from py_yt import Playlist, VideosSearch

from anony import config, logger
from anony.helpers import Track, utils


class DummyLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = Path(__file__).resolve().parent.parent / "cookies"
        self.download_dir = Path("downloads")
        self.warned = False

    def _youtube_id(self, url: str) -> str | None:
        try:
            parsed = urlparse(url if "://" in url else "https://" + url)
            host = (parsed.hostname or "").lower()
            if host in {"youtu.be", "www.youtu.be"}:
                value = parsed.path.strip("/").split("/")[0]
                return value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value) else None
            if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
                if parsed.path == "/watch":
                    value = parse_qs(parsed.query).get("v", [None])[0]
                elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/live/"):
                    value = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
                else:
                    value = None
                return value if value and re.fullmatch(r"[A-Za-z0-9_-]{11}", value) else None
        except Exception:
            pass
        return None

    def valid(self, url: str) -> bool:
        return bool(self._youtube_id(url) or re.search(r"youtube\.com/playlist\?list=", url))

    def invalid(self, url: str) -> bool:
        return bool(re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/", url) and not self.valid(url))

    def get_cookies(self):
        if not self.checked:
            self.cookie_dir.mkdir(parents=True, exist_ok=True)
            self.cookies = [str(p.resolve()) for p in self.cookie_dir.glob("*.txt") if p.is_file()]
            self.checked = True
            if self.cookies:
                logger.info("Found %s cookie file(s).", len(self.cookies))
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("YouTube cookies are not configured in %s", self.cookie_dir)
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        cookie_path = self.cookie_dir / "cookies.txt"

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                async with session.get(url, allow_redirects=True) as resp:
                    resp.raise_for_status()
                    content = await resp.read()
                    if not content.strip():
                        raise ValueError("Downloaded YouTube cookies file is empty")
                    cookie_path.write_bytes(content)

        self.cookies = [
            str(p.resolve())
            for p in self.cookie_dir.glob("*.txt")
            if p.is_file() and p.stat().st_size > 0
        ]
        self.checked = True
        if self.cookies:
            logger.info("YouTube cookies downloaded successfully.")

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            results = await VideosSearch(query, limit=1, with_live=False).next()
            if results and results.get("result"):
                data = results["result"][0]
                thumbs = data.get("thumbnails") or [{}]
                return Track(
                    id=data.get("id"), channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"), duration_sec=utils.to_seconds(data.get("duration")),
                    message_id=m_id, title=(data.get("title") or "Unknown")[:25],
                    thumbnail=(thumbs[-1].get("url") or "").split("?")[0],
                    url=data.get("link"), view_count=data.get("viewCount", {}).get("short"), video=video,
                )
        except Exception as ex:
            logger.warning("YouTube search failed: %s", ex)
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in (plist.get("videos") or [])[:limit]:
                thumbs = data.get("thumbnails") or [{}]
                tracks.append(Track(
                    id=data.get("id"), channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"), duration_sec=utils.to_seconds(data.get("duration") or "0:00"),
                    title=(data.get("title") or "Unknown")[:25],
                    thumbnail=(thumbs[-1].get("url") or "").split("?")[0],
                    url=(data.get("link") or "").split("&list=")[0], user=user,
                    view_count="", video=video,
                ))
        except Exception as ex:
            logger.warning("YouTube playlist fetch failed: %s", ex)
        return tracks

    async def download(
        self, video_id: str, video: bool = False, audio_format: str | None = None
    ) -> str | None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        extension = "mp4" if video else (audio_format or "webm")
        expected = self.download_dir / f"{video_id}.{extension}"
        if expected.exists() and expected.stat().st_size > 0:
            return str(expected)

        url = self.base + video_id
        cookie = self.get_cookies()
        opts = {
            "outtmpl": str(self.download_dir / "%(id)s.%(ext)s"),
            "quiet": True, "noplaylist": True, "geo_bypass": True,
            "no_warnings": True, "overwrites": False,
            "logger": DummyLogger(), "nocheckcertificate": True,
            "remote_components": ["ejs:github"],
            "retries": 3, "fragment_retries": 3, "continuedl": True,
            "max_filesize": config.DOWNLOAD_LIMIT_BYTES,
        }
        if cookie:
            opts["cookiefile"] = cookie
        if video:
            opts.update({
                "format": "best[height<=720][ext=mp4]/best[height<=720]/best",
                "merge_output_format": "mp4",
            })
        elif audio_format:
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "192",
                }],
            })
        else:
            opts.update({"format": "bestaudio[ext=webm]/bestaudio", "postprocessors": []})

        def _download():
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    prepared = Path(ydl.prepare_filename(info))
                    candidates = [prepared]
                    if video and prepared.suffix.lower() != ".mp4":
                        candidates.insert(0, prepared.with_suffix(".mp4"))
                    elif audio_format and prepared.suffix.lower() != f".{audio_format}":
                        candidates.insert(0, prepared.with_suffix(f".{audio_format}"))
                    for candidate in candidates:
                        if candidate.exists() and candidate.stat().st_size:
                            return str(candidate)
                    # yt-dlp bazen birleştirme sonrası uzantıyı değiştirir.
                    matches = sorted(self.download_dir.glob(f"{video_id}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
                    return str(matches[0]) if matches and matches[0].stat().st_size else None
            except Exception as ex:
                logger.warning("YouTube download failed (%s): %s", video_id, ex)
                return None

        return await asyncio.to_thread(_download)
