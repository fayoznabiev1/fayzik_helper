import os
import logging
import aiohttp
import uuid
import asyncio
import time
from collections import defaultdict
from insta_utils import download_media, cleanup_file
from typing import Dict
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BufferedInputFile
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

# Импорты для webhook / aiohttp (перенесены вверх, чтобы не дублироваться внизу)
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# Загрузить переменные окружения из .env файла
load_dotenv()

# ==== Настройки ====
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

if not all([BOT_TOKEN, OPENAI_API_KEY, NEWS_API_KEY, OPENWEATHER_API_KEY]):
    raise ValueError("Одна или несколько переменных окружения не заданы!")

client = OpenAI(api_key=OPENAI_API_KEY)


# ==== Параметры параллелизма и очередь задач ====
MAX_PARALLEL_DOWNLOADS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", 2))
download_semaphore = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)

# 2) Глобальная очередь/хранилище задач (в начале файла, рядом с user_downloads)
download_jobs: Dict[str, asyncio.Task] = {}  # job_id -> Task

# 3) Функция фоновой задачи (делает загрузку и отправляет результат пользователю)
async def _background_download_and_send(chat_id: int, url: str, job_id: str, max_size: int):
    """
    Загружает медиа и отправляет пользователю.
    Эта функция запускается через asyncio.create_task — поэтому не блокирует webhook.
    Добавлен семафор для ограничения параллельных загрузок и логирование.
    """
    try:
        # Уведомим пользователя, что задача в работе (можно редактировать предыдущее сообщение)
        try:
            await bot.send_message(chat_id, f"⏳ Обработка ссылки... (job {job_id})")
        except Exception:
            logging.exception("Не удалось отправить 'обработка' сообщение пользователю")

        # ограничиваем количество одновременно выполняемых загрузок
        async with download_semaphore:
            try:
                result = await download_media(url, max_filesize=max_size)
            except Exception:
                logging.exception("Фатальная ошибка при вызове download_media")
                try:
                    await bot.send_message(chat_id, "❌ Внутренняя ошибка при попытке скачать файл.")
                except Exception:
                    pass
                return

        if result.get("error"):
            # если yt-dlp вернул специфическую ошибку — сообщим пользователю понятным образом
            err = result["error"] or ""
            err_low = err.lower()
            if "login required" in err_low or "sign in" in err_low:
                await bot.send_message(chat_id, "❌ Не удалось скачать: требуется авторизация (cookies) или сервис блокирует запросы.")
            elif "file_too_large" in err:
                await bot.send_message(chat_id, "⚠️ Файл получился слишком большим для отправки.")
            else:
                # более детализированное сообщение без утечки секретов
                await bot.send_message(chat_id, f"❌ Ошибка при скачивании: {err}")
            return

        path = result.get("path")
        if not path:
            await bot.send_message(chat_id, "❌ Не удалось скачать файл. Попробуй публичную ссылку или используй cookies.")
            return

        # Отправляем файл — если большой, можно отправить как документ
        try:
            size = os.path.getsize(path)
            # Если файл маленький, отправляем как видео, иначе как документ
            threshold = int(os.getenv("TELEGRAM_VIDEO_THRESHOLD", 50 * 1024 * 1024))
            if size <= threshold:
                await bot.send_video(chat_id, video=FSInputFile(path))
            else:
                await bot.send_document(chat_id, document=FSInputFile(path), caption="Готово (как файл)")
        except Exception:
            logging.exception("Ошибка при отправке файла пользователю")
            try:
                await bot.send_message(chat_id, "❌ Ошибка при отправке файла. Возможно, слишком большой файл или проблемы с сетью.")
            except Exception:
                pass
        finally:
            try:
                cleanup_file(path)
            except Exception:
                logging.exception("Не удалось удалить временный файл")
    finally:
        # удалим задачу из списка по завершению
        download_jobs.pop(job_id, None)


# Защиты и лимиты
# Опция: ALLOWED_USERS — заполни через env var как "12345,67890" или оставь пустой (тогда whitelist отключён)
ALLOWED_USERS = set()
if os.getenv("ALLOWED_USERS"):
    try:
        ALLOWED_USERS = set(int(x.strip()) for x in os.getenv("ALLOWED_USERS").split(",") if x.strip())
    except Exception:
        ALLOWED_USERS = set()

# rate limit: limit_count downloads per period_seconds per user
RATE_LIMIT_COUNT = int(os.getenv("RATE_LIMIT_COUNT", 3))
RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", 600))  # seconds (10 minutes default)

user_downloads = defaultdict(list)  # user_id -> list of timestamps


# ==== Логирование ====
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==== Утилиты для скачивания видео ====
def download_video(url, filename):
    try:
        from yt_dlp import YoutubeDL
        if os.path.exists(filename):
            os.remove(filename)

        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': filename,
        }

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(filename):
            return filename
    except Exception as e:
        logging.exception(f"yt-dlp error: {e}")
    return None

user_chats = {}  # для истории диалогов

async def ask_ai(user_id: int, query: str):
    if user_id not in user_chats:
        user_chats[user_id] = []

    user_chats[user_id].append({"role": "user", "content": query})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "Ты умный и дружелюбный помощник."}] + user_chats[user_id],
        max_tokens=500,
        temperature=0.7
    )

    answer = response.choices[0].message.content
    user_chats[user_id].append({"role": "assistant", "content": answer})
    return answer

def can_download(user_id: int) -> bool:
    """Returns True if user can download now; also records the attempt."""
    if not user_id:
        # не даём анонимным/сервисным апдейтам скачивать
        return False

    now = time.time()
    times = user_downloads[user_id]
    # keep only recent timestamps
    window = [t for t in times if now - t < RATE_LIMIT_PERIOD]
    user_downloads[user_id] = window
    if len(window) >= RATE_LIMIT_COUNT:
        return False
    user_downloads[user_id].append(now)
    return True

# ==== Проверка ссылок ====
def is_tiktok_url(text): return "tiktok.com" in text
def is_instagram_url(text): return "instagram.com" in text or "instagram." in text
def is_youtube_url(text): return "youtube.com" in text or "youtu.be" in text


# ==== TikTok API ====
async def get_tiktok_video(url):
    api = f"https://www.tikwm.com/api/?url={url}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api) as resp:
                data = await resp.json()
                return data.get("data", {}).get("play")
    except Exception as e:
        logging.exception("TikTok error")
    return None

# ==== Генерация изображений через OpenAI ====
async def generate_image(prompt: str) -> bytes:
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1
    )
    image_url = response.data[0].url

    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as resp:
            return await resp.read()

# ==== Намаз ====
async def send_namaz_time(message: types.Message):
    logging.info("Получен запрос на время намаза")
    try:
        latitude = 41.2995  # Ташкент
        longitude = 69.2401
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.aladhan.com/v1/timings?latitude={latitude}&longitude={longitude}&method=2"
            ) as response:
                logging.info(f"API ответил: {response.status}")
                data = await response.json()
                logging.debug(f"Данные: {data}")

        timings = data["data"]["timings"]
        fajr = timings["Fajr"]
        dhuhr = timings["Dhuhr"]
        asr = timings["Asr"]
        maghrib = timings["Maghrib"]
        isha = timings["Isha"]

        await message.answer(
            f"🕌 Время намаза в Ташкенте:\n\n"
            f"🌅 Фаджр: {fajr}\n"
            f"🏙 Зухр: {dhuhr}\n"
            f"🌇 Аср: {asr}\n"
            f"🌆 Магриб: {maghrib}\n"
            f"🌃 Иша: {isha}"
        )

    except Exception:
        logging.exception("Ошибка при получении времени намаза")
        await message.answer("❌ Не удалось получить время намаза.")

async def get_news():
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=5&apiKey={NEWS_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()

            if data.get("status") != "ok" or not data.get("articles"):
                return None

            news_list = []
            for article in data["articles"]:
                title = article.get("title", "Без заголовка")
                description = article.get("description", "Без описания")
                url = article.get("url", "")
                news_list.append(f"📰 <b>{title}</b>\n{description}\n<a href='{url}'>Читать подробнее</a>")

            return "\n\n".join(news_list)

@dp.message(Command("news"))
async def news_cmd(msg: types.Message):
    news_text = await get_news()
    if news_text:
        await msg.answer(news_text, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await msg.answer("⚠️ Новости не найдены, попробуйте позже.")

# ==== Погода в Ташкенте ====
async def get_weather_tashkent():
    url = f"https://api.openweathermap.org/data/2.5/weather?q=Tashkent&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                temp = data["main"]["temp"]
                feels_like = data["main"]["feels_like"]
                description = data["weather"][0]["description"].capitalize()
                humidity = data["main"]["humidity"]
                wind = data["wind"]["speed"]
                return f"🌤 Погода в Ташкенте:\n" \
                       f"Температура: {temp}°C (ощущается как {feels_like}°C)\n" \
                       f"Описание: {description}\n" \
                       f"💧 Влажность: {humidity}%\n" \
                       f"💨 Ветер: {wind} м/с"
    except Exception:
        logging.exception("Ошибка при получении погоды")
        return None

@dp.message(Command("pogoda"))
async def pogoda_cmd(msg: types.Message):
    await msg.answer("⏳ Получаю погоду в Ташкенте...")
    weather_text = await get_weather_tashkent()
    if weather_text:
        await msg.answer(weather_text)
    else:
        await msg.answer("❌ Не удалось получить погоду. Проверь API ключ.")



# ==== Мотивация / цитаты ====
async def get_motivation():
    url = "https://zenquotes.io/api/random"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "⚠️ Не удалось получить цитату, попробуй позже."
                data = await resp.json()
                quote = data[0]["q"]
                author = data[0]["a"]
                return f"💡 {quote}\n\n👤 {author}"
    except Exception:
        logging.exception("Ошибка при получении цитаты")
        return "⚠️ Ошибка при получении цитаты."

@dp.message(Command("motivation"))
async def motivation_cmd(msg: types.Message):
    quote = await get_motivation()
    await msg.answer(quote)

@dp.message(Command("namaz"))
async def namaz_command_handler(message: types.Message):
    await send_namaz_time(message)

@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    weather_text = await get_weather_tashkent()
    await msg.answer(
        "👋 <b>Привет!</b>\n\n"
        f"{weather_text if weather_text else '🌤 Погода недоступна'}\n\n"
        "📅 <b>Загрузка видео:</b>\n"
        "Просто отправь ссылку на TikTok, Instagram или YouTube — я скачаю его для тебя.\n\n"
        "🎨 <b>Генерация изображений:</b>\n"
        "Напиши: <code>/generate</code> + описание — и я пришлю картинку!\n\n"
        "📰 <b>Новости:</b>\n"
        "Напиши <code>/news</code>, и я пришлю свежие заголовки с кратким описанием и ссылками.\n\n"
        "🕌 <b>Намаз вақти:</b> /namaz\n\n"
        "❓ <b>Помощь:</b> /help\n\n"
        "<b>Motivation:</b> /motivation",
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    weather_text = await get_weather_tashkent()
    await msg.answer(
        "❓ <b>Помощь по боту</b>\n\n"
        f"{weather_text if weather_text else '🌤 Погода недоступна'}\n\n"
        "🎮 <b>Загрузка видео:</b>\nПросто отправь ссылку на видео из TikTok, Instagram или YouTube.\n\n"
        "🎨 <b>Генерация картинок:</b>\nНапиши: <code>/generate</code> + описание.\n\n"
        "📰 <b>Новости:</b>\nНапиши <code>/news</code>, и я пришлю свежие заголовки с кратким описанием и ссылками.\n\n"
        "🕌 <b>Намаз вақти:</b> /namaz\n\n"
        "<b>Motivation:</b> /motivation\n\n"
        "📢 <b>Поддержка:</b> если есть вопросы — просто напиши сюда!",
        parse_mode="HTML"
    )

@dp.message(Command("generate"))
async def generate_cmd(msg: types.Message):
    prompt = msg.text.replace("/generate", "").strip()
    if not prompt:
        await msg.answer("Напиши описание после команды. Пример: /generate кот в шляпе")
        return
    await msg.answer("🎨 Генерирую изображение...")
    try:
        image_data = await generate_image(prompt)
        image = BufferedInputFile(image_data, filename="image.png")
        await msg.answer_photo(image, caption=f"🖌️ По запросу: {prompt}")
    except Exception as e:
        logging.exception("Ошибка генерации изображения")
        await msg.answer(f"❌ Ошибка генерации: {e}")


@dp.message(F.text)
async def universal_message_handler(msg: types.Message):
    text = (msg.text or "").strip()
    user_id = msg.from_user.id if msg.from_user else None

    # whitelist если задан
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await msg.answer("⚠️ У тебя нет доступа к скачиванию через этого бота.")
        return

    # rate limit
    if not can_download(user_id):
        await msg.answer("⛔ Лимит скачиваний превышен. Попробуй позже.")
        return

    # только ссылки
    if not (is_instagram_url(text) or is_youtube_url(text) or is_tiktok_url(text)):
        return  # остальная логика выше/ниже в файле обработает команды

    # Ограничение размера из env
    max_size = int(os.getenv("MAX_FILESIZE_BYTES", 50 * 1024 * 1024))

    # Создаём job и ставим её в фон
    job_id = str(uuid.uuid4())[:8]
    task = asyncio.create_task(_background_download_and_send(msg.chat.id, text, job_id, max_size))
    download_jobs[job_id] = task

    await msg.answer(f"✅ Ссылка принята в очередь. Номер задачи: {job_id}. Я пришлю файл, как только он будет готов.")
    return


    # остальная логика (AI, команды и т.д.) остаётся как есть


# ==== Webhook / запуск aiohttp приложения ====
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://fayzik-helper.onrender.com")
WEBHOOK_PATH = "/webhook"  # без токена
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

async def on_startup(app):
    logging.info("[INFO] Устанавливаю webhook...")
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"[INFO] Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    logging.info("[INFO] Удаляю webhook...")
    await bot.delete_webhook()

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, on_startup=on_startup, on_shutdown=on_shutdown)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)
