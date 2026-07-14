# Prompt to give Claude Code

Copy everything in the fenced block below into Claude Code, run from the root of
your `jellyfin-recs` repo. Place the four reference files (TASK.md,
franchise_detection_reference.py, recommender_reference_functions.py,
smoke_test_reference.py, verify_snippet.py) somewhere it can read them — e.g. a
`handoff/` folder in the repo, or just paste their contents when asked.

---

```
I need you to implement version 0.2.0 of this app. The full spec is in
handoff/TASK.md — read it first, then implement.

Summary: the app currently sends Claude only genre counts + a small watched
sample, so recommendations are weak and re-suggest owned titles. I want it to
send the FULL library (densely encoded to keep tokens ~9k not 600k) and add
deterministic franchise-gap detection so missing entries from partially-owned
franchises become the top recommendations.

Reference implementations (already written and tested against real data) are in:
- handoff/recommender_reference_functions.py  — the target build_profile,
  _build_prompt, FRANCHISES dict, and detect_franchise_gaps. Match these in
  src/jellyfin_recs/recommender.py, and wire detect_franchise_gaps into
  generate() as shown at the bottom of that file.
- handoff/smoke_test_reference.py — the updated tests/smoke_test.py (adds
  franchise + new-field checks). Match it.
- handoff/verify_snippet.py — copy to the repo root, run
  `PYTHONPATH=src python3 verify_snippet.py`, confirm all checks pass, then
  delete it.

Steps:
1. Apply the recommender.py changes (full-library prompt + franchise detection,
   wired into generate). Keep _parse_json / _repair_truncated_json and
   _filter_owned exactly as they are — do not touch them.
2. Apply the smoke test changes.
3. Run: make lint && make test  — both must pass.
4. Run the verify_snippet.py check, confirm it passes, then remove it.
5. Bump version: make release-minor (0.1.1 -> 0.2.0).
6. Update CHANGELOG.md: add a [0.2.0] section describing full-library context
   and franchise-gap detection.
7. Bump the pinned image in deploy/docker-compose.yaml from 0.1.1 to 0.2.0.
8. Verify no secrets/data/library-json are staged: git status. Then commit:
   git add -A && git commit -m "Full-library context + franchise-gap detection (v0.2.0)"
   git tag -a v0.2.0 -m "Release v0.2.0"
9. Show me the diff summary and the verify output. Do NOT push yet — I'll review
   and push manually (pushing the tag triggers the GHCR build).

Constraints: package imports are relative (from . import config). Don't commit
.env, data/, or any jellyfin_*.json. The output-token cap MAX_OUTPUT_TOKENS
(8000) and the JSON-repair salvage logic must stay intact.
```

---

## What to expect

Claude Code should end with `make lint` + `make test` green, the verify snippet
passing, version at 0.2.0, and a committed + tagged `v0.2.0` (unpushed).

When you're ready to deploy:
```
git push && git push origin v0.2.0
```
That triggers the GHCR build. Then bump the running image to 0.2.0 in Komodo and
redeploy. Trigger a refresh — the new recommendations.json should include
franchise-gap picks like Skyfall, Logan, and Mad Max: Fury Road that the old
version structurally could not surface.

## Token/cost note

The richer prompt is ~9,800 input tokens (vs ~800 before) — measured against
your real library. That's roughly $0.07/refresh, ~$3.80/year at weekly cadence,
up from ~$2/year. The jump buys full-collection awareness and franchise
detection.
