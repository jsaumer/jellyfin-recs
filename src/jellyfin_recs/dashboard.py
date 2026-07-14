"""
Dashboard web server.

Serves a single-page UI to browse recommendations, approve/dismiss titles,
trigger a manual refresh, and (when staging is enabled later) push approved
titles to Radarr/Sonarr.

Run:
    python3 dashboard.py
Then open http://127.0.0.1:8577

Uses Flask. Install with:  pip install flask
"""

import threading

from flask import Flask, jsonify, request, Response

from . import config
from . import settings
from . import storage
from . import staging
from .dashboard_ui import PAGE

app = Flask(__name__)
_refresh_lock = threading.Lock()
_refresh_status = {"running": False, "last_error": None, "last_finished": None}


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/api/recommendations")
def api_recommendations():
    recs = storage.load_recommendations()
    state = storage.load_state()
    return jsonify({"recommendations": recs, "state": state,
                    "staging": staging.connection_status(),
                    "version": config.VERSION})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Kick off a refresh in the background so the UI stays responsive."""
    if _refresh_status["running"]:
        return jsonify({"ok": False, "message": "Refresh already running."}), 409

    def _worker():
        from . import pipeline
        with _refresh_lock:
            _refresh_status["running"] = True
            _refresh_status["last_error"] = None
            try:
                pipeline.run_refresh(verbose=False)
            except Exception as e:
                _refresh_status["last_error"] = str(e)
            finally:
                _refresh_status["running"] = False
                import time
                _refresh_status["last_finished"] = time.time()

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "message": "Refresh started."})


@app.route("/api/refresh/status")
def api_refresh_status():
    return jsonify(_refresh_status)


@app.route("/api/item", methods=["POST"])
def api_item():
    """Set a title's status: approved / dismissed / reset."""
    data = request.get_json(force=True)
    key = storage.item_key(data["title"], data.get("year"))
    status = data["status"]  # approved | dismissed | reset
    if status == "reset":
        state = storage.load_state()
        state.pop(key, None)
        storage._write(config.STATE_FILE, state)
        return jsonify({"ok": True})
    storage.set_item_status(key, status)
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Effective settings (stored > env default > hardcoded).
    Never includes URLs or API keys — those are environment-only."""
    return jsonify({"settings": settings.all_settings(),
                    "search_tv_modes": list(settings.SEARCH_TV_MODES)})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """Merge validated settings into settings.json. Unknown keys or bad values
    are rejected wholesale with a 400 — nothing is written."""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "message": "Expected a JSON object."}), 400
    try:
        updated = settings.save(data)
    except ValueError as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    return jsonify({"ok": True, "settings": updated})


@app.route("/api/profiles")
def api_profiles():
    """Live quality profiles + library usage counts, per app, for the Settings
    page. Best-effort: an unreachable app reports an error instead of failing
    the whole request."""
    out = {}
    for which in ("radarr", "sonarr"):
        try:
            out[which] = staging.list_profiles(which)
        except Exception as e:
            out[which] = {"error": str(e), "profiles": [], "total": 0}
    return jsonify(out)


@app.route("/api/stage", methods=["POST"])
def api_stage():
    """Push an approved title to Radarr/Sonarr. Requires the staging setting.

    Routing:
      movies    -> Radarr
      shows     -> Sonarr (TV root)
      cartoons  -> Sonarr (cartoon root)
    """
    if not settings.get("staging_enabled"):
        return jsonify({"ok": False,
                        "message": "Staging is disabled. Enable it in Settings when ready."}), 403
    data = request.get_json(force=True)
    category = data.get("category")  # movies | shows | cartoons
    try:
        if category == "movies":
            # Prefer the enriched TMDB id (exact match) over fuzzy name lookup.
            result = staging.stage_movie(tmdb_id=data.get("tmdb_id"),
                                         title=data["title"], year=data.get("year"))
            landed = config.RADARR_ROOT_FOLDER
        elif category in ("shows", "cartoons"):
            # Prefer the enriched TVDB id; fall back to TMDB id (resolved via
            # Sonarr) then fuzzy name lookup — see staging.stage_series.
            result = staging.stage_series(tvdb_id=data.get("tvdb_id"),
                                          tmdb_id=data.get("tmdb_id"),
                                          title=data["title"], year=data.get("year"),
                                          category=category)
            landed = result.get("rootFolderPath") or staging.resolve_sonarr_root(category)
        else:
            return jsonify({"ok": False, "message": f"Unknown category '{category}'."}), 400
        key = storage.item_key(data["title"], data.get("year"))
        storage.set_item_status(key, "staged")
        return jsonify({"ok": True,
                        # Surfaced so the UI can toast it — a substituted
                        # quality profile is never applied silently.
                        "profile_drift": result.get("profile_drift"),
                        "result": {"id": result.get("id"),
                                   "title": result.get("title"),
                                   "root": landed}})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/roots")
def api_roots():
    """Expose live root folders + routing so the UI can display them."""
    return jsonify(staging.connection_status())


def main():
    problems = config.validate(require_claude=False)
    if problems:
        print("Warning — config issues (dashboard will still start):")
        for p in problems:
            print("  -", p)
    print(f"Dashboard running at http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, debug=False)


if __name__ == "__main__":
    main()
