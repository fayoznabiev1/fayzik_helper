import os
import asyncio
import tempfile
import time
import shutil
from typing import Optional
from yt_dlp import YoutubeDL

# Чтение конфигурации из переменных окружения
# COOKIES_FILE - путь на файловой системе к cookies.txt (если вы загрузили файл)
# COOKIES_TXT  - сам текст cookies.txt (многострочный) — удобно хранить как секрет в Render
# COOKIES_FROM_BROWSER - имя браузера для cookiesfrombrowser (например "chrome"), но на Render обычно не работает
# YTDLP_PROXY - строка прокси (например "http://user:pass@host:port") (опционально)
COOKIES_FILE = os.getenv("COOKIES_FILE")
COOKIES_TXT = os.getenv("COOKIES_TXT")
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER")
YTDLP_PROXY = os.getenv("YTDLP_PROXY")

def _temp_filename(prefix="video", ext="mp4"):
    ts = int(time.time() * 1000)
    return os.path.join(tempfile.gettempdir(), f"{prefix}_{ts}.{ext}")

def _prepare_cookiefile() -> Optional[str]:
    """
    Возвращает путь к cookies файлу, если он доступен.
    Приоритет:
    1) COOKIES_FILE (существующий путь)
    2) COOKIES_TXT (записываем в файл в /tmp и возвращаем путь)
    3) None
    """
    # 1) если задан путь и файл существует
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        return COOKIES_FILE

    # 2) если задан текст cookies, создаём временный файл
    if COOKIES_TXT:
        path = os.path.join(tempfile.gettempdir(), f"cookies_{int(time.time()*1000)}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(COOKIES_TXT)
            return path
        except Exception as e:
            print(f"⚠️ Не удалось записать COOKIES_TXT в файл: {e}")
            return None

    # 3) нет cookies
    return None

async def _download_with_yt_dlp(url: str, out_path: str, ydl_opts_extra: dict = None) -> Optional[str]:
    loop = asyncio.get_running_loop()

    # Подготовим cookiefile (может быть None)
    cookiefile = _prepare_cookiefile()
    is_temp_cookiefile = bool(os.getenv("COOKIES_TXT")) and cookiefile and (not COOKIES_FILE)

    def _run():
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": out_path,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            # Уменьшаем проблемы с заголовками/сертификатами
            "http_chunk_size": 0,
        }

        # прокси, если указан
        if YTDLP_PROXY:
            ydl_opts["proxy"] = YTDLP_PROXY

        # cookies
        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile
        elif COOKIES_FROM_BROWSER:
            # попытаемся использовать cookiesfrombrowser (на сервере обычно не работает, но допустим)
            ydl_opts["cookiesfrombrowser"] = COOKIES_FROM_BROWSER

        # дополнительные опции
        if ydl_opts_extra:
            ydl_opts.update(ydl_opts_extra)

        # Убедимся, что директория для файла существует
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except Exception:
            pass

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            print(f"❌ yt-dlp error for {url}: {e}")

    try:
        await loop.run_in_executor(None, _run)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception as e:
        print(f"Executor error: {e}")
    finally:
        # удалим временный cookie файл, если он был создан из COOKIES_TXT
        if is_temp_cookiefile and cookiefile:
            try:
                os.remove(cookiefile)
            except Exception:
                pass

    return None

async def get_instagram_video(url: str) -> Optional[str]:
    """
    Скачивает видео с Instagram (также может работать для некоторых TikTok/прочих).
    Возвращает путь к файлу или None.
    """
    out = _temp_filename("insta", "mp4")
    # можно добавить дополнительные опции, например ограничение размера
    return await _download_with_yt_dlp(url, out)

async def get_youtube_video(url: str) -> Optional[str]:
    """
    Скачивает YouTube видео и возвращает путь к mp4 файлу.
    """
    out = _temp_filename("yt", "mp4")
    return await _download_with_yt_dlp(url, out)

def cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Не удалось удалить файл {path}: {e}")

