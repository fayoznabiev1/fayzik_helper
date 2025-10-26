# Унифицированный модуль скачивания через yt-dlp
# Поддерживает:
# - cookies (COOKIES_FILE или COOKIES_TXT env)
# - proxy (YTDLP_PROXY env)
# - ограничение размера
# - запуск yt-dlp в executor (не блокирует asyncio)
# - cleanup_file для удаления временных файлов
import os
import time
import tempfile
import asyncio
from typing import Optional, Dict, Any
from yt_dlp import YoutubeDL

# Опции из окружения
COOKIES_FILE = os.getenv("COOKIES_FILE")       # путь к cookies.txt, если есть
COOKIES_TXT = os.getenv("COOKIES_TXT")         # содержимое cookies.txt (многострочный)
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER")  # например "chrome" (на серверах обычно не работает)
YTDLP_PROXY = os.getenv("YTDLP_PROXY")         # пример: "http://user:pass@host:port"
DEFAULT_MAX_FILESIZE = int(os.getenv("MAX_FILESIZE_BYTES", 50 * 1024 * 1024))  # 50 MB

def _temp_filename(prefix="video", ext="mp4") -> str:
    ts = int(time.time() * 1000)
    return os.path.join(tempfile.gettempdir(), f"{prefix}_{ts}.{ext}")

def _write_temp_cookies(txt: str) -> Optional[str]:
    try:
        path = os.path.join(tempfile.gettempdir(), f"cookies_{int(time.time()*1000)}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt)
        return path
    except Exception as e:
        print(f"⚠️ Не удалось записать cookies в файл: {e}")
        return None

def _prepare_cookiefile() -> Optional[str]:
    # приоритет: COOKIES_FILE (существующий файл) -> COOKIES_TXT (создать) -> None
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        return COOKIES_FILE
    if COOKIES_TXT:
        return _write_temp_cookies(COOKIES_TXT)
    return None

async def _run_yt_dlp(url: str, out_path: str, max_filesize: int | None = None, ydl_opts_extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Выполняет yt-dlp в blocking executor. Возвращает dict:
    { "path": str | None, "error": str | None, "info": dict | None }
    """
    loop = asyncio.get_running_loop()
    cookiefile = _prepare_cookiefile()
    is_temp_cookie = bool(COOKIES_TXT) and cookiefile and (not (COOKIES_FILE and os.path.exists(COOKIES_FILE)))

    def _worker():
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": out_path,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noplaylist": True,
            # уменьшить шансы проблем с chunked downloads
            "http_chunk_size": 0,
        }

        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile
        elif COOKIES_FROM_BROWSER:
            ydl_opts["cookiesfrombrowser"] = COOKIES_FROM_BROWSER

        if YTDLP_PROXY:
            ydl_opts["proxy"] = YTDLP_PROXY

        if max_filesize:
            ydl_opts["max_filesize"] = max_filesize

        if ydl_opts_extra:
            ydl_opts.update(ydl_opts_extra)

        try:
            # ensure dir exists
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except Exception:
            pass

        result = {"path": None, "error": None, "info": None}
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                result["info"] = info
                # if yt-dlp created out_path, set path
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    result["path"] = out_path
        except Exception as e:
            result["error"] = str(e)
        return result

    try:
        result = await loop.run_in_executor(None, _worker)
        return result
    finally:
        # удаляем временный cookie файл если он был создан из COOKIES_TXT
        if is_temp_cookie and cookiefile and os.path.exists(cookiefile):
            try:
                os.remove(cookiefile)
            except Exception:
                pass

async def download_media(url: str, max_filesize: int | None = None) -> Dict[str, Any]:
    """
    Основная функция для вызова из бота.
    Возвращает dict с ключами:
      - path (str|None)
      - error (str|None)
      - info (dict|None) - если yt-dlp вернул metadata
    """
    out = _temp_filename("media", "mp4")
    max_fs = max_filesize or DEFAULT_MAX_FILESIZE
    res = await _run_yt_dlp(url, out, max_filesize=max_fs)
    # если файл > max_filesize, удаляем и считаем ошибкой
    if res.get("path"):
        try:
            size = os.path.getsize(res["path"])
            if max_fs and size > max_fs:
                try:
                    os.remove(res["path"])
                except Exception:
                    pass
                return {"path": None, "error": f"file_too_large ({size} bytes)", "info": res.get("info")}
        except Exception:
            pass
    return res

def cleanup_file(path: Optional[str]):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Не удалось удалить файл {path}: {e}")
