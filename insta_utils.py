import os
import asyncio
import tempfile
import time
from yt_dlp import YoutubeDL
import imageio_ffmpeg as ffmpeg

# Общая функция загрузки через yt-dlp, выполняется в executor (не блокирует event loop)
async def _download_with_yt_dlp(url: str, out_path: str, ydl_opts_extra: dict = None) -> str | None:
    loop = asyncio.get_running_loop()

    def _run():
        # Подставляем ffmpeg из imageio-ffmpeg, чтобы не требовать системного ffmpeg
        ffmpeg_path = ffmpeg.get_ffmpeg_exe()
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": out_path,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            # Передаём путь до ffmpeg, если yt-dlp будет его использовать
            "ffmpeg_location": ffmpeg_path,
            # Уменьшаем вероятность проблем с сертификатами/заголовками
            "http_chunk_size": 0,
        }
        if ydl_opts_extra:
            ydl_opts.update(ydl_opts_extra)

        # Убедимся, что директория для файла существует
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            # yt-dlp пишет много информации сам; здесь логируем просто для отладки
            print(f"❌ yt-dlp error for {url}: {e}")

    try:
        await loop.run_in_executor(None, _run)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception as e:
        print(f"Executor error: {e}")
    return None

# Использовать временные файлы в /tmp (подходит для Render)
def _temp_filename(prefix="video", ext="mp4"):
    ts = int(time.time() * 1000)
    return os.path.join(tempfile.gettempdir(), f"{prefix}_{ts}.{ext}")

# Интерфейс для Instagram (и TikTok, если нужно)
async def get_instagram_video(url: str) -> str | None:
    """
    Скачивает видео с Instagram (также может работать для коротких ссылок TikTok/прочих),
    возвращает путь к файлу или None.
    """
    out = _temp_filename("insta", "mp4")
    return await _download_with_yt_dlp(url, out)

# Интерфейс для YouTube
async def get_youtube_video(url: str) -> str | None:
    """
    Скачивает YouTube видео (лучший вариант) и возвращает путь к mp4 файлу.
    """
    out = _temp_filename("yt", "mp4")
    # Можно задать дополнительные опции, например ограничение по длительности/размеру
    # ydl_opts_extra = {"max_filesize": 200000000}  # пример
    return await _download_with_yt_dlp(url, out)

# (Опционально) Удаление файла — можно вызывать из бота после отправки
def cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Не удалось удалить файл {path}: {e}")

