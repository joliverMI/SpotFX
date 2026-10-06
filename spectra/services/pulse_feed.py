"""THE PULSE FEED — section intensity and tempo pushed into the one-colour
effect on the Singles (Pulse, fx/effects/pulse.py; single-led-power plan,
phase 2, approved by the Admiral 2026-10-05 "with all recommendations").

Pulse hears hits from live audio itself; what it cannot know is where the
SONG is: how intense this section is (which sets its resting level, how far
a hit lifts it and how fast a pulse fades) and how long a beat is (fades are
counted in beats). This module tells it, through the effect's two hooks,
`energy` (0..1) and `beat_ms` (0 = unknown, the effect then uses the live
pipeline's tempo). Charge/lull/drop are NOT here: they reach Pulse through
the shared phase keys like every phase effect (fx.device_model.
PHASE_EFFECTS, scene_response._drive_phase), on the same ramp the crystal
and strips get.

WHAT `energy` IS — the render intensity a section would fire at:
    energy = intensity_scale.combine_measured_and_scale(measured, factor)
  measured — the section's own intensity, per-song min-max stretched with
      the generator's floor and edge trim (midsong_generator.
      section_intensities), so every song spans its own calm-to-intense
      range: the SAME number a generated scene cue at that section carries.
  factor — the song's scaling factor (intensity_scale.song_scaling_factor:
      automatic up to 125%, or his per-track mark up to 200%).
  So it obeys his 0.75 automatic ceiling (HEADROOM_RESERVE): a section only
  reaches 1.0 — Pulse's "intense" end — on a track he has marked.
  A song with no analysis is fed NEUTRAL_ENERGY (0.5, the effect's own
  default and the bridge's down-degrade value) and beat_ms 0.

WHEN IT IS PUSHED — at section edges, eased by the effect itself:
  - every TICK_S the feed reads the song position (bridge.
    effective_position_ms, the position the trigger clock ticks on before
    the A/V lead — section intensity needs no lead: the effect eases each
    new value over its own ENERGY_SLEW_S, 2 s) and pushes ONLY a value that
    differs from what the virtual already carries — in practice once per
    section edge and once per song;
  - a scene fire that INSTALLS Pulse carries the values in its own write
    (overlay, called from scene_compiler.fire_scene), so a fresh instance
    is born at the section's energy instead of starting neutral and easing
    over;
  - "what the virtual carries" is the conductor's own baseline for it
    (VirtualState.param_baseline): a fire's write seeds it and every push
    moves it (conductor.on_surge), which is also what keeps the parameter
    watchdog in agreement — a pushed value IS the baseline, never an orphan.
  - while the conductor is deferred (preview, pause, dinner party, Ambient
    — bridge.conductor_deferral) nothing is pushed; it catches up after.

The section table is parsed ONCE per song, in a worker thread (a
.librosa.json is ~400 KB), never on the event loop per tick. His intensity
mark is read when a value is computed (a section edge), so a mark set
mid-song lands at the next edge.

Not here: the room's A/V lead (one application point, the trigger clock),
any write to a virtual not running a one-colour effect, and any light
decision — the effect owns every brightness."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fx import device_model

logger = logging.getLogger(__name__)

TICK_S = 0.25
"""How often the feed reads the song position. A section edge lands within
this of its moment; the effect then eases over 2 s."""

NEUTRAL_ENERGY = 0.5
"""Fed when the song has no section analysis: the effect's own default and
the bridge's neutral intensity when the music feed is down."""

ENERGY_EPSILON = 0.005
"""A computed energy closer than this to what the virtual carries is not
re-pushed (energies are rounded to 3 places)."""

BEAT_EPSILON_MS = 0.5

MAX_BEAT_MS = 4000.0
"""The top of Pulse's own `beat_ms` schema range."""


@dataclass(frozen=True)
class SongFeed:
    """One song's section table in SONG time (the capture offset applied),
    each section's measured intensity, and its beat length."""
    uri: str
    sections: tuple[tuple[int, int, float], ...] = ()
    beat_ms: float = 0.0
    offset_ms: int = 0

    def section_at(self, position_ms: int) -> Optional[int]:
        """Index of the section containing position_ms, else the nearest —
        analysis_reader.section_energy_at's own rule."""
        if not self.sections:
            return None
        for i, (start, end, _m) in enumerate(self.sections):
            if start <= position_ms < end:
                return i
        return min(range(len(self.sections)),
                   key=lambda i: min(abs(self.sections[i][0] - position_ms),
                                     abs(self.sections[i][1] - position_ms)))


def load_song(uri: str) -> SongFeed:
    """Parse one song's analysis into a SongFeed. BLOCKING (file reads):
    called in a worker thread by PulseFeed.prepare."""
    from spectra.services import analysis_reader, midsong_generator, testbed_audio
    with analysis_reader.memoized_reads():
        raw = analysis_reader.sections_for_uri(uri) or []
        bpm = analysis_reader.tempo_bpm_for_uri(uri)
    ordered = sorted((s for s in raw if isinstance(s, dict)),
                     key=lambda s: int(s.get("start_ms", 0) or 0))
    measured = midsong_generator.section_intensities(ordered)
    offset = testbed_audio.capture_offset_ms_or_zero(uri) if ordered else 0
    sections = tuple(
        (int(s.get("start_ms", 0) or 0) + offset,
         int(s.get("end_ms", 0) or 0) + offset, float(m))
        for s, m in zip(ordered, measured))
    # A tempo outside the effect's own beat_ms range (0..4000) would fail its
    # schema, and a write that fails validation is dropped whole — energy
    # with it. Such a read is unknown, which the effect already handles.
    beat_ms = round(60000.0 / bpm, 1) if bpm else 0.0
    if not 0.0 < beat_ms <= MAX_BEAT_MS:
        beat_ms = 0.0
    return SongFeed(uri=uri, sections=sections, beat_ms=beat_ms,
                    offset_ms=offset)


def _default_factor(uri: str, genres: list[str]) -> float:
    from spectra.services import intensity_scale
    return intensity_scale.song_scaling_factor(uri, genres)


def _render(measured: float, factor: float) -> float:
    from spectra.services import intensity_scale
    return intensity_scale.combine_measured_and_scale(measured, factor)


@dataclass
class _Computed:
    key: tuple
    values: dict[str, float]
    section: Optional[int]
    factor: Optional[float]
    measured: Optional[float]


@dataclass
class PulseFeed:
    loader: Callable[[str], SongFeed] = load_song
    factor: Callable[[str, list[str]], float] = _default_factor
    clock: Callable[[], float] = time.monotonic
    _song: Optional[SongFeed] = None
    _computed: Optional[_Computed] = None
    pushes: int = 0
    last_push: Optional[dict] = None
    deferred_by: Optional[str] = None
    last_error: Optional[str] = None

    def reset(self) -> None:
        """Forget the cached song and every counter (tests; a restart)."""
        self._song = None
        self._computed = None
        self.pushes = 0
        self.last_push = None
        self.deferred_by = None
        self.last_error = None

    # ── the song table ──────────────────────────────────────────────────

    def song(self, uri: Optional[str]) -> Optional[SongFeed]:
        """The cached table for `uri`, or None if it is not loaded yet."""
        if uri is not None and self._song is not None and self._song.uri == uri:
            return self._song
        return None

    async def prepare(self, uri: Optional[str]) -> Optional[SongFeed]:
        """Load `uri`'s table off the event loop (once per song)."""
        if uri is None:
            return None
        cached = self.song(uri)
        if cached is not None:
            return cached
        # No lock: two loads of one song (the track-change preload and a
        # tick) produce the same table, and a load that finishes after the
        # song changed again is simply a cache miss for the new song.
        try:
            song = await asyncio.to_thread(self.loader, uri)
        except Exception as exc:                         # noqa: BLE001
            logger.exception("pulse feed: analysis for %s unreadable — "
                             "feeding neutral", uri)
            self.last_error = f"analysis unreadable: {exc}"
            song = SongFeed(uri=uri)
        self._song = song
        self._computed = None
        return song

    # ── the values ──────────────────────────────────────────────────────

    def values(self, uri: Optional[str], position_ms: Optional[int],
               genres: Callable[[], list[str]] = lambda: []
               ) -> Optional[dict[str, float]]:
        """{"energy", "beat_ms"} for the song at position_ms, or None when it
        cannot be said yet (no song, no position, table not loaded)."""
        song = self.song(uri)
        if song is None or position_ms is None:
            return None
        index = song.section_at(int(position_ms))
        key = (song.uri, index)
        if self._computed is not None and self._computed.key == key:
            return dict(self._computed.values)
        if index is None:
            energy, factor, measured = NEUTRAL_ENERGY, None, None
        else:
            measured = song.sections[index][2]
            try:
                factor = float(self.factor(song.uri, genres()))
            except Exception:                            # noqa: BLE001
                logger.exception("pulse feed: scaling factor unreadable — 1.0")
                factor = 1.0
            energy = _render(measured, factor)
        values = {"energy": round(float(energy), 3),
                  "beat_ms": float(song.beat_ms)}
        self._computed = _Computed(key=key, values=values, section=index,
                                   factor=factor, measured=measured)
        return dict(values)

    @staticmethod
    def _differs(carried: Any, value: float, eps: float) -> bool:
        if not isinstance(carried, (int, float)) or isinstance(carried, bool):
            return True
        return abs(float(carried) - value) > eps

    def _patch(self, carried: dict, values: dict[str, float]) -> dict[str, float]:
        patch: dict[str, float] = {}
        if self._differs(carried.get("energy"), values["energy"], ENERGY_EPSILON):
            patch["energy"] = values["energy"]
        if self._differs(carried.get("beat_ms"), values["beat_ms"],
                         BEAT_EPSILON_MS):
            patch["beat_ms"] = values["beat_ms"]
        return patch

    # ── the two ways a value reaches the effect ─────────────────────────

    def overlay(self, writes: list[dict], uri: Optional[str],
                position_ms: Optional[int],
                genres: Callable[[], list[str]] = lambda: []) -> list[dict]:
        """A scene fire's writes with `energy`/`beat_ms` added to every
        one-colour effect's config, so the instance a fire creates starts
        where the song is. Never mutates the input (compile_scene shares one
        config dict across a category's virtuals); writes with no one-colour
        effect, or a song not known yet, come back unchanged — the tick
        pushes as soon as it can."""
        if not any(w.get("effect_type") in device_model.ONE_COLOUR_EFFECTS
                   for w in writes):
            return writes
        values = self.values(uri, position_ms, genres)
        if values is None:
            return writes
        out = []
        for w in writes:
            if w.get("effect_type") in device_model.ONE_COLOUR_EFFECTS:
                w = {**w, "config": {**w["config"], **values}}
            out.append(w)
        return out

    async def tick(self, uri: Optional[str], position_ms: Optional[int], *,
                   conductor, deferral: Optional[str] = None,
                   genres: Callable[[], list[str]] = lambda: []) -> int:
        """Push the current values to every one-colour virtual of the live
        scene whose carried values differ. Returns how many were written."""
        self.deferred_by = deferral
        if deferral is not None:
            return 0
        if uri is None or position_ms is None:
            return 0
        if not any(st.effect_type in device_model.ONE_COLOUR_EFFECTS
                   for st in conductor.virtuals.values()):
            return 0
        if self.song(uri) is None:
            await self.prepare(uri)
        values = self.values(uri, position_ms, genres)
        if values is None:
            return 0
        written = 0
        for vid in list(conductor.virtuals):
            state = conductor.virtuals.get(vid)
            # re-read each time: a scene fire between two awaits replaces
            # conductor.virtuals, and a stale effect type here would switch
            # the virtual back to Pulse
            if state is None or state.effect_type not in device_model.ONE_COLOUR_EFFECTS:
                continue
            patch = self._patch(state.param_baseline, values)
            if not patch:
                continue
            try:
                await conductor.executor.jump(vid, state.effect_type, patch)
            except Exception as exc:                     # noqa: BLE001
                logger.exception("pulse feed: push to %s failed", vid)
                self.last_error = f"push to {vid} failed: {exc}"
                continue
            if conductor.virtuals.get(vid) is state:
                conductor.on_surge({(vid, k): v for k, v in patch.items()})
            written += 1
            self.pushes += 1
            self.last_push = {"at": self.clock(), "virtual_id": vid,
                              "uri": uri, "position_ms": int(position_ms),
                              **patch}
        return written

    # ── status ──────────────────────────────────────────────────────────

    def status(self) -> dict:
        song = self._song
        comp = self._computed
        return {
            "uri": song.uri if song else None,
            "sections": len(song.sections) if song else 0,
            "beat_ms": song.beat_ms if song else None,
            "capture_offset_ms": song.offset_ms if song else None,
            "section": comp.section if comp else None,
            "measured": comp.measured if comp else None,
            "factor": comp.factor if comp else None,
            "values": dict(comp.values) if comp else None,
            "pushes": self.pushes,
            "last_push": self.last_push,
            "deferred_by": self.deferred_by,
            "last_error": self.last_error,
        }


feed = PulseFeed()
