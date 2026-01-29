# YouTube to MP3 Telegram Bot

Telegram bot for converting YouTube videos to MP3 format using Python, aiogram 3.x, yt-dlp, and ffmpeg.

## Features

- ✅ Converts YouTube videos to MP3 format (128 kbps)
- ✅ Shows download and conversion progress
- ✅ Sends MP3 files with metadata (title, artist)
- ✅ Validates video duration (max 10 minutes)
- ✅ Handles errors gracefully
- ✅ Cleans up temporary files automatically
- ✅ Ready for Railway deployment

## Requirements

- Python 3.11+
- ffmpeg
- Telegram Bot Token

## Local Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd podcast_utube_bot
```

### 2. Install dependencies

**On Windows:**
```bash
# Install ffmpeg (using chocolatey or download from https://ffmpeg.org/)
choco install ffmpeg

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install Python packages
pip install -r requirements.txt
```

**On Linux/Mac:**
```bash
# Install ffmpeg
sudo apt-get install ffmpeg  # Ubuntu/Debian
brew install ffmpeg  # macOS

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Edit `.env` and add your Telegram bot token:

```
BOT_TOKEN=your_actual_bot_token_here
```

To get a bot token:
1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the token and paste it into `.env`

### 4. Run the bot

```bash
python bot.py
```

The bot will start and you can test it by sending a YouTube link to your bot.

## Railway Deployment

### 1. Prepare your repository

Make sure all files are committed and pushed to GitHub/GitLab.

### 2. Deploy on Railway

1. Go to [Railway](https://railway.app)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your repository
5. Railway will automatically detect the Dockerfile

### 3. Set environment variables

In Railway dashboard:
1. Go to your project → Variables
2. Add `BOT_TOKEN` with your Telegram bot token
3. Railway will automatically redeploy

### 4. Monitor logs

Check the Railway logs to see if the bot started successfully:
```
Starting YouTube to MP3 bot...
```

## Usage

1. Start a conversation with your bot
2. Send `/start` to see welcome message
3. Send a YouTube link (youtube.com/watch?v=... or youtu.be/...)
4. Wait for the bot to download, convert, and send the MP3 file

## Supported URL Formats

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`

## Using Cookies (Optional)

To bypass YouTube bot detection more effectively, you can use cookies from your browser:

### Export Cookies from Browser

**Chrome/Edge:**
1. Install extension: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Go to `youtube.com` and log in
3. Click the extension icon
4. Select `youtube.com` domain
5. Click "Export" and save as `cookies.txt` in project root

**Firefox:**
1. Install extension: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
2. Go to `youtube.com` and log in
3. Click the extension icon
4. Select `youtube.com` domain
5. Click "Export" and save as `cookies.txt` in project root

### Add Cookies to Project

1. Copy `cookies.txt.example` to `cookies.txt`:
   ```bash
   cp cookies.txt.example cookies.txt
   ```
2. Export your cookies from browser and paste them into `cookies.txt`
3. The bot will automatically detect and use cookies if file has content
4. **Important:** If you add real cookies, uncomment `cookies.txt` in `.gitignore` to prevent committing them!

### Without Cookies

The bot works without cookies, but may encounter more YouTube bot detection blocks. Cookies help bypass these restrictions.

## Limitations

- No length limits (videos of any duration)
- Audio quality: 128 kbps MP3
- Video quality: up to 1080p MP4
- Some videos may be unavailable (private, region-locked)

## Project Structure

```
podcast_utube_bot/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration for Railway
├── .env.example        # Environment variables template
├── cookies.txt         # YouTube cookies (template in repo, add real cookies locally)
├── cookies.txt.example # Cookies file template
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

## Troubleshooting

### Bot doesn't respond

- Check if `BOT_TOKEN` is set correctly in `.env`
- Verify the bot is running (check logs)
- Make sure you started a conversation with the bot

### Download fails

- Check internet connection
- Verify the YouTube URL is correct
- Some videos may be unavailable or region-locked

### FFmpeg errors

- Ensure ffmpeg is installed: `ffmpeg -version`
- On Railway, ffmpeg is included in the Dockerfile

### File too large

- The bot limits videos to 10 minutes
- For longer videos, consider increasing `MAX_VIDEO_DURATION` in `bot.py`

## License

MIT License - feel free to use and modify as needed.
