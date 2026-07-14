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
    with open(md, "w") as f:
        f.write("| Title | Year | Why | Owned | Watched |\n|---|---|---|---|---|\n"
                "| Rocky Balboa | 2006 | arc | ✅ Owned | ⬜ No |\n"
                "| Heat | 1995 | classic | ❌ No | ⬜ No |\n")
    seeds, rats = seed_history.parse_master_md(md)
    check("owned row seeded", any("Rocky" in s[0] for s in seeds))
    check("unowned row not seeded", not any("Heat" in s[0] for s in seeds))
    check("rationale captured", "heat" in rats)

    hist = os.path.join(_TMP, "history.txt")
    with open(hist, "w") as f:
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
                "documentaries": []}
        tmdb.enrich_all(recs)
        m = recs["movies"]["Action"][0]
        check("movie tmdb_id", m.get("tmdb_id") == 37724)
        check("movie imdb link", m.get("imdb_url", "").endswith("tt1074638/"))
        check("movie poster", "sky.jpg" in m.get("poster", ""))
        check("movie rating", m.get("rating") == 7.2)
        s = recs["top10_shows"][0]
        check("tv tvdb_id for sonarr", s.get("tvdb_id") == 280619)
        check("top10 key walked", s.get("tmdb_id") == 63639)
        # no-key no-op
        config.TMDB_API_KEY = ""
        r2 = {"documentaries": [{"title": "X", "year": 2000, "why": "w"}]}
        tmdb.enrich_all(r2)
        check("no key -> no-op", "tmdb_id" not in r2["documentaries"][0])
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
               '"movies": {"Action": [{"title": "Heat", "year": 1995, "why": "x"}]},'
               '"shows": {}, "documentaries": []}')
    recs = recommender._parse_json(payload)
    check("top10_movies parsed", len(recs["top10_movies"]) == 2)
    # "Nobody" is owned -> must be dropped; ranked ordering/fields preserved.
    owned = {"nobody"}
    filtered, removed = recommender._filter_owned(recs, owned)
    check("owned dropped from top10", "Nobody" in removed)
    kept = filtered["top10_movies"]
    check("top10 survives filter", len(kept) == 1 and kept[0]["title"] == "Skyfall")
    check("rank preserved", kept[0].get("rank") == 1)


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
    test_dashboard_endpoints()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        sys.exit(1)
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()
