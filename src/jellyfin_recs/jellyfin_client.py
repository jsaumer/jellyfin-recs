"""
Jellyfin API client — fetches library items with watched status.
Reuses the logic from the standalone export script, adapted for the pipeline.
"""

import json
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

from . import config

ITEM_FIELDS = ",".join([
    "Genres", "GenreItems", "CommunityRating", "OfficialRating",
    "ProductionYear", "PremiereDate", "RunTimeTicks", "ProviderIds",
    "Overview", "UserData",
])

# Keep only reliable watched-state fields (play-counts are unreliable).
WATCHED_ONLY = ["Played", "UnplayedItemCount", "IsFavorite", "ItemId", "Key"]


def _get(path, params=None):
    url = f"{config.JELLYFIN_URL}{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url)
    req.add_header("X-Emby-Token", config.JELLYFIN_API_KEY)
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raise RuntimeError(f"Jellyfin HTTP {e.code} on {path}: {e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"Jellyfin connection error on {path}: {e.reason}") from e


def resolve_user_id():
    uid = config.JELLYFIN_USER_ID
    if uid and len(uid.replace("-", "")) == 32:
        return uid
    if not config.JELLYFIN_USERNAME:
        raise RuntimeError("No valid JELLYFIN_USER_ID or JELLYFIN_USERNAME provided.")
    for user in _get("/Users"):
        if user.get("Name", "").strip().lower() == config.JELLYFIN_USERNAME.strip().lower():
            return user["Id"]
    raise RuntimeError(f"Username '{config.JELLYFIN_USERNAME}' not found on server.")


def _scrub(items):
    for item in items:
        ud = item.get("UserData")
        if isinstance(ud, dict):
            item["UserData"] = {k: ud[k] for k in WATCHED_ONLY if k in ud}
    return items


def fetch_library():
    """Return {category: [items...]} for every mapped library view."""
    user_id = resolve_user_id()
    views = _get(f"/Users/{user_id}/Views").get("Items", [])
    view_by_name = {v.get("Name", "").strip().lower(): v for v in views}

    result = {}
    for view_name, category in config.LIBRARY_MAP.items():
        view = view_by_name.get(view_name.lower())
        if not view:
            continue
        params = {
            "ParentId": view["Id"], "Recursive": "true",
            "IncludeItemTypes": "Movie,Series", "Fields": ITEM_FIELDS,
            "SortBy": "SortName", "SortOrder": "Ascending",
        }
        items = _get(f"/Users/{user_id}/Items", params).get("Items", [])
        result[category] = _scrub(items)
    return result
