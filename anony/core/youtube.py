import asyncio
import os
import re
import time
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
USE_SHRUTI_FALLBACK = False


async def _download_file(video_id: str, media_type: str) -> str | None:
    ext = "mp4" if media_type == "video" else "mp3"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")

    if Path(file_path).exists() and os.path.getsize(file_path) > 0:
        logger.info(f"[DEBUG] {video_id}: already cached at {file_path}, skipping download")
        return file_path

    timeout_sec = 600 if media_type == "video" else 300

    # ── DEVIL API ATTEMPT ────────────────────────────────────────
    logger.info(f"[DEBUG] {video_id}: DEVIL_API_URL={'set' if DEVIL_API_URL else 'EMPTY'}, "
                f"DEVIL_API_KEY={'set' if DEVIL_API_KEY else 'EMPTY'}")

    if DEVIL_API_URL and DEVIL_API_KEY:
        devil_start = time.monotonic()
        request_url = f"{DEVIL_API_URL}/download"
        params = {"url": video_id, "type": media_type, "api_key": DEVIL_API_KEY}
        logger.info(f"[DEBUG] {video_id}: attempting Devil API -> GET {request_url} "
                    f"params={{'url': '{video_id}', 'type': '{media_type}', 'api_key': '***'}} "
                    f"timeout={timeout_sec}s")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    request_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout_sec),
                ) as resp:
                    elapsed = round(time.monotonic() - devil_start, 2)
                    logger.info(f"[DEBUG] {video_id}: Devil API responded HTTP {resp.status} "
                                f"in {elapsed}s, content-type={resp.headers.get('content-type')}, "
                                f"content-length={resp.headers.get('content-length')}")

                    if resp.status == 200:
                        bytes_written = 0
                        with open(file_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(131072):
                                f.write(chunk)
                                bytes_written += len(chunk)
                        logger.info(f"[DEBUG] {video_id}: Devil API wrote {bytes_written} bytes to {file_path}")

                        if Path(file_path).exists() and os.path.getsize(file_path) > 0:
                            logger.info(f"[DEBUG] {video_id}: SUCCESS via Devil API "
                                        f"(file size={os.path.getsize(file_path)} bytes, total time={elapsed}s)")
                            return file_path
                        else:
                            logger.warning(f"[DEBUG] {video_id}: Devil API returned 200 but file "
                                            f"is missing or empty after write")
                    else:
                        # Try to read body for error detail (APIs often return JSON error on non-200)
                        try:
                            body_text = await resp.text()
                            logger.warning(f"[DEBUG] {video_id}: Devil API non-200 body: {body_text[:500]}")
                        except Exception as read_ex:
                            logger.warning(f"[DEBUG] {video_id}: could not read Devil API error body: {read_ex}")
        except asyncio.TimeoutError:
            elapsed = round(time.monotonic() - devil_start, 2)
            logger.warning(f"[DEBUG] {video_id}: Devil API TIMEOUT after {elapsed}s (limit was {timeout_sec}s)")
        except aiohttp.ClientConnectorError as ex:
            elapsed = round(time.monotonic() - devil_start, 2)
            logger.warning(f"[DEBUG] {video_id}: Devil API CONNECTION FAILED after {elapsed}s: {ex} "
                            f"(this usually means DNS failure, refused connection, or network block)")
        except aiohttp.ClientError as ex:
            elapsed = round(time.monotonic() - devil_start, 2)
            logger.warning(f"[DEBUG] {video_id}: Devil API client error after {elapsed}s: {type(ex).__name__}: {ex}")
        except Exception as ex:
            elapsed = round(time.monotonic() - devil_start, 2)
            logger.warning(f"[DEBUG] {video_id}: Devil API unexpected error after {elapsed}s: "
                            f"{type(ex).__name__}: {ex}")
    else:
        logger.info(f"[DEBUG] {video_id}: skipping Devil API — URL or KEY not set in environment")

    if not USE_SHRUTI_FALLBACK:
        logger.info(f"[DEBUG] {video_id}: Shruti fallback is DISABLED for this debug run "
                    f"(USE_SHRUTI_FALLBACK=False) — stopping here so failure is isolated to Devil API")
        if Path(file_path).exists():
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None

    logger.info(f"[DEBUG] {video_id}: SHRUTI_API_URL={SHRUTI_API_URL}, "
                f"SHRUTI_API_KEY={'set' if SHRUTI_API_KEY else 'EMPTY'}")
    shruti_start = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SHRUTI_API_URL}/download",
                params={"url": video_id, "type": media_type, "api_key": SHRUTI_API_KEY},
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                elapsed = round(time.monotonic() - shruti_start, 2)
                logger.info(f"[DEBUG] {video_id}: Shruti API responded HTTP {resp.status} in {elapsed}s")
                if resp.status != 200:
                    body_text = await resp.text()
                    logger.warning(f"[DEBUG] {video_id}: Shruti failed: HTTP {resp.status}, body: {body_text[:500]}")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)

        if Path(file_path).exists() and os.path.getsize(file_path) > 0:
            logger.info(f"[DEBUG] {video_id}: SUCCESS via Shruti API (file size={os.path.getsize(file_path)} bytes)")
            return file_path
        return None

    except asyncio.TimeoutError:
        logger.warning(f"[DEBUG] {video_id}: Shruti API TIMEOUT after {timeout_sec}s")
    except aiohttp.ClientConnectorError as ex:
        logger.warning(f"[DEBUG] {video_id}: Shruti CONNECTION FAILED: {ex}")
    except Exception as ex:
        logger.warning(f"[DEBUG] {video_id}: Shruti failed: {type(ex).__name__}: {ex}")

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
        search_start = time.monotonic()
        logger.info(f"[DEBUG] search: querying py_yt for '{query}'")
        try:
            _search = VideosSearch(query, limit=1)
            results = await _search.next()
            elapsed = round(time.monotonic() - search_start, 2)

            if results and results.get("result"):
                data = results["result"][0]
                logger.info(f"[DEBUG] search: SUCCESS in {elapsed}s -> id={data.get('id')}, "
                            f"title={data.get('title')[:40]!r}")
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
            else:
                logger.warning(f"[DEBUG] search: py_yt returned no results for '{query}' "
                                f"in {elapsed}s (raw results={results!r})")
        except Exception as ex:
            elapsed = round(time.monotonic() - search_start, 2)
            logger.warning(f"[DEBUG] search failed after {elapsed}s: {type(ex).__name__}: {ex}")
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
        logger.info(f"[DEBUG] download: starting for video_id={video_id}, media_type={media_type}")
        result = await _download_file(video_id, media_type)
        if result:
            logger.info(f"[DEBUG] download: FINAL RESULT for {video_id} -> {result}")
        else:
            logger.warning(f"[DEBUG] download: FINAL RESULT for {video_id} -> None (all sources failed)")
        return result
