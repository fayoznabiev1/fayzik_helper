import os
import aiohttp
from yt_dlp import YoutubeDL

# === Instagram через API (SnapInsta) ===
async def get_instagram_video(url: str):
    try:
        api_url = f"https://api.snapinsta.app/api/v1/fetch?url={url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    print(f"❌ SnapInsta API error: {resp.status}")
                    return None

                data = await resp.json()
                if "media" in data and len(data["media"]) > 0:
                    video_url = data["media"][0]["url"]
                    async with session.get(video_url) as video_resp:
                        if video_resp.status == 200:
                            content = await video_resp.read()
                            file_path = "insta_video.mp4"
                            with open(file_path, "wb") as f:
                                f.write(content)
                            print("✅ Instagram video downloaded successfully")
                            return file_path
                        else:
                            print(f"❌ Can't download Instagram video: {video_resp.status}")
                else:
                    print("❌ No media found in SnapInsta API response")
    except Exception as e:
        print(f"⚠️ Instagram download error: {e}")
    return None


# === YouTube через yt-dlp ===
def get_youtube_video(url: str):
    try:
        ydl_opts = {
            "outtmpl": "yt_video.mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "format": "bv+ba/best",
        }

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists("yt_video.mp4"):
            print("✅ YouTube video downloaded successfully")
            return "yt_video.mp4"

    except Exception as e:
        print(f"⚠️ YouTube download error: {e}")

    return None

