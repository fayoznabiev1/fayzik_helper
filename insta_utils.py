import os
import aiohttp
import asyncio
from yt_dlp import YoutubeDL

# === TikTok / Instagram через TikWM API ===
async def get_instagram_video(url: str):
    """Скачивает видео с Instagram или TikTok через TikWM API"""
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    print(f"❌ TikWM API error: {resp.status}")
                    return None

                data = await resp.json()
                if not data.get("data") or not data["data"].get("play"):
                    print("❌ No video found in TikWM response")
                    return None

                video_url = data["data"]["play"]
                async with session.get(video_url) as video_resp:
                    if video_resp.status == 200:
                        file_path = "insta_video.mp4"
                        with open(file_path, "wb") as f:
                            f.write(await video_resp.read())
                        print("✅ Instagram/TikTok video downloaded successfully")
                        return file_path
                    else:
                        print(f"❌ Can't download file: {video_resp.status}")
    except Exception as e:
        print(f"⚠️ Instagram download error: {e}")
    return None


# === YouTube через альтернативный API (без yt-dlp) ===
async def get_youtube_video(url: str):
    """Скачивает YouTube-видео через внешнее API"""
    try:
        api = f"https://youtube-mp4.p.rapidapi.com/dl?id={url.split('v=')[-1]}"
        headers = {
            "x-rapidapi-key": "2cc3ebf6b1msh9e3d3e37b0f40f0p1b6878jsn5a9db82b20ab",
            "x-rapidapi-host": "youtube-mp4.p.rapidapi.com"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(api, headers=headers) as resp:
                if resp.status != 200:
                    print(f"❌ YouTube API error: {resp.status}")
                    return None

                data = await resp.json()
                download_url = data.get("link")

                if not download_url:
                    print("❌ No download URL in YouTube API response")
                    return None

                async with session.get(download_url) as video_resp:
                    if video_resp.status == 200:
                        file_path = "yt_video.mp4"
                        with open(file_path, "wb") as f:
                            f.write(await video_resp.read())
                        print("✅ YouTube video downloaded successfully")
                        return file_path
                    else:
                        print(f"❌ Can't download YouTube file: {video_resp.status}")
    except Exception as e:
        print(f"⚠️ YouTube download error: {e}")
    return None



