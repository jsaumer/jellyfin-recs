"""
Radarr / Sonarr staging layer.

STATUS: Wired but DORMANT. Nothing here runs unless config.STAGING_ENABLED is
True AND the dashboard explicitly calls stage_movie / stage_series for an
approved title. Even then, it only ADDS a title to Radarr/Sonarr's monitored
list — it does not force downloads (search-on-add is off by default).

This module is intentionally isolated so that turning staging on later is a
config flip, not a code change.
"""

import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from . import config


def _api(base_url, api_key, path, method="GET", payload=None):
    url = f"{base_url}/api/v3{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("X-Api-Key", api_key)
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"{base_url} HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise RuntimeError(f"{base_url} connection error: {e.reason}") from e


def _guard():
    if not config.STAGING_ENABLED:
        raise RuntimeError(
            "Staging is disabled. Set STAGING_ENABLED=true in config/.env to "
            "allow pushing titles to Radarr/Sonarr."
        )


def _quality_profile_id(base_url, api_key, wanted_name):
    profiles = _api(base_url, api_key, "/qualityprofile")
    for p in profiles:
        if p.get("name", "").lower() == wanted_name.lower():
            return p["id"]
    # Fall back to the first profile if the named one isn't found.
    return profiles[0]["id"] if profiles else 1


def get_root_folders(which):
    """Return the list of configured root folders from Radarr or Sonarr.
    `which` is 'radarr' or 'sonarr'. Each entry: {path, freeSpace, accessible}.
    Used by the dashboard to display real folders and by routing below."""
    if which == "radarr":
        base, key = config.RADARR_URL, config.RADARR_API_KEY
    else:
        base, key = config.SONARR_URL, config.SONARR_API_KEY
    return _api(base, key, "/rootfolder")


def resolve_sonarr_root(category):
    """Pick the correct Sonarr root folder path for a given category.

    Both 'shows' and 'cartoons' are Sonarr series, but go to different roots.
    We read the LIVE root folders from Sonarr and match against a configured
    hint substring (SONARR_TV_ROOT_HINT / SONARR_CARTOON_ROOT_HINT), so the
    actual paths never have to be hardcoded — they're whatever Sonarr reports.

    Falls back to the first available root if no hint matches, and raises a
    clear error if Sonarr has no root folders at all.
    """
    folders = get_root_folders("sonarr")
    if not folders:
        raise RuntimeError("Sonarr reports no root folders configured.")
    paths = [f["path"] for f in folders]

    hint = (config.SONARR_CARTOON_ROOT_HINT if category == "cartoons"
            else config.SONARR_TV_ROOT_HINT)

    # 1) exact path match, 2) case-insensitive substring match on the hint.
    if hint:
        for p in paths:
            if p == hint:
                return p
        for p in paths:
            if hint.lower() in p.lower():
                return p

    # No hint matched — if there's only one root, use it; otherwise this is
    # ambiguous and we surface the choices so the user can set the right hint.
    if len(paths) == 1:
        return paths[0]
    raise RuntimeError(
        f"Couldn't match a Sonarr root folder for category '{category}'. "
        f"Available roots: {paths}. Set "
        f"{'SONARR_CARTOON_ROOT_HINT' if category=='cartoons' else 'SONARR_TV_ROOT_HINT'} "
        f"to one of these paths (or a distinctive substring)."
    )


# ------------------------------- Radarr ------------------------------------
def stage_movie(tmdb_id=None, title=None, year=None):
    """Add a movie to Radarr's monitored list. Requires a TMDB id OR a title
    to look up. Returns the Radarr movie record."""
    _guard()
    base, key = config.RADARR_URL, config.RADARR_API_KEY

    if not tmdb_id:
        term = f"{title} {year}" if year else title
        results = _api(base, key, f"/movie/lookup?term={term}")
        if not results:
            raise RuntimeError(f"Radarr found no match for '{term}'.")
        tmdb_id = results[0]["tmdbId"]
        lookup = results[0]
    else:
        lookup = _api(base, key, f"/movie/lookup/tmdb?tmdbId={tmdb_id}")

    payload = {
        "title": lookup["title"],
        "tmdbId": tmdb_id,
        "year": lookup.get("year", year),
        "qualityProfileId": _quality_profile_id(base, key, config.RADARR_QUALITY_PROFILE),
        "rootFolderPath": config.RADARR_ROOT_FOLDER,
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": not config.RADARR_ADD_MONITORED_ONLY},
    }
    return _api(base, key, "/movie", method="POST", payload=payload)


# ------------------------------- Sonarr ------------------------------------
def stage_series(tvdb_id=None, title=None, year=None, category="shows",
                 tmdb_id=None):
    """Add a series to Sonarr's monitored list, routed to the correct root
    folder for its category ('shows' -> TV root, 'cartoons' -> cartoon root).
    Root folders are read live from Sonarr."""
    _guard()
    base, key = config.SONARR_URL, config.SONARR_API_KEY
    chosen = None

    # Prefer an exact tvdb_id. If we only have a tmdb_id, resolve it to a
    # tvdb_id via Sonarr's Skyhook (which accepts `tmdb:` terms) before falling
    # back to a fuzzy name lookup — keeps staging exact-ID end-to-end.
    if not tvdb_id and tmdb_id:
        try:
            results = _api(base, key, f"/series/lookup?term=tmdb:{tmdb_id}")
            if results and results[0].get("tvdbId"):
                chosen = results[0]
                tvdb_id = chosen["tvdbId"]
        except Exception:
            pass  # fall through to name lookup

    if not tvdb_id:
        term = title
        results = _api(base, key, f"/series/lookup?term={term}")
        if not results:
            raise RuntimeError(f"Sonarr found no match for '{term}'.")
        chosen = results[0]
        tvdb_id = chosen["tvdbId"]
    elif chosen is None:
        results = _api(base, key, f"/series/lookup?term=tvdb:{tvdb_id}")
        chosen = results[0] if results else {}

    root_path = resolve_sonarr_root(category)

    payload = {
        "title": chosen["title"],
        "tvdbId": tvdb_id,
        "qualityProfileId": _quality_profile_id(base, key, config.SONARR_QUALITY_PROFILE),
        "rootFolderPath": root_path,
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "searchForMissingEpisodes": not config.SONARR_ADD_MONITORED_ONLY,
            "monitor": "all",
        },
    }
    return _api(base, key, "/series", method="POST", payload=payload)


def connection_status():
    """Lightweight health check used by the dashboard to show whether staging
    is reachable, plus the live root folders discovered from each service."""
    status = {"enabled": config.STAGING_ENABLED, "radarr": "off", "sonarr": "off",
              "roots": {"radarr": [], "sonarr": []},
              "routing": {"shows": None, "cartoons": None}}
    if not config.STAGING_ENABLED:
        return status
    for name, base, key in [
        ("radarr", config.RADARR_URL, config.RADARR_API_KEY),
        ("sonarr", config.SONARR_URL, config.SONARR_API_KEY),
    ]:
        try:
            _api(base, key, "/system/status")
            status[name] = "ok"
            status["roots"][name] = [f.get("path") for f in get_root_folders(name)]
        except Exception as e:
            status[name] = f"error: {e}"
    # Report where TV vs Cartoons will actually land, so it's visible in the UI.
    if status["sonarr"] == "ok":
        for cat in ("shows", "cartoons"):
            try:
                status["routing"][cat] = resolve_sonarr_root(cat)
            except Exception as e:
                status["routing"][cat] = f"unresolved: {e}"
    return status
