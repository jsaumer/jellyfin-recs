# Docker / Swarm Deployment

Runs the whole app (dashboard + scheduler) as **one container** on your Docker
Swarm. Config and secrets are supplied as **plain environment variables** — in
this homelab, Komodo stages the `.env` and injects them into the stack at
deploy time. The `data/` dir is **bind-mounted** to a host path.

## What's in the box

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image (Python 3.12-slim, ~2 deps) |
| `deploy/entrypoint.sh` | Optional `*_FILE` secret expansion, then launches the app |
| `run_container.py` | Runs dashboard + scheduler together in one process |
| `deploy/docker-compose.yaml` | Swarm deployment (Traefik + dockns + NFS data, single network) |
| `deploy/compose.local.yml` | Local single-host testing with a `.env` |

## Deployment (matches your swarm conventions)

`deploy/docker-compose.yaml` is written to fit your existing patterns:

- **Traefik** routing + TLS via the `cloudflare` cert resolver, exposed at
  `jellyfin-recs.saumer.cloud` (no published port — Traefik fronts it).
- **dockns** A-record registration on `technitium01`.
- **NFS-backed data** at `/mnt/nfs/container/jellyfin-recs/data` — shared across
  nodes, so no single-node pinning is required.
- **Worker placement**, 512M memory limit, `PUID/PGID/TZ` honored by the
  entrypoint (the app runs as UID 1000, and the data dir is chowned to match).
- Attaches to the `traefik-public` (external) overlay network only.

**Before deploying, adjust these in `deploy/docker-compose.yaml` to match your setup:**

1. `dockns...ip=172.16.50.35` — set to the VIP/ingress IP you want the DNS
   record to point at (copied from your Mealie example; change if different).
2. Make sure Jellyfin/Radarr/Sonarr are reachable on `traefik-public` by service
   name; otherwise point the `*_URL` env vars at the right addresses.
3. NFS path `/mnt/nfs/container/jellyfin-recs/data` — create it first and drop
   in your seed files:
   ```bash
   sudo mkdir -p /mnt/nfs/container/jellyfin-recs/data
   sudo cp jellyfin_recommendations.md /mnt/nfs/container/jellyfin-recs/data/
   sudo cp history.example.txt          /mnt/nfs/container/jellyfin-recs/data/history.txt
   ```

**Deploy.** The image is published to GHCR automatically when you push a version
tag (see GIT.md → "Versioning & releasing"), so you normally don't build by
hand. Point Komodo at `deploy/docker-compose.yaml` with your staged `.env` and
deploy — it pulls `ghcr.io/jsaumer/jellyfin-recs:<version>`.

By hand instead:
```bash
docker stack deploy --with-registry-auth -c deploy/docker-compose.yaml jellyfin-recs
docker service logs -f jellyfin-recs_jellyfin-recs
```
(`--with-registry-auth` distributes your GHCR login to all nodes so they can
pull the private image.) Then browse to `https://jellyfin-recs.saumer.cloud`.

To build locally for testing without the registry:
```bash
make build     # builds ghcr.io/jsaumer/jellyfin-recs:<VERSION> locally
```

## Environment variables

Komodo supplies these. Only the API keys are secret; the rest is wiring.

**Required**
```
JELLYFIN_URL            e.g. http://jellyfin:8096
JELLYFIN_API_KEY        (secret)
JELLYFIN_USERNAME       e.g. saumz   (or JELLYFIN_USER_ID)
ANTHROPIC_API_KEY       (secret)
```

**Optional / tunable**
```
CLAUDE_MODEL            default claude-sonnet-4-6
RECS_PER_GENRE          default 5
REFRESH_INTERVAL_HOURS  default 168 (weekly)
DATA_DIR                default /data
```

**Radarr / Sonarr (staging — dormant until enabled)**
```
STAGING_ENABLED         default false
RADARR_URL              e.g. http://radarr:7878
RADARR_API_KEY          (secret)
RADARR_ROOT_FOLDER      default /movies
SONARR_URL              e.g. http://sonarr:8989
SONARR_API_KEY          (secret)
SONARR_TV_ROOT_HINT     default /tv       (matches TV to your Sonarr TV root)
SONARR_CARTOON_ROOT_HINT default /cartoon (matches cartoons to cartoon root)
```

**Swarm deploy wiring (used by docker-compose.yaml)**
```
IMAGE                   default jellyfin-recs:latest
DATA_HOST_PATH          default /opt/jellyfin-recs/data
DEPLOY_NODE             hostname to pin to (bind mount lives here)
PUBLISH_PORT            default 8577
```

If you use file-based secrets instead of plain env, set e.g.
`JELLYFIN_API_KEY_FILE=/run/secrets/jellyfin_key` and the entrypoint exports
the file's contents to `JELLYFIN_API_KEY` at startup.

## Networking notes

- Everything runs on the single `traefik-public` overlay: Traefik routes inbound
  to the dashboard, and the app reaches Jellyfin/Radarr/Sonarr by service name
  over the same network (`http://jellyfin:8096`, etc.). Make sure those services
  are attached to `traefik-public` too.
- If any of them live elsewhere, point the relevant `*_URL` var at the right
  address instead.
- Data lives on **NFS** (`/mnt/nfs/container/jellyfin-recs/data`), shared across
  nodes — so the service can run on any worker without pinning, and approvals/
  recs survive a reschedule.

## Enabling Radarr/Sonarr staging

When ready (see main README), set:
```
STAGING_ENABLED=true
SONARR_TV_ROOT_HINT=/tv           # or your actual Sonarr TV root
SONARR_CARTOON_ROOT_HINT=/cartoon # or your actual Sonarr cartoon root
```
and make sure `RADARR_API_KEY` / `SONARR_API_KEY` are set. Redeploy.

## Local smoke test before Swarm (optional)

```bash
cp .env.example .env      # fill in keys
docker compose -f deploy/compose.local.yml up --build
open http://localhost:8577
```

## Updating

To ship a new version: bump, tag, and push — the Action builds and publishes the
new image to GHCR (see GIT.md). Then point the deployment at the new tag:
```bash
# after the release Action has published ghcr.io/jsaumer/jellyfin-recs:0.2.0
# bump the image tag in deploy/docker-compose.yaml (or set IMAGE in Komodo), then:
docker service update --image ghcr.io/jsaumer/jellyfin-recs:0.2.0 jellyfin-recs_jellyfin-recs
# or re-deploy the stack (or let Komodo redeploy on the repo change)
```
`update_config: order: stop-first` ensures the old container releases the NFS
mount before the new one starts.
