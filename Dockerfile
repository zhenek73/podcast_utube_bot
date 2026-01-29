# Multi-stage build for Railway deployment
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

# Install ffmpeg and runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create temp directory for temporary files
RUN mkdir -p /tmp/yt_mp3_bot && chmod 777 /tmp/yt_mp3_bot

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Set working directory
WORKDIR /app

# Copy application code
COPY bot.py .

# Copy cookies.txt (empty template file exists in repo, user can replace with real cookies)
# Bot checks for file size > 0 before using cookies
COPY cookies.txt /app/cookies.txt

# Healthcheck endpoint (if needed for Railway)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Run the bot
CMD ["python", "bot.py"]
