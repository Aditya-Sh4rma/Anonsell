# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import os
import re
import aiohttp
from pathlib import Path

from py_yt import VideosSearch, Playlist

from anony import logger
from anony.helpers import Track, utils


FALLBACK_API_URL = "https://shrutibots.site"
_api_url: str | None = None


async def _load_api_url() -> None:
    global _api_url
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://pastebin.com/raw/rLsBhAQa",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    _api_url = (await resp.text()).strip()
                    logger.info("YouTube API URL loaded successfully.")
                    return
    except Exception:
        pass
    _api_url = FALLBACK_API_URL
    logger.warning(f"Using fallback YouTube API URL: {FALLBACK_API_URL}")


async def _get_api_url() -> str:
    global _api_url
    if not _api_url:
        await _load_api_url()
    return _api_url


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from a URL or return as-is if already an ID."""
        if "v=" in url:
            return url.split("v=")[-1].split("&")[0]
        if "youtu.be/" in url:
            return url.split("youtu.be/")[-1].split("?")[0]
        return url  # already a raw video ID

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            _search = VideosSearch(query, limit=1)
            results = await _search.next()
            if results and results.get("result"):
                data = results["result"][0]
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    message_id=m_id,
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=video,
                )
        except Exception as ex:
            logger.warning(f"YouTube search failed: {ex}")
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist.get("videos", [])[:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
                    url=data.get("link", "").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception as ex:
            logger.warning(f"YouTube playlist fetch failed: {ex}")
        return tracks

    async def _api_download(self, video_id: str, video: bool = False) -> str | None:
        """Download audio/video via API and return local file path."""
        api_url = await _get_api_url()
        ext = "mp4" if video else "mp3"
        file_path = f"downloads/{video_id}.{ext}"
        media_type = "video" if video else "audio"

        if Path(file_path).exists():
            return file_path

        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: Request download token
                async with session.get(
                    f"{api_url}/download",
                    params={"url": video_id, "type": media_type},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"API token request failed: HTTP {resp.status}")
                        return None
                    data = await resp.json()
                    token = data.get("download_token")
                    if not token:
                        logger.warning("API returned no download_token.")
                        return None

                # Step 2: Stream file using token
                stream_url = f"{api_url}/stream/{video_id}?type={media_type}"
                timeout = aiohttp.ClientTimeout(total=600 if video else 300)
                async with session.get(
                    stream_url,
                    headers={"X-Download-Token": token},
                    timeout=timeout,
                ) as file_resp:
                    if file_resp.status != 200:
                        logger.warning(f"API stream failed: HTTP {file_resp.status}")
                        return None
                    with open(file_path, "wb") as f:
                        async for chunk in file_resp.content.iter_chunked(16384):
                            f.write(chunk)

            return file_path

        except asyncio.TimeoutError:
            logger.warning(f"API download timed out for {video_id}")
        except Exception as ex:
            logger.warning(f"API download failed for {video_id}: {ex}")

        # Clean up partial file if exists
        if Path(file_path).exists():
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None

    async def download(self, video_id: str, video: bool = False) -> str | None:
        """
        Main download entry point.
        Tries API first; returns file path or None on failure.
        """
        return await self._api_download(video_id, video=video)
