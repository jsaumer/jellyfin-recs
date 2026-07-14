# Task: Send the full library to Claude + add franchise-gap detection (v0.2.0)

## Context

`jellyfin-recs` is a Python app (package at `src/jellyfin_recs/`) that reads a
Jellyfin library, asks the Claude API for recommendations, and serves a
dashboard. It's deployed as a container on Docker Swarm via GitHub Actions →
GHCR. Current version is 0.1.1.

## The problem being fixed

The recommendation quality is weak because the prompt sent to Claude only
includes **genre counts** and a **60-item sample of watched titles** — NOT the
actual library. As a result the model:
- Can't see what the user owns, so it re-recommends owned titles (a local
  ownership filter then strips them post-hoc, wasting the model's picks).
- Can't detect franchise/series gaps (e.g. "owns Casino Royale + Spectre but
  not Skyfall"), which are the highest-value recommendations for this user's
  completionist taste.

## What to change

### 1. Send the FULL library, densely encoded

Rework `build_profile()` and `_build_prompt()` in
`src/jellyfin_recs/recommender.py` to include every owned title (not just
watched), encoded densely to keep tokens reasonable.

**Format that was measured and chosen** (≈9k tokens for a 1,300-item library,
vs 623k for a naive JSON dump — a 69× saving for the same signal):
- Per category: a header line with counts + top genres, then a single
  comma-separated line of `✓Title (Year)` entries, where a leading `✓` marks a
  watched title and no prefix means owned-but-unwatched.

The reference implementation of both functions is in
`recommender_reference_functions.py` — match it. It is already tested against
real data and produces a ~9,600-token prompt containing all 1,298 movies with
correct watched markers.

### 2. Add franchise-gap detection

Add deterministic franchise-gap detection so the highest-confidence
recommendations (missing entries from partially-owned franchises) don't rely on
the model noticing them from the raw list.

The reference implementation is in `franchise_detection_reference.py` — add
`FRANCHISES` and `detect_franchise_gaps()` to `recommender.py`. Then, in
`generate()`, compute the gaps from `profile["owned_titles"]` and inject them
into the prompt as an explicit high-priority section, e.g.:

```
## FRANCHISE GAPS — highest-priority recommendations (the user owns some but not all)
James Bond (Craig): missing Quantum of Solace, Skyfall, No Time to Die
X-Men: missing X2, X-Men: The Last Stand, X-Men: First Class, X-Men: Days of Future Past, Logan
...
```

Tested output against the real library correctly finds Mad Max, X-Men, Craig
Bond, Terminator, Alien, Predator, and Planet of the Apes gaps.

Wire this into `_build_prompt()` (add a `franchise_gaps` parameter) and pass it
from `generate()`. Instruct the model to prioritize these gaps first.

### 3. Update the smoke tests

`tests/smoke_test.py` references the OLD profile field `watched_sample`, which
no longer exists (it's now `owned_entries` + `watched_count`). Fix the profiling
test accordingly, and add a test for `detect_franchise_gaps()` (give it a fake
owned set that partially covers one franchise; assert the missing entries come
back).

### 4. Version + changelog + compose

- Bump `VERSION` to `0.2.0` (this is a feature release: `make release-minor`).
- Add a `[0.2.0]` entry to `CHANGELOG.md` under a new "### Added" / "### Changed"
  describing full-library context and franchise-gap detection.
- Bump the pinned image tag in `deploy/docker-compose.yaml` from
  `0.1.1` to `0.2.0`.

## Constraints / gotchas

- Keep the 8000-token output cap (`MAX_OUTPUT_TOKENS`) from 0.1.1 — with the
  richer prompt the model may produce more, and the JSON-repair salvage logic
  must remain intact. Don't touch `_parse_json` / `_repair_truncated_json`.
- The local ownership verification in `generate()` (`_filter_owned`) must stay —
  it's the safety net. Franchise detection and full-library context reduce dupes
  but don't replace the post-hoc filter.
- Imports inside the package are relative (`from . import config`). Match style.
- Run `make lint` and `make test` — both must pass before committing.
- Do NOT commit secrets, `.env`, `data/`, or library JSON files (`.gitignore`
  already covers these; verify with `git status` before committing).

## Definition of done

1. `make lint` and `make test` pass.
2. A dry run of the prompt builder against a sample library shows: full titles
   present, watched markers correct, and a "FRANCHISE GAPS" section when the
   library partially owns a franchise. (See `verify_snippet.py` for a ready
   check you can run.)
3. Version is 0.2.0, changelog updated, compose image tag bumped.
4. Commit, tag `v0.2.0`, push, and push the tag to trigger the GHCR build:
   `git push && git push origin v0.2.0`.

## After deploy

In Komodo, bump the running image to `0.2.0` and redeploy. Trigger a refresh;
`recommendations.json` should now include franchise-gap picks (e.g. Skyfall,
Logan, Mad Max: Fury Road) that the old version couldn't surface.
