"""
Radarr / Sonarr staging layer.

Nothing here runs unless the `staging_enabled` setting is on AND the dashboard
explicitly calls stage_movie / stage_series for an approved title.

Two behaviours are user-controlled from the Settings page:
  - Quality profile: chosen by NAME and resolved LIVE at every grab. IDs are
    never cached — Profilarr/Dictionarry re-syncs renumber them, so a cached ID
    silently points at the wrong profile later. If a configured name no longer
    exists we fall back to the majority-in-library profile and report the
    substitution as "profile_drift" rather than silently picking.
  - Search on grab: movies search immediately by default; TV is off /
    first-season-only / all-missing-episodes.

URLs and API keys stay environment-only and never pass through settings.
"""

import json
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from . import config
from . import settings


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
    if not settings.get("staging_enabled"):
        raise RuntimeError(
            "Staging is disabled. Enable it on the dashboard Settings page to "
            "allow pushing titles to Radarr/Sonarr."
        )


def _creds(which):
    """(base_url, api_key) for 'radarr' or 'sonarr'. Env-only — never settings."""
    if which == "radarr":
        return config.RADARR_URL, config.RADARR_API_KEY
    return config.SONARR_URL, config.SONARR_API_KEY


# --------------------------- quality profiles ------------------------------
# Profile IDs are NEVER cached. Profilarr / Dictionarry re-syncs renumber them,
# so a cached ID silently points at the wrong profile later. We resolve by NAME,
# live, on every grab.
def _profile_usage_counts(base, api_key, which):
    """Count qualityProfileId occurrences across the existing library.
    Radarr counts /movie, Sonarr counts /series. Best-effort: {} on failure."""
    path = "/movie" if which == "radarr" else "/series"
    try:
        items = _api(base, api_key, path)
    except Exception:
        return {}
    counts = {}
    for item in items or []:
        pid = item.get("qualityProfileId")
        if pid is not None:
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def _majority_profile(profiles, counts):
    """The profile most of the library uses; the first profile if unknown."""
    if counts:
        top_id = max(counts, key=lambda pid: counts[pid])
        for p in profiles:
            if p.get("id") == top_id:
                return p
    return profiles[0]


def _resolve_quality_profile(which, configured_name):
    """Resolve a quality profile to an ID by NAME, live.

    Order: configured name (case-insensitive exact, then substring) ->
    majority-in-library -> first profile.

    Returns (profile_id, drift_message_or_None). `drift_message` is set only
    when a configured name failed to resolve, so the caller can surface it —
    we never silently substitute a different profile.
    """
    base, api_key = _creds(which)
    profiles = _api(base, api_key, "/qualityprofile")
    if not profiles:
        raise RuntimeError(f"{which.title()} reports no quality profiles.")

    name = (configured_name or "").strip()
    if name:
        for p in profiles:
            if p.get("name", "").strip().lower() == name.lower():
                return p["id"], None
        for p in profiles:
            if name.lower() in p.get("name", "").strip().lower():
                return p["id"], None
        # Configured, but gone — fall back loudly.
        fallback = _majority_profile(
            profiles, _profile_usage_counts(base, api_key, which))
        drift = (f"Quality profile '{name}' no longer exists in "
                 f"{which.title()}; used '{fallback.get('name')}' instead.")
        print(f"[staging] WARNING: {drift}", file=sys.stderr)
        return fallback["id"], drift

    # "" = auto: whatever the library mostly uses.
    fallback = _majority_profile(
        profiles, _profile_usage_counts(base, api_key, which))
    return fallback["id"], None


def list_profiles(which):
    """Live quality profiles + library usage counts, for the Settings page.

    Returns {"profiles": [{id, name, count, is_default}], "total": n}, where
    is_default marks the majority (library default) profile.
    """
    base, api_key = _creds(which)
    profiles = _api(base, api_key, "/qualityprofile")
    counts = _profile_usage_counts(base, api_key, which)
    top_id = max(counts, key=lambda pid: counts[pid]) if counts else None
    return {
        "profiles": [{"id": p.get("id"), "name": p.get("name", ""),
                      "count": counts.get(p.get("id"), 0),
                      "is_default": p.get("id") == top_id}
                     for p in profiles],
        "total": sum(counts.values()),
    }


def get_root_folders(which):
    """Return the list of configured root folders from Radarr or Sonarr.
    `which` is 'radarr' or 'sonarr'. Each entry: {path, freeSpace, accessible}.
    Used by the dashboard to display real folders and by routing below."""
    base, key = _creds(which)
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
    to look up. Returns the Radarr movie record, plus a "profile_drift" key if
    the configured quality profile had to be substituted."""
    _guard()
    base, key = _creds("radarr")

    if not tmdb_id:
        term = f"{title} {year}" if year else title
        results = _api(base, key, f"/movie/lookup?term={term}")
        if not results:
            raise RuntimeError(f"Radarr found no match for '{term}'.")
        tmdb_id = results[0]["tmdbId"]
        lookup = results[0]
    else:
        lookup = _api(base, key, f"/movie/lookup/tmdb?tmdbId={tmdb_id}")

    profile_id, drift = _resolve_quality_profile(
        "radarr", settings.get("radarr_quality_profile"))

    payload = {
        "title": lookup["title"],
        "tmdbId": tmdb_id,
        "year": lookup.get("year", year),
        "qualityProfileId": profile_id,
        "rootFolderPath": config.RADARR_ROOT_FOLDER,
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {
            "searchForMovie": bool(settings.get("search_on_grab_movies")),
        },
    }
    result = _api(base, key, "/movie", method="POST", payload=payload) or {}
    if drift:
        result["profile_drift"] = drift
    return result


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
    profile_id, drift = _resolve_quality_profile(
        "sonarr", settings.get("sonarr_quality_profile"))

    payload = _series_payload(chosen, tvdb_id, profile_id, root_path,
                              settings.get("search_on_grab_tv"))
    result = _api(base, key, "/series", method="POST", payload=payload) or {}
    if drift:
        result["profile_drift"] = drift
    return result


def _series_payload(chosen, tvdb_id, profile_id, root_path, mode):
    """Build the Sonarr /series add payload for a search-on-grab `mode`.

    "off"          -> monitor every season, do not search (queue only).
    "first_season" -> monitor ONLY season 1 (explicit seasons array) and search.
    "all"          -> monitor every season and search for all missing episodes.

    Pure/side-effect free so the three shapes can be asserted in tests.
    """
    search = mode in ("first_season", "all")
    payload = {
        "title": chosen.get("title"),
        "tvdbId": tvdb_id,
        "qualityProfileId": profile_id,
        "rootFolderPath": root_path,
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "searchForMissingEpisodes": search,
            # "firstSeason" makes Sonarr's own monitoring agree with the
            # explicit seasons array below; "all" covers the other two modes.
            "monitor": "firstSeason" if mode == "first_season" else "all",
        },
    }
    if mode == "first_season":
        seasons = [s.get("seasonNumber") for s in (chosen.get("seasons") or [])]
        # Fall back to a lone season 1 if the lookup carried no season list.
        numbers = [n for n in seasons if n is not None] or [1]
        payload["seasons"] = [{"seasonNumber": n, "monitored": n == 1}
                              for n in numbers]
    return payload


def connection_status():
    """Lightweight health check used by the dashboard to show whether staging
    is reachable, plus the live root folders discovered from each service."""
    enabled = settings.get("staging_enabled")
    status = {"enabled": enabled, "radarr": "off", "sonarr": "off",
              "roots": {"radarr": [], "sonarr": []},
              "routing": {"shows": None, "cartoons": None}}
    if not enabled:
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
