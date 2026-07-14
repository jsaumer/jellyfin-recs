#!/usr/bin/env python3
"""
Quick verification that the v0.2.0 changes work, without needing an API key or
a live Jellyfin. Run from the repo root:

    PYTHONPATH=src python3 verify_snippet.py

It builds a small fake library that partially owns the James Bond (Craig)
franchise, then checks:
  1. build_profile emits dense owned_entries with watched markers.
  2. detect_franchise_gaps finds the missing Bond films.
  3. _build_prompt includes the full titles AND a franchise-gaps section.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from jellyfin_recs import recommender

# Fake library: owns 2 of 5 Craig Bond films, one watched.
library = {
    "movies": [
        {"Name": "Casino Royale", "ProductionYear": 2006, "Genres": ["Action"],
         "UserData": {"Played": True}},
        {"Name": "Spectre", "ProductionYear": 2015, "Genres": ["Action"],
         "UserData": {"Played": False}},
        {"Name": "Heat", "ProductionYear": 1995, "Genres": ["Crime"],
         "UserData": {"Played": False}},
    ],
    "shows": [],
    "cartoons": [],
}

profile = recommender.build_profile(library)

# 1. dense owned_entries with watched marker
entries = profile["categories"]["movies"]["owned_entries"]
assert any(e.startswith("✓Casino Royale") for e in entries), entries
assert any(e.startswith("Spectre") and not e.startswith("✓") for e in entries), entries
print("[PASS] dense owned_entries with watched markers:", entries)

# 2. franchise gap detection
gaps = recommender.detect_franchise_gaps(profile["owned_titles"])
bond = dict(gaps).get("James Bond (Craig)")
assert bond and "Skyfall" in bond and "No Time to Die" in bond, gaps
print("[PASS] franchise gaps detected:", bond)

# 3. prompt contains full titles + a gaps section
prompt = recommender._build_prompt(profile, set(), gaps)
assert "Casino Royale" in prompt and "Spectre" in prompt
assert "FRANCHISE GAPS" in prompt or "franchise" in prompt.lower()
assert "Skyfall" in prompt   # the missing entry is named for the model
print("[PASS] prompt includes full library + franchise-gap section")

print("\nAll verification checks passed.")
