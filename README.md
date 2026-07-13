# Jellyfin Recommendation Pipeline

Automates the whole loop: reads your Jellyfin library → asks Claude for
recommendations that fit your taste → stores them → serves a dashboard where you
browse, approve, and dismiss titles. Radarr/Sonarr staging is fully wired but
**dormant** until you choose to enable it.

```
Jellyfin ──► Claude API ──► recommendations.json ──► Dashboard ──►(later) Radarr/Sonarr
```

Everything runs on your own machine. All API keys stay local.

## Running in Docker / Swarm

To deploy as a container on Docker Swarm (one container running both the
dashboard and scheduler, config via plain environment variables — staged by
Komodo in this homelab — and `data/` bind-mounted to the host), see
**`DOCKER.md`**. For a quick local container test, `docker compose -f deploy/compose.local.yml up --build`
uses a plain `.env`.

## Repository layout

```
jellyfin-recs/
├── src/jellyfin_recs/        # the application package
│   ├── config.py             # all settings; reads env vars / .env
│   ├── jellyfin_client.py    # pulls library + watched status from Jellyfin
│   ├── recommender.py        # taste profile → Claude API → verify ownership
│   ├── pipeline.py           # orchestrates one full refresh
│   ├── storage.py            # JSON persistence (recs, cache, approvals)
│   ├── seed_history.py       # imports prior curation so nothing repeats
│   ├── staging.py            # Radarr/Sonarr push — disabled by default
│   ├── dashboard.py          # Flask server + API endpoints
│   ├── dashboard_ui.py       # single-page UI
│   ├── run_container.py      # runs dashboard + scheduler in one process
│   └── run_scheduler.py      # standalone periodic refresh
├── deploy/
│   ├── docker-compose.yaml   # Swarm deploy file (Komodo pulls this)
│   ├── compose.local.yml     # local single-host testing
│   └── entrypoint.sh         # container entrypoint (PUID/PGID/TZ + launch)
├── docs/
│   ├── DOCKER.md             # container/Swarm deployment guide
│   └── GIT.md                # Git workflow + versioning
├── tests/
│   └── smoke_test.py         # fast checks, no Docker/network/keys needed
├── Dockerfile
├── Makefile                  # build / deploy / test / version helpers
├── pyproject.toml            # package metadata + console entry points
├── requirements.txt
├── VERSION                   # single source of truth for the version
├── CHANGELOG.md
├── .env.example
└── history.example.txt
```

Run from source with `PYTHONPATH=src`, e.g. `PYTHONPATH=src python3 -m
jellyfin_recs.pipeline`. Installed via `pip install .`, the console commands
`jellyfin-recs`, `jellyfin-recs-refresh`, and `jellyfin-recs-seed` are available.

## Seeding project history (recommended first step)

Your months of curation in the Claude.ai project — confirmed acquisitions,
dismissed titles, prior rationales — live in two places the app *can* read:
the master `jellyfin_recommendations.md` file and an optional `history.txt`
log. (The Claude.ai chat threads themselves stay in Anthropic's interface and
aren't reachable from a standalone app, so this on-disk distillation is how the
history carries over.)

1. Drop your master `jellyfin_recommendations.md` into the app folder.
2. Optionally create `history.txt` (copy `history.example.txt`) and list
   confirmed owned / incoming / dismissed titles, one per line:
   ```
   owned: Rocky Balboa (2006)
   incoming: Special When Lit
   dismissed: The Emoji Movie
   ```
3. Run:
   ```bash
   PYTHONPATH=src python3 -m jellyfin_recs.seed_history
   ```

This marks those titles as handled so Claude won't re-suggest them, and
preserves prior "why" rationales to merge into future recs. It's safe to re-run
and it never overwrites anything you've already acted on in the dashboard.

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure**
   ```bash
   cp .env.example .env
   # edit .env with your Jellyfin + Anthropic keys
   ```
   You need, at minimum: `JELLYFIN_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_USERNAME`
   (or `JELLYFIN_USER_ID`), and `ANTHROPIC_API_KEY`.

3. **Generate your first set**
   ```bash
   PYTHONPATH=src python3 -m jellyfin_recs.pipeline
   ```
   This fetches the library and calls Claude once. Cost is small — the library
   is compressed to a ~1k-token profile, not a full dump.

4. **Launch the dashboard**
   ```bash
   PYTHONPATH=src python3 -m jellyfin_recs.dashboard
   ```
   Open http://127.0.0.1:8577. Browse by category tab, **Approve** what you
   want, **Dismiss** what you don't. Approvals persist across restarts. Hit
   **↻ Refresh** any time to regenerate.

## Automatic refresh (the "scheduled" half)

Either leave the built-in scheduler running:
```bash
PYTHONPATH=src python3 -m jellyfin_recs.run_scheduler          # refreshes now, then every REFRESH_INTERVAL_HOURS
```
…or use cron instead (weekly, Sundays 6am):
```
0 6 * * 0 cd /path/to/jellyfin-recs && PYTHONPATH=src /usr/bin/python3 -m jellyfin_recs.pipeline >> refresh.log 2>&1
```
Manual refresh (the button in the dashboard) works regardless.

## Token usage & cost

Each refresh makes **one** Claude API call. The important design detail: the
prompt sends a *compressed profile* of your library — genre counts plus a capped
sample of watched titles — **not** the full list of items. So token usage is
essentially **flat regardless of how many videos are in Jellyfin**.

Measured against a real library:

| Library size | Input tokens per refresh |
|---|---|
| ~1,400 items | ~805 |
| ~5,300 items (simulated 4×) | ~806 |

A library nearly 4× larger changed the input by **one token**. What actually
drives cost is `RECS_PER_GENRE` (how many recommendations come back), since that
determines output length:

| `RECS_PER_GENRE` | Output tokens | Cost per refresh* |
|---|---|---|
| 3 | ~1,800 | ~$0.03 |
| 5 (default) | ~2,500 | ~$0.04 |
| 8 | ~3,600 | ~$0.06 |

At the **weekly default** (52 refreshes/year) with `RECS_PER_GENRE=5`, that's
roughly **$2/year** (~$0.17/month). Even daily refreshes land near **$15/year**.

\* Based on Claude Sonnet 4.6 at $3/M input, $15/M output (the model set in
`CLAUDE_MODEL`). Prices can change — check
[claude.com/pricing](https://claude.com/pricing). Manual refreshes from the
dashboard cost the same per click. If you switch `CLAUDE_MODEL` to a cheaper or
pricier model, scale accordingly (output dominates the bill).

## Enabling Radarr/Sonarr staging later

Staging is intentionally off. When you're ready:

1. In `.env` set `STAGING_ENABLED=true` and fill in `RADARR_API_KEY` and
   `SONARR_API_KEY`, plus quality profiles.
2. Restart the dashboard. Approved titles now show a **→ Grab** button on the
   Movies, TV Shows, and Cartoons tabs.

**Routing** is automatic and reads your live folder layout from each service:

| Tab | Goes to | Root folder |
|---|---|---|
| 🎬 Movies | Radarr | `RADARR_ROOT_FOLDER` |
| 📺 TV Shows | Sonarr | matched via `SONARR_TV_ROOT_HINT` |
| 🎨 Cartoons | Sonarr | matched via `SONARR_CARTOON_ROOT_HINT` |

Because TV and Cartoons are both Sonarr series but live in different root
folders, the app calls Sonarr's `/rootfolder` API, reads your actual configured
roots, and matches each category to the right one using the hints. It tries an
exact path match first, then a case-insensitive substring — so you can set the
hints to full paths (`/data/media/cartoons`) or just distinctive fragments
(`cartoon`). If a hint matches nothing and you have multiple roots, the app
refuses to guess and tells you the available paths so you can set the hint
correctly. The header shows exactly where TV and Cartoons will land once
staging is on.

Grabs add the title as **monitored**. By default they do **not** auto-search
for downloads (`*_ADD_MONITORED_ONLY=true`) — the title lands in your wanted
list for you to grab when ready. Set that to `false` for search-on-add.

## Notes & safety

- **Ownership is verified locally** after Claude responds — any suggestion that
  matches your library is dropped automatically, so you won't get dupes even if
  the model slips.
- **Watched = yes/no only.** Play-counts are ignored (they're unreliable).
- Bind the dashboard to `127.0.0.1` (default). If you expose it on your LAN,
  put it behind your reverse proxy / auth — there's no built-in login.
- The Claude call is the only thing that costs money; it runs on refresh only,
  not on every dashboard load.

## Running as a service (optional)

A minimal systemd unit for the dashboard:
```ini
[Unit]
Description=Jellyfin Recs Dashboard
After=network.target

[Service]
WorkingDirectory=/path/to/jellyfin-recs
Environment=PYTHONPATH=src
ExecStart=/usr/bin/python3 -m jellyfin_recs.dashboard
EnvironmentFile=/path/to/jellyfin-recs/.env
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
Do the same for `run_scheduler.py` if you want scheduled refreshes as a service.
