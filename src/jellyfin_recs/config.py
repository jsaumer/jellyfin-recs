"""
Central configuration for the Jellyfin Recommendation Pipeline.

Every setting can be provided by an environment variable (recommended for
secrets) or edited directly here. Environment variables win.

Copy .env.example to .env and fill it in, or export the variables in your
shell / systemd unit / docker-compose file.
"""

import os

# ---- Optional: load a .env file if python-dotenv is installed --------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env support is optional; env vars still work without it


def _clean(url: str) -> str:
    return url.rstrip("/") if url else url


# ============================ JELLYFIN =====================================
JELLYFIN_URL = _clean(os.environ.get("JELLYFIN_URL", "http://localhost:8096"))
JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
# Provide EITHER a User ID GUID or a username (username is auto-resolved).
JELLYFIN_USER_ID = os.environ.get("JELLYFIN_USER_ID", "")
JELLYFIN_USERNAME = os.environ.get("JELLYFIN_USERNAME", "")

# Library view names (as they appear in Jellyfin) -> internal category key.
LIBRARY_MAP = {
    "movies": "movies",
    "shows": "shows",
    "cartoons": "cartoons",
}

# ============================ CLAUDE API ===================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
# How many picks each genre deep-dive section requests. First-boot default for
# the `recs_per_genre` setting (the Settings page owns it after that).
RECS_PER_GENRE = int(os.environ.get("RECS_PER_GENRE", "3"))
# Cap the library summary size sent to the API (keeps token cost predictable).
MAX_TITLES_IN_PROMPT = int(os.environ.get("MAX_TITLES_IN_PROMPT", "1500"))
# Cap on the model's output. The over-provisioned response (20 candidates per
# top10_* list + 5 documentaries + capped genre sections) is longer than the
# displayed set; too low a cap truncates the JSON and breaks parsing. 12000
# gives the ~20+20+20+5 candidate lists comfortable headroom.
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "12000"))

# ============================ TMDB =========================================
# Optional. Enriches each recommendation with poster, rating, IMDb/TMDB links,
# and exact TMDB/TVDB IDs (for precise Radarr/Sonarr staging). Best-effort:
# with no key, enrichment is a silent no-op. Get a free key at
# https://www.themoviedb.org/settings/api
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

# ============================ STORAGE ======================================
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
RECS_FILE = os.path.join(DATA_DIR, "recommendations.json")
LIBRARY_CACHE = os.path.join(DATA_DIR, "library_cache.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")  # approvals, dismissals, staged flags

# ============================ DASHBOARD ====================================
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8577"))

# ============================ SCHEDULER ====================================
# Cron-style refresh handled by run_scheduler.py. Value is hours between runs.
REFRESH_INTERVAL_HOURS = int(os.environ.get("REFRESH_INTERVAL_HOURS", "168"))  # weekly


# ============================ VERSION ======================================
def _read_version():
    """Read the app version from the VERSION file at the repo root."""
    here = os.path.dirname(__file__)
    # Walk up to find VERSION (repo root), covering both installed and
    # run-from-source layouts.
    for candidate in (
        os.path.join(here, "VERSION"),
        os.path.join(here, "..", "..", "VERSION"),
        os.path.join(here, "..", "VERSION"),
    ):
        try:
            with open(candidate, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return "unknown"


VERSION = _read_version()

# ==================== RADARR / SONARR (STAGING — DORMANT) ==================
# Fully wired but DISABLED by default. Flip STAGING_ENABLED to True only when
# you're ready to let the dashboard push approved titles into Radarr/Sonarr.
# Even when enabled, this only ADDS titles to the wanted/monitored list — it
# never triggers downloads on its own beyond Radarr/Sonarr's normal behavior.
STAGING_ENABLED = os.environ.get("STAGING_ENABLED", "false").lower() == "true"

RADARR_URL = _clean(os.environ.get("RADARR_URL", "http://localhost:7878"))
RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
# "" = auto: use the profile most of the library already uses. Resolved by NAME
# live at every grab (see staging._resolve_quality_profile).
RADARR_QUALITY_PROFILE = os.environ.get("RADARR_QUALITY_PROFILE", "")
RADARR_ROOT_FOLDER = os.environ.get("RADARR_ROOT_FOLDER", "/movies")
# If True, Radarr won't auto-search on add (safest — you trigger searches yourself).
RADARR_ADD_MONITORED_ONLY = os.environ.get("RADARR_ADD_MONITORED_ONLY", "true").lower() == "true"

SONARR_URL = _clean(os.environ.get("SONARR_URL", "http://localhost:8989"))
SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")
SONARR_QUALITY_PROFILE = os.environ.get("SONARR_QUALITY_PROFILE", "")
SONARR_ADD_MONITORED_ONLY = os.environ.get("SONARR_ADD_MONITORED_ONLY", "true").lower() == "true"

# ---- Search-on-grab (first-boot defaults for the matching settings) --------
# Movies default to searching immediately on grab; TV defaults to off so a
# multi-season add doesn't kick off a huge download without an explicit choice.
SEARCH_ON_GRAB_MOVIES = os.environ.get("SEARCH_ON_GRAB_MOVIES", "true").lower() == "true"
SEARCH_ON_GRAB_TV = os.environ.get("SEARCH_ON_GRAB_TV", "off").strip().lower()
# Sonarr holds both TV and Cartoons as series, but in different root folders.
# These hints are matched (exact path first, then case-insensitive substring)
# against the LIVE root folders read from Sonarr's API — so you set them to
# whatever paths Sonarr actually reports. Leave blank to auto-use the only root
# if there's just one. TV shows route via TV hint, cartoons via cartoon hint.
SONARR_TV_ROOT_HINT = os.environ.get("SONARR_TV_ROOT_HINT", "/tv")
SONARR_CARTOON_ROOT_HINT = os.environ.get("SONARR_CARTOON_ROOT_HINT", "/cartoon")


def validate(require_claude=True, require_staging=False):
    """Return a list of human-readable config problems (empty = all good)."""
    from . import settings   # local import: settings imports config

    problems = []
    if not JELLYFIN_API_KEY:
        problems.append("JELLYFIN_API_KEY is not set.")
    if not JELLYFIN_USER_ID and not JELLYFIN_USERNAME:
        problems.append("Set JELLYFIN_USER_ID or JELLYFIN_USERNAME.")
    if require_claude and not ANTHROPIC_API_KEY:
        problems.append("ANTHROPIC_API_KEY is not set (needed for recommendations).")
    if require_staging and settings.get("staging_enabled"):
        if not RADARR_API_KEY:
            problems.append("Staging is enabled but RADARR_API_KEY is not set.")
        if not SONARR_API_KEY:
            problems.append("Staging is enabled but SONARR_API_KEY is not set.")
    return problems
