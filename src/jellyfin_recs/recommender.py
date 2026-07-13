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
    """Return (dismissed_titles_set, rationales_dict) from seeded project
    history, so we exclude already-handled titles and carry rationales forward.
    Empty/safe if seeding was never run."""
    dismissed = set()
    for key, entry in storage.load_state().items():
        if entry.get("status") in ("dismissed", "owned", "incoming", "staged"):
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


# ----------------------------- profiling -----------------------------------
def _norm(title):
    return (title or "").strip().lower()


def build_profile(library):
    """Compress the raw library into a compact structure for the prompt."""
    profile = {"categories": {}, "owned_titles": set()}
    for category, items in library.items():
        genres = Counter()
        watched, owned = [], []
        for it in items:
            for g in it.get("Genres", []):
                genres[g] += 1
            name = it.get("Name", "")
            year = it.get("ProductionYear")
            label = f"{name} ({year})" if year else name
            owned.append(label)
            profile["owned_titles"].add(_norm(name))
            ud = it.get("UserData", {})
            is_watched = ud.get("Played") or (
                ud.get("UnplayedItemCount", 1) == 0 and category != "movies"
            )
            if is_watched:
                watched.append(label)
        profile["categories"][category] = {
            "count": len(items),
            "top_genres": genres.most_common(10),
            "watched_sample": watched[:60],
        }
    return profile


def _build_prompt(profile, history_dismissed=None):
    cats = profile["categories"]
    lines = ["Here is a Jellyfin media library to analyze.\n"]
    for cat, data in cats.items():
        lines.append(f"## {cat.upper()} — {data['count']} items")
        genre_str = ", ".join(f"{g} ({c})" for g, c in data["top_genres"])
        lines.append(f"Top genres: {genre_str}")
        if data["watched_sample"]:
            lines.append("Recently/actually watched: " + "; ".join(data["watched_sample"]))
        lines.append("")

    if history_dismissed:
        # Cap the list so the prompt stays lean, but give Claude the memory.
        sample = sorted(history_dismissed)[:200]
        lines.append("## ALREADY HANDLED — do NOT recommend any of these")
        lines.append("(already owned, incoming, or previously dismissed by the user)")
        lines.append("; ".join(sample))
        lines.append("")

    instruction = f"""
You are a media curator. Based on the taste profile above, recommend
{config.RECS_PER_GENRE} MOVIES and {config.RECS_PER_GENRE} TV SHOWS for EACH of
the top genres in the movie and show libraries respectively. Also include a
short list of documentaries and cartoons/anime that fill obvious gaps.

Rules:
- Recommend only high-quality, well-regarded titles that fit the demonstrated taste.
- Do NOT recommend anything likely already owned (ownership is verified separately, but avoid obvious dupes).
- Each "why" must reference specific owned or watched titles from the profile.
- Return STRICT JSON ONLY. No prose, no markdown, no code fences.

JSON schema:
{{
  "movies": {{ "<genre>": [ {{"title": str, "year": int, "why": str}} ] }},
  "shows":  {{ "<genre>": [ {{"title": str, "year": int, "why": str}} ] }},
  "documentaries": [ {{"title": str, "year": int, "why": str}} ],
  "cartoons": [ {{"title": str, "year": int, "why": str}} ]
}}
"""
    return "\n".join(lines) + instruction


# ----------------------------- API call ------------------------------------
def _call_claude(prompt):
    body = json.dumps({
        "model": config.CLAUDE_MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = Request(ANTHROPIC_URL, data=body, method="POST")
    req.add_header("x-api-key", config.ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    try:
        with urlopen(req, timeout=120) as resp:
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
    return text.strip()


def _parse_json(text):
    # Strip accidental code fences, then parse.
    cleaned = text.replace("```json", "").replace("```", "").strip()
    # Find the outermost JSON object if there's stray text.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


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
    for section in ("documentaries", "cartoons"):
        if section in recs:
            recs[section] = clean_list(recs[section])
    return recs, removed


# ------------------------------- entry point -------------------------------
def generate(library):
    """Full flow: profile -> prompt -> Claude -> parse -> verify ownership.
    Also applies seeded project history: excludes already-handled titles from
    the prompt and the final list, and merges prior rationales back in."""
    history_dismissed, rationales = _load_history_context()
    profile = build_profile(library)
    prompt = _build_prompt(profile, history_dismissed)
    raw = _call_claude(prompt)
    recs = _parse_json(raw)
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
    for section in ("documentaries", "cartoons"):
        if section in recs:
            recs[section] = drop_hist(recs[section])

    recs["_meta"] = {
        "removed_as_owned": removed,
        "removed_from_history": hist_removed,
        "history_titles_known": len(history_dismissed),
        "library_counts": {c: d["count"] for c, d in profile["categories"].items()},
    }
    return recs
