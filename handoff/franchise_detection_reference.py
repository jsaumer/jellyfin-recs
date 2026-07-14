# Reference implementation for franchise-gap detection — to add to recommender.py
# This is tested logic; Claude Code should integrate it and wire it into the prompt.

# Curated canonical franchise/series title lists. Ownership uses lowercase
# substring matching against the library. Only franchises where the user owns
# SOME but not ALL entries are surfaced as "gaps" (highest-confidence recs).
FRANCHISES = {
    "Mad Max": ["Mad Max", "The Road Warrior", "Mad Max Beyond Thunderdome",
                "Mad Max: Fury Road", "Furiosa"],
    "X-Men": ["X-Men", "X2", "X-Men: The Last Stand", "X-Men: First Class",
              "X-Men: Days of Future Past", "X-Men: Apocalypse", "Logan",
              "Deadpool", "Deadpool 2"],
    "James Bond (Craig)": ["Casino Royale", "Quantum of Solace", "Skyfall",
                           "Spectre", "No Time to Die"],
    "Terminator": ["The Terminator", "Terminator 2: Judgment Day",
                   "Terminator 3: Rise of the Machines", "Terminator Salvation",
                   "Terminator Genisys", "Terminator: Dark Fate"],
    "Alien": ["Alien", "Aliens", "Alien 3", "Alien Resurrection", "Prometheus",
              "Alien: Covenant", "Alien: Romulus"],
    "Predator": ["Predator", "Predator 2", "Predators", "The Predator", "Prey"],
    "The Godfather": ["The Godfather", "The Godfather Part II",
                      "The Godfather Part III"],
    "Indiana Jones": ["Raiders of the Lost Ark", "Temple of Doom",
                      "The Last Crusade", "Kingdom of the Crystal Skull",
                      "Dial of Destiny"],
    "Rocky/Creed": ["Rocky", "Rocky II", "Rocky III", "Rocky IV", "Rocky V",
                    "Rocky Balboa", "Creed", "Creed II", "Creed III"],
    "Planet of the Apes (reboot)": ["Rise of the Planet of the Apes",
                                    "Dawn of the Planet of the Apes",
                                    "War for the Planet of the Apes",
                                    "Kingdom of the Planet of the Apes"],
    "Spider-Verse": ["Spider-Man: Into the Spider-Verse",
                     "Spider-Man: Across the Spider-Verse"],
    "The Matrix": ["The Matrix", "The Matrix Reloaded", "The Matrix Revolutions",
                   "The Matrix Resurrections"],
    "Blade Runner": ["Blade Runner", "Blade Runner 2049"],
}


def detect_franchise_gaps(owned_titles):
    """Given the set of lowercase owned titles, return a list of
    (franchise_name, [missing_titles]) for franchises the user partially owns.
    Only franchises with >=1 owned and >=1 missing are returned."""
    def owned(title):
        t = title.lower()
        return t in owned_titles or any(t in o for o in owned_titles)

    gaps = []
    for name, titles in FRANCHISES.items():
        have = [t for t in titles if owned(t)]
        missing = [t for t in titles if not owned(t)]
        if have and missing:
            gaps.append((name, missing))
    return gaps
