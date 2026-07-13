# syntax=docker/dockerfile:1

# ---- Base image -----------------------------------------------------------
# Slim Python keeps the image small; the app has only two pure-Python deps.
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and buffering stdout/stderr (so logs
# stream to `docker service logs` in real time).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DATA_DIR=/data \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8577

WORKDIR /app

# ---- Minimal runtime tools -------------------------------------------------
# gosu: clean privilege-drop to PUID/PGID in the entrypoint.
# tzdata: lets the TZ env var set the container clock.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu tzdata \
 && rm -rf /var/lib/apt/lists/*

# ---- Python dependencies (cached layer) -----------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Application code ------------------------------------------------------
# Package source, the version file, and the entrypoint.
COPY src/ ./src/
COPY VERSION ./
COPY deploy/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

# Data dir is a mount point; create it so it exists even without a bind mount.
RUN mkdir -p /data

# ---- Runtime ---------------------------------------------------------------
EXPOSE 8577

# Healthcheck hits the dashboard's status API using Python (already present),
# so no extra tools like curl are needed in the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8577/api/refresh/status',timeout=3).status==200 else 1)" \
      || exit 1

ENTRYPOINT ["./entrypoint.sh"]
