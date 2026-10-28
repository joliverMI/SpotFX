"""THE FIRE MOMENT (2026-10-28 — the Drops panel proposal's Q4: the Home
Drops panel's countdown, and the top bar's next-event box for a drop, count
to "the moment it fires: mark + drop timing").

  1. drop_timing.fire_moment_ms is ONE definition: the mark, the drop band's
     offset and the drop timing offset (clamped against its build) — the
     same three terms trigger_engine.tick() sums into a drop's target.
     drop_timing.his_fire_moment_ms is the twin for one of HIS OWN authored
     drop triggers, whose stored "fires at" moment (and its lull/charge's)
     is already offset-inclusive (SpectraTrigger.trigger_offset_ms folded
     in) — the clamp must run against the RAW stored timestamps, never
     those, or a nonzero trigger_offset_ms silently double-counts inside
     the clamp floor.
  2. PROVED FROM THE SHOW SIDE: TriggerEngine.drop_fire_ms/his_drop_fire_ms
     name exactly the position the real swept tick() fires the drop at — a
     stored drop of his (offsets and a clamped shift included) and a
     drop-sequence member alike.
  3. drop_firing.annotate stamps `fire_ms` on every listed sequence and on
     his own rows (the latter through the separate `his_fire_ms`/
     HisFireMoment callable, for the same raw-vs-offset-inclusive reason);
     annotated_view reads the room's live offset; GET /api/upcoming carries
     it on drop events beside the unmoved `ms`.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.trigger import FireResponseAction, SpectraTrigger
from spectra.services import drop_firing, drop_sequences, drop_timing
from spectra.services.trigger_engine import TriggerEngine

pytestmark = pytest.mark.drop_timing_live

URI = "spotify:track:dropfiremoment"


# ── 1. the one definition ─────────────────────────────────────────────────

def test_the_fire_moment_is_the_mark_plus_band_plus_clamped_offset():
    assert drop_timing.fire_moment_ms(10_000, -400) == 9_600
    assert drop_timing.fire_moment_ms(10_000, -100, 7_000) == 9_900
    assert drop_timing.fire_moment_ms(10_000, -400, 7_000, band_offset_ms=-50) == 9_550
    # a lull 300 ms ahead: the clamp holds the drop after its build
    assert drop_timing.fire_moment_ms(10_000, -400, 9_700) == 9_700 + drop_timing.MIN_BUILD_MS
    assert drop_timing.fire_moment_ms(10_000, 0) == 10_000


def test_his_fire_moment_ms_clamps_against_raw_timestamps_not_offset_inclusive_ones():
    # his drop's own fires-at is 10_000 (raw) + 150 (its own offset) =
    # 10_150; his lull's is 9_700 (raw) + -80 (its own offset) = 9_620. A
    # -400 drop timing offset clamps against the RAW gap (10_000 vs
    # 9_700 + MIN_BUILD_MS = 9_800), never the offset-inclusive one.
    assert drop_timing.his_fire_moment_ms(
        10_150, 150, -400, build_timestamp_ms=9_620, build_trigger_offset_ms=-80) == 9_950
    # naively feeding the offset-inclusive marks into fire_moment_ms (as if
    # they were raw) clamps against the WRONG gap and gets a different,
    # wrong answer — the divergence this helper exists to close
    assert drop_timing.fire_moment_ms(10_150, -400, 9_620) == 9_750
    # with no trigger_offset_ms anywhere the two formulas agree (the common,
    # unclamped-or-offset-free case — every one of his drops until now)
    assert (drop_timing.his_fire_moment_ms(10_000, 0, -400, build_timestamp_ms=9_700)
            == drop_timing.fire_moment_ms(10_000, -400, 9_700))


# ── 2. from the show side ─────────────────────────────────────────────────

class _Rec:
    def __init__(self):
        self.position = 0
        self.resp: list[tuple] = []
        self.seq: list[tuple] = []

    async def fire_response(self, cls, intensity, gap=None):
        self.resp.append((self.position, cls))

    async def fire_sequence(self, cls, intensity, gap):
        self.seq.append((self.position, cls))


async def _noop(_uri):
    return None


def _engine(triggers, rec, *, offset, band, view=None):
    kw = {}
    if view is not None:
        kw.update(drop_view=lambda uri, trigs: view, drop_revision=lambda: 0)
    return TriggerEngine(
        list_triggers=lambda uri: list(triggers),
        scene_change_mode=lambda: "full" if view is None else "analysed",
        fire_response=rec.fire_response, fire_sequence=rec.fire_sequence,
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: band, drop_offset_ms=lambda: offset,
        sequencer_enabled=lambda: False, transition_intensity=lambda: 0.5,
        select_scene=lambda i: "S", auto_generate=_noop, auto_refresh=_noop, **kw)


def _sweep(engine, rec, stop, step=10):
    async def run():
        await engine.on_track_state(URI)
        for pos in range(0, stop + step, step):
            rec.position = pos
            await engine.tick(pos)
    asyncio.run(run())


@pytest.mark.parametrize("offset,band", [(-400, 0), (-100, -50), (0, 0), (250, 0)])
def test_drop_fire_ms_names_where_tick_fires_his_stored_drop(offset, band):
    rec = _Rec()
    trig = SpectraTrigger(id="d", timestamp_ms=10_000, source="authored",
                          action=FireResponseAction(event_class="drop", intensity=0.8))
    engine = _engine([trig], rec, offset=offset, band=band)
    predicted = engine.drop_fire_ms(10_000, 0.8, None)
    _sweep(engine, rec, 12_000)
    fired = [p for p, c in rec.resp if c == "drop"]
    assert fired == [predicted]
    assert predicted == 10_000 + band + offset


def test_his_drop_fire_ms_matches_tick_when_offsets_and_clamp_both_apply():
    """A nonzero trigger_offset_ms on the drop AND its own lull, with the
    drop timing offset actually clamped against the lull's build — the
    exact shape that silently diverged before his_drop_fire_ms existed
    (the Drops panel's countdown must never re-derive the fire moment from
    the offset-inclusive marks alone)."""
    rec = _Rec()
    lull = SpectraTrigger(id="l", timestamp_ms=9_700, trigger_offset_ms=-80,
                          source="authored",
                          action=FireResponseAction(event_class="lull", intensity=0.5))
    drop = SpectraTrigger(id="d", timestamp_ms=10_000, trigger_offset_ms=150,
                          source="authored",
                          action=FireResponseAction(event_class="drop", intensity=0.8))
    engine = _engine([lull, drop], rec, offset=-400, band=0)
    drop_display_ms = drop.timestamp_ms + drop.trigger_offset_ms
    lull_display_ms = lull.timestamp_ms + lull.trigger_offset_ms
    predicted = engine.his_drop_fire_ms(
        drop_display_ms, drop.trigger_offset_ms, 0.8,
        lull_display_ms, lull.trigger_offset_ms)
    _sweep(engine, rec, 12_000)
    fired = [p for p, c in rec.resp if c == "drop"]
    assert fired == [predicted] == [9_950]
    # the naive FireMoment path (what the yours-row display used before
    # his_drop_fire_ms existed) disagrees — proving the divergence is real
    naive = engine.drop_fire_ms(drop_display_ms, 0.8, lull_display_ms)
    assert naive != fired[0]


def test_drop_fire_ms_names_where_tick_fires_a_sequence_drop():
    view = {"uri": URI, "song": {"beat_ms": 500.0},
            "sequences": [{"key": "drop:10000", "state": "confident", "origin": "detected",
                           "tier": "confident", "drop_ms": 10_000, "lull_ms": 7_000,
                           "charge_ms": 3_000, "step": 0.8}],
            "authored": [], "authored_lone": []}
    rec = _Rec()
    engine = _engine([], rec, offset=-100, band=0, view=view)
    seq = drop_firing.firing_sequences(view)[0]
    annotated = drop_firing.annotate(
        view, "analysed", False,
        fire_ms=lambda d, i, s: engine.drop_fire_ms(d, i, s))
    s = annotated["sequences"][0]
    assert s["fire_ms"] == engine.drop_fire_ms(10_000, seq.intensity, seq.build_start_ms("analysed"))
    _sweep(engine, rec, 12_000)
    assert [p for p, c in rec.seq if c == "drop"] == [s["fire_ms"]] == [9_900]


# ── 3. annotate, annotated_view, upcoming ─────────────────────────────────

def test_annotate_stamps_every_listed_sequence_and_his_rows():
    view = {"uri": URI, "song": {"beat_ms": 500.0}, "authored": [], "authored_lone": [],
            "sequences": [
                {"key": "drop:10000", "state": "confident", "origin": "detected",
                 "tier": "confident", "drop_ms": 10_000, "lull_ms": 7_000, "charge_ms": None},
                {"key": "drop:20000", "state": "suggested", "origin": "detected",
                 "tier": "suggested", "drop_ms": 20_000, "lull_ms": None, "charge_ms": None},
                {"key": "drop:30000", "state": "dismissed", "origin": "detected",
                 "tier": "suggested", "drop_ms": 30_000, "lull_ms": None, "charge_ms": None}],
            "yours": [{"key": "his:h", "charge": None,
                       "lull": {"id": "hl", "timestamp_ms": 37_000, "enabled": True},
                       "drop": {"id": "h", "timestamp_ms": 40_000, "enabled": True},
                       "enabled": True, "detections": [], "detection": None}]}
    seen = []
    his_seen = []

    def fire(d, i, s):
        seen.append((d, i, s))
        return d - 100

    def his_fire(ts, toff, i, bts, boff):
        his_seen.append((ts, toff, i, bts, boff))
        return ts - 100

    out = drop_firing.annotate(view, "analysed", False, fire_ms=fire, his_fire_ms=his_fire,
                               his_intensity={"h": 0.9})
    by = {s["key"]: s for s in out["sequences"]}
    assert by["drop:10000"]["fire_ms"] == 9_900
    assert by["drop:20000"]["fire_ms"] == 19_900       # a suggestion too (Testing may fire it)
    assert "fire_ms" not in by["drop:30000"]            # a removed drop has no moment
    assert out["yours"][0]["fire_ms"] == 39_900
    # his drop: its own offset-inclusive timestamp/offset, intensity, and his lull's
    assert (40_000, 0, 0.9, 37_000, 0) in his_seen
    # without a reader: the mark (bare), the offset-inclusive one for yours
    bare = drop_firing.annotate(view, "analysed", False)
    assert {s["key"]: s.get("fire_ms") for s in bare["sequences"]}["drop:10000"] == 10_000
    assert bare["yours"][0]["fire_ms"] == 40_000


def test_annotate_yours_row_fire_ms_matches_tick_with_offsets_and_clamp():
    """The real drop_sequences.yours_rows grouping, through annotate()'s
    actual HisFireMoment wiring, against a real swept tick() — proof the
    Drops panel's own display path (not just the pure helper) lands on the
    moment the room actually fires his drop at, offsets and clamp alike."""
    rec = _Rec()
    lull = SpectraTrigger(id="l", timestamp_ms=9_700, trigger_offset_ms=-80,
                          source="authored",
                          action=FireResponseAction(event_class="lull", intensity=0.5))
    drop = SpectraTrigger(id="d", timestamp_ms=10_000, trigger_offset_ms=150,
                          source="authored",
                          action=FireResponseAction(event_class="drop", intensity=0.8))
    engine = _engine([lull, drop], rec, offset=-400, band=0)
    _sweep(engine, rec, 12_000)
    fired = [p for p, c in rec.resp if c == "drop"]
    assert fired == [9_950]

    rows = drop_sequences.yours_rows([lull, drop], [])
    view = {"uri": URI, "yours": rows}
    out = drop_firing.annotate(
        view, "full", True,
        his_fire_ms=lambda ts, toff, i, bts, boff: engine.his_drop_fire_ms(
            ts, toff, i, bts, boff),
        his_intensity={"d": 0.8})
    assert out["yours"][0]["fire_ms"] == fired[0] == 9_950


@pytest.fixture
def _store(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import drop_sequences as ds
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "DROP_SEQUENCES_FILE", tmp_path / "drop_sequences.json")
    ds.reset()

    def fn(entry):
        entry["detected"] = {
            "uri": URI, "detector_version": "x", "confident_score": 1.0,
            "suggested_score": 0.7, "tempo_bpm": 120.0, "beat_ms": 500.0,
            "captured_from_ms": 0, "captured_to_ms": 200_000, "duration_ms": 200_000,
            "stamp": "t",
            "sequences": [{"key": "drop:44000", "drop_ms": 44_000, "lull_ms": 40_000,
                           "charge_ms": 35_000, "score": 1.2, "tier": "confident",
                           "step": 1.0, "notes": []}],
            "excluded": []}
    ds._mutate(URI, fn)
    yield
    ds.reset()


def test_annotated_view_reads_the_rooms_live_drop_timing(_store, monkeypatch):
    from spectra.services import room_controls
    from spectra.services.trigger_engine import trigger_engine
    room_controls.save_room_controls(room_controls.RoomControlState(drop_timing_offset_ms=-100))
    monkeypatch.setattr(trigger_engine, "_response_offset_ms", lambda a: 0)
    monkeypatch.setattr(TriggerEngine, "_active_scene", staticmethod(lambda: None))
    v = drop_firing.annotated_view(URI)
    assert v["sequences"][0]["fire_ms"] == 43_900


def test_upcoming_drop_events_carry_fire_ms_beside_the_unmoved_mark(_store, monkeypatch):
    from spectra.api import upcoming
    from spectra.services import room_controls
    from spectra.services.trigger_engine import trigger_engine
    room_controls.save_room_controls(room_controls.RoomControlState(
        drop_timing_offset_ms=-100, scene_change_mode="analysed"))
    monkeypatch.setattr(trigger_engine, "_response_offset_ms", lambda a: 0)
    monkeypatch.setattr(TriggerEngine, "_active_scene", staticmethod(lambda: None))
    events = upcoming.upcoming_for_song(URI)["events"]
    drops = [e for e in events if e["kind"] == "drop"]
    assert drops and drops[0]["ms"] == 44_000 and drops[0]["fire_ms"] == 43_900
    assert all("fire_ms" not in e for e in events if e["kind"] != "drop")
