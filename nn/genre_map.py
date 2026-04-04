"""
SpotFX NN — Genre mapping.

Maps Spotify's free-form genre strings to a small set of macro genre IDs.
The NN uses these IDs as input to a learned embedding layer so that
similar genres can cluster naturally during training.

To add a new genre: just add entries to GENRE_LOOKUP below and retrain.
"""

# Macro genre IDs
EDM = 0
LATIN = 1
ROCK = 2
POP = 3
HIPHOP = 4
OTHER = 5

NUM_GENRES = 6

GENRE_NAMES = ["edm", "latin", "rock", "pop", "hiphop", "other"]

# Lowercase Spotify genre string → macro ID
GENRE_LOOKUP: dict[str, int] = {
    # EDM
    "edm": EDM,
    "dubstep": EDM,
    "future bass": EDM,
    "electronic": EDM,
    "stutter house": EDM,
    "house": EDM,
    "bass house": EDM,
    "bassline": EDM,
    "rally house": EDM,
    "drumstep": EDM,
    "melodic bass": EDM,
    "riddim": EDM,
    "bass music": EDM,
    "deathstep": EDM,
    "chillstep": EDM,
    "drum and bass": EDM,
    "liquid funk": EDM,
    "progressive house": EDM,
    "electro house": EDM,
    "trance": EDM,
    "techno": EDM,
    "hardstyle": EDM,
    "brostep": EDM,
    "complextro": EDM,
    "filthstep": EDM,
    "color bass": EDM,
    "tearout": EDM,

    # Latin
    "reggaeton": LATIN,
    "trap latino": LATIN,
    "urbano latino": LATIN,
    "latin": LATIN,
    "latin pop": LATIN,
    "reggaeton flow": LATIN,
    "latin hip hop": LATIN,
    "latin trap": LATIN,

    # Rock
    "rock": ROCK,
    "indie rock": ROCK,
    "alternative": ROCK,
    "indie": ROCK,
    "glam rock": ROCK,
    "hard rock": ROCK,
    "classic rock": ROCK,
    "rock and roll": ROCK,
    "glam metal": ROCK,
    "metal": ROCK,
    "punk": ROCK,
    "grunge": ROCK,

    # Pop
    "pop": POP,
    "k-pop": POP,
    "synth-pop": POP,
    "electropop": POP,
    "dance pop": POP,
    "indie pop": POP,

    # Hip-Hop
    "hip hop": HIPHOP,
    "rap": HIPHOP,
    "trap": HIPHOP,
    "southern hip hop": HIPHOP,
    "conscious hip hop": HIPHOP,
}


def map_genre(spotify_genres: list[str]) -> int:
    """
    Map a list of Spotify genre strings to a single macro genre ID.

    Strategy: take the first match found (Spotify orders genres by relevance).
    Falls back to OTHER if nothing matches.
    """
    for g in spotify_genres:
        g_lower = g.lower().strip()
        if g_lower in GENRE_LOOKUP:
            return GENRE_LOOKUP[g_lower]
    return OTHER
