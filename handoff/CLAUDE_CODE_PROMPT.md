# Prompt to give Claude Code (v0.3.0)

Place this `handoff/` folder in the repo root, open Claude Code there, and
paste the fenced block:

---

```
Implement version 0.3.0 of this app. Full spec: handoff/TASK.md — read it
first, then implement.

Summary of the release:
1. Restructure Claude's output around ranked "Top 10" lists per category
   (movies / shows / cartoons) as the primary tier, with genre sections capped
   to top-6 movie genres and top-4 show genres at 3 picks each, and docs as a
   flat list of 5. New JSON schema + instruction text is in
   handoff/prompt_instruction_reference.py — use it.
2. Add TMDB enrichment: new module src/jellyfin_recs/tmdb.py, copied from
   handoff/tmdb_reference.py (already tested with mocked HTTP). Wire
   tmdb.enrich_all(recs) into pipeline.py right after recommender.generate().
   Add TMDB_API_KEY to config.py, deploy/docker-compose.yaml env, and
   .env.example. Enrichment adds tmdb_id/imdb_id/imdb_url/tmdb_url/poster/
   rating (+tvdb_id for TV) to each rec — best-effort, no-op without a key.
3. Update /api/stage in dashboard.py and the UI stage call to pass the
   enriched tmdb_id / tvdb_id through to staging.stage_movie / stage_series
   (they already accept these params — exact-ID staging replaces fuzzy name
   lookup when IDs are present).
4. Dashboard UI: each tab renders "🏆 Top 10" first (show the rank number),
   then capped genre sections; cards show poster thumbnail, ★ rating badge,
   and IMDb/TMDB link buttons when those fields exist. Must tolerate missing
   enrichment fields and short Top 10 lists.
5. Update generate() so the ownership filter and history-dismiss pass also walk
   top10_movies / top10_shows / top10_cartoons (flat lists, keep the rank
   field). The old flat "cartoons" list is replaced by top10_cartoons.
6. Tests: add test_tmdb_enrichment (pattern in handoff/tmdb_test_snippet.py)
   and a schema-shape test for the new top10 keys. make lint && make test must
   pass.
7. Version: make release-minor (-> 0.3.0). CHANGELOG [0.3.0] entry. Bump the
   pinned image in deploy/docker-compose.yaml to 0.3.0.
8. Verify git status shows no secrets/data/library JSON, then commit:
   "Top-10 restructure + TMDB enrichment (v0.3.0)" and tag v0.3.0.
   Do NOT push — show me the diff summary and test output for review.

Constraints: do not touch _parse_json/_repair_truncated_json; keep
MAX_OUTPUT_TOKENS=8000; relative imports (from . import x) inside the package.
```

---

## After Claude Code finishes (your steps)

1. Review the diff, then: `git push && git push origin v0.3.0` → GHCR builds.
2. Get a free TMDB API key: themoviedb.org → Settings → API → request key.
3. Add `TMDB_API_KEY` to the stack env in Komodo.
4. Bump the running image to 0.3.0 in Komodo, redeploy, hit Refresh.

Expected result: each tab leads with a ranked Top 10 (franchise gaps at the
top), poster thumbnails, ★ ratings, IMDb/TMDB links — and when you later enable
staging, grabs land on exact TMDB/TVDB IDs instead of name matches.
