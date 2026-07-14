# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-13

### Added
- **Top-10 restructure**: Claude's output now leads with ranked `top10_movies`,
  `top10_shows`, and `top10_cartoons` lists (rank 1-10) as the primary tier —
  franchise gaps and series completions are steered to the top ranks. The
  dashboard renders a "🏆 Top 10" section first on each tab, showing the rank
  number. The old flat `cartoons` list is replaced by `top10_cartoons`.
- **Capped genre deep-dives**: the `movies`/`shows` genre sections are now a
  browse-deeper tier — top 6 movie genres and top 4 show genres, 3 picks each,
  with no repeats of Top-10 titles. Documentaries remain a flat list of 5. The
  net result is fewer, higher-signal recs (~55 vs ~80), so the 8000-token output
  cap has more headroom.
- **TMDB enrichment** (`tmdb.py`): after the Claude call, each recommendation is
  looked up against TMDB (zero AI tokens) to add `tmdb_id`, `imdb_id`,
  `imdb_url`, `tmdb_url`, `poster` (w342), `rating`, and `tvdb_id` (TV). Wired
  into the pipeline right after `recommender.generate()`. Best-effort: a failed
  lookup leaves the rec un-enriched, and with no `TMDB_API_KEY` it is a silent
  no-op. Cards now show a poster thumbnail, a ★ rating badge, and IMDb/TMDB link
  buttons when those fields are present, tolerating any missing enrichment.
- **Exact-ID staging**: the "Grab" flow now passes the enriched `tmdb_id` /
  `tvdb_id` through to `staging.stage_movie` / `stage_series`, so approved
  titles land on exact TMDB/TVDB IDs instead of a fuzzy name lookup when
  enrichment is available.

### Changed
- `_filter_owned` and the history-dismiss pass in `generate()` now also walk the
  three `top10_*` flat lists, preserving the `rank` field through filtering. The
  `_parse_json` / `_repair_truncated_json` salvage logic and the local ownership
  filter are unchanged.

## [0.2.0] - 2026-07-13

### Added
- **Full-library context**: the prompt now sends the *entire* owned library to
  Claude — every title, densely encoded as `✓Title (Year)` (a `✓` marks watched,
  no prefix means owned-but-unwatched) — instead of only genre counts and a
  60-item watched sample. The dense encoding keeps a ~1,300-item library at
  ~9.8k input tokens (vs ~623k for a naive JSON dump), so the model can reason
  over the actual collection: follow directors/actors, respect eras, and avoid
  re-suggesting owned titles rather than working from a blurry genre summary.
- **Franchise-gap detection** (`FRANCHISES`, `detect_franchise_gaps`):
  deterministic detection of partially-owned franchises. When the user owns some
  but not all entries of a known franchise (e.g. Craig-era Bond, X-Men,
  Mad Max), the missing entries are injected into the prompt as an explicit
  highest-priority "FRANCHISE GAPS" section, so high-confidence picks like
  Skyfall, Logan, and Mad Max: Fury Road are surfaced first rather than relying
  on the model noticing the gap in the raw list.

### Changed
- `build_profile()` now emits `owned_entries` (the full dense per-title list) and
  `watched_count` per category, replacing the old `watched_sample`. The
  `_build_prompt()` curation guidance was rewritten to reason over the actual
  titles and prioritize franchise/series gaps. The 8000-token output cap and the
  truncated-JSON salvage logic are unchanged; the local ownership filter remains
  as the post-hoc safety net.
- Richer prompt raises input cost to ~$0.07/refresh (~$3.80/year at the weekly
  default), up from ~$2/year, in exchange for full-collection awareness.

## [0.1.1] - 2026-07-13

### Fixed
- Refresh failed with a JSON parse error (`Expecting ',' delimiter`) when the
  model's recommendation response was truncated by the output-token limit.
  Raised the default output cap to 8000 tokens (configurable via
  `MAX_OUTPUT_TOKENS`) and made JSON parsing resilient: a truncated response is
  now repaired by salvaging all complete recommendations instead of discarding
  the entire result.


### Added
- GitHub Actions release workflow that builds and publishes the container image
  to GHCR (`ghcr.io/jsaumer/jellyfin-recs`) on every `v*.*.*` tag push. The
  Swarm compose file now pins a specific image version.
- README section documenting token usage and cost: usage is flat regardless of
  library size (~805 input tokens whether 1,400 or 5,300 items), ~$2/year at the
  weekly default.

### Changed
- Restructured to a standard Python `src/` package layout
  (`src/jellyfin_recs/`), with deploy files under `deploy/`, docs under `docs/`,
  and console entry points defined in `pyproject.toml`. Intra-package imports
  are now relative; the container runs via `python3 -m jellyfin_recs.run_container`.

## [0.1.0] - 2026-07-13

Initial release. Automated Jellyfin recommendation pipeline with a browsable
dashboard, deployable as a single container on Docker Swarm.

### Added
- **Recommendation engine** (`recommender.py`): compresses the Jellyfin library
  into a compact taste profile (~800 tokens), calls the Anthropic API for
  genre-organized recommendations, parses strict JSON, and verifies ownership
  locally so already-owned titles are never re-suggested.
- **Jellyfin client** (`jellyfin_client.py`): reads Movies/Shows/Cartoons with
  watched status; watched is treated as a boolean (play-counts ignored).
- **Dashboard** (`dashboard.py`, `dashboard_ui.py`): single-page UI to browse
  recommendations by category and genre, approve/dismiss/reset titles, and
  trigger manual refreshes. Approvals persist across restarts.
- **History seeding** (`seed_history.py`): imports the master
  `jellyfin_recommendations.md` and an optional `history.txt` so prior
  curation (owned/incoming/dismissed titles and rationales) carries forward.
- **Radarr/Sonarr staging** (`staging.py`): one-click "Grab" for approved
  titles, dormant until `STAGING_ENABLED=true`. Routes Movies to Radarr, TV to
  the Sonarr TV root, and Cartoons to the Sonarr cartoon root — root folders
  read live from the Sonarr API.
- **Scheduler**: automatic weekly refresh (`REFRESH_INTERVAL_HOURS`, default
  168), plus a manual refresh button.
- **Containerization**: `Dockerfile`, single-container runner
  (`run_container.py`) for dashboard + scheduler, and `entrypoint.sh` honoring
  `PUID`/`PGID`/`TZ` with privilege-drop via gosu.
- **Swarm deploy** (`docker-compose.yaml`): Traefik routing + TLS, dockns DNS
  registration, NFS-backed data, worker placement, memory limits — matching the
  homelab conventions. `compose.local.yml` for local testing.
- **Tooling**: `Makefile` (build/deploy/redeploy/logs/test/lint), smoke tests
  (`tests/smoke_test.py`), and CI workflows for GitHub and Gitea.
- **Docs**: `README.md`, `DOCKER.md`, `GIT.md`.

[Unreleased]: https://github.com/jsaumer/jellyfin-recs/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/jsaumer/jellyfin-recs/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jsaumer/jellyfin-recs/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/jsaumer/jellyfin-recs/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jsaumer/jellyfin-recs/releases/tag/v0.1.0
