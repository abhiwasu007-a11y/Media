# AMW Studio: sample production line + basic dashboard.
FROM python:3.12-slim

ARG WITH_TTS=0
ARG WITH_DEPTH=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AMW_STUDIO_DATA=/data HF_HOME=/data/hf-cache
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libraqm0 libsndfile1 fonts-noto-core fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-tts.txt requirements-depth.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$WITH_DEPTH" = "1" ]; then pip install --no-cache-dir -r requirements-depth.txt; fi \
 && if [ "$WITH_TTS" = "1" ]; then pip install --no-cache-dir -r requirements-tts.txt; fi
COPY studio ./studio
RUN chmod -R a+rX /app  # readable by the non-root user whatever the host umask was
# The app runs as uid 10001. Bind-mounted ./data must be owned by it: `sudo chown -R 10001 data` (deploy.sh does this).
RUN useradd -m -u 10001 studio && mkdir -p /data && chown studio /data
USER studio
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')" || exit 1
CMD ["python", "-m", "studio", "serve"]
