"""
Project history seeding.

The standalone dashboard cannot read the Claude.ai chat threads in your
project — those live in Anthropic's chat interface, not on your server. But the
*distilled output* of all that curation history does live on disk: the master
`jellyfin_recommendations.md` file, plus an optional plain-text history log.

This module imports both so the dashboard inherits the project's memory:
  - Titles already marked owned/incoming  -> seeded as "dismissed" (so Claude
    won't re-suggest them and they won't clutter the dashboard).
  - Titles you've explicitly dismissed in the past -> seeded as "dismissed".
  - Prior "why" rationales -> preserved and merged into new recs when the same
    title reappears, so the reasoning history carries forward.

Run once after first setup:
    python3 seed_history.py

It's safe to re-run; it merges rather than overwrites.

INPUT FILES (place either or both in the app directory or DATA_DIR):
  1. jellyfin_recommendations.md   — your existing master list
  2. history.txt (optional)        — freeform log, one entry per line:
         owned: The Master (2012)
         owned: Rocky Balboa
         dismissed: Emoji Movie
         incoming: Special When Lit
     Lines starting with '#' are ignored. Year is optional.
"""

import os
import re
import sys

from . import config
from . import storage

# Where to look for the seed files (app dir first, then DATA_DIR).
# Where to look for the seed files. In the container these live in the mounted
# data dir; when running from source, also check the current working directory.
_SEARCH_DIRS = [config.DATA_DIR, os.getcwd()]

# Markdown table row:  | Title | Year | Why | Owned | Watched |
_ROW = re.compile(r"^\|\s*(?P<title>[^|]+?)\s*\|\s*(?P<year>\d{4}|—|-)?\s*\|"
                  r"\s*(?P<why>[^|]*?)\s*\|\s*(?P<owned>[^|]*?)\s*\|")

# History log line:  status: Title (Year)
_HIST = re.compile(r"^\s*(?P<status>owned|incoming|dismissed|approved)\s*:\s*"
                   r"(?P<title>.+?)\s*(?:\((?P<year>\d{4})\))?\s*$", re.IGNORECASE)


def _find(filename):
    for d in _SEARCH_DIRS:
        path = os.path.join(d, filename)
        if os.path.exists(path):
            return path
    return None


def _clean_title(t):
    # Strip markdown emphasis and trailing notes like "(series)".
    t = t.replace("*", "").strip()
    return t


def _year_or_none(y):
    return int(y) if y and y.isdigit() else None


def parse_master_md(path):
    """Return (seeds, rationales).
    seeds: list of (title, year, status)
    rationales: {title_lower: why}
    Owned/incoming titles in the master list become 'dismissed' so they're not
    re-recommended; their rationale is still captured for reference."""
    seeds, rationales = [], {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _ROW.match(line)
            if not m:
                continue
            title = _clean_title(m.group("title"))
            if title.lower() in ("title", ""):     # header row
                continue
            year = _year_or_none((m.group("year") or "").strip())
            why = (m.group("why") or "").strip()
            owned_cell = (m.group("owned") or "").lower()
            if why:
                rationales[title.lower()] = why
            # Anything already flagged owned/incoming shouldn't be re-suggested.
            if "yes" in owned_cell or "✅" in owned_cell or "incoming" in owned_cell:
                seeds.append((title, year, "dismissed"))
    return seeds, rationales


def parse_history_txt(path):
    seeds = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#") or not line.strip():
                continue
            m = _HIST.match(line)
            if not m:
                continue
            status = m.group("status").lower()
            title = _clean_title(m.group("title"))
            year = _year_or_none(m.group("year"))
            # owned/incoming -> dismissed (don't resuggest); others as-is.
            mapped = "dismissed" if status in ("owned", "incoming") else status
            seeds.append((title, year, mapped))
    return seeds


def seed(verbose=True):
    all_seeds, rationales = [], {}

    md = _find("jellyfin_recommendations.md")
    if md:
        s, r = parse_master_md(md)
        all_seeds += s
        rationales.update(r)
        if verbose:
            print(f"Parsed master list: {len(s)} owned/incoming titles, "
                  f"{len(r)} rationales  ({md})")
    else:
        if verbose:
            print("No jellyfin_recommendations.md found — skipping master list.")

    hist = _find("history.txt")
    if hist:
        s = parse_history_txt(hist)
        all_seeds += s
        if verbose:
            print(f"Parsed history.txt: {len(s)} entries  ({hist})")

    if not all_seeds:
        if verbose:
            print("Nothing to seed. Place jellyfin_recommendations.md and/or "
                  "history.txt in the app folder and re-run.")
        return {"seeded": 0, "rationales": 0}

    # Merge into state without clobbering anything you've already acted on.
    existing = storage.load_state()
    added = 0
    for title, year, status in all_seeds:
        key = storage.item_key(title, year)
        if key not in existing:
            existing[key] = {"status": status, "ts": 0, "source": "history"}
            added += 1
    storage._write(config.STATE_FILE, existing)

    # Persist rationales so the recommender can merge them into fresh recs.
    rat_path = os.path.join(config.DATA_DIR, "history_rationales.json")
    storage._write(rat_path, rationales)

    if verbose:
        print(f"\nSeeded {added} new state entries (owned/incoming/dismissed).")
        print(f"Saved {len(rationales)} rationales to {rat_path}")
        print("The dashboard and future refreshes will now skip these titles.")
    return {"seeded": added, "rationales": len(rationales)}


def main():
    try:
        seed(verbose=True)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
