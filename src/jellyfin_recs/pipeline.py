"""
Pipeline orchestrator: Jellyfin -> Claude -> storage.

Run directly to refresh recommendations once:
    python3 pipeline.py

Or import and call run_refresh() from the dashboard / scheduler.
"""

import sys
import time

from . import config
from . import jellyfin_client
from . import recommender
from . import storage
from . import tmdb


def rerank_by_rating(recs):
    """Reorder each displayed top list by TMDB rating (descending), then
    reassign ranks 1..N. Entries missing a rating sort last, preserving their
    prior relative order (stable). Selection is unchanged — franchise gaps keep
    their spots — only the DISPLAY ORDER of the surviving list becomes
    rating-based. Genre sections are left untouched. Call AFTER enrichment so
    ratings exist."""
    def sort_key(rec):
        rating = rec.get("rating")
        if isinstance(rating, (int, float)):
            return (0, -rating)   # rated first, highest rating leads
        return (1, 0.0)           # unrated last (stable keeps prior order)

    for section in recommender.RANKED_LISTS:
        lst = recs.get(section)
        if isinstance(lst, list):
            recs[section] = sorted(lst, key=sort_key)
    recommender._rerank(recs)
    return recs


def run_refresh(verbose=True):
    """Fetch the library, generate recommendations, persist everything.
    Returns the recommendations dict."""
    problems = config.validate(require_claude=True)
    if problems:
        raise RuntimeError("Config problems:\n  - " + "\n  - ".join(problems))

    if verbose:
        print("[1/3] Fetching library from Jellyfin ...")
    library = jellyfin_client.fetch_library()
    counts = {c: len(items) for c, items in library.items()}
    if verbose:
        print("      " + ", ".join(f"{c}: {n}" for c, n in counts.items()))
    storage.save_library_cache(library)

    if verbose:
        print(f"[2/3] Requesting recommendations from Claude ({config.CLAUDE_MODEL}) ...")
    recs = recommender.generate(library)
    # Best-effort TMDB enrichment (posters, ratings, IMDb/TMDB links, exact
    # IDs). No-op without TMDB_API_KEY; never fails the refresh.
    recs = tmdb.enrich_all(recs)
    # Order each displayed top list by rating (needs the ratings enrichment
    # just added). Selection stays model-priority; only display order changes.
    recs = rerank_by_rating(recs)

    if verbose:
        removed = recs.get("_meta", {}).get("removed_as_owned", [])
        n_movies = sum(len(v) for v in recs.get("movies", {}).values())
        n_shows = sum(len(v) for v in recs.get("shows", {}).values())
        print(f"      {n_movies} movie + {n_shows} show recs "
              f"({len(removed)} dropped as already owned)")

    if verbose:
        print("[3/3] Saving results ...")
    storage.save_recommendations(recs)
    if verbose:
        print(f"      Done. Saved to {config.RECS_FILE}")
    return recs


def main():
    try:
        run_refresh(verbose=True)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
