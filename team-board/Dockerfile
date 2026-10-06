# Team Board — one small container. Config is mounted read-only, data lives in a volume.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TEAM_BOARD_CONFIG=/config/config.json

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY team_board ./team_board
COPY tb.py .

# Run as an unprivileged user; /data is where the sqlite files and backups go.
RUN useradd --system --uid 10001 --home-dir /app board && mkdir -p /data /config && chown board /data
USER board
VOLUME ["/data"]
EXPOSE 10890

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:10890/healthz', timeout=2).status == 200 else 1)"

# Inside a container the server must listen on all interfaces, which requires auth: "token" in the config
# (local no-login mode refuses to listen beyond loopback).
CMD ["python", "-m", "team_board", "start", "--host", "0.0.0.0", "--port", "10890"]
