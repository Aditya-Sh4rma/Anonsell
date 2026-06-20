import asyncio
import os
import re
import aiohttp
from pathlib import Path

from py_yt import VideosSearch, Playlist

from anony import logger
from anony.helpers import Track, utils


DEVIL_API_URL = os.environ.get("DEVIL_API_URL", "")
DEVIL_API_KEY = os.environ.get("DEVIL_API_KEY", "")

SHRUTI_API_URL = os.environ.get("SHRUTI_API_URL", "https://api.shrutibots.site")
SHRUTI_API_KEY = os.environ.get("SHRUTI_API_KEY", "")

DOWNLOAD_DIR = "downloads"


async def _download_file(video_id: str, media_type: str) -> str | None:
    ext = "mp4" if media_type == "video" else "mp3"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")

    if Path(file_path).exists() and os.path.getsize(file_path) > 0:
        return file_path

    timeout_sec = 600 if media_type == "video" else 300

    if DEVIL_API_URL and DEVIL_API_KEY:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DEVIL_API_URL}/download",
                    params={"url": video_id, "type": media_type, "api_key": DEVIL_API_KEY},
                    timeout=aiohttp.ClientTimeout(total=timeout_sec),
                ) as resp:
                    if resp.status == 200:
                        with open(file_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(131072):
                                f.write(chunk)
                        if Path(file_path).exists() and os.path.getsize(file_path) > 0:
                            logger.info(f"{video_id}: devil api")
                            return file_path
        except Exception as ex:
            logger.warning(f"{video_id}: devil failed: {ex}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SHRUTI_API_URL}/download",
                params={"url": video_id, "type": media_type, "api_key": SHRUTI_API_KEY},
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"{video_id}: shruti failed: HTTP {resp.status}")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)

        if Path(file_path).exists() and os.path.getsize(file_path) > 0:
            logger.info(f"{video_id}: shruti api")
            return file_path
        return None

    except asyncio.TimeoutError:
        logger.warning(f"{video_id}: shruti timeout")
    except Exception as ex:
        logger.warning(f"{video_id}: shruti failed: {ex}")

    if Path(file_path).exists():
        try:
            os.remove(file_path)
        except Exception:
            pass
    return None


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
            logger.warning(f"search failed: {ex}")
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
            logger.warning(f"playlist failed: {ex}")
        return tracks

    async def download(self, video_id: str, video: bool = False) -> str | None:
        media_type = "video" if video else "audio"
        return await _download_file(video_id, media_type)
