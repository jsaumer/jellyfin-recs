#!/usr/bin/env python3
"""
Smoke tests — no Docker, no network, no API keys required.

Validates the pieces that don't need live services: profiling, ownership
verification, history parsing, storage round-trips, and dashboard endpoints
(against seeded fake data). Safe to run in CI on every push.

    python3 tests/smoke_test.py
"""

import os
import sys
import tempfile
import json

# Run from the repo root regardless of where invoked; add src/ to path.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Isolate all state in a temp dir so tests never touch real data.
_TMP = tempfile.mkdtemp(prefix="jfr-smoke-")
os.environ["DATA_DIR"] = _TMP

_failures = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    if not cond:
        _failures.append(name)


def test_profiling_and_ownership():
    print("profiling + ownership verification")
    from jellyfin_recs import recommender
    library = {
        "movies": [
            {"Name": "Nobody", "ProductionYear": 2021, "Genres": ["Action"],
             "UserData": {"Played": True}},
            {"Name": "John Wick", "ProductionYear": 2014, "Genres": ["Action"],
             "UserData": {"Played": False}},
        ]
    }
    profile = recommender.build_profile(library)
    check("library counted", profile["categories"]["movies"]["count"] == 2)
    check("owned set built", "nobody" in profile["owned_titles"])
    # New full-library fields (replaced the old watched_sample).
    mv = profile["categories"]["movies"]
    check("owned_entries present", len(mv["owned_entries"]) == 2)
    check("watched marker applied",
          any(e.startswith("✓Nobody") for e in mv["owned_entries"]))
    check("watched_count correct", mv["watched_count"] == 1)
    # "Heat" is NOT in the library, so it must survive the ownership filter.
    fake = {"movies": {"Action": [
        {"title": "Nobody", "year": 2021, "why": "x"},
        {"title": "Heat", "year": 1995, "why": "x"},
    ]}, "shows": {}, "documentaries": [], "cartoons": []}
    filtered, removed = recommender._filter_owned(fake, profile["owned_titles"])
    check("owned title dropped", "Nobody" in removed)
    check("unowned kept", any(r["title"] == "Heat"
                              for r in filtered["movies"]["Action"]))


def test_franchise_gaps():
    print("franchise gap detection")
    from jellyfin_recs import recommender
    # Owns 2 of 5 Craig Bond films.
    owned = {"casino royale", "spectre", "heat"}
    gaps = dict(recommender.detect_franchise_gaps(owned))
    bond = gaps.get("James Bond (Craig)")
    check("partial franchise detected", bond is not None)
    check("missing entries listed",
          bond is not None and "Skyfall" in bond and "No Time to Die" in bond)
    # A fully-owned or fully-unowned franchise should NOT appear.
    check("complete franchise not flagged", "Blade Runner" not in gaps)


def test_history_parsing():
    print("history seeding")
    from jellyfin_recs import seed_history
    md = os.path.join(_TMP, "jellyfin_recommendations.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("| Title | Year | Why | Owned | Watched |\n|---|---|---|---|---|\n"
                "| Rocky Balboa | 2006 | arc | ✅ Owned | ⬜ No |\n"
                "| Heat | 1995 | classic | ❌ No | ⬜ No |\n")
    seeds, rats = seed_history.parse_master_md(md)
    check("owned row seeded", any("Rocky" in s[0] for s in seeds))
    check("unowned row not seeded", not any("Heat" in s[0] for s in seeds))
    check("rationale captured", "heat" in rats)

    hist = os.path.join(_TMP, "history.txt")
    with open(hist, "w", encoding="utf-8") as f:
        f.write("owned: Predator (1987)\ndismissed: The Emoji Movie\n")
    hseeds = seed_history.parse_history_txt(hist)
    check("history owned->dismissed", any(s[0] == "Predator" and s[2] == "dismissed"
                                          for s in hseeds))


def test_storage_roundtrip():
    print("storage round-trip")
    from jellyfin_recs import storage
    storage.save_recommendations({"movies": {"Action": [
        {"title": "Heat", "year": 1995, "why": "x"}]}})
    loaded = storage.load_recommendations()
    check("recs persisted", loaded["movies"]["Action"][0]["title"] == "Heat")
    key = storage.item_key("Heat", 1995)
    storage.set_item_status(key, "approved")
    check("state persisted", storage.load_state()[key]["status"] == "approved")


def test_tmdb_enrichment():
    print("tmdb enrichment (mocked)")
    from jellyfin_recs import tmdb, config
    saved_key, saved_get = config.TMDB_API_KEY, tmdb._get
    config.TMDB_API_KEY = "test-key"
    MOCK = {
        ("/search/movie", "Skyfall"): {"results": [
            {"id": 37724, "poster_path": "/sky.jpg", "vote_average": 7.242}]},
        ("/movie/37724/external_ids", None): {"imdb_id": "tt1074638"},
        ("/search/tv", "The Expanse"): {"results": [
            {"id": 63639, "poster_path": "/e.jpg", "vote_average": 8.4}]},
        ("/tv/63639/external_ids", None): {"imdb_id": "tt3230854",
                                            "tvdb_id": 280619},
    }
    tmdb._get = lambda path, params=None: MOCK.get(
        (path, (params or {}).get("query")),
        MOCK.get((path, None), {"results": []}))
    try:
        recs = {"movies": {"Action": [{"title": "Skyfall", "year": 2012, "why": "w"}]},
                "top10_shows": [{"title": "The Expanse", "year": 2015, "why": "w"}],
                "top3_documentaries": [{"title": "Skyfall", "year": 2012, "why": "w"}]}
        tmdb.enrich_all(recs)
        m = recs["movies"]["Action"][0]
        check("movie tmdb_id", m.get("tmdb_id") == 37724)
        check("movie imdb link", m.get("imdb_url", "").endswith("tt1074638/"))
        check("movie poster", "sky.jpg" in m.get("poster", ""))
        check("movie rating", m.get("rating") == 7.2)
        s = recs["top10_shows"][0]
        check("tv tvdb_id for sonarr", s.get("tvdb_id") == 280619)
        check("top10 key walked", s.get("tmdb_id") == 63639)
        d = recs["top3_documentaries"][0]
        check("top3_documentaries walked", d.get("tmdb_id") == 37724)
        # no-key no-op
        config.TMDB_API_KEY = ""
        r2 = {"top3_documentaries": [{"title": "X", "year": 2000, "why": "w"}]}
        tmdb.enrich_all(r2)
        check("no key -> no-op", "tmdb_id" not in r2["top3_documentaries"][0])
    finally:
        config.TMDB_API_KEY, tmdb._get = saved_key, saved_get


def test_top10_schema_shape():
    print("top10 schema shape + ownership filter")
    from jellyfin_recs import recommender
    payload = ('{"top10_movies": ['
               '{"rank": 1, "title": "Skyfall", "year": 2012, "why": "x"},'
               '{"rank": 2, "title": "Nobody", "year": 2021, "why": "x"}],'
               '"top10_shows": [{"rank": 1, "title": "The Expanse", "year": 2015, "why": "x"}],'
               '"top10_cartoons": [{"rank": 1, "title": "Arcane", "year": 2021, "why": "x"}],'
               '"top3_documentaries": [{"rank": 1, "title": "Free Solo", "year": 2018, "why": "x"}],'
               '"movies": {"Action": [{"title": "Heat", "year": 1995, "why": "x"}]},'
               '"shows": {}}')
    recs = recommender._parse_json(payload)
    check("top10_movies parsed", len(recs["top10_movies"]) == 2)
    check("top3_documentaries parsed", len(recs["top3_documentaries"]) == 1)
    # "Nobody" is owned -> must be dropped; ranked ordering/fields preserved.
    owned = {"nobody"}
    filtered, removed = recommender._filter_owned(recs, owned)
    check("owned dropped from top10", "Nobody" in removed)
    kept = filtered["top10_movies"]
    check("top10 survives filter", len(kept) == 1 and kept[0]["title"] == "Skyfall")
    check("rank preserved", kept[0].get("rank") == 1)


def test_contiguous_rerank():
    print("contiguous re-ranking after filtering")
    from jellyfin_recs import recommender
    # Ranks 1,2,3 with the #2 entry removed by the ownership filter should
    # come out re-ranked 1,2 (no hole at #2).
    recs = {"top10_movies": [
        {"rank": 1, "title": "Skyfall", "year": 2012, "why": "x"},
        {"rank": 2, "title": "Nobody", "year": 2021, "why": "x"},
        {"rank": 3, "title": "Heat", "year": 1995, "why": "x"}],
        "top3_documentaries": [
        {"rank": 1, "title": "Owned Doc", "year": 2000, "why": "x"},
        {"rank": 2, "title": "Free Solo", "year": 2018, "why": "x"}]}
    filtered, _ = recommender._filter_owned(recs, {"nobody", "owned doc"})
    recommender._rerank(filtered)
    mv = filtered["top10_movies"]
    check("survivors kept in order",
          [r["title"] for r in mv] == ["Skyfall", "Heat"])
    check("ranks contiguous 1..N", [r["rank"] for r in mv] == [1, 2])
    docs = filtered["top3_documentaries"]
    check("docs re-ranked contiguous", [r["rank"] for r in docs] == [1])


def test_dashboard_endpoints():
    print("dashboard endpoints")
    try:
        from jellyfin_recs import dashboard
    except ImportError as e:
        check(f"flask available ({e})", False)
        return
    dashboard.app.config["TESTING"] = True
    c = dashboard.app.test_client()
    check("index serves html", b"<!DOCTYPE html>" in c.get("/").data)
    check("recommendations endpoint 200", c.get("/api/recommendations").status_code == 200)
    check("status endpoint 200", c.get("/api/refresh/status").status_code == 200)
    r = c.post("/api/stage", json={"title": "Heat", "year": 1995, "category": "movies"})
    check("stage blocked while dormant", r.status_code == 403)


def test_overprovision_truncation():
    print("over-provision truncation to display caps")
    from jellyfin_recs import recommender
    # 15 candidates, 4 of them owned -> 11 survive ownership -> capped to 10.
    owned_titles = {f"owned {i}" for i in range(4)}
    top = []
    for i in range(15):
        title = f"Owned {i}" if i < 4 else f"Pick {i}"
        top.append({"rank": i + 1, "title": title, "year": 2000 + i, "why": "x"})
    recs = {"top10_movies": top}
    recs, _ = recommender._filter_owned(recs, owned_titles)
    recommender._truncate_and_rerank(recs)
    mv = recs["top10_movies"]
    check("truncated to exactly 10", len(mv) == 10)
    check("ranks 1..10 contiguous", [r["rank"] for r in mv] == list(range(1, 11)))
    check("owned titles gone", not any(r["title"].startswith("Owned") for r in mv))


def test_cross_section_dedupe():
    print("cross-section dedupe (top list wins)")
    from jellyfin_recs import recommender
    recs = {
        "top10_shows": [{"rank": 1, "title": "The Expanse", "year": 2015, "why": "x"}],
        "shows": {"Sci-Fi": [
            {"title": "The Expanse", "year": 2015, "why": "x"},   # dup of top10
            {"title": "Babylon 5", "year": 1994, "why": "x"}]},   # unique, stays
    }
    removed = recommender._dedupe_cross_section(recs)
    genre = recs["shows"]["Sci-Fi"]
    check("dup dropped from genre", not any(r["title"] == "The Expanse" for r in genre))
    check("unique genre entry kept", any(r["title"] == "Babylon 5" for r in genre))
    check("survives in top list", recs["top10_shows"][0]["title"] == "The Expanse")
    check("dedupe reported", "The Expanse" in removed)


def test_why_hygiene():
    print("why hygiene (drop deliberation leaks)")
    from jellyfin_recs import recommender
    recs = {"top10_movies": [
        {"rank": 1, "title": "Clean", "year": 2020, "why": "Fans of Heat will love it."},
        {"rank": 2, "title": "Leaky", "year": 2021,
         "why": "Already in top 10 — replacing. Selecting: something else."}]}
    dropped = recommender._clean_why(recs)
    titles = [r["title"] for r in recs["top10_movies"]]
    check("bad-why rec dropped", "Leaky" not in titles)
    check("clean rec kept", "Clean" in titles)
    check("dropped counted", dropped == 1)


def test_rating_rerank():
    print("rating-based display re-rank")
    from jellyfin_recs import pipeline
    recs = {"top10_movies": [
        {"rank": 1, "title": "A", "year": 2001, "why": "x", "rating": 7.1},
        {"rank": 2, "title": "B", "year": 2002, "why": "x", "rating": 8.4},
        {"rank": 3, "title": "C", "year": 2003, "why": "x"},            # no rating
        {"rank": 4, "title": "D", "year": 2004, "why": "x", "rating": 7.9}]}
    pipeline.rerank_by_rating(recs)
    order = [r["title"] for r in recs["top10_movies"]]
    check("ordered by rating desc, unrated last", order == ["B", "D", "A", "C"])
    check("ranks reassigned 1..4",
          [r["rank"] for r in recs["top10_movies"]] == [1, 2, 3, 4])


def test_prompt_candidate_buffer():
    print("prompt over-provision buffer")
    from jellyfin_recs import recommender
    library = {"movies": [{"Name": "Skyfall", "ProductionYear": 2012,
                           "Genres": ["Action"], "UserData": {"Played": True}}]}
    profile = recommender.build_profile(library)
    prompt = recommender._build_prompt(profile, set(), [])
    check("asks for 20 top candidates", "ranked list of 20" in prompt
          and "rank 1-20" in prompt)
    check("docs stay at 5", "5 documentary candidates" in prompt)
    # Server still truncates to the display caps regardless of the buffer.
    check("caps unchanged 10/3", recommender.DISPLAY_CAPS["top10_movies"] == 10
          and recommender.DISPLAY_CAPS["top3_documentaries"] == 3)


def test_ui_density():
    print("condensed card UI")
    from jellyfin_recs.dashboard_ui import PAGE
    from jellyfin_recs import tmdb
    check("dense auto-fill grid", "minmax(250px, 1fr)" in PAGE)
    check("why clamped to 3 lines", "-webkit-line-clamp: 3" in PAGE)
    check("why expand toggle", ".why.expanded" in PAGE
          and 'classList.toggle("expanded")' in PAGE)
    check("posters use w154", tmdb.POSTER_BASE.endswith("/w154"))
    check("tmdb attribution footer kept",
          "not endorsed or certified by TMDB" in PAGE)


def test_settings_precedence_and_validation():
    print("settings precedence + validation")
    from jellyfin_recs import settings, config
    import os as _os
    # Start clean: no settings.json -> env/hardcoded defaults win.
    try:
        _os.remove(settings.settings_file())
    except OSError:
        pass
    saved = config.REFRESH_INTERVAL_HOURS
    config.REFRESH_INTERVAL_HOURS = 168
    try:
        check("env default used when unset", settings.get("refresh_interval_hours") == 168)
        check("hardcoded default for search_on_grab_movies",
              settings.get("search_on_grab_movies") is True)
        check("hardcoded default for search_on_grab_tv",
              settings.get("search_on_grab_tv") == "off")
        # Stored value WINS over the env default.
        settings.save({"refresh_interval_hours": 24})
        check("stored value wins over env", settings.get("refresh_interval_hours") == 24)
        # ...and keeps winning even if the env changes afterwards.
        config.REFRESH_INTERVAL_HOURS = 999
        check("stored still wins after env change",
              settings.get("refresh_interval_hours") == 24)
        check("settings.json written atomically",
              _os.path.exists(settings.settings_file()))
        # Validation.
        for bad, label in [({"search_on_grab_tv": "sometimes"}, "bad enum"),
                           ({"refresh_interval_hours": 0}, "int below 1"),
                           ({"refresh_interval_hours": "abc"}, "non-int"),
                           ({"totally_made_up": 1}, "unknown key")]:
            try:
                settings.save(bad)
                check(f"{label} rejected", False)
            except ValueError:
                check(f"{label} rejected", True)
        # A rejected save must not have clobbered the good value.
        check("rejected save wrote nothing",
              settings.get("refresh_interval_hours") == 24)
        check("enum accepts valid mode",
              settings.save({"search_on_grab_tv": "first_season"})["search_on_grab_tv"]
              == "first_season")
        # Secrets must never be managed here.
        for secret in ("radarr_api_key", "radarr_url", "anthropic_api_key"):
            check(f"{secret} not a managed key", secret not in settings.MANAGED_KEYS)
    finally:
        config.REFRESH_INTERVAL_HOURS = saved
        try:
            _os.remove(settings.settings_file())
        except OSError:
            pass


def test_quality_profile_resolution():
    print("quality profile resolution (live, by name)")
    from jellyfin_recs import staging
    saved_api = staging._api
    calls = []

    # Two profiles; the library mostly uses id 2 ("HD-1080p").
    state = {"profiles": [{"id": 1, "name": "Any"}, {"id": 2, "name": "HD-1080p"}],
             "movies": [{"qualityProfileId": 2}, {"qualityProfileId": 2},
                        {"qualityProfileId": 1}]}

    def fake_api(base, key, path, method="GET", payload=None):
        calls.append(path)
        if path == "/qualityprofile":
            return state["profiles"]
        if path == "/movie":
            return state["movies"]
        return {}

    staging._api = fake_api
    try:
        # Configured name wins.
        pid, drift = staging._resolve_quality_profile("radarr", "HD-1080p")
        check("configured name resolves", pid == 2 and drift is None)
        # Auto ("") picks the majority-in-library profile.
        pid, drift = staging._resolve_quality_profile("radarr", "")
        check("auto picks majority", pid == 2 and drift is None)
        # A configured name that no longer exists -> majority + drift message.
        pid, drift = staging._resolve_quality_profile("radarr", "Remux-2160p")
        check("missing name falls back to majority", pid == 2)
        check("drift reported", drift is not None and "Remux-2160p" in drift
              and "HD-1080p" in drift)
        # IDs are never cached: renumber the profiles and re-resolve.
        state["profiles"] = [{"id": 9, "name": "HD-1080p"}, {"id": 7, "name": "Any"}]
        state["movies"] = [{"qualityProfileId": 9}]
        pid, drift = staging._resolve_quality_profile("radarr", "HD-1080p")
        check("re-resolves fresh id after re-sync (no caching)", pid == 9)
        check("qualityprofile re-fetched each call",
              calls.count("/qualityprofile") == 4)
    finally:
        staging._api = saved_api


def test_sonarr_search_modes():
    print("sonarr payload shaping (search-on-grab modes)")
    from jellyfin_recs import staging
    chosen = {"title": "The Expanse",
              "seasons": [{"seasonNumber": 1}, {"seasonNumber": 2}, {"seasonNumber": 3}]}

    off = staging._series_payload(chosen, 280619, 2, "/tv", "off")
    check("off: no search", off["addOptions"]["searchForMissingEpisodes"] is False)
    check("off: monitors all", off["addOptions"]["monitor"] == "all")
    check("off: no seasons override", "seasons" not in off)

    first = staging._series_payload(chosen, 280619, 2, "/tv", "first_season")
    check("first_season: searches", first["addOptions"]["searchForMissingEpisodes"] is True)
    monitored = [s["seasonNumber"] for s in first["seasons"] if s["monitored"]]
    unmonitored = [s["seasonNumber"] for s in first["seasons"] if not s["monitored"]]
    check("first_season: only season 1 monitored", monitored == [1])
    check("first_season: later seasons unmonitored", unmonitored == [2, 3])
    check("first_season: monitor=firstSeason",
          first["addOptions"]["monitor"] == "firstSeason")

    allm = staging._series_payload(chosen, 280619, 2, "/tv", "all")
    check("all: searches", allm["addOptions"]["searchForMissingEpisodes"] is True)
    check("all: monitors all", allm["addOptions"]["monitor"] == "all")
    check("all: no seasons override", "seasons" not in allm)
    check("profile id passed through", allm["qualityProfileId"] == 2)


def test_settings_api():
    print("settings API round-trip")
    try:
        from jellyfin_recs import dashboard, settings
    except ImportError as e:
        check(f"flask available ({e})", False)
        return
    import os as _os
    dashboard.app.config["TESTING"] = True
    c = dashboard.app.test_client()
    try:
        r = c.get("/api/settings")
        check("GET /api/settings 200", r.status_code == 200)
        body = r.get_json()
        check("returns managed keys", "refresh_interval_hours" in body["settings"])
        check("never leaks secrets", not any(
            k in body["settings"] for k in ("radarr_api_key", "jellyfin_api_key",
                                            "anthropic_api_key", "radarr_url")))
        r = c.post("/api/settings", json={"search_on_grab_tv": "all",
                                          "refresh_interval_hours": 12})
        check("POST /api/settings 200", r.status_code == 200)
        check("round-trips saved value",
              c.get("/api/settings").get_json()["settings"]["search_on_grab_tv"] == "all")
        r = c.post("/api/settings", json={"search_on_grab_tv": "nope"})
        check("bad enum -> 400", r.status_code == 400)
        r = c.post("/api/settings", json={"radarr_api_key": "leak"})
        check("unknown/secret key -> 400", r.status_code == 400)
    finally:
        try:
            _os.remove(settings.settings_file())
        except OSError:
            pass


def test_json_repair():
    print("truncated JSON repair")
    from jellyfin_recs import recommender
    # Clean JSON parses.
    clean = '{"movies": {"Action": [{"title": "Heat", "year": 1995, "why": "x"}]}}'
    check("clean parses", recommender._parse_json(clean)["movies"]["Action"][0]["title"] == "Heat")
    # Truncated mid-string still salvages the complete entries.
    trunc = ('{"movies": {"Action": [{"title": "Heat", "year": 1995, "why": "Mann"}, '
             '{"title": "Sicario", "year": 2015, "why": "Villeneuve tha')
    r = recommender._parse_json(trunc, truncated=True)
    check("truncated salvaged", r is not None and
          "Heat" in [x["title"] for x in r["movies"]["Action"]])
    # Unparseable input still raises.
    try:
        recommender._parse_json("not json", truncated=False)
        check("garbage raises", False)
    except Exception:
        check("garbage raises", True)


def main():
    print("Running smoke tests...\n")
    test_profiling_and_ownership()
    test_franchise_gaps()
    test_history_parsing()
    test_storage_roundtrip()
    test_json_repair()
    test_tmdb_enrichment()
    test_top10_schema_shape()
    test_contiguous_rerank()
    test_overprovision_truncation()
    test_cross_section_dedupe()
    test_why_hygiene()
    test_rating_rerank()
    test_prompt_candidate_buffer()
    test_ui_density()
    test_settings_precedence_and_validation()
    test_quality_profile_resolution()
    test_sonarr_search_modes()
    test_settings_api()
    test_dashboard_endpoints()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        sys.exit(1)
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()
