# Reference: replacement for the `instruction` block inside _build_prompt()
# in src/jellyfin_recs/recommender.py. Everything before the instruction
# (library dump, franchise gaps, dismissed list) stays as-is from v0.2.0.
#
# Design: a ranked Top 10 per category is the primary output; genre sections
# are capped (top 6 genres, 3 picks each) as the browse-deeper tier; docs stay
# a small flat list. Franchise gaps should dominate the Top 10s.

INSTRUCTION = '''
Using the FULL library above, produce:

1. TOP 10 MOVIES, TOP 10 TV SHOWS, and TOP 10 CARTOONS — ranked overall lists
   of the best additions across all genres. These are the primary output.
   Franchise gaps and franchise/series completions belong at the TOP of these
   lists; they are the highest-confidence picks.
2. Genre deep-dives: for the TOP 6 movie genres and TOP 4 show genres only
   (by the counts above), exactly 3 additional picks each. Do NOT repeat
   titles already placed in a Top 10.
3. A short documentaries list (5 picks) matching the documentary taste shown.

Curation rules — reason over the ACTUAL titles, not just genre counts:
- Identify collector patterns: franchises they complete, directors/actors they
  follow, eras and styles they favor.
- Never recommend a title already in the library above; avoid near-duplicates.
- Favor titles a fan of the specific owned/watched titles would genuinely want;
  no generic "popular in genre" filler.
- Each "why" MUST cite specific owned or watched titles by name. Prefer citing
  watched (marked ✓) titles where possible.
- "rank" is 1-10 within each Top 10 list, 1 = strongest recommendation.
- Return STRICT JSON ONLY. No prose, no markdown, no code fences.

JSON schema:
{
  "top10_movies":   [ {"rank": int, "title": str, "year": int, "why": str} ],
  "top10_shows":    [ {"rank": int, "title": str, "year": int, "why": str} ],
  "top10_cartoons": [ {"rank": int, "title": str, "year": int, "why": str} ],
  "movies": { "<genre>": [ {"title": str, "year": int, "why": str} ] },
  "shows":  { "<genre>": [ {"title": str, "year": int, "why": str} ] },
  "documentaries": [ {"title": str, "year": int, "why": str} ]
}
'''

# NOTES for integration:
# - The old top-level "cartoons" flat list is REPLACED by top10_cartoons.
# - _filter_owned() and the history drop pass in generate() must also walk the
#   three new top10_* lists (they're flat lists like documentaries).
# - Only 27 cartoons exist in the library; if the model can't find 10 strong
#   cartoon picks it may return fewer — the dashboard must tolerate short lists.
