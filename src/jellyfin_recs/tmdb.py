"""
TMDB enrichment — looks up each Claude recommendation against TMDB.

After Claude returns recommendations, look each title up against TMDB to get:
  - exact tmdb_id (movies) / tvdb_id via external IDs (series) -> precise
    Radarr/Sonarr staging, no more fuzzy name matching
  - imdb_id -> clickable IMDb link in the dashboard
  - poster_path -> poster thumbnail
  - vote_average, runtime/episode info -> displayed rating

Zero AI tokens — this is plain REST after the Claude call. Requires a free
TMDB API key (https://www.themoviedb.org/settings/api) in TMDB_API_KEY.
Enrichment is best-effort: a failed lookup leaves the rec un-enriched rather
than failing the refresh.
"""

import json
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

from . import config

TMDB_BASE = "https://api.themoviedb.org/3"
# w154 is sharp at the dashboard's condensed thumbnail size and roughly halves
# image weight versus w342.
POSTER_BASE = "https://image.tmdb.org/t/p/w154"


def _get(path, params=None):
    params = dict(params or {})
    params["api_key"] = config.TMDB_API_KEY
    url = f"{TMDB_BASE}{path}?{urlencode(params)}"
    req = Request(url)
    req.add_header("Accept", "application/json")
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search(kind, title, year):
    """kind: 'movie' or 'tv'. Returns the best result dict or None."""
    params = {"query": title}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = year
    data = _get(f"/search/{kind}", params)
    results = data.get("results") or []
    if not results and year:
        # Retry without the year — Claude's year can be off by one.
        data = _get(f"/search/{kind}", {"query": title})
        results = data.get("results") or []
    return results[0] if results else None


def _external_ids(kind, tmdb_id):
    try:
        return _get(f"/{kind}/{tmdb_id}/external_ids")
    except Exception:
        return {}


def enrich_rec(rec, kind):
    """Mutate a single rec dict {title, year, why} in place with TMDB fields.
    kind: 'movie' or 'tv'. Best-effort; silently skips on any failure."""
    try:
        hit = _search(kind, rec.get("title", ""), rec.get("year"))
        if not hit:
            return rec
        rec["tmdb_id"] = hit["id"]
        if hit.get("poster_path"):
            rec["poster"] = POSTER_BASE + hit["poster_path"]
        if hit.get("vote_average"):
            rec["rating"] = round(hit["vote_average"], 1)
        ext = _external_ids(kind, hit["id"])
        if ext.get("imdb_id"):
            rec["imdb_id"] = ext["imdb_id"]
            rec["imdb_url"] = f"https://www.imdb.com/title/{ext['imdb_id']}/"
        if kind == "tv" and ext.get("tvdb_id"):
            rec["tvdb_id"] = ext["tvdb_id"]
        rec["tmdb_url"] = f"https://www.themoviedb.org/{kind}/{hit['id']}"
    except (HTTPError, URLError, KeyError, json.JSONDecodeError):
        pass  # leave the rec un-enriched
    return rec


def enrich_all(recs):
    """Walk the full recommendations structure and enrich every rec.
    Movies + documentaries -> 'movie'; shows + cartoons -> 'tv'.
    (Cartoon FILMS will still resolve via the tv->movie fallback below.)
    Ranked lists (top10_*, top3_documentaries) are enriched by their own keys.
    No-op if TMDB_API_KEY is unset."""
    if not config.TMDB_API_KEY:
        return recs

    def walk(lst, kind):
        for rec in lst or []:
            enrich_rec(rec, kind)
            # Cartoons can be films; if tv search found nothing, try movie.
            if kind == "tv" and "tmdb_id" not in rec:
                enrich_rec(rec, "movie")

    for section, kind in (("movies", "movie"), ("shows", "tv")):
        block = recs.get(section)
        if isinstance(block, dict):          # genre-keyed
            for genre in block:
                walk(block[genre], kind)
        elif isinstance(block, list):        # flat list
            walk(block, kind)
    # ranked lists live under their own keys
    for key, kind in (("top10_movies", "movie"), ("top10_shows", "tv"),
                      ("top10_cartoons", "tv"), ("top3_documentaries", "movie")):
        walk(recs.get(key), kind)
    return recs
