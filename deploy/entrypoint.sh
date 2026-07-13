#!/bin/sh
# ---------------------------------------------------------------------------
# Container entrypoint.
#
# Config/secrets arrive as plain environment variables (Komodo stages the .env
# and injects them). The app reads os.environ directly.
#
# Honors PUID/PGID/TZ conventions used across the swarm:
#   - creates/uses a user with the given UID/GID
#   - chowns the data dir so NFS-backed writes have correct ownership
#   - drops privileges to that user to run the app
#
# Also supports *_FILE env vars (e.g. /run/secrets/xxx) by exporting file
# contents to the matching var name — a no-op if unused.
# ---------------------------------------------------------------------------
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Expand any *_FILE secrets into their target vars.
for var in $(env | grep '_FILE=' | cut -d= -f1); do
  target="${var%_FILE}"
  path=$(printenv "$var")
  if [ -f "$path" ]; then
    export "$target=$(cat "$path")"
  fi
done

# Set timezone if provided and tzdata is present.
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
  ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
  echo "$TZ" > /etc/timezone 2>/dev/null || true
fi

# Ensure a group/user with the requested IDs exists.
if ! getent group "$PGID" >/dev/null 2>&1; then
  addgroup --gid "$PGID" appgroup >/dev/null 2>&1 || groupadd -g "$PGID" appgroup >/dev/null 2>&1 || true
fi
if ! getent passwd "$PUID" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" --uid "$PUID" --gid "$PGID" appuser >/dev/null 2>&1 \
    || useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin appuser >/dev/null 2>&1 || true
fi

# Make sure the data dir is writable by the target user (NFS-backed mount).
mkdir -p "${DATA_DIR:-/data}"
chown -R "$PUID:$PGID" "${DATA_DIR:-/data}" 2>/dev/null || true

# Drop to the target user and launch. Prefer gosu/su-exec if available;
# fall back to running as root if neither is present.
# Runs the package as a module (PYTHONPATH=/app/src is set in the Dockerfile).
if command -v gosu >/dev/null 2>&1; then
  exec gosu "$PUID:$PGID" python3 -u -m jellyfin_recs.run_container
elif command -v su-exec >/dev/null 2>&1; then
  exec su-exec "$PUID:$PGID" python3 -u -m jellyfin_recs.run_container
else
  exec python3 -u -m jellyfin_recs.run_container
fi
