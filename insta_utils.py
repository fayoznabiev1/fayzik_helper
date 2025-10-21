import os
from yt_dlp import YoutubeDL

def download_video(url, filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)

        ydl_opts = {
            'format': 'mp4',
            'outtmpl': filename,
            'quiet': True,
            'no_warnings': True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(filename):
            return filename
    except Exception as e:
        print(f"❌ yt-dlp error: {e}")
    return None

def get_instagram_video(url):
    return download_video(url, "insta_video.mp4")

def get_youtube_video(url):
    return download_video(url, "yt_video.mp4")