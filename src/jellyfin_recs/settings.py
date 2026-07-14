"""
User-tunable settings, persisted to DATA_DIR/settings.json.

Precedence, highest first:
  1. the value stored in settings.json (written by the dashboard Settings page)
  2. the env-derived default in config.py  (FIRST-BOOT default only)
  3. the hardcoded default in HARDCODED below

SETTINGS WIN OVER ENV after first boot. Environment variables seed the initial
value, but once a key has been saved from the UI the stored value is
authoritative — changing the env var later will NOT override it. To hand control
back to the environment, delete the key from settings.json (or reset it in the
UI).

SECURITY: URLs, API keys, PUID/PGID/TZ, DATA_DIR, MAX_OUTPUT_TOKENS and
CLAUDE_MODEL are deliberately NOT managed here. They stay environment-only and
must never be written to settings.json or exposed in the dashboard.
"""

import json
import os

from . import config

# Allowed values for the TV search-on-grab mode.
SEARCH_TV_MODES = ("off", "first_season", "all")

# Tier 3: last-resort defaults, used only if config has no matching attribute.
HARDCODED = {
    "refresh_interval_hours": 168,
    "recs_per_genre": 3,
    "staging_enabled": False,
    "radarr_quality_profile": "",     # "" = auto (majority-in-library)
    "sonarr_quality_profile": "",     # "" = auto (majority-in-library)
    "search_on_grab_movies": True,
    "search_on_grab_tv": "off",
}

# Managed key -> the config.py attribute holding its env-derived default.
_ENV_DEFAULT_ATTR = {
    "refresh_interval_hours": "REFRESH_INTERVAL_HOURS",
    "recs_per_genre": "RECS_PER_GENRE",
    "staging_enabled": "STAGING_ENABLED",
    "radarr_quality_profile": "RADARR_QUALITY_PROFILE",
    "sonarr_quality_profile": "SONARR_QUALITY_PROFILE",
    "search_on_grab_movies": "SEARCH_ON_GRAB_MOVIES",
    "search_on_grab_tv": "SEARCH_ON_GRAB_TV",
}

MANAGED_KEYS = tuple(HARDCODED)


def settings_file():
    """Resolved at call time so DATA_DIR changes (tests) are picked up."""
    return os.path.join(config.DATA_DIR, "settings.json")


# ------------------------------ validation ---------------------------------
def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError("expected a boolean")


def _as_positive_int(value):
    if isinstance(value, bool):          # bool is an int subclass — reject it
        raise ValueError("expected an integer")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("expected an integer") from None
    if n < 1:
        raise ValueError("must be 1 or greater")
    return n


def validate(key, value):
    """Coerce and validate one setting. Raises ValueError on a bad key/value."""
    if key not in MANAGED_KEYS:
        raise ValueError(f"unknown setting '{key}'")
    if key in ("refresh_interval_hours", "recs_per_genre"):
        return _as_positive_int(value)
    if key in ("staging_enabled", "search_on_grab_movies"):
        return _as_bool(value)
    if key == "search_on_grab_tv":
        v = str(value).strip().lower()
        if v not in SEARCH_TV_MODES:
            raise ValueError(f"must be one of {', '.join(SEARCH_TV_MODES)}")
        return v
    # Quality profile names: free text; "" means auto.
    return str(value).strip()


# ------------------------------ persistence --------------------------------
def load():
    """The raw stored overrides (may be partial or empty)."""
    try:
        with open(settings_file(), encoding="utf-8") as f:
            stored = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return stored if isinstance(stored, dict) else {}


def _write(stored):
    """Atomic write: temp file + rename."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = settings_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stored, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _env_default(key):
    return getattr(config, _ENV_DEFAULT_ATTR[key], HARDCODED[key])


def get(key):
    """The effective value for `key` (stored > env default > hardcoded)."""
    if key not in MANAGED_KEYS:
        raise ValueError(f"unknown setting '{key}'")
    stored = load()
    if key in stored:
        try:
            return validate(key, stored[key])
        except ValueError:
            pass  # corrupt stored value — fall through to the defaults
    try:
        return validate(key, _env_default(key))
    except ValueError:
        return HARDCODED[key]


def all_settings():
    """Every managed key with its effective value."""
    return {key: get(key) for key in MANAGED_KEYS}


def save(updates):
    """Validate `updates` and merge them into settings.json.

    Rejects unknown keys and bad values with ValueError, writing nothing.
    Returns the full effective settings after the merge.
    """
    if not isinstance(updates, dict):
        raise ValueError("settings payload must be an object")
    clean = {}
    for key, value in updates.items():
        clean[key] = validate(key, value)   # raises on unknown key / bad value
    stored = load()
    stored.update(clean)
    _write(stored)
    return all_settings()
