"""
SpotFX — the Jukebox's show settings (data/jukebox-plan/report.md §4 and
§3.5, phase 3 PR 3.3's settings half): every economy setting with its
range, the party-size presets, and the "price check" that works the current
rules on real examples. models.jukebox.ShowConfig is the data,
services/jukebox/economy.py the rules.

ONE VALIDATOR. `apply_patch` is the only way an edit becomes a ShowConfig:
the stored settings with the patch on top, validated whole, an unknown key
or an out-of-range value refused BY NAME. The ranges are read off
EconomyConfig's own field bounds (`fields()`), never typed a second time, so
the page's inputs and the validator can't disagree.

THE PRESETS (§3.5). The economy uses ONE set of prices from 4 to 30 guests;
what changes with the crowd is how many slots the jukebox gets, so a preset
sets the PROGRAM (every other · two per set song · jukebox first) and, for
Large, "new phones need my approval". Any setting can be changed after
picking one; the preset is only remembered as the last one applied.

The price check is pure: the current settings in, examples out — the same
functions the economy runs, at the room sizes he picks.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationError

from models.jukebox import EconomyConfig, ProgramConfig, ShowConfig
from services.jukebox import economy

# The page's words for each setting, grouped as §4's cards. Every
# EconomyConfig field appears exactly once (tests hold it to that), so a new
# setting can't arrive without a label and a card.
FIELDS: list[tuple[str, str, str, str]] = [
    # key, card, label, unit
    ("start_credits", "Free credits", "Starting credits", "credits"),
    ("start_rest_after_min", "Free credits", "The second half arrives after", "min"),
    ("topup_every_min", "Free credits", "Top-up every (0 = off)", "min"),
    ("topup_cap", "Free credits", "Top-ups pause at", "credits held"),
    ("qr_bonus", "Free credits", "QR bonus card", "credits"),
    ("vote_reward", "Earning", "Per vote", "credits"),
    ("adder_up_reward", "Earning", "Per ▲ on your song", "credits"),
    ("tips", "Earning", "Tips", ""),
    ("tip_unit", "Earning", "Credits a tip tap", "credits"),
    ("tip_max_per_song", "Earning", "Most tips per song (per tipper)", "taps"),
    ("gift_double_first", "Earning", "First credits given count double (0 = off)", "credits"),
    ("add_base", "Add a song", "Base price", "credits"),
    ("add_free_min", "Add a song", "Base price while the wait is under", "min"),
    ("add_double_min", "Add a song", "Then doubles every (0 = flat)", "min of wait"),
    ("add_cap", "Add a song", "Price cap", "credits"),
    ("long_over_min", "Add a song", "Long songs: over", "min"),
    ("long_extra_per_min", "Add a song", "Long songs: extra per started minute", "credits"),
    ("learn_first_extra", "Add a song", "Not learned yet", "credits"),
    ("max_waiting", "Add a song", "Songs in line per guest", "songs"),
    ("fair_order", "Add a song", "1st songs before 2nd songs", ""),
    ("bump_up_base", "Bumps", "Up one place: base", "credits"),
    ("bump_up_per_behind", "Bumps", "Up: per song behind it", "credits"),
    ("bump_down_base", "Bumps", "Down one place: base", "credits"),
    ("bump_down_per_ahead", "Bumps", "Down: per song ahead of it", "credits"),
    ("bump_down_max_places", "Bumps", "Most places a song can be pushed back", "places"),
    ("next_base", "Play next", "Base price", "credits"),
    ("next_per_min", "Play next", "Per minute it jumps", "credits"),
    ("next_min_away_min", "Play next", "Only for songs at least", "min away"),
    ("skip_max", "Skip", "With nothing waiting", "credits"),
    ("skip_half_min", "Skip", "Halves at a line of", "min"),
    ("skip_floor", "Skip", "Never below", "credits"),
    ("skip_crowd", "Skip", "Scales with the room (√ guests ÷ 8)", ""),
    ("skip_down_pct", "Skip", "Each net ▼ takes off", "%"),
    ("skip_min", "Skip", "Lowest price", "credits"),
    ("chip_in", "Skip", "Chip in", ""),
    ("skip_grace_s", "Skip", "No skip in the first", "s"),
    ("jail_net_downs", "Jail", "Net ▼ to go to jail", "▼"),
    ("jail_scale", "Jail", "Rise with the crowd (6 at 8, 8 at 15, 10 at 30)", ""),
    ("jail_fee", "Jail", "Break-out price", "credits"),
]

PRESETS: dict[str, dict[str, Any]] = {
    "small": {"guests": "4-8", "program": {"mode": "auto", "every": 1, "run": 1},
              "approve_new_phones": False,
              "why": "Every other song is the jukebox's: ~30 guest songs a night, the set stays the backbone."},
    "medium": {"guests": "9-16", "program": {"mode": "auto", "every": 1, "run": 2},
               "approve_new_phones": False,
               "why": "Two jukebox songs per set song: every other would leave a quarter fewer songs to share."},
    "large": {"guests": "17-30", "program": {"mode": "jukebox_first"},
              "approve_new_phones": True,
              "why": "Jukebox first, the set fills any gap — the only shape that fits ~2 songs a guest; new phones need your approval."},
}

SHOW_KEYS = frozenset({"economy", "approve_new_phones"})


def fields() -> list[dict]:
    """Every economy setting as the page draws it: its card, words, unit,
    kind, default and range — the range read off the model's own bounds."""
    out = []
    model_fields = EconomyConfig.model_fields
    default = EconomyConfig()
    for key, card, label, unit in FIELDS:
        f = model_fields[key]
        lo = hi = None
        for m in f.metadata:
            lo = getattr(m, "ge", lo)
            hi = getattr(m, "le", hi)
        value = getattr(default, key)
        kind = "bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "float"
        out.append({"key": key, "card": card, "label": label, "unit": unit, "kind": kind,
                    "default": value, "min": lo, "max": hi})
    return out


def _first_error(exc: ValidationError, prefix: str = "") -> str:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ())) or "settings"
    return f"{prefix}{where}: {first.get('msg')}"


def apply_patch(current: ShowConfig, patch: dict) -> ShowConfig:
    """THE validator: `current` with a PARTIAL patch on top —
    {"economy": {key: value, ...}, "approve_new_phones": bool} — validated
    whole. Raises ValueError naming the first bad key; changes nothing."""
    if not isinstance(patch, dict):
        raise ValueError("expected a JSON object")
    unknown = sorted(set(patch) - SHOW_KEYS)
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}")
    eco_patch = patch.get("economy", {})
    if not isinstance(eco_patch, dict):
        raise ValueError("economy: expected an object of settings")
    unknown = sorted(set(eco_patch) - set(EconomyConfig.model_fields))
    if unknown:
        raise ValueError(f"unknown economy setting(s): {', '.join(unknown)}")
    merged = current.model_dump(mode="json")
    merged["economy"] = {**merged["economy"], **eco_patch}
    if "approve_new_phones" in patch:
        merged["approve_new_phones"] = patch["approve_new_phones"]
    try:
        return ShowConfig.model_validate(merged)
    except ValidationError as exc:
        raise ValueError(_first_error(exc)) from None


def apply_preset(name: str, show: ShowConfig, program: ProgramConfig) -> tuple[ShowConfig, ProgramConfig]:
    """A party-size preset: the program it sets (manual slots he placed are
    kept, for when he switches back to Manual) and the approval switch."""
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r} (use {', '.join(PRESETS)})")
    p = PRESETS[name]
    new_program = ProgramConfig.model_validate({**program.model_dump(mode="json"), **p["program"]})
    new_show = show.model_copy(update={"preset": name,
                                       "approve_new_phones": p["approve_new_phones"]})
    return new_show, new_program


def presets() -> list[dict]:
    return [{"name": k, **v} for k, v in PRESETS.items()]


# ── the price check ──────────────────────────────────────────────────────────

ADD_WAITS = (0, 15, 20, 30, 45, 60)
SKIP_CASES = ((0, 0), (10, 2), (20, 4), (40, 4))
NEXT_JUMPS = (10, 20, 30, 60)
BUMP_PLACES = (0, 4, 8)
TYPICAL_SONG_MIN = 3.6           # his library's median song (report §13)


def price_check(cfg: EconomyConfig, guests: int) -> dict:
    """The current rules on real examples, at a room of `guests`."""
    n = max(1, int(guests))
    now, later, after = economy.start_grants(cfg)
    return {
        "guests": n,
        "add": [{"wait_min": w, "price": economy.add_price(w, TYPICAL_SONG_MIN, True, cfg)}
                for w in ADD_WAITS],
        "add_long": {"duration_min": 6.5, "price": economy.add_price(0, 6.5, True, cfg)},
        "add_not_learned": economy.add_price(0, TYPICAL_SONG_MIN, False, cfg),
        "skip": [{"line_min": w, "downs": d, "price": economy.skip_price(w, 0, d, n, cfg)}
                 for w, d in SKIP_CASES],
        "play_next": [{"jump_min": j, "price": economy.play_next_price(j, cfg)} for j in NEXT_JUMPS],
        "bump_up": [{"behind": b, "price": economy.bump_up_price(b, cfg)} for b in BUMP_PLACES],
        "bump_down": [{"ahead": a, "price": economy.bump_down_price(a, cfg)} for a in BUMP_PLACES],
        "jail": {"threshold": economy.jail_threshold(n, cfg), "fee": cfg.jail_fee},
        "start": {"now": now, "later": later, "after_min": after},
        "topup": {"every_min": cfg.topup_every_min, "pauses_at": cfg.topup_cap},
        "tips": {"on": cfg.tips, "max_per_song": cfg.tip_max_per_song,
                 "double_first": cfg.gift_double_first},
        "songs_in_line": cfg.max_waiting,
    }


def read(show: Optional[ShowConfig] = None) -> dict:
    """What GET /api/jukebox/show answers: the settings, the field table,
    the presets."""
    from services.jukebox import store
    show = show or store.load_show()
    return {"show": show.model_dump(mode="json"), "fields": fields(), "presets": presets()}
