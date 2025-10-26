import os
import asyncio
import tempfile
import time
from yt_dlp import YoutubeDL
import imageio_ffmpeg as ffmpeg

"""
insta_utils.py
- Скачивает публичные видео (Instagram/YouTube/TikTok) через yt-dlp.
- Работает в executor чтобы не блокировать asyncio loop.
- Пишет временный файл в tempfile.gettempdir() и возвращает путь.
- Ограничивает максимальный размер загрузки (по умолчанию 50 MB).
"""

DEFAULT_MAX_FILESIZE_BYTES = int(os.getenv("MAX_FILESIZE_BYTES", 50 * 1024 * 1024))  # 50 MB by default

def _temp_filename(prefix="video", ext="mp4"):
    ts = int(time.time() * 1000)
    return os.path.join(tempfile.gettempdir(), f"{prefix}_{ts}.{ext}")

async def _download_with_yt_dlp(url: str, out_path: str, max_filesize: int = None, ydl_opts_extra: dict = None) -> str | None:
    loop = asyncio.get_running_loop()
    max_filesize = max_filesize or DEFAULT_MAX_FILESIZE_BYTES

    # Get packaged ffmpeg binary path (if available). yt-dlp will use it if merging required.
    try:
        ffmpeg_path = ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_path = None

    def _run():
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": out_path,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noplaylist": True,
            # reduce chunking issues
            "http_chunk_size": 0,
        }

        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = ffmpeg_path

        # set max filesize if supported
        if max_filesize:
            # yt-dlp accepts int bytes for "max_filesize"
            ydl_opts["max_filesize"] = max_filesize

        if ydl_opts_extra:
            ydl_opts.update(ydl_opts_extra)

        try:
            # ensure dir exists
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except Exception:
            pass

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            # yt-dlp writes lots of info itself; we keep a concise message
            print(f"❌ yt-dlp error for {url}: {e}")

    try:
        await loop.run_in_executor(None, _run)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            # final size check
            size = os.path.getsize(out_path)
            if max_filesize and size > max_filesize:
                print(f"⚠️ Downloaded file bigger than max_filesize: {size} > {max_filesize}")
                try:
                    os.remove(out_path)
                except Exception:
                    pass
                return None
            return out_path
    except Exception as e:
        print(f"Executor error: {e}")
    return None

# Public Instagram and TikTok (public) downloader
async def get_instagram_video(url: str, max_filesize: int | None = None) -> str | None:
    out = _temp_filename("insta", "mp4")
    return await _download_with_yt_dlp(url, out, max_filesize=max_filesize)

# YouTube downloader
async def get_youtube_video(url: str, max_filesize: int | None = None) -> str | None:
    out = _temp_filename("yt", "mp4")
    # for youtube you might want to limit resolution or duration via ydl_opts_extra
    return await _download_with_yt_dlp(url, out, max_filesize=max_filesize)

def cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Не удалось удалить файл {path}: {e}")

