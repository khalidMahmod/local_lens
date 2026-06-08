FROM python:3.11-slim

# `ffmpeg` is a system dep for the ingestion track (vision frame extraction).
# Adding it now so the same image works once the ingestion CLI ships.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# Install Python deps first so the layer is cached when only code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot/ ./bot/
COPY data/ ./data/
COPY prompts/ ./prompts/
COPY config.py ./

EXPOSE 8080 8081

CMD ["python", "-m", "bot.main"]
