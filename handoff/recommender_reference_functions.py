# Reference: the target functions, TESTED against real data.
# Claude Code: match these in src/jellyfin_recs/recommender.py.

# --- franchise detection (add near top of module) ---
FRANCHISES = {'Mad Max': ['Mad Max', 'The Road Warrior', 'Mad Max Beyond Thunderdome', 'Mad Max: Fury Road', 'Furiosa'], 'X-Men': ['X-Men', 'X2', 'X-Men: The Last Stand', 'X-Men: First Class', 'X-Men: Days of Future Past', 'X-Men: Apocalypse', 'Logan', 'Deadpool', 'Deadpool 2'], 'James Bond (Craig)': ['Casino Royale', 'Quantum of Solace', 'Skyfall', 'Spectre', 'No Time to Die'], 'Terminator': ['The Terminator', 'Terminator 2: Judgment Day', 'Terminator 3: Rise of the Machines', 'Terminator Salvation', 'Terminator Genisys', 'Terminator: Dark Fate'], 'Alien': ['Alien', 'Aliens', 'Alien 3', 'Alien Resurrection', 'Prometheus', 'Alien: Covenant', 'Alien: Romulus'], 'Predator': ['Predator', 'Predator 2', 'Predators', 'The Predator', 'Prey'], 'The Godfather': ['The Godfather', 'The Godfather Part II', 'The Godfather Part III'], 'Indiana Jones': ['Raiders of the Lost Ark', 'Temple of Doom', 'The Last Crusade', 'Kingdom of the Crystal Skull', 'Dial of Destiny'], 'Rocky/Creed': ['Rocky', 'Rocky II', 'Rocky III', 'Rocky IV', 'Rocky V', 'Rocky Balboa', 'Creed', 'Creed II', 'Creed III'], 'Planet of the Apes (reboot)': ['Rise of the Planet of the Apes', 'Dawn of the Planet of the Apes', 'War for the Planet of the Apes', 'Kingdom of the Planet of the Apes'], 'Spider-Verse': ['Spider-Man: Into the Spider-Verse', 'Spider-Man: Across the Spider-Verse'], 'The Matrix': ['The Matrix', 'The Matrix Reloaded', 'The Matrix Revolutions', 'The Matrix Resurrections'], 'Blade Runner': ['Blade Runner', 'Blade Runner 2049']}

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


# --- profile + prompt builders ---
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
        lines.append("## PREVIOUSLY DISMISSED — do NOT recommend these again")
        lines.append("; ".join(sample))
        lines.append("")

    instruction = f"""
Using the FULL library above, recommend {config.RECS_PER_GENRE} MOVIES and
{config.RECS_PER_GENRE} TV SHOWS for EACH of the library's top genres, plus a
short list of documentaries and cartoons/anime that fill obvious gaps.

Curation guidance — reason over the ACTUAL titles, not just genre counts:
- Identify the user's collector patterns: franchises they complete, directors
  or actors they follow, and eras/styles they favor. Recommend accordingly.
- Prioritize FRANCHISE and SERIES GAPS: if they own most of a franchise or a
  director's filmography but are missing entries, surface those first — they're
  the highest-confidence picks.
- Never recommend a title already in the library above (check the lists — this
  is verified separately too, but avoid obvious dupes and near-duplicates).
- Favor titles that a fan of the specific owned/watched titles would genuinely
  want; avoid generic "popular in this genre" picks that ignore their taste.
- Each "why" MUST cite specific owned or watched titles by name to justify the
  fit. Prefer citing watched (✓) titles where possible.
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


# --- in generate(), replace the prompt line with: ---
# prompt = _build_prompt(profile, history_dismissed,
#                        detect_franchise_gaps(profile["owned_titles"]))
