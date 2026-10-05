"""THE LIGHT SHOW's HIGH and LOW TRIGGERS — ONE of each per song (the
Admiral, 2026-10-04, his answer to the plan's Q1: "ONE High and ONE Low
Trigger per song, at the biggest rise and biggest fall in section energy,
excluding the first and last 15 s"; plan: /home/javi/fleet-spotfx/data/
light-show-plan/report.md §6).

DERIVED AT PLAY TIME, NEVER STORED AS TRIGGERS. Only HIS MOVES are saved
(`storage/spectra/show_cues.json`, `{uri: {"high": {timestamp_ms, ...},
"low": {...}}}`). Storing the cues as rows in triggers.json was rejected in
the plan for three reasons that still hold: a human edit stamps a trigger
`source="authored"`, which under "My triggers only" would silence every
analysed scene change on that song; a stored row blocks auto-generation for
a song with none; and every write rewrites the whole ~9.5 MB file.

THE SCORE IS THE PLANNER'S. `midsong_generator.section_energy_shift` — the
signed form of the section-energy change the scene-change planner ranks by
— so "the biggest shift" means the same thing to a High Trigger and to the
top-ranked scene change. High = the largest RISE, Low = the largest FALL.

THE TIME IS THE PLANNER'S TOO. Each boundary sits at its PLACED time (edge,
then downbeat, then the WAV-time -> song-time frame shift) from
`plan_moments` — so a High lands on exactly the moment that boundary's scene
change or flare fires. A boundary the plan does not place (nothing should
miss, `claimed` is passed empty) falls back to its raw time + the capture
offset, the same frame shift.

EDGES. Any boundary placed inside the first or last EDGE_MS (15 s) of the
song is never a High or a Low (measured in the plan: without this, 30% of
Lows are the fade-out and 17% of Highs are the intro).

SEEDED FROM HIS OWN DROP MARKS (an approved add-on). A song where he has
hand-placed a drop (an authored `fire_response` trigger with
`event_class="drop"`, at its own timestamp + offset) gets its High ON that
mark: of several, the one sitting nearest the biggest rise (the largest rise
of any boundary within DROP_MATCH_MS of it), the earliest on a tie. A drop
mark inside the edges is ignored like anything else.

HIS MOVE ALWAYS WINS. A dragged position replaces both the automatic and the
drop-seeded one; one tap ("back to automatic") deletes the override. The
automatic position, the shift that put it there, and up to two ALTERNATES
(the runners-up) are always reported beside it, and `close` names a
runner-up within RUNNER_UP_FRACTION (10%) of the winner — on about a fifth
of his songs the automatic pick is a near-tie and the Timeline offers it.

CACHED PER SONG, re-derived on demand: `cues_for_song` is pure computation
over the analysis (worker-thread cost, like the analysed-flare plan);
`cached` answers instantly for the trigger engine's tick and schedules the
computation in a thread when the song is not cached yet. Any override write
or a song change invalidates.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from spectra import config

logger = logging.getLogger(__name__)

HIGH = "high"
LOW = "low"
LEVELS = (HIGH, LOW)

EDGE_MS = 15_000
"""His word: the first and last 15 s are never a High or a Low."""

RUNNER_UP_FRACTION = 0.10
"""A runner-up within 10% of the winner's shift is CLOSE — offered on the
Timeline as a one-tap alternative."""

MAX_ALTERNATES = 2

DROP_MATCH_MS = 4_000
"""How near a boundary must sit to one of his drop marks to lend it its
rise, when choosing among several drop marks (two bars at 120 bpm)."""


@dataclass
class Alternate:
    timestamp_ms: int
    shift: float
    close: bool


@dataclass
class Cue:
    level: str
    timestamp_ms: int
    #: auto | drop_mark | moved
    source: str
    shift: Optional[float] = None
    #: where the analysis puts it (the automatic pick), whatever wins
    auto_ms: Optional[int] = None
    auto_shift: Optional[float] = None
    #: his own drop mark the High was seeded from, if any
    drop_mark_ms: Optional[int] = None
    alternates: list[Alternate] = field(default_factory=list)
    #: a runner-up sits within RUNNER_UP_FRACTION of the winner
    runner_up_close: bool = False
    #: his dragged position, when there is one
    moved_ms: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SongCues:
    uri: str
    high: Optional[Cue] = None
    low: Optional[Cue] = None
    reason: Optional[str] = None
    duration_ms: Optional[int] = None

    def get(self, level: str) -> Optional[Cue]:
        return self.high if level == HIGH else self.low if level == LOW else None

    def as_dict(self) -> dict:
        return {"uri": self.uri, "reason": self.reason,
                "duration_ms": self.duration_ms,
                "high": self.high.as_dict() if self.high else None,
                "low": self.low.as_dict() if self.low else None}


# ── his moves (the only thing stored) ──────────────────────────────────────

_lock = threading.RLock()


def _read() -> dict:
    path = config.SHOW_CUES_FILE
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: unreadable cue overrides %s", path)
        return {}


def _write(data: dict) -> None:
    path = str(config.SHOW_CUES_FILE)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".show_cues", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def overrides_for(uri: str) -> dict:
    return dict(_read().get(uri) or {})


def set_override(uri: str, level: str, timestamp_ms: int) -> dict:
    """Save his dragged position for this song's High or Low."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    ts = int(timestamp_ms)
    if ts < 0:
        raise ValueError("a cue cannot sit before the song starts")
    with _lock:
        data = _read()
        song = dict(data.get(uri) or {})
        song[level] = {"timestamp_ms": ts, "set_ms": int(time.time() * 1000)}
        data[uri] = song
        _write(data)
    invalidate(uri)
    return song[level]


def clear_override(uri: str, level: str) -> bool:
    """One tap: back to automatic."""
    with _lock:
        data = _read()
        song = dict(data.get(uri) or {})
        if level not in song:
            return False
        song.pop(level)
        if song:
            data[uri] = song
        else:
            data.pop(uri, None)
        _write(data)
    invalidate(uri)
    return True


# ── derivation ─────────────────────────────────────────────────────────────

def _his_drop_marks(uri: str) -> list[int]:
    from spectra.services import trigger_store
    out = []
    for t in trigger_store.list_for_song(uri):
        a = t.action
        if (t.source == "authored" and t.enabled
                and getattr(a, "kind", None) == "fire_response"
                and getattr(a, "event_class", None) == "drop"):
            out.append(int(t.timestamp_ms + t.trigger_offset_ms))
    return sorted(out)


def _placed_times(uri: str) -> dict[str, int]:
    """generator_key -> placed song-time ms for EVERY boundary."""
    from spectra.services import midsong_generator
    plan = midsong_generator.plan_moments(uri, claimed=set())
    return {m.generator_key: int(m.timestamp_ms)
            for m in [*plan.kept, *plan.unselected, *plan.dropped]}


def _pick(cands: list[tuple[int, float]], level: str) -> tuple[Optional[tuple[int, float]], list[Alternate], bool]:
    """(winner, alternates, runner_up_close) among (ms, shift) candidates."""
    if level == HIGH:
        pool = [c for c in cands if c[1] > 0]
        pool.sort(key=lambda c: (-c[1], c[0]))
    else:
        pool = [c for c in cands if c[1] < 0]
        pool.sort(key=lambda c: (c[1], c[0]))
    if not pool:
        return None, [], False
    win = pool[0]
    mag = abs(win[1])
    alts = [Alternate(int(ms), round(sh, 4), abs(sh) >= mag * (1 - RUNNER_UP_FRACTION))
            for ms, sh in pool[1:1 + MAX_ALTERNATES]]
    return win, alts, any(a.close for a in alts)


def cues_for_song(uri: str, *, duration_ms: Optional[int] = None,
                  sections: Optional[list[dict]] = None,
                  placed: Optional[dict[str, int]] = None,
                  offset_ms: Optional[int] = None,
                  drop_marks: Optional[list[int]] = None,
                  overrides: Optional[dict] = None) -> SongCues:
    """This song's High and Low (every keyword is an injection seam for
    tests; omitted, each is read from the live analysis/stores)."""
    from spectra.services import analysis_reader, midsong_generator, testbed_audio
    if sections is None:
        sections = analysis_reader.sections_for_uri(uri) or []
    ordered = sorted(sections, key=lambda s: int(s.get("start_ms", 0)))
    out = SongCues(uri=uri)
    if overrides is None:
        overrides = overrides_for(uri)
    if len(ordered) < 2 and not overrides:
        out.reason = "no section analysis for this song yet"
        return out
    if offset_ms is None:
        offset_ms = testbed_audio.capture_offset_ms_or_zero(uri)
    if duration_ms is None:
        duration_ms = max((int(s.get("end_ms", 0)) for s in ordered), default=0) + int(offset_ms)
    out.duration_ms = int(duration_ms)
    if placed is None:
        try:
            placed = _placed_times(uri) if len(ordered) >= 2 else {}
        except Exception:                                # noqa: BLE001
            logger.exception("light show: placement failed for %s; raw times used", uri)
            placed = {}
    shifts = midsong_generator.section_energy_shift(ordered)
    cands: list[tuple[int, float]] = []
    for sec, sh in zip(ordered[1:], shifts[1:]):
        raw = int(sec.get("start_ms", 0))
        if raw <= 0:
            continue
        ms = placed.get(f"section:{raw}", raw + int(offset_ms))
        if ms < EDGE_MS or ms > duration_ms - EDGE_MS:
            continue
        cands.append((int(ms), float(sh)))
    if drop_marks is None:
        try:
            drop_marks = _his_drop_marks(uri)
        except Exception:                                # noqa: BLE001
            drop_marks = []
    drops = [d for d in drop_marks if EDGE_MS <= d <= duration_ms - EDGE_MS]

    for level in LEVELS:
        win, alts, close = _pick(cands, level)
        cue: Optional[Cue] = None
        if win is not None:
            cue = Cue(level=level, timestamp_ms=win[0], source="auto",
                      shift=round(win[1], 4), auto_ms=win[0],
                      auto_shift=round(win[1], 4), alternates=alts,
                      runner_up_close=close)
        if level == HIGH and drops:
            def lift(d: int) -> float:
                near = [sh for ms, sh in cands if abs(ms - d) <= DROP_MATCH_MS and sh > 0]
                return max(near, default=0.0)
            best = sorted(drops, key=lambda d: (-lift(d), d))[0]
            if cue is None:
                cue = Cue(level=level, timestamp_ms=best, source="drop_mark")
            cue.timestamp_ms = best
            cue.source = "drop_mark"
            cue.drop_mark_ms = best
            cue.shift = round(lift(best), 4) or None
        ov = overrides.get(level) if isinstance(overrides, dict) else None
        if isinstance(ov, dict) and isinstance(ov.get("timestamp_ms"), (int, float)):
            ms = int(ov["timestamp_ms"])
            if cue is None:
                cue = Cue(level=level, timestamp_ms=ms, source="moved")
            cue.timestamp_ms = ms
            cue.source = "moved"
            cue.moved_ms = ms
        setattr(out, level, cue)
    if out.high is None and out.low is None:
        out.reason = ("no rise or fall in section energy outside the first "
                      "and last 15 s")
    return out


# ── the cache the trigger clock reads ──────────────────────────────────────

_cache: dict[str, SongCues] = {}
_computing: set[str] = set()
_generation = 0


CACHE_SONGS = 16


def _store(uri: str, cues: SongCues) -> None:
    _cache.pop(uri, None)
    _cache[uri] = cues
    while len(_cache) > CACHE_SONGS:
        _cache.pop(next(iter(_cache)))


def invalidate(uri: Optional[str] = None) -> None:
    global _generation
    _generation += 1
    if uri is None:
        _cache.clear()
    else:
        _cache.pop(uri, None)


def cached(uri: Optional[str]) -> Optional[SongCues]:
    """The cues for `uri` if computed; otherwise schedule the computation
    (off the event loop) and return None. Never blocks."""
    if not uri:
        return None
    hit = _cache.get(uri)
    if hit is not None:
        return hit
    if uri not in _computing:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        _computing.add(uri)
        gen = _generation

        async def compute():
            try:
                result = await asyncio.to_thread(cues_for_song, uri)
                if gen == _generation:
                    _store(uri, result)
                else:                                    # invalidated mid-flight
                    _cache.pop(uri, None)
            except Exception:                            # noqa: BLE001
                logger.exception("light show: cue derivation failed for %s", uri)
                _store(uri, SongCues(uri=uri, reason="the cue derivation failed"))
            finally:
                _computing.discard(uri)
        loop.create_task(compute())
    return None


def get_or_compute(uri: str) -> SongCues:
    """Synchronous read-through (call it off the event loop): the cached
    cues, or compute and cache them now."""
    hit = _cache.get(uri)
    if hit is not None:
        return hit
    gen = _generation
    result = cues_for_song(uri)
    if gen == _generation:
        _store(uri, result)
    return result


def reset() -> None:
    """Tests."""
    invalidate()
    _computing.clear()
