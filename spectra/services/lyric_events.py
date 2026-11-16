"""Word colours and imprints (lyrics plan step 4): what a matched word does in
the show. The word timeline, the emphasis score, the sung labels and the
matches are steps 1 to 3; this module turns them into timed colour events.

The Admiral, 2026-11-09: "I want specific words and phrases to lead to events,
like changing the color ... The key is getting timings of words and events, and
for now doing some color work." And: "Q6 lyric events should instead imprint on
the drop, flare, or scene change/update if they are nearby. Start with 2s in
either direction. It should make the lyric color the flare or scene color."

OFF FOR EVERY SHOW UNLESS HE TURNS ONE ON. A show here is one song's show, by
URI: nothing in code or stored data switches one on, and an unreadable store
reads as off. With the switch off the trigger clock never reaches this module's
planner and its output is exactly what it was without the feature
(tests/test_lyric_events.py proves it against an engine running the same show).

THE PLAN IS ONE PURE FUNCTION, `plan_words` (behind `plan_play`, which rolls
the play first), and the Test Bed and the trigger clock both call it, so what
the page says a word will do is what the show does.
It decides, once per word, whether the word DRAWS ITS SHAPE, FIRES ALONE,
IMPRINTS on an event or does NOTHING and why. Only three facts need the room at the moment it happens,
and those are decided there and logged: whether the scene showing allows the
colour, whether that event can really carry it, and whether anything is holding
the room's colours.

THE ROLL (2026-11-12). Each play of a song rolls which words act this time,
once, before the plan is worked out, so the timeline is ready while the song
plays. The Admiral: "Instead of always using a "word" effect, it should randomly
be used, based on it's confidence ... My goal is for more words to get to show
up occassionally, but also to prevent a song always doing the same thing every
play", and "if the confidence leve is .97, it runs 97% of the time. If it is
.03, it runs 3% of the time. We might add more math to that later, but start
there." So:

  - A word's chance is `chance_for`: its confidence, exactly. His own matches
    are 1.0 and always play. His pin overrides it: Always is 1.0, Never 0.0.
    Every later change to the mapping belongs in that one function.
  - A play has one number, its seed. Each word's draw is a hash of the seed,
    the song and the word's own span and label, in [0, 1); the word plays this
    time when its draw is under its chance. A word's draw does not depend on
    any other word, so adding or pinning one moves nothing else, and the same
    seed always gives the same winners.
  - A word that did not win sits out BEFORE the planner runs, so it frees its
    phrase, its event and its gap for the next word: a weaker word that is
    always crowded out today gets its turn on the plays a stronger neighbour
    sits out.
  - A new play: a different song, the same song after another song or after
    PLAY_GAP_S without it, or a repeat wrap (the end of the song straight back
    to its start). Pause, seek, rewind and a SPECTRA restart keep the play.
  - "Keep this roll": he can keep a play's number as the song's plan
    (`keep_roll`); every later play then uses it.
  - With no play (a song not playing and no kept roll) the Test Bed shows
    every word as if it won, each with its chance, and can sample a play.

WORD SHAPES (Word Shapes plan W0.3, 2026-11-15 — the Admiral: "It would
operate like a flare in the scenes panel, just only fire by sung word"). A
match may now reach a SHAPE as well as (or instead of) a colour set, and a
word that reaches one takes the SHAPE BRANCH BEFORE the colour branch: a
shape word fires the showing scene's "word" response section, whose own
colour kinds are how a word recolours the room from there, so a word that
reaches BOTH a shape and colour sets is a shape — never both, never the
colour path's fallback. His rules, each one applied where it is named:

  - a shape word TAKES ITS LINE and counts toward the minimum gap exactly
    like a fired colour word (one word's worth of show, whichever kind it
    is);
  - A DROP WITHIN THE IMPRINT WINDOW WINS and the SHAPE is skipped
    (`WHY_DROP_WINS`, his Q5 A) — the drop is the bigger moment, and the
    shape would be forming straight into it. **THE COLOUR IS NOT SKIPPED
    WITH IT**: the word falls through to the colour branch and imprints on
    that drop exactly as it does today, carrying `shape_skipped` as the
    only trace. A flare or a scene change does not stop a shape at all,
    and a shape never imprints on anything;
  - NOTHING CAN DRAW IT, asked at PLAN time (`can_draw`, bound to the
    showing scene's Words band by `engine.lyric_can_draw`): the word is
    planned as the ordinary colour word it is, with its OWN `fire_at`, its
    own transition and its own imprint. This is a plan-time question
    BECAUSE IT DECIDES THE TIMING — a shape fires its form (0.5-0.9 s)
    early, a colour its own `transition_ms_for` (0.15-3 s) — and a
    fire-time fallback cannot give back a lead that has already passed;
  - the timing is one rule, `room_controls.word_shape_timing`: the form
    paces with Energy, the hold is the sung phrase clamped, the release is
    a multiple of the form. The form is ALSO the lead — `transition_ms`
    here, so `fire_at = word − form` (LEAD family, positive = earlier) and
    the shape completes ON the word, which is the whole promise of the
    feature ("the trigger lands on where the shape is first fully formed");
  - and the FIRE-TIME NET for the one race the plan cannot see — the
    showing scene changed inside the replan window — is
    `colour_fallback` / `SHAPE_NOTHING_DREW`: the colour path again, with
    the shape's own lead behind it, which is the best available once the
    moment has passed.

HIS EXISTING WORD COLOURS ARE UNCHANGED BY ALL OF THIS. Every one of his 57
songs with sung words has word colours switched on, and the two rules above
are what keep a shape from ever SUBTRACTING one: a word near a drop still
tints the drop, and a word nothing can draw still fires or imprints its own
colour on its own clock. A shape only ever happens where a scene can
actually draw it.

THE BAND IS THE SWITCH (his Q6 A): a shape word does something only if the
showing scene has a Words band with a Word Shape kind in it. A scene
without one is byte-identical to today — which is why this planner's shape
branch is unreachable for every song whose labels reach no shape, and why
`WORD_SHAPE_EFFECTS` being empty means even a Words band writes to no
fixture until wave 1.

HOW A WORD IS WEIGHED. Among the words that play, the strongest goes first (his
own matches ahead of every guess, then Claude's confidence, then the emphasis
score, then the earlier word), so a stronger word can never be crowded out by a
weaker one:

  1. A word sitting out this play fires nothing. A match that reaches only an
     effect has no event yet, and fires nothing.
  2. Once per phrase: a sung line that already gave a lyric event gives no more.
  2b. A word that reaches a SHAPE draws it (rules above) and stops here.
  3. The event: every drop, scene change or update, and flare within the imprint
     window either way, inclusive of the window's edge. Drop first, then scene
     change or update, then flare; the nearest wins a tie. No event near it, and
     the word fires alone.
  4. No imprint and no fire if that event cannot carry colour.
  5. One imprint per event: a word that loses it to a stronger word does nothing,
     because it is within the window of an event. Only a word further than the
     window from every event fires alone.
  6. The minimum gap, across fired and imprinted words alike, measured between
     words. Only a word that really did something counts against the next.

A word imprints on at most one event and never tries its second choice.

ENERGY RULES APPLY ONLY TO WORDS FIRING ALONE. Energy is read at the word, on
the show's own clock (spectra/services/energy.py). At or above the cut-off the
colour is momentary: it holds through the sung words and fades back. Below it the
colour holds until the next scene change or next matched word. Energy also sets
the transition, which is the LEAD: fired that much early so the colour arrives on
the word (docs/SPECTRA_TIMING_CONVENTIONS.md, "Word colours").

AN IMPRINT CARRIES ITS COLOUR ON A CONTEXT VARIABLE (`ACTIVE`), set by the
trigger clock around the event's own fire. The existing paths read it where they
would otherwise pick a colour: the drop colour change, a scene fire's colour set,
a flare's or update's colour jump. There is no second colour path, every gate
those paths already apply still applies, and a staggered flare kind carries it the
way it carries the drop's "colour already done" flag.

WHO READS WHAT. This module imports nothing from the label, match or Claude
modules at import time: `load_words` imports them when a switched-on show is
loaded, off the event loop. The show's import graph is checked by
tests/test_lyric_reading.py.

THE HIGHLIGHT (2026-11-12). `word_marks` is this plan as the song strip, Home
and the Test Bed's Word events row draw it ahead of the song (joined onto
`/api/upcoming` by trigger id), and `fired_payload` is what the engine tells
every open page the moment a word fires or imprints (`{"type": "word_colour"}`
on the websocket). Neither changes what fires or when.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Optional, Sequence

from spectra import config
from spectra.models.lyric_labels import (
    SEED_MAX, LyricEventSettings, LyricEventStore, LyricPlay, LyricPlayStore, LyricShowState,
)

logger = logging.getLogger(__name__)

VERDICT_FIRE = "fire"
VERDICT_IMPRINT = "imprint"
VERDICT_NOTHING = "nothing"
# WORD SHAPES (W0.3): the fourth verdict. A shape word fires the showing
# scene's "word" response section and nothing else — it never imprints.
VERDICT_SHAPE = "shape"

WHY_SAT_OUT = "sat_out"
WHY_NO_COLOUR = "no_colour_set"
WHY_PHRASE = "phrase_taken"
WHY_TOO_SOON = "too_soon"
WHY_LOST = "lost_event"
WHY_CANNOT_CARRY = "event_cannot_carry"
# A shape word with a DROP inside the imprint window: the drop wins, the
# shape is skipped (his Q5 A). A flare or scene change never does this.
WHY_DROP_WINS = "drop_wins"

KIND_DROP = "drop"
KIND_SCENE = "scene"
KIND_FLARE = "flare"
_PRIORITY = {KIND_DROP: 0, KIND_SCENE: 1, KIND_FLARE: 2}

# Why an event cannot carry colour, known ahead of time.
CANNOT_DROP_COLOUR_OFF = "drop colour changes are off"
CANNOT_OWN_COLOUR = "it names its own colour"

# His per-match override of the chance (SongMatches.pins). No pin is Chance.
PIN_ALWAYS = "always"
PIN_NEVER = "never"
PIN_CHANCE = "chance"
PINS = (PIN_ALWAYS, PIN_NEVER)

# THE ROLL: away from a song this long, and coming back to it is a new play.
# How often a switched-on show's play under way is written down, so a restart
# mid-song finds it (LyricPlay.seen_ms).
PLAY_GAP_S = 600.0
PLAY_SAVE_S = 60.0
# A repeat wrap: from the last tenth of the song straight to its first
# twentieth.
WRAP_FROM = 0.9
WRAP_TO = 0.05

# Energy unknown is neutral, the way every Energy reader treats it.
NEUTRAL_ENERGY = 0.5
# Matches within this much of the strongest on the same words count as the
# strongest: the chooser picks among them. His matches always outrank guesses.
STRONG_TIE = 0.05

# First guesses, his to tune once he has seen them. At FAST_AT_ENERGY or above a
# word changes as fast as it can; Energy tops out there on a song he has not
# Marked (energy.AUTO_CEILING), so a loud unmarked song can reach the fastest.
FAST_TRANSITION_MS = 150
SLOW_TRANSITION_MS = 3000
FAST_AT_ENERGY = 0.75

# How long a momentary colour stays: through the sung words, within these
# bounds, then it fades back over this multiple of the time it took to arrive
# (the colour-rotate flare's own ratio).
MOMENT_HOLD_MIN_MS = 350
MOMENT_HOLD_MAX_MS = 1500
MOMENT_FADE_RATIO = 1.5
MOMENT_FADE_MIN_MS = 150

# WORD SHAPES (W0.3), THE COLOUR FALLBACK. What `on_word_shape` reports
# when NOTHING IN THE ROOM COULD DRAW the shape — the showing scene has no
# Words section, its bands do not reach this word's Energy, or no scene is
# showing at all. Deliberately NOT every non-`applied` result:
#   * a HOLD (a preview, Absorb, a house mode, P3 A's charge/lull/drop) is
#     something deliberately holding the room, and a colour word is held by
#     those same gates today — falling back there would walk straight
#     through a gate;
#   * `applied` with `virtuals: 0` is a Words band that RAN (its own colour
#     kinds included, which is the designed colour path for a shape word);
#     he attached that band and chose its behaviour. Before wave 1 wires an
#     effect that is every Words band, and it must stay the Words
#     behaviour rather than fall back.
SHAPE_NOTHING_DREW = ("no_class", "no_band", "no_active_scene")
# ... and the PLAN-TIME form of the same question (round-2 review): no scene
# could draw this word's shape at this Energy, decided while the plan is
# made rather than at the word, so the word keeps its OWN colour timing
# (`fire_at`, transition, imprint) instead of inheriting the shape's lead.
WHY_CANNOT_DRAW = "nothing_can_draw"
# ... and what the show log calls a shape word that took the colour path
# instead, so "it did nothing" and "it went red" are never the same row.
RESULT_FELL_BACK = "fell_back_to_colour"

# What the imprint's fire reports back, read by the show log.
RESULT_LANDED = "landed"
RESULT_SCENE_DISALLOWS = "scene_disallows"
RESULT_NOT_IN_SELECTOR = "not_in_selector"
RESULT_CANNOT_CARRY = "cannot_carry"
RESULT_STAGGERED = "staggered"


class StoreUnreadable(RuntimeError):
    pass


# ── the store ───────────────────────────────────────────────────────────────

_lock = threading.RLock()
_cache: Optional[tuple[tuple[str, int, int], LyricEventStore]] = None


def _load() -> LyricEventStore:
    global _cache
    path = config.LYRIC_EVENTS_FILE
    try:
        st = path.stat()
    except FileNotFoundError:
        return LyricEventStore()
    sig = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache is not None and _cache[0] == sig:
            return _cache[1]
        try:
            store = LyricEventStore.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return LyricEventStore()
        except Exception as exc:
            raise StoreUnreadable(
                f"{path.name} cannot be read ({exc}); refusing to treat it as empty") from exc
        _cache = (sig, store)
        return store


def _save(store: LyricEventStore) -> None:
    path = config.LYRIC_EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def enabled(uri: Optional[str]) -> bool:
    """Is this show switched on? Never raises: anything unreadable is OFF, so a
    damaged file can only ever stop a word from firing."""
    if not uri:
        return False
    try:
        state = _load().shows.get(uri)
    except Exception:                                    # noqa: BLE001
        logger.exception("word colours: the switch is unreadable — treated as off")
        return False
    return bool(state is not None and state.enabled)


def settings() -> LyricEventSettings:
    """The live tuning. Unreadable falls back to the first guesses."""
    try:
        return _load().settings
    except Exception:                                    # noqa: BLE001
        logger.exception("word colours: settings unreadable — using the defaults")
        return LyricEventSettings()


def set_show(uri: str, on: bool) -> bool:
    """He turned this show's word colours on or off. An unreadable store raises
    rather than being overwritten."""
    with _lock:
        store = _load().model_copy(deep=True)
        prior = store.shows.get(uri) or LyricShowState()
        store.shows[uri] = prior.model_copy(
            update={"enabled": bool(on), "changed_ms": int(time.time() * 1000)})
        _save(store)
    return bool(on)


def kept_seed(uri: Optional[str]) -> Optional[int]:
    """The play number he kept for this song, or None. Never raises: an
    unreadable store keeps nothing, so every play rolls its own."""
    if not uri:
        return None
    try:
        state = _load().shows.get(uri)
    except Exception:                                    # noqa: BLE001
        logger.exception("word colours: the kept roll is unreadable — rolling fresh")
        return None
    return None if state is None else state.kept_seed


def keep_roll(uri: str, seed: Optional[int]) -> Optional[int]:
    """Keep this play number as the song's plan, or (None) let every play
    roll again. Does not touch the show's switch. An unreadable store raises
    rather than being overwritten; a number out of range raises ValueError."""
    if seed is not None and not 0 <= int(seed) <= SEED_MAX:
        raise ValueError(f"a play number is between 0 and {SEED_MAX}")
    with _lock:
        store = _load().model_copy(deep=True)
        prior = store.shows.get(uri) or LyricShowState()
        store.shows[uri] = prior.model_copy(update={
            "kept_seed": None if seed is None else int(seed),
            "kept_ms": int(time.time() * 1000) if seed is not None else 0})
        _save(store)
    return None if seed is None else int(seed)


def update_settings(energy_cutoff: Optional[float] = None, min_gap_s: Optional[float] = None,
                    imprint_window_s: Optional[float] = None) -> LyricEventSettings:
    """Only the values given change. Out of range raises ValueError."""
    with _lock:
        store = _load().model_copy(deep=True)
        changes = {k: v for k, v in (("energy_cutoff", energy_cutoff),
                                     ("min_gap_s", min_gap_s),
                                     ("imprint_window_s", imprint_window_s)) if v is not None}
        store.settings = LyricEventSettings.model_validate(
            {**store.settings.model_dump(), **changes})
        _save(store)
    return store.settings


def shows_on() -> list[str]:
    try:
        return sorted(uri for uri, s in _load().shows.items() if s.enabled)
    except Exception:                                    # noqa: BLE001
        logger.exception("word colours: the switch is unreadable")
        return []


# ── the play under way (THE ROLL) ───────────────────────────────────────────

ROLL_PLAYING = "playing"
ROLL_KEPT = "kept"
ROLL_SAMPLE = "sample"
ROLL_NONE = "none"


@dataclass(frozen=True)
class Play:
    """One play of one song: the number its words were rolled with.
    `source` says where it came from: the song playing now, his kept roll
    for a song not playing, or a throwaway sample from the Test Bed."""
    uri: str
    seed: int
    started_ms: int = 0
    kept: bool = False
    restored: bool = False
    source: str = ROLL_PLAYING

    @property
    def tag(self) -> str:
        """The short name a page prints for this play."""
        return f"{self.seed & 0xFFFF:04x}"


def new_seed() -> int:
    return secrets.randbits(32)


def _load_plays() -> LyricPlayStore:
    path = config.LYRIC_PLAYS_FILE
    try:
        return LyricPlayStore.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return LyricPlayStore()


def save_play(play: Play, now_ms: Optional[int] = None) -> None:
    """Write down the play under way (or refresh when it was last seen).
    Only ever called for a switched-on show. Never raises: losing it costs
    only a fresh roll after a restart."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    path = config.LYRIC_PLAYS_FILE
    try:
        record = LyricPlayStore(current=LyricPlay(
            uri=play.uri, seed=play.seed, started_ms=play.started_ms, seen_ms=now_ms,
            kept=play.kept))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.model_dump(), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, path)
    except Exception:                                    # noqa: BLE001
        logger.exception("word colours: could not write down the play under way")


def begin_play(uri: str, *, restore: bool, now_ms: Optional[int] = None) -> Play:
    """The play of `uri` starting now, for a switched-on show. `restore`
    (only the first play since SPECTRA started, with no other song between)
    carries on the play written down before a restart, when it is this song
    and was seen less than PLAY_GAP_S ago. Otherwise his kept roll, else a
    fresh number. Written down either way. Never raises."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if restore:
        try:
            saved = _load_plays().current
        except Exception:                                # noqa: BLE001
            logger.exception("word colours: the play under way is unreadable — rolling fresh")
            saved = None
        if (saved is not None and saved.uri == uri
                and 0 <= now_ms - saved.seen_ms < PLAY_GAP_S * 1000):
            play = Play(uri, saved.seed, saved.started_ms, kept=saved.kept, restored=True)
            save_play(play, now_ms)
            return play
    kept = kept_seed(uri)
    play = (Play(uri, kept, now_ms, kept=True) if kept is not None
            else Play(uri, new_seed(), now_ms))
    save_play(play, now_ms)
    return play


def is_repeat_wrap(last_ms: int, position_ms: int, duration_ms: Optional[int]) -> bool:
    """The song went from its end straight back to its start: repeat-one,
    or he started it over from the very end. Unknown length: never."""
    if not duration_ms or duration_ms <= 0:
        return False
    return last_ms >= WRAP_FROM * duration_ms and position_ms <= WRAP_TO * duration_ms


# ── what the plan works on ──────────────────────────────────────────────────


@dataclass(frozen=True)
class WordHit:
    """One matched span of words. Overlapping matches collapse into one hit,
    whose colour sets are every colour set the strongest of them reaches."""
    key: str
    first_word: int
    last_word: int
    phrase: str
    label: str
    line: int
    ms: float
    end_ms: float
    emphasis: float
    strength: float
    his: bool
    set_ids: tuple[str, ...] = ()
    set_names: tuple[str, ...] = ()
    energy: Optional[float] = None
    why_not: Optional[str] = None
    # WORD SHAPES (W0.3): the shape this word reaches, if any — the FIRST
    # shape target the strongest match reaches (`hits_from_matches`). A hit
    # with one takes the shape branch; a hit with one and no colour set is
    # NOT `WHY_NO_COLOUR` any more, because it has something to do.
    shape_id: Optional[str] = None
    shape_name: Optional[str] = None
    # One swatch per set in `set_ids` (sung_labels.Target.swatch, the colour
    # the Word matches row draws a set with), so the song strip can lend a
    # word's colour to the event it reaches before the song plays. None where
    # a set has no swatch.
    swatches: tuple[Optional[str], ...] = ()
    # THE ROLL. `match_id` is the leading match's id (what a pin is set
    # through); `pin` his override, if any. `chance` is set by roll_hits;
    # `draw` and `won` only when a play is rolled (None: not rolled, every
    # word planned as if it won).
    match_id: Optional[str] = None
    pin: Optional[str] = None
    chance: Optional[float] = None
    draw: Optional[float] = None
    won: Optional[bool] = None

    @property
    def swatch(self) -> Optional[str]:
        """The colour a page shows for this word ahead of fire time: its
        first candidate set's, the same one the Word matches row draws."""
        return next((s for s in self.swatches if s), None)


def swatch_for(hit: WordHit, set_id: Optional[str]) -> Optional[str]:
    """The swatch of the set that actually landed, or the word's own when
    the set is not one of the word's (or is unknown). Pure, no store read:
    this runs on the fire path."""
    if set_id is not None:
        for sid, sw in zip(hit.set_ids, hit.swatches):
            if sid == set_id and sw:
                return sw
    return hit.swatch


@dataclass(frozen=True)
class EventMoment:
    """One thing the engine will fire. `ms` is its target on the show clock,
    every offset already in it: the moment it lands, the same one tick() times."""
    id: str
    kind: str
    ms: int
    label: str
    can_carry: bool = True
    why_not: Optional[str] = None


@dataclass(frozen=True)
class WordAction:
    hit: WordHit
    verdict: str
    why: Optional[str] = None
    event: Optional[EventMoment] = None
    blocked_by: Optional[str] = None
    energy: float = NEUTRAL_ENERGY
    momentary: bool = False
    # For a colour word, the colour change's own duration; for a SHAPE word,
    # the form time. Both are the LEAD (`fire_at = word − transition_ms`,
    # positive = earlier), so one field carries both and the trigger clock
    # needs no second idea of "how early".
    transition_ms: int = 0
    # WORD SHAPES (W0.3): the whole envelope the effect is told, from
    # `room_controls.word_shape_timing`. form_s == transition_ms / 1000 by
    # construction; hold and release are durations on the effect's own
    # clock. All three are 0 on anything but a shape.
    form_s: float = 0.0
    hold_s: float = 0.0
    release_s: float = 0.0
    # WORD SHAPES (W0.3 round-2 review): why this word reaches a shape and
    # is NOT drawing one — `WHY_DROP_WINS` (a drop inside the window) or
    # `WHY_CANNOT_DRAW` (no scene can draw it at this Energy). The word is
    # then planned as the COLOUR word it would be without the shape, and
    # this field is the only trace of the shape it skipped, so the Test Bed
    # can say "it would have drawn a heart, but ..." instead of silently
    # looking like an ordinary colour word.
    shape_skipped: Optional[str] = None

    @property
    def shape_id(self) -> Optional[str]:
        return self.hit.shape_id if self.verdict == VERDICT_SHAPE else None


@dataclass(frozen=True)
class SongWords:
    uri: str
    status: str
    note: Optional[str] = None
    hits: tuple[WordHit, ...] = ()
    clock_flagged: bool = False


@dataclass
class Imprint:
    """A word giving its colour to the event firing right now. Mutable because
    it is how that event's own path says what became of it."""
    hit: WordHit
    event: EventMoment
    result: Optional[str] = None
    set_id: Optional[str] = None
    set_name: Optional[str] = None
    rung: Optional[str] = None

    @property
    def set_ids(self) -> tuple[str, ...]:
        return self.hit.set_ids

    @property
    def landed(self) -> bool:
        return self.result == RESULT_LANDED

    def note_landed(self, set_id: Optional[str], set_name: Optional[str] = None,
                    rung: Optional[str] = None) -> None:
        self.result = RESULT_LANDED
        self.set_id = set_id
        self.set_name = set_name
        self.rung = rung


ACTIVE: ContextVar[Optional[Imprint]] = ContextVar("spectra_lyric_imprint", default=None)


def active() -> Optional[Imprint]:
    return ACTIVE.get()


# ── energy ──────────────────────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def transition_ms_for(energy: float) -> int:
    """Energy to the time the change takes: louder is quicker."""
    span = SLOW_TRANSITION_MS - FAST_TRANSITION_MS
    return int(round(SLOW_TRANSITION_MS - _clamp01(energy / FAST_AT_ENERGY) * span))


def is_momentary(energy: float, cutoff: float) -> bool:
    return float(energy) >= float(cutoff)


def moment_dwell_ms(hit: WordHit) -> int:
    """How long a momentary colour sits once it has arrived."""
    sung = int(round(hit.end_ms - hit.ms))
    return max(MOMENT_HOLD_MIN_MS, min(MOMENT_HOLD_MAX_MS, sung))


def moment_fade_ms(transition_ms: int) -> int:
    return max(MOMENT_FADE_MIN_MS, int(round(transition_ms * MOMENT_FADE_RATIO)))


# ── a word's shape timing (WORD SHAPES, W0.3) ───────────────────────────────

# (energy, phrase_ms) -> (form_s, hold_s, release_s). The planner takes this
# as a CALLABLE rather than reading the room itself: the one rule lives in
# `room_controls.word_shape_timing` (where the five settings are), and this
# module stays a pure function of what it is handed, exactly as it is for
# every other number here. The trigger clock and the Test Bed both bind the
# live room's settings into it (`TriggerEngine._lyric_shape_timing`).
ShapeTiming = Callable[[float, float], "tuple[float, float, float]"]

# (energy) -> can the showing scene actually DRAW a shape at this Energy?
# Taken as a CALLABLE for the same reason as ShapeTiming above: the answer
# needs the room (a Words band covering this Energy with a Word Shape kind
# in it — scene_response.words_band_draws), and this module stays a pure
# function of what it is handed. A caller with no room says True, which is
# what every pure `plan_words` spec wants.
CanDraw = Callable[[float], bool]


def default_shape_timing(energy: float, phrase_ms: float) -> tuple[float, float, float]:
    """The plan's own defaults, for a caller with no room to read (a pure
    `plan_words` spec, a Test Bed preview on a host with no room controls).
    Deliberately the same numbers `fx/effects/word_shape_keys.py` states —
    imported, never re-typed — so "the default" is one value everywhere."""
    from fx.effects import word_shape_keys as wsk
    e = _clamp01(energy)
    frac = 1.0 if FAST_AT_ENERGY <= 0 else min(1.0, e / FAST_AT_ENERGY)
    form_s = wsk.DEFAULT_FORM_S + (0.5 - wsk.DEFAULT_FORM_S) * frac
    hold_s = min(max(max(0.0, float(phrase_ms or 0.0)) / 1000.0,
                     wsk.DEFAULT_HOLD_S), 2.0)
    return (round(form_s, 4), round(hold_s, 4),
            round(wsk.release_s_for(form_s), 4))


# ── the roll ────────────────────────────────────────────────────────────────


def colour_fallback(action: WordAction,
                    tuning: LyricEventSettings) -> Optional[WordAction]:
    """THE COLOUR FALLBACK (W0.3 review, 2026-11-16). The same word, planned
    as the COLOUR word it would have been if it reached no shape — for the
    one case where nothing in the room could draw (`SHAPE_NOTHING_DREW`
    above). None when the word reaches no colour set, which is the honest
    "there was nothing else to do" case.

    WHY THIS EXISTS AT ALL. His 57 songs with sung words all have word
    colours switched ON, and a word that reaches a shape is a shape (his
    Q5 A) — so between this row and W2.5 attaching Words bands to his
    scenes, every shape-reaching word on every scene without one would have
    gone from changing his colours to doing nothing. A feature that is
    "off until a band exists" must not SUBTRACT behaviour while it waits.

    EXACTLY TODAY'S COLOUR WORD, re-derived from the same two functions the
    colour branch uses (`is_momentary` against the cut-off, and
    `transition_ms_for`), never carried over from the shape: the shape's
    own `transition_ms` is its FORM, a different quantity on a different
    scale, and reusing it would silently retune every fallback word's fade
    (`moment_fade_ms` reads it). The RAMP the fire path hands the colour is
    still the time LEFT to the word, so the colour lands on the word exactly
    as it would have."""
    if not action.hit.set_ids:
        return None
    energy = float(action.energy)
    return replace(
        action, verdict=VERDICT_FIRE, why=None, event=None, blocked_by=None,
        momentary=is_momentary(energy, tuning.energy_cutoff),
        transition_ms=transition_ms_for(energy),
        form_s=0.0, hold_s=0.0, release_s=0.0)


def chance_for(hit: WordHit) -> float:
    """The share of plays this word acts on: its confidence, exactly (his
    own matches are 1.0), unless he pinned it. The one place the mapping
    lives, so "more math later" changes only this."""
    if hit.pin == PIN_ALWAYS:
        return 1.0
    if hit.pin == PIN_NEVER:
        return 0.0
    if hit.his:
        return 1.0
    return _clamp01(hit.strength)


def draw_for(seed: int, uri: str, hit: WordHit) -> float:
    """This word's draw for this play, in [0, 1): the same seed, song, words
    and label always give the same number, and no other word changes it."""
    text = f"{int(seed)}|{uri}|{hit.first_word}|{hit.last_word}|{hit.label.strip().casefold()}"
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def roll_hits(hits: Sequence[WordHit], play: Optional[Play]) -> list[WordHit]:
    """Every hit with its chance and, when a play is rolled, its draw and
    whether it won. A word that did not win sits out (WHY_SAT_OUT) BEFORE
    plan_words runs, so it takes no phrase, event or gap from another word.
    No play: nothing is rolled, and every word is planned as if it won."""
    out: list[WordHit] = []
    for hit in hits:
        chance = chance_for(hit)
        if play is None:
            out.append(replace(hit, chance=chance, draw=None, won=None))
            continue
        u = draw_for(play.seed, play.uri, hit)
        won = u < chance
        why_not = hit.why_not if (won or hit.why_not is not None) else WHY_SAT_OUT
        out.append(replace(hit, chance=chance, draw=u, won=won, why_not=why_not))
    return out


def plan_play(hits: Sequence[WordHit], events: Sequence[EventMoment],
              tuning: LyricEventSettings, play: Optional[Play],
              shape_timing: Optional[ShapeTiming] = None,
              can_draw: Optional[CanDraw] = None) -> list[WordAction]:
    """Roll this play, then plan the words that won it. What the trigger
    clock and the Test Bed both call."""
    return plan_words(roll_hits(hits, play), events, tuning,
                      shape_timing=shape_timing, can_draw=can_draw)


# ── the plan ────────────────────────────────────────────────────────────────


def _weigh(hit: WordHit) -> tuple:
    return (not hit.his, -hit.strength, -hit.emphasis, hit.ms, hit.first_word)


def _event_for(hit: WordHit, events: Sequence[EventMoment],
               window_ms: float) -> Optional[EventMoment]:
    near = [e for e in events if abs(e.ms - hit.ms) <= window_ms]
    if not near:
        return None
    return min(near, key=lambda e: (_PRIORITY[e.kind], abs(e.ms - hit.ms), e.ms, e.id))


def _drop_near(hit: WordHit, events: Sequence[EventMoment],
               window_ms: float) -> Optional[EventMoment]:
    """The nearest DROP within the imprint window of this word, or None —
    the one event that stops a shape (his Q5 A). Deliberately blind to
    `can_carry`: that flag is about carrying a COLOUR (the drop colour
    change being switched off, say), and a drop is the bigger musical
    moment either way."""
    near = [e for e in events if e.kind == KIND_DROP
            and abs(e.ms - hit.ms) <= window_ms]
    if not near:
        return None
    return min(near, key=lambda e: (abs(e.ms - hit.ms), e.ms, e.id))


def plan_words(hits: Sequence[WordHit], events: Sequence[EventMoment],
               tuning: LyricEventSettings,
               shape_timing: Optional[ShapeTiming] = None,
               can_draw: Optional[CanDraw] = None) -> list[WordAction]:
    """One action per hit, in song order. The rules are in the module docstring,
    and they run in this order."""
    window_ms = float(tuning.imprint_window_s) * 1000.0
    gap_ms = float(tuning.min_gap_s) * 1000.0
    timing = shape_timing or default_shape_timing
    drawable = can_draw or (lambda _energy: True)
    done: dict[str, WordAction] = {}
    lines_taken: set[int] = set()
    events_taken: dict[str, WordHit] = {}
    fired: list[WordHit] = []
    # Why the word under consideration reaches a shape and is not drawing
    # one, or None. Read by `nothing` and by the colour branch's own two
    # WordActions below — all three are in this scope, so the value the
    # loop last set is the one they see.
    skipped: Optional[str] = None

    def too_soon(hit: WordHit) -> Optional[WordHit]:
        return next((w for w in fired if abs(w.ms - hit.ms) < gap_ms), None)

    def nothing(hit: WordHit, why: str, event: Optional[EventMoment] = None,
                blocked_by: Optional[str] = None) -> WordAction:
        return WordAction(hit, VERDICT_NOTHING, why=why, event=event, blocked_by=blocked_by,
                          energy=NEUTRAL_ENERGY if hit.energy is None else float(hit.energy),
                          shape_skipped=skipped)

    for hit in sorted(hits, key=_weigh):
        skipped = None
        if hit.why_not is not None:
            done[hit.key] = nothing(hit, hit.why_not)
            continue
        if hit.line in lines_taken:
            done[hit.key] = nothing(hit, WHY_PHRASE)
            continue
        if hit.shape_id:
            # WORD SHAPES (W0.3), BEFORE the colour branch: a word that
            # reaches a shape IS a shape, even when it also reaches colour
            # sets — the Words band's own colour kinds are how a shape word
            # recolours the room (module docstring).
            #
            # TWO WAYS OUT OF THAT, both added by the round-2 review
            # (2026-11-16) and both for the same reason: HIS EXISTING WORD
            # COLOURS MUST STAY BYTE-FOR-BYTE AS TODAY. Each one FALLS
            # THROUGH to the colour branch below rather than ending the
            # word, and leaves `skipped` as the only trace:
            #   * A DROP INSIDE THE WINDOW. His Q5 A skips the SHAPE, not
            #     the colour — so the word goes on to imprint on that drop
            #     exactly as it does today. (Ending here instead would have
            #     stopped every "love"/"heart"/"star" sung within 2 s of a
            #     drop from tinting it, on every scene, for good.)
            #   * NOTHING CAN DRAW IT. Decided HERE, at plan time, not at
            #     the fire: the word then keeps its OWN colour timing — its
            #     own `fire_at`, its own transition, its own imprint — where
            #     a fire-time fallback can only hand the colour whatever is
            #     left of the SHAPE's lead, which is 500-900 ms in place of
            #     the 1.5-3 s a quiet colour glides in over. A fire-time
            #     fallback cannot restore a lead that has already passed.
            # A word with NO colour set has nothing to fall through to, so
            # it stays with its shape either way: a drop near it ends it
            # (nothing to do), and an undrawable one is still planned as a
            # shape, which the fire path then logs as `no_class`.
            drop = _drop_near(hit, events, window_ms)
            energy = NEUTRAL_ENERGY if hit.energy is None else float(hit.energy)
            if drop is not None and not hit.set_ids:
                done[hit.key] = nothing(hit, WHY_DROP_WINS, event=drop)
                continue
            if drop is not None:
                skipped = WHY_DROP_WINS
            elif drawable(energy) or not hit.set_ids:
                soon = too_soon(hit)
                if soon is not None:
                    done[hit.key] = nothing(hit, WHY_TOO_SOON, blocked_by=soon.phrase)
                    continue
                form_s, hold_s, release_s = timing(energy, hit.end_ms - hit.ms)
                done[hit.key] = WordAction(
                    hit, VERDICT_SHAPE, energy=energy,
                    transition_ms=int(round(form_s * 1000.0)),
                    form_s=form_s, hold_s=hold_s, release_s=release_s)
                # A shape takes its line and counts toward the gap, exactly
                # like a fired colour word.
                lines_taken.add(hit.line)
                fired.append(hit)
                continue
            else:
                skipped = WHY_CANNOT_DRAW
        event = _event_for(hit, events, window_ms)
        if event is None:
            soon = too_soon(hit)
            if soon is not None:
                done[hit.key] = nothing(hit, WHY_TOO_SOON, blocked_by=soon.phrase)
                continue
            energy = NEUTRAL_ENERGY if hit.energy is None else float(hit.energy)
            done[hit.key] = WordAction(
                hit, VERDICT_FIRE, energy=energy,
                momentary=is_momentary(energy, tuning.energy_cutoff),
                transition_ms=transition_ms_for(energy),
                shape_skipped=skipped)
            lines_taken.add(hit.line)
            fired.append(hit)
            continue
        if not event.can_carry:
            done[hit.key] = nothing(hit, WHY_CANNOT_CARRY, event=event)
            continue
        winner = events_taken.get(event.id)
        if winner is not None:
            done[hit.key] = nothing(hit, WHY_LOST, event=event, blocked_by=winner.phrase)
            continue
        soon = too_soon(hit)
        if soon is not None:
            done[hit.key] = nothing(hit, WHY_TOO_SOON, event=event, blocked_by=soon.phrase)
            continue
        done[hit.key] = WordAction(
            hit, VERDICT_IMPRINT, event=event,
            energy=NEUTRAL_ENERGY if hit.energy is None else float(hit.energy),
            shape_skipped=skipped)
        events_taken[event.id] = hit
        lines_taken.add(hit.line)
        fired.append(hit)

    return sorted(done.values(), key=lambda a: (a.hit.ms, a.hit.first_word))


# ── from matches to hits ────────────────────────────────────────────────────


def _strength(match: Mapping[str, Any]) -> float:
    if match.get("source") == "his":
        return 1.0
    return float(match.get("confidence") or 0.0)


def _clusters(matches: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    out: list[list[Mapping[str, Any]]] = []
    reach = -1
    for match in sorted(matches, key=lambda m: (m["first_word"], m["last_word"])):
        if out and match["first_word"] <= reach:
            out[-1].append(match)
            reach = max(reach, match["last_word"])
        else:
            out.append([match])
            reach = match["last_word"]
    return out


def _pin_of(lead: Mapping[str, Any], considered: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """The hit's pin: the leading match's own, else the first pinned match
    among those it stands for (strongest first)."""
    if lead.get("pin") in PINS:
        return str(lead["pin"])
    for match in sorted(considered, key=lambda m: -_strength(m)):
        if match.get("pin") in PINS:
            return str(match["pin"])
    return None


def hits_from_matches(matches: Sequence[Mapping[str, Any]], lines: Sequence[int],
                      energy_at: Callable[[int], Optional[float]],
                      reach: Callable[[Mapping[str, Any]], Sequence[tuple[str, str]]],
                      shapes: Optional[Callable[[Mapping[str, Any]],
                                                Sequence[tuple[str, str]]]] = None
                      ) -> list[WordHit]:
    """Pure. `lines` is each word's sung line; `reach(match)` every colour set a
    match reaches as (id, name) or (id, name, swatch), effects left out. His
    matches outrank every guess on the same words, so a correction wins without
    him also having to delete what it replaces. No guess is too weak to keep:
    its confidence is its chance (chance_for).

    `shapes(match)` (WORD SHAPES, W0.3) is every SHAPE a match reaches, as
    (id, name) — the hit takes the FIRST one the strongest match reaches,
    strongest match first, so a correction decides the shape the same way it
    decides the colour. Omitted (the default) means no shape reach at all,
    which is exactly what this function did before shapes existed. A hit
    that reaches a shape is no longer `WHY_NO_COLOUR` when it reaches no
    colour set: it has something to do."""
    hits: list[WordHit] = []
    for cluster in _clusters(matches):
        first = min(m["first_word"] for m in cluster)
        last = max(m["last_word"] for m in cluster)
        his = [m for m in cluster if m.get("source") == "his"]
        considered = his or cluster
        why_not: Optional[str] = None
        top = max(_strength(m) for m in considered)
        best = [m for m in considered if _strength(m) >= top - STRONG_TIE]
        lead = max(best, key=_strength)
        pairs: dict[str, tuple[str, Optional[str]]] = {}
        for match in best:
            for reached in reach(match):
                set_id, name = reached[0], reached[1]
                swatch = reached[2] if len(reached) > 2 else None
                pairs.setdefault(set_id, (name, swatch))
        shape_id = shape_name = None
        if shapes is not None:
            for match in sorted(best, key=lambda m: -_strength(m)):
                reached = list(shapes(match))
                if reached:
                    shape_id, shape_name = str(reached[0][0]), str(reached[0][1])
                    break
        if why_not is None and not pairs and shape_id is None:
            why_not = WHY_NO_COLOUR
        hits.append(WordHit(
            key=f"{first}-{last}", first_word=first, last_word=last, phrase=str(lead["phrase"]),
            label=str(lead["label"]), line=int(lines[first]) if first < len(lines) else 0,
            ms=float(lead["ms"]), end_ms=float(lead["end_ms"]),
            emphasis=max(float(m.get("score") or 0.0) for m in best),
            strength=top, his=bool(his), set_ids=tuple(pairs),
            set_names=tuple(name for name, _sw in pairs.values()),
            swatches=tuple(sw for _name, sw in pairs.values()),
            energy=energy_at(int(lead["ms"])), why_not=why_not,
            shape_id=shape_id, shape_name=shape_name,
            match_id=None if lead.get("id") is None else str(lead["id"]),
            pin=_pin_of(lead, considered)))
    return hits


def load_words(uri: str) -> SongWords:
    """One song's hits, read off the event loop. Only ever reached for a show
    switched on, and by the Test Bed's own page."""
    from spectra.services import (colour_words, energy as energy_mod, lyric_matches,
                                  lyrics_timeline, sung_labels)
    timeline = lyrics_timeline.timeline_for_uri(uri)
    if not timeline.usable:
        return SongWords(uri, timeline.status, timeline.note)
    doc = lyric_matches.load(uri)
    catalogue = sung_labels.catalogue()
    matches, _unplaced = lyric_matches.resolve(doc, timeline.scored, catalogue)
    energy = energy_mod.timeline(uri)

    def energy_at(ms: int) -> Optional[float]:
        return None if energy is None else energy.at(ms)

    def _targets(match: Mapping[str, Any], kind: str
                 ) -> list[tuple[str, str, Optional[str]]]:
        if match.get("source") == "his":
            return [(t["id"], t["name"], t.get("swatch")) for t in match.get("targets", ())
                    if t.get("kind") == kind]
        owners = catalogue.owners.get(colour_words.word_key(str(match.get("label") or "")), ())
        return [(t.id, t.name, t.swatch) for t in owners if t.kind == kind]

    def reach(match: Mapping[str, Any]) -> list[tuple[str, str, Optional[str]]]:
        return _targets(match, sung_labels.KIND_COLOR_SET)

    def shapes(match: Mapping[str, Any]) -> list[tuple[str, str, Optional[str]]]:
        """WORD SHAPES (W0.3): the shape targets a match reaches — W0.2's
        own third target kind (`sung_labels.KIND_SHAPE`), read off the same
        `catalogue.owners` the colour reach above reads.

        W0.2's PRECEDENCE RULE IS ALREADY IN THAT ORDER and is not re-stated
        here: `_owner_rank` lists a shape target BEFORE an effect target
        carrying the same word (today "star"/"stars"/"estrella" sit on both
        the Star shape and EFFECT_SEEDS["radial"]), so taking the first
        shape among a word's owners is taking the one W0.2 decided. The
        shape-vs-COLOUR question is the planner's, not the catalogue's: a
        word reaching both is a shape because `plan_words` runs the shape
        branch first (this module's docstring)."""
        return _targets(match, sung_labels.KIND_SHAPE)

    hits = hits_from_matches(matches, [w.line for w in timeline.scored], energy_at,
                             reach, shapes)
    return SongWords(uri, timeline.status, timeline.note, tuple(hits),
                     clock_flagged=timeline.clock.flagged)


# ── saying what a word will do ──────────────────────────────────────────────


def _clock_words(ms: float) -> str:
    seconds = max(0.0, float(ms) / 1000.0)
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def _seconds(ms: float) -> str:
    return f"{float(ms) / 1000.0:.2f}".rstrip("0").rstrip(".") + " s"


def _percent(chance: Optional[float]) -> str:
    return "–" if chance is None else f"{int(round(float(chance) * 100))}%"


def chance_words(hit: WordHit) -> str:
    """How often this word plays, in a few words."""
    if hit.pin == PIN_ALWAYS:
        return "Pinned to play every time."
    if hit.pin == PIN_NEVER:
        return "Pinned to never play."
    if hit.his:
        return "Your own match: plays every time."
    return f"Plays on about {_percent(hit.chance)} of plays (Claude's confidence)."


def _skipped_words(action: WordAction) -> str:
    """The clause the Test Bed appends when a word reaches a shape and is
    doing its colour instead — so a shaped word that looks like a plain
    colour word on the page says why."""
    if action.shape_skipped is None:
        return ""
    name = action.hit.shape_name or action.hit.shape_id
    if action.shape_skipped == WHY_DROP_WINS:
        return (f" The {name} shape is skipped: a drop lands inside the "
                f"window, and the drop is the bigger moment.")
    if action.shape_skipped == WHY_CANNOT_DRAW:
        return (f" The {name} shape is skipped: no scene showing can draw "
                f"one at this Energy (give a scene a Words band with a "
                f"Word Shape kind).")
    return f" The {name} shape is skipped."


def describe(action: WordAction) -> str:
    """The sentence the Test Bed prints for this word."""
    hit, event = action.hit, action.event
    if action.why == WHY_SAT_OUT:
        return (f"Sits out this play: its chance is {_percent(hit.chance)} and it did not "
                "come up this time.")
    if action.verdict == VERDICT_SHAPE:
        name = hit.shape_name or hit.shape_id
        return (f"Draws the {name} shape: it forms over "
                f"{_seconds(action.form_s * 1000)}, finishing on the word, "
                f"holds {_seconds(action.hold_s * 1000)} and releases over "
                f"{_seconds(action.release_s * 1000)}.")
    if action.verdict == VERDICT_FIRE:
        how = (f"high energy ({action.energy:.2f}), so it is momentary" if action.momentary
               else (f"low energy ({action.energy:.2f}), so it holds until the next scene "
                     "change or matched word"))
        return (f"Fires on its own: {how}, changing over "
                f"{_seconds(action.transition_ms)}.{_skipped_words(action)}")
    if action.verdict == VERDICT_IMPRINT and event is not None:
        away = (event.ms - hit.ms) / 1000.0
        return (f"Gives its colour to the {event.label} at {_clock_words(event.ms)} "
                f"({away:+.1f} s from the word).{_skipped_words(action)}")
    if action.why == WHY_DROP_WINS and event is not None:
        return (f"A drop lands at {_clock_words(event.ms)}, inside the window, "
                f"so the shape is skipped — the drop is the bigger moment — "
                f"and this word reaches no colour set to give it instead.")
    if action.why == WHY_NO_COLOUR:
        return "This match reaches no colour set, so it fires nothing yet."
    if action.why == WHY_PHRASE:
        return "A stronger word in this phrase already has the phrase's one event."
    if action.why == WHY_TOO_SOON:
        return f"Too close to \"{action.blocked_by}\": inside the minimum gap."
    if action.why == WHY_LOST and event is not None:
        return (f"\"{action.blocked_by}\" is the stronger word for the {event.label} at "
                f"{_clock_words(event.ms)}, and this word is too close to it to fire alone.")
    if action.why == WHY_CANNOT_CARRY and event is not None:
        return (f"The {event.label} at {_clock_words(event.ms)} cannot carry colour "
                f"({event.why_not}), so nothing fires.")
    return "Nothing."


def action_payload(action: WordAction) -> dict[str, Any]:
    hit, event = action.hit, action.event
    return {
        "key": hit.key, "first_word": hit.first_word, "last_word": hit.last_word,
        "phrase": hit.phrase, "label": hit.label, "ms": hit.ms, "end_ms": hit.end_ms,
        "source": "his" if hit.his else "claude", "strength": round(hit.strength, 3),
        "match_id": hit.match_id, "pin": hit.pin,
        "chance": None if hit.chance is None else round(hit.chance, 3),
        "draw": None if hit.draw is None else round(hit.draw, 4), "won": hit.won,
        "chance_words": chance_words(hit),
        "set_names": list(hit.set_names), "set_ids": list(hit.set_ids), "swatch": hit.swatch,
        "shape": hit.shape_id, "shape_name": hit.shape_name,
        "shape_skipped": action.shape_skipped,
        "verdict": action.verdict, "why": action.why,
        "words": describe(action), "energy": round(action.energy, 3),
        "momentary": action.momentary, "transition_ms": action.transition_ms,
        "form_s": round(action.form_s, 4), "hold_s": round(action.hold_s, 4),
        "release_s": round(action.release_s, 4),
        "blocked_by": action.blocked_by,
        "event": None if event is None else {
            "id": event.id, "kind": event.kind, "ms": event.ms, "label": event.label,
            "away_ms": int(round(event.ms - hit.ms)), "can_carry": event.can_carry,
            "why_not": event.why_not},
    }


# ── the highlight: what a page draws before, and is told at, fire time ──────

KIND_WORD = "word"


def word_marks(actions: Sequence[WordAction]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """The plan as the song strip, Home and the Test Bed draw it, ahead of
    the song (2026-11-12, the Admiral: "a visual highlight to scene changes
    and flares and drops that are getting a word related effect" — option A
    of data/word-effect-highlight-options). Pure.

    Returns (imprints, fires): `imprints` maps an event's id (the trigger id
    tick() fires, the same id `/api/upcoming` now carries) to the word that
    gives it its colour — its phrase, time and swatch; `fires` is one marker
    per word firing on its own — a colour word OR a shape word, the latter
    carrying `shape` (W0.3) — kind "word" (a diamond on the marker row),
    drawn where the word is sung. Words that do nothing are left out: the
    Test Bed's Word actions row is where those are explained.

    The swatch is the word's FIRST candidate set's, as the Word matches row
    draws it (his default, 2026-11-12): which set really lands, and whether
    the event can carry it, is decided at fire time and told through
    `fired_payload`."""
    imprints: dict[str, dict[str, Any]] = {}
    fires: list[dict[str, Any]] = []
    for action in actions:
        hit = action.hit
        if action.verdict == VERDICT_IMPRINT and action.event is not None:
            imprints[action.event.id] = {
                "word": hit.phrase, "word_ms": int(round(hit.ms)), "swatch": hit.swatch,
                "word_key": hit.key}
        elif action.verdict in (VERDICT_FIRE, VERDICT_SHAPE):
            # A SHAPE word is a marker of the same kind, carrying its shape
            # (W0.3): one row, one idea — "a word did something here" —
            # whether the something was a colour or a shape.
            fires.append({
                "ms": int(round(hit.ms)), "end_ms": int(round(hit.end_ms)), "kind": KIND_WORD,
                "rank": None, "rank_of": None, "source": "word", "id": fire_id(hit),
                "word": hit.phrase, "word_ms": int(round(hit.ms)), "swatch": hit.swatch,
                "word_key": hit.key, "momentary": action.momentary,
                "shape": action.shape_id})
    return imprints, fires


def fire_id(hit: WordHit) -> str:
    """The id a fire-alone word's marker carries on `/api/upcoming`, and the
    `event_id` its fire-time push names, so a page can find the marker."""
    return f"lyric:{hit.key}"


def fired_payload(verdict: str, hit: WordHit, *, event: Optional[EventMoment],
                  set_id: Optional[str], set_name: Optional[str], result: Optional[str],
                  landed: bool, uri: Optional[str], position_ms: Optional[int]) -> dict[str, Any]:
    """What the engine tells every open page the moment a word fires or
    imprints (`TriggerEngine._lyric_fired`, pushed as {"type": "word_colour",
    ...} on SPECTRA's websocket by engine.py): enough for the strip's marker
    flash and the next-event box to take the word's colour — option E's live
    pulse — without a second idea of what happened. `swatch` is the set that
    actually landed when known, else the word's own."""
    return {
        "uri": uri, "verdict": verdict, "phrase": hit.phrase, "label": hit.label,
        "word_ms": int(round(hit.ms)), "word_key": hit.key,
        "event_id": fire_id(hit) if event is None else event.id,
        "event_kind": KIND_WORD if event is None else event.kind,
        "event_ms": int(round(hit.ms)) if event is None else int(event.ms),
        "result": result, "landed": bool(landed), "set_id": set_id, "set_name": set_name,
        "swatch": swatch_for(hit, set_id), "position_ms": position_ms,
        # WORD SHAPES (W0.3): the shape that just formed, or None. `verdict`
        # is VERDICT_SHAPE on a shape word, so a page can tell the two
        # kinds of fire-alone apart without reading this field at all.
        "shape": hit.shape_id if verdict == VERDICT_SHAPE else None,
    }


@dataclass
class Preview:
    enabled: bool
    words: SongWords
    actions: list[WordAction] = field(default_factory=list)
    n_events: int = 0
    play: Optional[Play] = None
    kept_seed: Optional[int] = None
    playing: bool = False


def roll_payload(preview: Preview) -> dict[str, Any]:
    """Which play the plan is for, and how many words won it."""
    play = preview.play
    rolled = [a for a in preview.actions if a.hit.won is not None]
    return {
        "state": ROLL_NONE if play is None else play.source,
        "seed": None if play is None else play.seed,
        "tag": None if play is None else play.tag,
        "started_ms": None if play is None else play.started_ms,
        "kept": bool(play is not None and play.kept),
        "kept_seed": preview.kept_seed,
        "playing": preview.playing,
        "n_words": len(preview.actions),
        "n_won": sum(1 for a in rolled if a.hit.won),
    }


def preview_payload(preview: Preview, tuning: LyricEventSettings) -> dict[str, Any]:
    return {
        "uri": preview.words.uri, "status": preview.words.status, "note": preview.words.note,
        "clock_flagged": preview.words.clock_flagged, "enabled": preview.enabled,
        "settings": tuning.model_dump(), "n_events": preview.n_events,
        "shows_on": len(shows_on()),
        "roll": roll_payload(preview),
        "actions": [action_payload(a) for a in preview.actions],
    }
