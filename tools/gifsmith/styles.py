"""Named dance styles: ordered key-pose lists (one pose lands per beat).

Add a new style by listing poses from poses.json (``!mirror`` suffix flips a
pose). Normal styles should loop smoothly over 8 beats; big (flare) variants
are shorter, exaggerated 4-beat bursts.
"""

DANCES: dict[tuple[str, str], dict] = {
    ("basic", "normal"): {
        "poses": [
            "idle", "sway_r", "arms_up", "sway_r!mirror",
            "step_r", "clap", "step_r!mirror", "arm_up_r",
        ],
        "tweens_per_beat": 2,
    },
    ("basic", "big"): {
        "poses": ["deep_squat", "star_jump", "jump_tuck", "star_jump"],
        "tweens_per_beat": 3,
    },
    ("disco", "normal"): {
        "poses": [
            "disco_point_r", "hips_r", "disco_point_r!mirror", "hips_r!mirror",
            "disco_point_r", "arms_up", "disco_point_r!mirror", "clap",
        ],
        "tweens_per_beat": 2,
    },
    ("disco", "big"): {
        "poses": ["deep_squat", "disco_big_r", "star_jump", "disco_big_r!mirror"],
        "tweens_per_beat": 3,
    },
    ("wave", "normal"): {
        "poses": [
            "arm_up_r", "arms_up", "arm_up_r!mirror", "sway_r",
            "arm_up_r", "clap", "arm_up_r!mirror", "sway_r!mirror",
        ],
        "tweens_per_beat": 2,
    },
    ("wave", "big"): {
        "poses": ["wave_big_r", "star_jump", "wave_big_r!mirror", "kick_big_r"],
        "tweens_per_beat": 3,
    },
}


def dance_spec(style: str, energy: str) -> dict:
    try:
        return DANCES[(style, energy)]
    except KeyError:
        styles = sorted({s for s, _ in DANCES})
        raise SystemExit(f"unknown style/energy '{style}/{energy}'; styles: {styles}")
