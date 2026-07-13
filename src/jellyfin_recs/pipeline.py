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
