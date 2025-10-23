import os
import aiohttp
from yt_dlp import YoutubeDL

# === Instagram через API TikWM ===
async def get_instagram_video(url: str):
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    print(f"❌ TikWM API error: {resp.status}")
                    return None

                data = await resp.json()
                if data.get("data") and data["data"].get("play"):
                    video_url = data["data"]["play"]
                    async with session.get(video_url) as video_resp:
                        if video_resp.status == 200:
                            file_path = "/tmp/insta_video.mp4"
                            with open(file_path, "wb") as f:
                                f.write(await video_resp.read())
                            print("✅ Instagram video downloaded successfully")
                            return file_path
                        else:
                            print(f"❌ Can't download video: {video_resp.status}")
                else:
                    print("❌ No video URL in TikWM API response")
    except Exception as e:
        print(f"⚠️ Instagram download error: {e}")
    return None


# === YouTube через yt-dlp ===
def get_youtube_video(url: str):
    try:
        file_path = "/tmp/yt_video.mp4"
        if os.path.exists(file_path):
            os.remove(file_path)

        ydl_opts = {
            "outtmpl": file_path,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "format": "bestvideo+bestaudio/best",
        }

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(file_path):
            print("✅ YouTube video downloaded successfully")
            return file_path

    except Exception as e:
        print(f"⚠️ YouTube download error: {e}")

    return None
