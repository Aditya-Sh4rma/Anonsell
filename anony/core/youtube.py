# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import os
import re
import aiohttp
from pathlib import Path
from urllib.parse import quote_plus

from py_yt import VideosSearch, Playlist

from anony import logger
from anony.helpers import Track, utils


API_URL = "https://kartik.opusx.workers.dev/yt"


async def _fetch_json_aio(session: aiohttp.ClientSession, url: str):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None


async def _download_stream_aio(session: aiohttp.ClientSession, url: str, dest_path: str):
    try:
        async with session.get(url, timeout=None) as resp:
            if resp.status != 200:
                return False
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(16384):
                    f.write(chunk)
            return True
    except Exception:
        return False


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
        if "v=" in url:
            return url.split("v=")[-1].split("&")[0]
        if "youtu.be/" in url:
            return url.split("youtu.be/")[-1].split("?")[0]
        return url

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
        link = self.base + video_id
        media_type = "video" if video else "audio"
        format_param = "mp4" if video else "mp3"

        if video:
            for ext in ["mp4", "webm", "mkv"]:
                file_path = f"downloads/{video_id}.{ext}"
                if Path(file_path).exists():
                    return file_path
        else:
            for ext in ["mp3", "m4a", "webm"]:
                file_path = f"downloads/{video_id}.{ext}"
                if Path(file_path).exists():
                    return file_path

        file_path = f"downloads/{video_id}.{format_param}"
        api_url = f"{API_URL}?url={quote_plus(link)}&type={media_type}&format={format_param}"

        try:
            async with aiohttp.ClientSession() as session:
                data = await _fetch_json_aio(session, api_url)
                if not data:
                    return None
                if not data.get("success", False):
                    return None
                download_url = data.get("download_url")
                if not download_url:
                    return None
                ok = await _download_stream_aio(session, download_url, file_path)
                return file_path if ok else None
        except asyncio.TimeoutError:
            logger.warning(f"API download timed out for {video_id}")
        except Exception as ex:
            logger.warning(f"API download failed for {video_id}: {ex}")

        if Path(file_path).exists():
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None

    async def download(self, video_id: str, video: bool = False) -> str | None:
        return await self._api_download(video_id, video=video)
