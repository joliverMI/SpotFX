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

THE PLAN IS ONE PURE FUNCTION, `plan_words`, and the Test Bed and the trigger
clock both call it, so what the page says a word will do is what the show does.
It decides, once per word, whether the word FIRES ALONE, IMPRINTS on an event or
does NOTHING and why. Only three facts need the room at the moment it happens,
and those are decided there and logged: whether the scene showing allows the
colour, whether that event can really carry it, and whether anything is holding
the room's colours.

HOW A WORD IS WEIGHED. The strongest word goes first (his own matches ahead of
every guess, then Claude's confidence, then the emphasis score, then the earlier
word), so a stronger word can never be crowded out by a weaker one:

  1. A weak match fires nothing. A match that reaches only an effect has no
     event yet, and fires nothing.
  2. Once per phrase: a sung line that already gave a lyric event gives no more.
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
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from spectra import config
from spectra.models.lyric_labels import LyricEventSettings, LyricEventStore, LyricShowState

logger = logging.getLogger(__name__)

VERDICT_FIRE = "fire"
VERDICT_IMPRINT = "imprint"
VERDICT_NOTHING = "nothing"

WHY_WEAK = "weak_match"
WHY_NO_COLOUR = "no_colour_set"
WHY_PHRASE = "phrase_taken"
WHY_TOO_SOON = "too_soon"
WHY_LOST = "lost_event"
WHY_CANNOT_CARRY = "event_cannot_carry"

KIND_DROP = "drop"
KIND_SCENE = "scene"
KIND_FLARE = "flare"
_PRIORITY = {KIND_DROP: 0, KIND_SCENE: 1, KIND_FLARE: 2}

# Why an event cannot carry colour, known ahead of time.
CANNOT_DROP_COLOUR_OFF = "drop colour changes are off"
CANNOT_OWN_COLOUR = "it names its own colour"

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
        store.shows[uri] = LyricShowState(enabled=bool(on), changed_ms=int(time.time() * 1000))
        _save(store)
    return bool(on)


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
    transition_ms: int = 0


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


# ── the plan ────────────────────────────────────────────────────────────────


def _weigh(hit: WordHit) -> tuple:
    return (not hit.his, -hit.strength, -hit.emphasis, hit.ms, hit.first_word)


def _event_for(hit: WordHit, events: Sequence[EventMoment],
               window_ms: float) -> Optional[EventMoment]:
    near = [e for e in events if abs(e.ms - hit.ms) <= window_ms]
    if not near:
        return None
    return min(near, key=lambda e: (_PRIORITY[e.kind], abs(e.ms - hit.ms), e.ms, e.id))


def plan_words(hits: Sequence[WordHit], events: Sequence[EventMoment],
               tuning: LyricEventSettings) -> list[WordAction]:
    """One action per hit, in song order. The rules are in the module docstring,
    and they run in this order."""
    window_ms = float(tuning.imprint_window_s) * 1000.0
    gap_ms = float(tuning.min_gap_s) * 1000.0
    done: dict[str, WordAction] = {}
    lines_taken: set[int] = set()
    events_taken: dict[str, WordHit] = {}
    fired: list[WordHit] = []

    def too_soon(hit: WordHit) -> Optional[WordHit]:
        return next((w for w in fired if abs(w.ms - hit.ms) < gap_ms), None)

    def nothing(hit: WordHit, why: str, event: Optional[EventMoment] = None,
                blocked_by: Optional[str] = None) -> WordAction:
        return WordAction(hit, VERDICT_NOTHING, why=why, event=event, blocked_by=blocked_by,
                          energy=NEUTRAL_ENERGY if hit.energy is None else float(hit.energy))

    for hit in sorted(hits, key=_weigh):
        if hit.why_not is not None:
            done[hit.key] = nothing(hit, hit.why_not)
            continue
        if hit.line in lines_taken:
            done[hit.key] = nothing(hit, WHY_PHRASE)
            continue
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
                transition_ms=transition_ms_for(energy))
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
            energy=NEUTRAL_ENERGY if hit.energy is None else float(hit.energy))
        events_taken[event.id] = hit
        lines_taken.add(hit.line)
        fired.append(hit)

    return sorted(done.values(), key=lambda a: (a.hit.ms, a.hit.first_word))


# ── from matches to hits ────────────────────────────────────────────────────


def _strength(match: Mapping[str, Any]) -> float:
    if match.get("source") == "his":
        return 1.0
    return float(match.get("confidence") or 0.0)


def _is_weak(match: Mapping[str, Any], threshold: float) -> bool:
    return match.get("source") != "his" and float(match.get("confidence") or 0.0) < threshold


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


def hits_from_matches(matches: Sequence[Mapping[str, Any]], lines: Sequence[int],
                      weak_threshold: float, energy_at: Callable[[int], Optional[float]],
                      reach: Callable[[Mapping[str, Any]], Sequence[tuple[str, str]]]
                      ) -> list[WordHit]:
    """Pure. `lines` is each word's sung line; `reach(match)` every colour set a
    match reaches as (id, name), effects left out. His matches outrank every
    guess on the same words, so a correction wins without him also having to
    delete what it replaces."""
    hits: list[WordHit] = []
    for cluster in _clusters(matches):
        first = min(m["first_word"] for m in cluster)
        last = max(m["last_word"] for m in cluster)
        his = [m for m in cluster if m.get("source") == "his"]
        pool = his or cluster
        strong = [m for m in pool if not _is_weak(m, weak_threshold)]
        why_not: Optional[str] = None if strong else WHY_WEAK
        considered = strong or pool
        top = max(_strength(m) for m in considered)
        best = [m for m in considered if _strength(m) >= top - STRONG_TIE]
        lead = max(best, key=_strength)
        pairs: dict[str, str] = {}
        for match in best:
            for set_id, name in reach(match):
                pairs.setdefault(set_id, name)
        if why_not is None and not pairs:
            why_not = WHY_NO_COLOUR
        hits.append(WordHit(
            key=f"{first}-{last}", first_word=first, last_word=last, phrase=str(lead["phrase"]),
            label=str(lead["label"]), line=int(lines[first]) if first < len(lines) else 0,
            ms=float(lead["ms"]), end_ms=float(lead["end_ms"]),
            emphasis=max(float(m.get("score") or 0.0) for m in best),
            strength=top, his=bool(his), set_ids=tuple(pairs), set_names=tuple(pairs.values()),
            energy=energy_at(int(lead["ms"])), why_not=why_not))
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

    def reach(match: Mapping[str, Any]) -> list[tuple[str, str]]:
        if match.get("source") == "his":
            return [(t["id"], t["name"]) for t in match.get("targets", ())
                    if t.get("kind") == sung_labels.KIND_COLOR_SET]
        owners = catalogue.owners.get(colour_words.word_key(str(match.get("label") or "")), ())
        return [(t.id, t.name) for t in owners if t.kind == sung_labels.KIND_COLOR_SET]

    hits = hits_from_matches(matches, [w.line for w in timeline.scored],
                             sung_labels.weak_match_threshold(), energy_at, reach)
    return SongWords(uri, timeline.status, timeline.note, tuple(hits),
                     clock_flagged=timeline.clock.flagged)


# ── saying what a word will do ──────────────────────────────────────────────


def _clock_words(ms: float) -> str:
    seconds = max(0.0, float(ms) / 1000.0)
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def _seconds(ms: float) -> str:
    return f"{float(ms) / 1000.0:.2f}".rstrip("0").rstrip(".") + " s"


def describe(action: WordAction) -> str:
    """The sentence the Test Bed prints for this word."""
    hit, event = action.hit, action.event
    if action.verdict == VERDICT_FIRE:
        how = (f"high energy ({action.energy:.2f}), so it is momentary" if action.momentary
               else (f"low energy ({action.energy:.2f}), so it holds until the next scene "
                     "change or matched word"))
        return f"Fires on its own: {how}, changing over {_seconds(action.transition_ms)}."
    if action.verdict == VERDICT_IMPRINT and event is not None:
        away = (event.ms - hit.ms) / 1000.0
        return (f"Gives its colour to the {event.label} at {_clock_words(event.ms)} "
                f"({away:+.1f} s from the word).")
    if action.why == WHY_WEAK:
        return "A weak match, so it fires nothing."
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
        "set_names": list(hit.set_names), "verdict": action.verdict, "why": action.why,
        "words": describe(action), "energy": round(action.energy, 3),
        "momentary": action.momentary, "transition_ms": action.transition_ms,
        "blocked_by": action.blocked_by,
        "event": None if event is None else {
            "id": event.id, "kind": event.kind, "ms": event.ms, "label": event.label,
            "away_ms": int(round(event.ms - hit.ms)), "can_carry": event.can_carry,
            "why_not": event.why_not},
    }


@dataclass
class Preview:
    enabled: bool
    words: SongWords
    actions: list[WordAction] = field(default_factory=list)
    n_events: int = 0


def preview_payload(preview: Preview, tuning: LyricEventSettings) -> dict[str, Any]:
    return {
        "uri": preview.words.uri, "status": preview.words.status, "note": preview.words.note,
        "clock_flagged": preview.words.clock_flagged, "enabled": preview.enabled,
        "settings": tuning.model_dump(), "n_events": preview.n_events,
        "shows_on": len(shows_on()),
        "actions": [action_payload(a) for a in preview.actions],
    }
