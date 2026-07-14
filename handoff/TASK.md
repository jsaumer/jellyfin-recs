# Task: Top-10 restructure + TMDB enrichment (v0.3.0)

## Context

`jellyfin-recs` at v0.2.0 sends the full library to Claude with franchise-gap
detection. Output quality is high, but the structure sprawls: 12+ genres × up
to 5 picks. This release restructures the output around ranked Top 10 lists and
enriches every recommendation with TMDB data (posters, IMDb/TMDB links,
ratings, and exact IDs for future Radarr/Sonarr staging).

## Changes

### 1. Output restructure (recommender.py)

Replace the `instruction` block in `_build_prompt()` with the version in
`prompt_instruction_reference.py`. New shape:

- `top10_movies`, `top10_shows`, `top10_cartoons` — ranked lists (rank 1-10),
  the primary output. Franchise gaps should dominate the top ranks.
- `movies`/`shows` genre dicts remain but capped: top 6 movie genres / top 4
  show genres, exactly 3 picks each, no repeats from the Top 10s.
- `documentaries` — flat list of 5.
- The old flat `cartoons` list is gone (replaced by `top10_cartoons`).

Update `generate()` so `_filter_owned` and the history-dismissed drop pass also
walk the three new `top10_*` flat lists (same treatment as `documentaries`).
Preserve the `rank` field through filtering. Everything else in generate()
(franchise gaps, JSON repair, `_meta`) stays.

### 2. New module: src/jellyfin_recs/tmdb.py

Copy from `tmdb_reference.py` (tested with mocked HTTP). It looks each rec up
against TMDB after the Claude call and adds: `tmdb_id`, `imdb_id`, `imdb_url`,
`tmdb_url`, `poster` (w342 URL), `rating`, and `tvdb_id` for TV. Best-effort:
failures leave recs un-enriched; no key = no-op.

Config: add to `config.py`:
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

Wire into `pipeline.py` after `recommender.generate()`:
    from . import tmdb
    recs = tmdb.enrich_all(recs)

Add `TMDB_API_KEY=${TMDB_API_KEY}` to the environment block in
`deploy/docker-compose.yaml`, and a commented line to `.env.example`.

### 3. Staging uses exact IDs (staging.py + dashboard.py)

In `dashboard.py` `/api/stage`: pass the rec's enriched IDs through —
`staging.stage_movie(tmdb_id=..., title=..., year=...)` and
`staging.stage_series(tvdb_id=..., title=..., year=..., category=...)`. The
staging functions already accept these params and prefer them over name lookup.
The UI must include `tmdb_id`/`tvdb_id` in the stage POST body when present on
the rec.

### 4. Dashboard UI (dashboard_ui.py)

- Each category tab shows a "🏆 Top 10" section FIRST (ranked, showing the rank
  number), then the capped genre sections (movies/shows), then nothing else.
  Docs tab is just the flat list. Cartoons tab is just its Top 10.
- Card upgrades when enrichment fields are present:
  - poster thumbnail on the left (the `poster` URL; hide gracefully if absent)
  - a ★ rating badge (`rating`)
  - small "IMDb" and "TMDB" link buttons opening `imdb_url` / `tmdb_url` in a
    new tab
- Tolerate missing fields everywhere (enrichment is best-effort) and tolerate
  short Top 10 lists (cartoons may return fewer than 10).
- Approve/Dismiss/state logic unchanged; keys remain title|year.

### 5. Tests

- Update `tests/smoke_test.py`: add a test for `tmdb.enrich_all` with a mocked
  `_get` (see the mock pattern in `tmdb_test_snippet.py`), asserting movie
  enrichment fields, tv `tvdb_id`, walking of `top10_*` keys, and the no-key
  no-op.
- Add a schema-shape test: feed `_parse_json` a valid new-schema payload and
  assert `top10_movies` survives `_filter_owned` with ranks intact.
- `make lint` and `make test` must pass.

### 6. Version / changelog / compose

- `make release-minor` (0.2.0 → 0.3.0)
- CHANGELOG `[0.3.0]`: Top-10 restructure, capped genres, TMDB enrichment,
  exact-ID staging.
- Bump image tag in `deploy/docker-compose.yaml` to 0.3.0.

## Constraints

- Do NOT touch `_parse_json` / `_repair_truncated_json`.
- Keep `MAX_OUTPUT_TOKENS` at 8000 — the restructure produces FEWER recs
  (~55 vs ~80), so headroom improves.
- Relative imports (`from . import config`). No secrets/data/library JSON in
  commits.
- Commit + tag `v0.3.0`; do NOT push (user reviews then pushes to trigger GHCR).

## Definition of done

1. `make lint` + `make test` green.
2. A dry prompt build shows the new instruction (Top 10 + capped genres).
3. Mocked enrichment test passes.
4. Version 0.3.0, changelog, compose bumped, committed, tagged, unpushed.

## After deploy (user steps, for reference)

- Get a free TMDB API key (themoviedb.org → Settings → API), add TMDB_API_KEY
  to Komodo env.
- Push + push tag → GHCR builds → bump Komodo to 0.3.0 → redeploy → refresh.
