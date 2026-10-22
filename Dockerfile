FROM python:3.12-slim

# ffmpeg нужен yt-dlp для перекодирования в mp3 и тегов
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# непривилегированный пользователь
RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app
USER bot

ENV DB_PATH=/app/data/music.db \
    DOWNLOAD_DIR=/app/data/downloads

VOLUME ["/app/data"]

CMD ["python", "-m", "bot"]
