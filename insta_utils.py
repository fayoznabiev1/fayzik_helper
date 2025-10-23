import os
import aiohttp

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


# === YouTube через API (вместо yt-dlp) ===
async def get_youtube_video(url: str):
    try:
        api_url = "https://yt-api.vercel.app/api/info"
        params = {"url": url}

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status != 200:
                    print(f"❌ YouTube API error: {resp.status}")
                    return None

                data = await resp.json()
                formats = data.get("formats", [])
                video_url = None

                # ищем mp4 или лучшее качество
                for f in formats:
                    if f.get("mimeType", "").startswith("video/mp4"):
                        video_url = f.get("url")
                        break

                if not video_url:
                    print("❌ No suitable video format found")
                    return None

                # скачиваем видео
                async with session.get(video_url) as video_resp:
                    if video_resp.status == 200:
                        content = await video_resp.read()
                        file_path = "/tmp/yt_video.mp4"
                        with open(file_path, "wb") as f:
                            f.write(content)
                        print("✅ YouTube video downloaded successfully")
                        return file_path
                    else:
                        print(f"❌ Can't download YouTube video: {video_resp.status}")

    except Exception as e:
        print(f"⚠️ YouTube API error: {e}")

    return None


