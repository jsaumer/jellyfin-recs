"""
Persistence layer. Stores the latest recommendations, a cache of the library,
and per-title user state (approved / dismissed / staged) in plain JSON files
under DATA_DIR. No database needed.
"""

import json
import os
import time

from . import config


def _ensure_dir():
    os.makedirs(config.DATA_DIR, exist_ok=True)


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path, obj):
    _ensure_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)  # atomic


# --------------------------- recommendations -------------------------------
def save_recommendations(recs):
    recs = dict(recs)
    recs["_generated_at"] = time.time()
    _write(config.RECS_FILE, recs)


def load_recommendations():
    return _read(config.RECS_FILE, {})


# ------------------------------ library cache ------------------------------
def save_library_cache(library):
    # Store only lightweight fields; full items aren't needed after profiling.
    slim = {}
    for cat, items in library.items():
        slim[cat] = [
            {
                "Name": it.get("Name"),
                "Year": it.get("ProductionYear"),
                "Played": it.get("UserData", {}).get("Played", False),
            }
            for it in items
        ]
    _write(config.LIBRARY_CACHE, {"cached_at": time.time(), "library": slim})


def load_library_cache():
    return _read(config.LIBRARY_CACHE, {})


# ------------------------------ user state ---------------------------------
# state = { "<title|year>": {"status": "approved|dismissed|staged", "ts": ...} }
def load_state():
    return _read(config.STATE_FILE, {})


def set_item_status(key, status):
    state = load_state()
    state[key] = {"status": status, "ts": time.time()}
    _write(config.STATE_FILE, state)
    return state


def item_key(title, year):
    return f"{title}|{year}"
