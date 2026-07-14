# Reference test for tests/smoke_test.py — mocked TMDB enrichment.
# Adapt into a test_tmdb_enrichment() function following the existing style.

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
        s = recs["top10_shows"][0]
        check("tv tvdb_id for sonarr", s.get("tvdb_id") == 280619)
        # no-key no-op
        config.TMDB_API_KEY = ""
        r2 = {"documentaries": [{"title": "X", "year": 2000, "why": "w"}]}
        tmdb.enrich_all(r2)
        check("no key -> no-op", "tmdb_id" not in r2["documentaries"][0])
    finally:
        config.TMDB_API_KEY, tmdb._get = saved_key, saved_get
