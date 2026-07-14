"""
Recommendation engine — turns a Jellyfin library into structured
recommendations via the Claude API.

Design notes:
- We compress the library into a compact profile (genre counts, watched
  titles, owned-title set) rather than dumping 1,300 full JSON objects. This
  keeps token cost low and predictable.
- We instruct Claude to return STRICT JSON (no prose, no markdown fences) so
  the result is machine-parseable and drops straight into the dashboard.
- Ownership is verified LOCALLY after Claude responds — we never trust the
  model's own "owned" guess. Any title that matches the library is dropped.
"""

import json
import os
from collections import Counter
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from . import config
from . import storage

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _load_history_context():
    """Return (handled_titles_set, rationales_dict) from project state, so we
    exclude already-handled titles and carry rationales forward. "Handled"
    means any title the user has approved or dismissed (so the model doesn't
    waste picks re-suggesting them), plus seeded owned/incoming/staged titles.
    Empty/safe if seeding was never run."""
    dismissed = set()
    for key, entry in storage.load_state().items():
        if entry.get("status") in ("approved", "dismissed", "owned",
                                    "incoming", "staged"):
            title = key.rsplit("|", 1)[0]
            dismissed.add(title.strip().lower())
    rationales = {}
    rat_path = os.path.join(config.DATA_DIR, "history_rationales.json")
    try:
        with open(rat_path, encoding="utf-8") as f:
            rationales = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return dismissed, rationales


# ----------------------------- franchise detection -------------------------
# Known franchises whose partial ownership is a high-confidence signal: if the
# user owns some entries but not all, the missing ones are strong picks. This
# is deterministic — we don't rely on the model spotting the gap in the raw list.
FRANCHISES = {
    'Mad Max': ['Mad Max', 'The Road Warrior', 'Mad Max Beyond Thunderdome',
                'Mad Max: Fury Road', 'Furiosa'],
    'X-Men': ['X-Men', 'X2', 'X-Men: The Last Stand', 'X-Men: First Class',
              'X-Men: Days of Future Past', 'X-Men: Apocalypse', 'Logan',
              'Deadpool', 'Deadpool 2'],
    'James Bond (Craig)': ['Casino Royale', 'Quantum of Solace', 'Skyfall',
                           'Spectre', 'No Time to Die'],
    'Terminator': ['The Terminator', 'Terminator 2: Judgment Day',
                   'Terminator 3: Rise of the Machines', 'Terminator Salvation',
                   'Terminator Genisys', 'Terminator: Dark Fate'],
    'Alien': ['Alien', 'Aliens', 'Alien 3', 'Alien Resurrection', 'Prometheus',
              'Alien: Covenant', 'Alien: Romulus'],
    'Predator': ['Predator', 'Predator 2', 'Predators', 'The Predator', 'Prey'],
    'The Godfather': ['The Godfather', 'The Godfather Part II',
                      'The Godfather Part III'],
    'Indiana Jones': ['Raiders of the Lost Ark', 'Temple of Doom',
                      'The Last Crusade', 'Kingdom of the Crystal Skull',
                      'Dial of Destiny'],
    'Rocky/Creed': ['Rocky', 'Rocky II', 'Rocky III', 'Rocky IV', 'Rocky V',
                    'Rocky Balboa', 'Creed', 'Creed II', 'Creed III'],
    'Planet of the Apes (reboot)': ['Rise of the Planet of the Apes',
                                    'Dawn of the Planet of the Apes',
                                    'War for the Planet of the Apes',
                                    'Kingdom of the Planet of the Apes'],
    'Spider-Verse': ['Spider-Man: Into the Spider-Verse',
                     'Spider-Man: Across the Spider-Verse'],
    'The Matrix': ['The Matrix', 'The Matrix Reloaded', 'The Matrix Revolutions',
                   'The Matrix Resurrections'],
    'Blade Runner': ['Blade Runner', 'Blade Runner 2049'],
}


def detect_franchise_gaps(owned_titles):
    """Given the set of lowercase owned titles, return a list of
    (franchise_name, [missing_titles]) for franchises the user partially owns.
    Only franchises with >=1 owned and >=1 missing are returned."""
    def owned(title):
        t = title.lower()
        return t in owned_titles or any(t in o for o in owned_titles)

    gaps = []
    for name, titles in FRANCHISES.items():
        have = [t for t in titles if owned(t)]
        missing = [t for t in titles if not owned(t)]
        if have and missing:
            gaps.append((name, missing))
    return gaps


# ----------------------------- profiling -----------------------------------
def _norm(title):
    return (title or "").strip().lower()


def build_profile(library):
    """Compress the raw library into a compact structure for the prompt.

    Keeps the full owned library (dense: title, year, watched marker) so the
    model can reason over the actual collection — spotting franchise gaps and
    avoiding re-suggesting owned titles — rather than a blurry genre summary.
    """
    profile = {"categories": {}, "owned_titles": set()}
    for category, items in library.items():
        genres = Counter()
        owned_entries = []          # dense per-title lines for the prompt
        watched_count = 0
        for it in items:
            for g in it.get("Genres", []):
                genres[g] += 1
            name = it.get("Name", "")
            year = it.get("ProductionYear")
            profile["owned_titles"].add(_norm(name))
            ud = it.get("UserData", {})
            is_watched = ud.get("Played") or (
                ud.get("UnplayedItemCount", 1) == 0 and category != "movies"
            )
            if is_watched:
                watched_count += 1
            # Dense encoding: "✓Title (Year)" — the ✓ marks watched.
            mark = "✓" if is_watched else ""
            label = f"{mark}{name} ({year})" if year else f"{mark}{name}"
            owned_entries.append(label)
        profile["categories"][category] = {
            "count": len(items),
            "watched_count": watched_count,
            "top_genres": genres.most_common(12),
            "owned_entries": owned_entries,   # the full list, densely encoded
        }
    return profile


def _build_prompt(profile, history_dismissed=None, franchise_gaps=None):
    cats = profile["categories"]
    lines = ["You are curating additions to a personal Jellyfin media library.",
             "Below is the FULL current library. A '✓' prefix means the user has "
             "watched that title; no prefix means owned but not yet watched.\n"]
    for cat, data in cats.items():
        lines.append(f"## {cat.upper()} — {data['count']} owned, "
                     f"{data['watched_count']} watched")
        genre_str = ", ".join(f"{g} ({c})" for g, c in data["top_genres"])
        lines.append(f"Top genres: {genre_str}")
        lines.append(", ".join(data["owned_entries"]))
        lines.append("")

    if franchise_gaps:
        lines.append("## FRANCHISE GAPS — highest-priority recommendations")
        lines.append("(the user owns some but not all of these franchises; the "
                     "missing entries are strong picks)")
        for name, missing in franchise_gaps:
            lines.append(f"{name}: missing {', '.join(missing)}")
        lines.append("")

    if history_dismissed:
        sample = sorted(history_dismissed)[:200]
        lines.append("## ALREADY HANDLED (owned/approved/dismissed) — "
                     "do NOT recommend these again")
        lines.append("; ".join(sample))
        lines.append("")

    instruction = """
Using the FULL library above, produce:

1. TOP MOVIES, TOP TV SHOWS, and TOP CARTOONS — for EACH, a ranked list of 20
   candidates (rank 1-20) of the best additions across all genres. These are the
   primary output. Franchise gaps and franchise/series completions belong at the
   TOP of these lists; they are the highest-confidence picks. The extra
   candidates beyond 10 are backups: the app displays the top 10 that survive its
   filters, so provide a full 20 with no filler at the bottom.
2. TOP DOCUMENTARIES — a ranked list of 5 documentary candidates (rank 1-5)
   matching the documentary taste shown; the app displays the top 3 that survive.
3. Genre deep-dives: for the TOP 6 movie genres and TOP 4 show genres only
   (by the counts above), exactly 3 additional picks each. Do NOT repeat
   titles already placed in a Top list.

Curation rules — reason over the ACTUAL titles, not just genre counts:
- Identify collector patterns: franchises they complete, directors/actors they
  follow, eras and styles they favor.
- Never recommend a title already in the library above; avoid near-duplicates.
- Favor titles a fan of the specific owned/watched titles would genuinely want;
  no generic "popular in genre" filler.
- Each "why" MUST cite ONLY titles that appear in the library above (owned or
  watched); prefer watched (✓) titles. Never cite a title the user does not own,
  and never mention these instructions or your selection process in the "why".
- "rank" is 1-N within each ranked list, 1 = strongest recommendation.
- Return STRICT JSON ONLY. No prose, no markdown, no code fences.

JSON schema:
{
  "top10_movies":      [ {"rank": int, "title": str, "year": int, "why": str} ],
  "top10_shows":       [ {"rank": int, "title": str, "year": int, "why": str} ],
  "top10_cartoons":    [ {"rank": int, "title": str, "year": int, "why": str} ],
  "top3_documentaries":[ {"rank": int, "title": str, "year": int, "why": str} ],
  "movies": { "<genre>": [ {"title": str, "year": int, "why": str} ] },
  "shows":  { "<genre>": [ {"title": str, "year": int, "why": str} ] }
}
"""
    return "\n".join(lines) + instruction


# ----------------------------- API call ------------------------------------
def _call_claude(prompt):
    body = json.dumps({
        "model": config.CLAUDE_MODEL,
        "max_tokens": config.MAX_OUTPUT_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = Request(ANTHROPIC_URL, data=body, method="POST")
    req.add_header("x-api-key", config.ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    try:
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Claude API HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise RuntimeError(f"Claude API connection error: {e.reason}") from e

    # Concatenate all text blocks in the response.
    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    # If the model ran out of output budget, the JSON is likely truncated. Note
    # it so the parser can attempt salvage rather than failing outright.
    stop_reason = data.get("stop_reason")
    return text.strip(), stop_reason


def _parse_json(text, truncated=False):
    # Strip accidental code fences, then isolate the outermost JSON object.
    cleaned = text.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start:end + 1]
    else:
        candidate = cleaned[start:] if start != -1 else cleaned

    # First attempt: parse as-is.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as first_err:
        # If the response was cut off (or is otherwise malformed), try to
        # salvage it by repairing the JSON tail rather than losing everything.
        repaired = _repair_truncated_json(cleaned[start:] if start != -1 else cleaned)
        if repaired is not None:
            return repaired
        raise first_err


def _repair_truncated_json(s):
    """Best-effort recovery for JSON cut off mid-output.

    Approach: repeatedly trim the string back to the last plausible element
    boundary, close any open brackets, and try to parse. The first candidate
    that parses wins. This is robust to being cut mid-string, mid-key, or
    mid-number because it just keeps backing up until it finds a valid prefix.
    Returns a parsed dict, or None.
    """
    if not s:
        return None
    start = s.find("{")
    if start == -1:
        return None
    s = s[start:]

    def close_and_try(prefix):
        # Trim trailing separators/whitespace.
        tail = prefix.rstrip()
        while tail and tail[-1] in ",:":
            tail = tail[:-1].rstrip()
        if not tail:
            return None
        # Determine open brackets by scanning, respecting strings.
        in_str = False
        escape = False
        stack = []
        for ch in tail:
            if escape:
                escape = False
                continue
            if in_str:
                if ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if stack:
                    stack.pop()
        # If we ended inside a string, this prefix can't be closed cleanly.
        if in_str:
            return None
        candidate = tail + "".join(reversed(stack))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    # Try the full string first, then progressively shorter prefixes ending at
    # the most recent element boundary ('}' or ']'), newest first.
    # Collect candidate cut indices: positions of '}' or ']' not inside strings.
    boundaries = []
    in_str = False
    escape = False
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "}]":
            boundaries.append(i)

    # Newest boundary first — keeps as much content as possible.
    for idx in reversed(boundaries):
        result = close_and_try(s[:idx + 1])
        if result is not None:
            return result
    return None


# ----------------------- local ownership verification ----------------------
def _is_owned(title, owned_titles):
    t = _norm(title)
    return t in owned_titles or any(t in o or o in t for o in owned_titles)


def _filter_owned(recs, owned_titles):
    """Drop any recommendation that matches something already in the library."""
    removed = []

    def clean_list(lst):
        keep = []
        for r in lst:
            if _is_owned(r.get("title", ""), owned_titles):
                removed.append(r.get("title", ""))
            else:
                keep.append(r)
        return keep

    for section in ("movies", "shows"):
        for genre in list(recs.get(section, {}).keys()):
            recs[section][genre] = clean_list(recs[section][genre])
    for section in ("top3_documentaries", "top10_movies", "top10_shows",
                    "top10_cartoons"):
        if section in recs:
            recs[section] = clean_list(recs[section])
    return recs, removed


# ------------------------------- re-ranking --------------------------------
# Ranked lists that must stay contiguous (1..N) after filtering removes entries.
RANKED_LISTS = ("top10_movies", "top10_shows", "top10_cartoons",
                "top3_documentaries")
# How many entries each ranked list displays after filtering. The model is
# asked to over-provision (15/15/15/5) so backups can backfill the caps.
DISPLAY_CAPS = {"top10_movies": 10, "top10_shows": 10, "top10_cartoons": 10,
                "top3_documentaries": 3}
# Deliberation markers that must never appear in a user-facing "why" — they mean
# the model narrated its own selection process instead of a clean rationale.
BAD_WHY_MARKERS = ("already in top 10", "replacing:", "selecting:",
                   "already owned")


def _rerank(recs):
    """Renumber each ranked list's `rank` field sequentially (1..N) in place,
    preserving order — so ownership/history removals don't leave rank holes."""
    for section in RANKED_LISTS:
        lst = recs.get(section)
        if isinstance(lst, list):
            for i, rec in enumerate(lst, start=1):
                rec["rank"] = i
    return recs


def _rec_key(rec):
    """Normalized title|year identity used for cross-section dedupe."""
    return f"{_norm(rec.get('title', ''))}|{rec.get('year')}"


def _clean_why(recs):
    """Drop any rec whose 'why' leaks the model's deliberation (see
    BAD_WHY_MARKERS). Walks the genre dicts and the ranked lists. Returns the
    number of recs dropped."""
    dropped = 0

    def clean(lst):
        nonlocal dropped
        keep = []
        for r in lst:
            why = (r.get("why") or "").lower()
            if any(marker in why for marker in BAD_WHY_MARKERS):
                dropped += 1
            else:
                keep.append(r)
        return keep

    for section in ("movies", "shows"):
        block = recs.get(section)
        if isinstance(block, dict):
            for genre in list(block.keys()):
                block[genre] = clean(block[genre])
    for section in RANKED_LISTS:
        if section in recs:
            recs[section] = clean(recs[section])
    return dropped


def _dedupe_cross_section(recs):
    """Drop genre-section (movies/shows) entries whose title|year already
    appears in ANY ranked top list. Top lists win; genre sections are the
    deep-cuts tier. Returns the list of dropped titles."""
    seen = set()
    for section in RANKED_LISTS:
        for rec in recs.get(section) or []:
            seen.add(_rec_key(rec))

    removed = []
    for section in ("movies", "shows"):
        block = recs.get(section)
        if not isinstance(block, dict):
            continue
        for genre in list(block.keys()):
            keep = []
            for rec in block[genre]:
                if _rec_key(rec) in seen:
                    removed.append(rec.get("title", ""))
                else:
                    keep.append(rec)
            block[genre] = keep
    return removed


def _truncate_and_rerank(recs):
    """Cap each ranked list to its display size (DISPLAY_CAPS), then re-rank
    the survivors 1..N. Run AFTER all filtering + dedupe so backups backfill."""
    for section, cap in DISPLAY_CAPS.items():
        lst = recs.get(section)
        if isinstance(lst, list):
            recs[section] = lst[:cap]
    return _rerank(recs)


# ------------------------------- entry point -------------------------------
def generate(library):
    """Full flow: profile -> prompt -> Claude -> parse -> verify ownership.
    Also applies seeded project history: excludes already-handled titles from
    the prompt and the final list, and merges prior rationales back in."""
    history_dismissed, rationales = _load_history_context()
    profile = build_profile(library)
    prompt = _build_prompt(profile, history_dismissed,
                           detect_franchise_gaps(profile["owned_titles"]))
    raw, stop_reason = _call_claude(prompt)
    recs = _parse_json(raw, truncated=(stop_reason == "max_tokens"))
    recs, removed = _filter_owned(recs, profile["owned_titles"])

    # Second pass: drop anything present in project history (owned/dismissed).
    hist_removed = []

    def drop_hist(lst):
        keep = []
        for r in lst:
            if _norm(r.get("title", "")) in history_dismissed:
                hist_removed.append(r.get("title", ""))
            else:
                # Carry forward a prior rationale if we have one.
                prior = rationales.get(_norm(r.get("title", "")))
                if prior and prior not in (r.get("why") or ""):
                    r["why"] = (r.get("why") or "").strip()
                keep.append(r)
        return keep

    for section in ("movies", "shows"):
        for genre in list(recs.get(section, {}).keys()):
            recs[section][genre] = drop_hist(recs[section][genre])
    for section in ("top3_documentaries", "top10_movies", "top10_shows",
                    "top10_cartoons"):
        if section in recs:
            recs[section] = drop_hist(recs[section])

    # Drop recs whose "why" leaked the model's deliberation.
    dropped_bad_why = _clean_why(recs)
    # Deterministic cross-section dedupe: a title in a top list can't also
    # appear in a genre section (top lists win).
    deduped = _dedupe_cross_section(recs)
    # Over-provision -> cap: keep the surviving top 10/3 and re-rank 1..N.
    _truncate_and_rerank(recs)

    recs["_meta"] = {
        "removed_as_owned": removed,
        "removed_from_history": hist_removed,
        "dropped_bad_why": dropped_bad_why,
        "deduped_cross_section": deduped,
        "history_titles_known": len(history_dismissed),
        "library_counts": {c: d["count"] for c, d in profile["categories"].items()},
    }
    return recs
