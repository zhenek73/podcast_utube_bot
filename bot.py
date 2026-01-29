"""
Telegram bot for converting YouTube videos to MP3 format.
Uses aiogram 3.x, yt-dlp, and ffmpeg for processing.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")

# Constants
MAX_VIDEO_DURATION = 600  # 10 minutes in seconds
TEMP_DIR = Path('/tmp/yt_mp3_bot')
TEMP_DIR.mkdir(exist_ok=True, parents=True)

# YouTube URL patterns
YOUTUBE_PATTERNS = [
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
]

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    for pattern in YOUTUBE_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_video_info(url: str) -> dict:
    """Get video information without downloading."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', 'Unknown'),
            'video_id': info.get('id', ''),
        }


def download_audio(url: str, video_id: str, progress_queue: asyncio.Queue) -> Path:
    """Download audio from YouTube video."""
    output_path = TEMP_DIR / f"{video_id}.%(ext)s"
    
    def progress_hook(d: dict):
        """Callback for download progress - puts updates in queue."""
        try:
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    text = f"📥 Downloading... {percent:.1f}%"
                elif 'downloaded_bytes' in d:
                    text = f"📥 Downloading... {d['downloaded_bytes']} bytes"
                else:
                    text = "📥 Downloading..."
            elif d['status'] == 'finished':
                text = "🔄 Converting to MP3..."
            else:
                return
            
            # Put update in queue (non-blocking)
            try:
                progress_queue.put_nowait(text)
            except asyncio.QueueFull:
                pass  # Skip if queue is full
        except Exception:
            pass  # Ignore errors in progress callback
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(output_path),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': False,
        'progress_hooks': [progress_hook],
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    # Find the downloaded file
    mp3_file = TEMP_DIR / f"{video_id}.mp3"
    if not mp3_file.exists():
        raise FileNotFoundError(f"Downloaded file not found: {mp3_file}")
    
    return mp3_file


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    welcome_text = (
        "🎵 Welcome to YouTube to MP3 Converter Bot!\n\n"
        "Send me a YouTube video link and I'll convert it to MP3 format.\n\n"
        "📋 Supported formats:\n"
        "• youtube.com/watch?v=...\n"
        "• youtu.be/...\n\n"
        "⚠️ Limitations:\n"
        "• Maximum video length: 10 minutes\n"
        "• Audio quality: 128 kbps MP3"
    )
    await message.answer(welcome_text)


@dp.message(F.text)
async def handle_youtube_link(message: Message):
    """Handle YouTube URL messages."""
    url = message.text.strip()
    
    # Extract video ID
    video_id = extract_video_id(url)
    if not video_id:
        await message.answer(
            "❌ Invalid YouTube URL. Please send a valid YouTube link.\n\n"
            "Examples:\n"
            "• https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "• https://youtu.be/dQw4w9WgXcQ"
        )
        return
    
    # Send initial status
    status_message = await message.answer("🔍 Checking video...")
    
    try:
        # Get video info
        video_info = get_video_info(url)
        duration = video_info.get('duration', 0)
        
        # Check duration limit
        if duration > MAX_VIDEO_DURATION:
            await status_message.edit_text(
                f"❌ Video is too long ({duration // 60} minutes).\n"
                f"Maximum allowed duration is {MAX_VIDEO_DURATION // 60} minutes."
            )
            return
        
        # Update status
        await status_message.edit_text(
            f"📹 Found: {video_info['title']}\n"
            f"👤 Author: {video_info['uploader']}\n"
            f"⏱ Duration: {duration // 60}:{duration % 60:02d}\n\n"
            f"📥 Starting download..."
        )
        
        # Create progress queue for status updates
        progress_queue = asyncio.Queue(maxsize=10)
        
        # Start progress monitor task
        async def monitor_progress():
            """Monitor progress queue and update status message."""
            while True:
                try:
                    # Wait for progress update with timeout
                    text = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                    await status_message.edit_text(
                        f"📹 {video_info['title']}\n"
                        f"👤 {video_info['uploader']}\n"
                        f"⏱ {duration // 60}:{duration % 60:02d}\n\n"
                        f"{text}"
                    )
                except asyncio.TimeoutError:
                    # Check if download is still running
                    continue
                except Exception:
                    break
        
        # Start monitoring task
        monitor_task = asyncio.create_task(monitor_progress())
        
        try:
            # Download and convert (runs in thread pool)
            mp3_file = await asyncio.to_thread(download_audio, url, video_id, progress_queue)
        finally:
            # Cancel monitor task
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        # Update status
        await status_message.edit_text("📤 Uploading MP3 file...")
        
        # Send MP3 file
        audio_file = FSInputFile(
            mp3_file,
            filename=f"{video_info['title'][:50]}.mp3"
        )
        
        await message.answer_audio(
            audio_file,
            title=video_info['title'],
            performer=video_info['uploader'],
            duration=duration
        )
        
        await status_message.edit_text("✅ Done! MP3 file sent.")
        
    except Exception as e:
        logger.error(f"Error processing video: {e}", exc_info=True)
        error_msg = "❌ An error occurred while processing the video."
        
        if "Private video" in str(e) or "unavailable" in str(e).lower():
            error_msg = "❌ This video is unavailable or private."
        elif "Sign in" in str(e) or "age-restricted" in str(e).lower():
            error_msg = "❌ This video is age-restricted or requires sign-in."
        elif "too long" in str(e).lower():
            error_msg = f"❌ Video exceeds maximum duration of {MAX_VIDEO_DURATION // 60} minutes."
        
        await status_message.edit_text(error_msg)
    
    finally:
        # Clean up temporary files
        try:
            if 'video_id' in locals():
                mp3_file_path = TEMP_DIR / f"{video_id}.mp3"
                if mp3_file_path.exists():
                    mp3_file_path.unlink()
                    logger.info(f"Cleaned up temporary file: {mp3_file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary file: {e}")


async def main():
    """Main function to start the bot."""
    logger.info("Starting YouTube to MP3 bot...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
