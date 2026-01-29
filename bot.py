"""
Telegram bot for converting YouTube videos to MP3/MP4 format.
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
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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
TEMP_DIR = Path('/tmp/yt_mp3_bot')
TEMP_DIR.mkdir(exist_ok=True, parents=True)
MAX_FILE_SIZE_WARNING = 50 * 1024 * 1024  # 50 MB in bytes

# YouTube URL patterns
YOUTUBE_PATTERNS = [
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',  # YouTube Shorts support
]

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Temporary storage for video URLs (video_id -> url)
video_urls: dict[str, str] = {}


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL. Supports watch, youtu.be, embed, and shorts formats."""
    for i, pattern in enumerate(YOUTUBE_PATTERNS):
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            # Log URL type for debugging
            if i == 0:
                url_type = 'watch/youtu.be'
            elif i == 1:
                url_type = 'embed'
            elif i == 2:
                url_type = 'shorts'
            else:
                url_type = 'unknown'
            logger.info(f"Detected YouTube {url_type} URL, video_id: {video_id}")
            return video_id
    return None


def get_ydl_opts_base(player_clients: list[str]) -> dict:
    """Get base yt-dlp options for bypassing bot detection."""
    opts = {
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        },
        'extractor_args': {
            'youtube': {
                'skip': ['hls', 'dash'],
                'player_client': player_clients
            }
        },
    }
    
    # Check for cookies in environment variable (for Railway/deployment)
    cookies_content = os.getenv('YOUTUBE_COOKIES')
    if cookies_content and cookies_content.strip():
        # Replace literal \n with actual newlines
        cookies_content = cookies_content.replace('\\n', '\n')
        cookies_path = str(TEMP_DIR / 'cookies.txt')
        try:
            # Ensure temp directory exists
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            with open(cookies_path, 'w', encoding='utf-8') as f:
                f.write(cookies_content)
            opts['cookiefile'] = cookies_path
            first_line = cookies_content.split('\n')[0] if cookies_content else 'empty'
            logger.info(f"Using cookies from YOUTUBE_COOKIES, first line: {first_line}")
        except Exception as e:
            logger.warning(f"Failed to create temporary cookies file: {e}")
    else:
        # Fallback to cookies.txt file (for local development)
        cookies_file = Path('/app/cookies.txt')
        if not cookies_file.exists():
            # Try local path for development
            cookies_file = Path('cookies.txt')
        
        if cookies_file.exists() and cookies_file.stat().st_size > 0:
            opts['cookiefile'] = str(cookies_file)
            logger.info(f"Using cookies file: {cookies_file}")
        else:
            logger.debug("No cookies found (neither YOUTUBE_COOKIES env var nor cookies.txt file), working without cookies")
    
    return opts


def get_video_info(url: str) -> dict:
    """Get video information without downloading. Retries with different clients if needed."""
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    # Try different player clients in order: android_music -> android -> web
    player_clients_list = [
        ['android_music', 'android'],
        ['android'],
        ['web'],
    ]
    
    last_error = None
    for player_clients in player_clients_list:
        try:
            ydl_opts = {
                **base_opts,
                **get_ydl_opts_base(player_clients),
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'video_id': info.get('id', ''),
                }
        except Exception as e:
            last_error = e
            logger.warning(f"Failed with player_clients {player_clients}: {e}")
            continue
    
    # If all attempts failed, raise the last error
    raise last_error or Exception("Failed to get video info")


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def download_audio(url: str, video_id: str, progress_queue: asyncio.Queue) -> Path:
    """Download audio from YouTube video and convert to MP3. Retries with different clients if needed."""
    output_path = TEMP_DIR / f"{video_id}.%(ext)s"
    
    def progress_hook(d: dict):
        """Callback for download progress - puts updates in queue."""
        try:
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    text = f"📥 Downloading audio... {percent:.1f}%"
                elif 'downloaded_bytes' in d:
                    text = f"📥 Downloading audio... {d['downloaded_bytes']} bytes"
                else:
                    text = "📥 Downloading audio..."
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
    
    base_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
        'outtmpl': str(output_path),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'quiet': False,
        'progress_hooks': [progress_hook],
    }
    
    # Try different player clients in order: android_music -> android -> web
    player_clients_list = [
        ['android_music', 'android'],
        ['android'],
        ['web'],
    ]
    
    last_error = None
    for player_clients in player_clients_list:
        try:
            # Clean up any previous failed downloads
            for ext in ['mp3', 'm4a', 'webm', 'opus']:
                temp_file = TEMP_DIR / f"{video_id}.{ext}"
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
            
            ydl_opts = {
                **base_opts,
                **get_ydl_opts_base(player_clients),
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file
            mp3_file = TEMP_DIR / f"{video_id}.mp3"
            if mp3_file.exists():
                return mp3_file
            
            raise FileNotFoundError(f"Downloaded file not found: {mp3_file}")
            
        except Exception as e:
            last_error = e
            logger.warning(f"Failed to download audio with player_clients {player_clients}: {e}")
            # Clean up failed download
            for ext in ['mp3', 'm4a', 'webm', 'opus']:
                temp_file = TEMP_DIR / f"{video_id}.{ext}"
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
            continue
    
    # If all attempts failed, raise the last error
    raise last_error or Exception("Failed to download audio")


def download_video(url: str, video_id: str, progress_queue: asyncio.Queue) -> Path:
    """Download video from YouTube in best quality (max 1080p). Retries with different clients if needed."""
    output_path = TEMP_DIR / f"{video_id}.%(ext)s"
    
    def progress_hook(d: dict):
        """Callback for download progress - puts updates in queue."""
        try:
            if d['status'] == 'downloading':
                if 'total_bytes' in d:
                    percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                    text = f"📥 Downloading video... {percent:.1f}%"
                elif 'downloaded_bytes' in d:
                    text = f"📥 Downloading video... {d['downloaded_bytes']} bytes"
                else:
                    text = "📥 Downloading video..."
            elif d['status'] == 'finished':
                text = "✅ Video ready!"
            else:
                return
            
            # Put update in queue (non-blocking)
            try:
                progress_queue.put_nowait(text)
            except asyncio.QueueFull:
                pass  # Skip if queue is full
        except Exception:
            pass  # Ignore errors in progress callback
    
    base_opts = {
        'format': 'best[height<=1080][ext=mp4]/best[height<=1080]/best',
        'outtmpl': str(output_path),
        'merge_output_format': 'mp4',
        'quiet': False,
        'progress_hooks': [progress_hook],
    }
    
    # Try different player clients in order: android_music -> android -> web
    player_clients_list = [
        ['android_music', 'android'],
        ['android'],
        ['web'],
    ]
    
    last_error = None
    for player_clients in player_clients_list:
        try:
            # Clean up any previous failed downloads
            for ext in ['mp4', 'webm', 'mkv', 'm4a']:
                temp_file = TEMP_DIR / f"{video_id}.{ext}"
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
            
            ydl_opts = {
                **base_opts,
                **get_ydl_opts_base(player_clients),
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file (could be .mp4 or other extension)
            video_file = None
            for ext in ['mp4', 'webm', 'mkv']:
                potential_file = TEMP_DIR / f"{video_id}.{ext}"
                if potential_file.exists():
                    video_file = potential_file
                    break
            
            if video_file and video_file.exists():
                return video_file
            
            raise FileNotFoundError(f"Downloaded video file not found for {video_id}")
            
        except Exception as e:
            last_error = e
            logger.warning(f"Failed to download video with player_clients {player_clients}: {e}")
            # Clean up failed download
            for ext in ['mp4', 'webm', 'mkv', 'm4a']:
                temp_file = TEMP_DIR / f"{video_id}.{ext}"
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
            continue
    
    # If all attempts failed, raise the last error
    raise last_error or Exception("Failed to download video")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    welcome_text = (
        "🎵 Welcome to YouTube Converter Bot!\n\n"
        "Send me a YouTube video link and choose format:\n"
        "• 🎵 MP3 Audio (128 kbps)\n"
        "• 🎥 MP4 Video (up to 1080p)\n\n"
        "📋 Supported URL formats:\n"
        "• youtube.com/watch?v=...\n"
        "• youtu.be/...\n"
        "• youtube.com/shorts/...\n\n"
        "✨ Features:\n"
        "• No length limits\n"
        "• Supports age-restricted videos\n"
        "• Supports YouTube Shorts"
    )
    await message.answer(welcome_text)


@dp.message(F.text)
async def handle_youtube_link(message: Message):
    """Handle YouTube URL messages - show format selection buttons."""
    url = message.text.strip()
    
    # Extract video ID
    video_id = extract_video_id(url)
    if not video_id:
        await message.answer(
            "❌ Invalid YouTube URL. Please send a valid YouTube link.\n\n"
            "Examples:\n"
            "• https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "• https://youtu.be/dQw4w9WgXcQ\n"
            "• https://www.youtube.com/shorts/xqrkk41Ga-w"
        )
        return
    
    # Log if it's a Shorts URL
    if '/shorts/' in url.lower():
        logger.info(f"Processing YouTube Shorts URL: {url}, video_id: {video_id}")
    
    # Send initial status
    status_message = await message.answer("🔍 Checking video...")
    
    try:
        # Get video info
        video_info = get_video_info(url)
        duration = video_info.get('duration', 0)
        
        # Store URL for later use in callback
        video_urls[video_id] = url
        
        # Create inline keyboard with format selection
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎵 MP3 Audio", callback_data=f"format:mp3:{video_id}"),
                InlineKeyboardButton(text="🎥 MP4 Video", callback_data=f"format:mp4:{video_id}"),
            ]
        ])
        
        # Show video info with format selection buttons
        duration_text = f"{duration // 60}:{duration % 60:02d}" if duration > 0 else "Unknown"
        await status_message.edit_text(
            f"📹 Found: {video_info['title']}\n"
            f"👤 Author: {video_info['uploader']}\n"
            f"⏱ Duration: {duration_text}\n\n"
            f"Choose format:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error getting video info: {e}", exc_info=True)
        error_msg = "❌ An error occurred while checking the video."
        
        if "Private video" in str(e) or "unavailable" in str(e).lower():
            error_msg = "❌ This video is unavailable or private."
        elif "Sign in" in str(e) or "age-restricted" in str(e).lower():
            error_msg = "❌ This video is age-restricted or requires sign-in."
        
        await status_message.edit_text(error_msg)


@dp.callback_query(F.data.startswith("format:"))
async def handle_format_selection(callback: CallbackQuery):
    """Handle format selection callback."""
    await callback.answer()
    
    # Parse callback data: format:mp3:video_id
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.message.answer("❌ Invalid format selection.")
        return
    
    format_type = parts[1]  # mp3 or mp4
    video_id = parts[2]
    
    # Get URL from storage
    url = video_urls.get(video_id)
    if not url:
        await callback.message.answer("❌ Video URL not found. Please send the link again.")
        return
    
    status_message = await callback.message.answer("🔍 Processing...")
    
    try:
        # Get video info again
        video_info = get_video_info(url)
        duration = video_info.get('duration', 0)
        
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
            if format_type == "mp3":
                # Download audio
                await status_message.edit_text(
                    f"📹 {video_info['title']}\n"
                    f"👤 {video_info['uploader']}\n"
                    f"⏱ {duration // 60}:{duration % 60:02d}\n\n"
                    f"📥 Starting download..."
                )
                
                file_path = await asyncio.to_thread(download_audio, url, video_id, progress_queue)
                
                # Get file size
                file_size = file_path.stat().st_size
                size_text = format_size(file_size)
                
                # Update status
                await status_message.edit_text(f"📤 Uploading MP3 file ({size_text})...")
                
                # Send MP3 file
                audio_file = FSInputFile(
                    file_path,
                    filename=f"{video_info['title'][:50]}.mp3"
                )
                
                await callback.message.answer_audio(
                    audio_file,
                    title=video_info['title'],
                    performer=video_info['uploader'],
                    duration=duration
                )
                
                await status_message.edit_text("✅ Done! MP3 file sent.")
                
            elif format_type == "mp4":
                # Download video
                await status_message.edit_text(
                    f"📹 {video_info['title']}\n"
                    f"👤 {video_info['uploader']}\n"
                    f"⏱ {duration // 60}:{duration % 60:02d}\n\n"
                    f"📥 Starting download..."
                )
                
                file_path = await asyncio.to_thread(download_video, url, video_id, progress_queue)
                
                # Get file size
                file_size = file_path.stat().st_size
                size_text = format_size(file_size)
                
                # Check file size and warn if > 50MB
                warning_text = ""
                if file_size > MAX_FILE_SIZE_WARNING:
                    warning_text = f"\n⚠️ File is large ({size_text}), upload may take time..."
                
                # Update status
                await status_message.edit_text(f"📤 Uploading MP4 file ({size_text})...{warning_text}")
                
                # Send MP4 file as video
                video_file = FSInputFile(
                    file_path,
                    filename=f"{video_info['title'][:50]}.mp4"
                )
                
                await callback.message.answer_video(
                    video_file,
                    caption=f"{video_info['title']}\n👤 {video_info['uploader']}",
                    duration=duration,
                    supports_streaming=True
                )
                
                await status_message.edit_text("✅ Done! MP4 file sent.")
            else:
                await status_message.edit_text("❌ Unknown format selected.")
                return
                
        finally:
            # Cancel monitor task
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
            # Clean up temporary files
            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")
            
            # Clean up URL from storage
            try:
                video_urls.pop(video_id, None)
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error processing video: {e}", exc_info=True)
        error_msg = "❌ An error occurred while processing the video."
        
        if "Private video" in str(e) or "unavailable" in str(e).lower():
            error_msg = "❌ This video is unavailable or private."
        elif "Sign in" in str(e) or "age-restricted" in str(e).lower():
            error_msg = "❌ This video is age-restricted or requires sign-in."
        elif "File too large" in str(e) or "too large" in str(e).lower():
            error_msg = "❌ File is too large to upload to Telegram."
        
        await status_message.edit_text(error_msg)


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
