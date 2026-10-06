"""THE PHASE PARTNER RULE — a charge builds to its own lull or drop, a lull
to its own drop, whatever sits between (drop-detection plan phase 1;
spectra/services/phase_partner.py is the binding statement).

Four layers, each held separately:

  1. The pure rule (phase_partner.build_target): partner selection, the
     restart case, the 60 s reach, and the no-partner fallback.
  2. The firing path (TriggerEngine._phase_partner_gap_ms through tick()):
     the four cases the build was asked to prove — a flare inside a charge,
     a scene change inside a charge, a lull with an intervening flare, and
     no partner ahead — plus the mode gate on the partner itself.
  3. The LIGHT: tick() → the real ResponseEngine → the real vendored
     blackhole on fx.headless. A flare inside a charge no longer makes the
     build peak at the flare; it is still mid-build there and reaches full
     ~90% of the way to its own drop.
  4. The drop-sequence preview lays its gaps out as partner gaps.

No live storage is read or written.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless  # noqa: E402
from fx.effects.particle_handoff import PHASE_HOLD_MAX_S  # noqa: E402
from spectra.models.trigger import (FireResponseAction, FireSceneAction,  # noqa: E402
                                    SelectColorSetAction, SpectraTrigger)
from spectra.services import phase_partner as pp  # noqa: E402
from test_spectra_engine import (VID, _categories_fixture, _engine, _fire,  # noqa: E402
                                 _host, _run)


# ── 1. the pure rule ─────────────────────────────────────────────────────────

def test_a_charge_builds_to_its_own_drop_past_a_flare():
    t = pp.build_target("charge", 1000, [(3000, None), (9000, "drop")])
    assert (t.ms, t.reason, t.target_class) == (9000, pp.TARGET_PARTNER, "drop")
    assert t.gap_ms(1000) == 8000


def test_a_charge_builds_to_its_own_lull_past_a_scene_change():
    t = pp.build_target("charge", 1000, [(2500, None), (6000, "lull"),
                                         (7000, "drop")])
    assert (t.ms, t.reason, t.target_class) == (6000, pp.TARGET_PARTNER, "lull")


def test_a_lull_builds_to_its_own_drop_past_a_flare():
    t = pp.build_target("lull", 2000, [(2500, None), (4000, "drop")])
    assert (t.ms, t.reason, t.target_class) == (4000, pp.TARGET_PARTNER, "drop")


def test_no_partner_ahead_keeps_the_next_trigger():
    """A charge he uses as its own effect builds into the next flare,
    exactly as it did before the rule."""
    t = pp.build_target("charge", 1000, [(3000, None), (8000, None)])
    assert (t.ms, t.reason, t.target_class) == (3000, pp.TARGET_NEXT_TRIGGER, None)
    nothing = pp.build_target("charge", 1000, [])
    assert (nothing.ms, nothing.reason) == (None, pp.TARGET_NONE)
    assert nothing.gap_ms(1000) is None


def test_a_later_charge_is_a_restart_not_a_partner():
    """A second charge rewrites phase_progress to 0 itself, so the first
    build ends there whatever comes after — reaching past it to the drop
    would cut the build mid-ramp. The pre-rule answer stands."""
    t = pp.build_target("charge", 1000, [(2000, None), (5000, "charge"),
                                         (9000, "drop")])
    assert (t.ms, t.reason) == (2000, pp.TARGET_NEXT_TRIGGER)
    direct = pp.build_target("charge", 1000, [(5000, "charge"), (9000, "drop")])
    assert (direct.ms, direct.reason, direct.target_class) == \
        (5000, pp.TARGET_NEXT_TRIGGER, "charge")
    # a lull is restarted by a charge or another lull, never built past them
    for restart in ("charge", "lull"):
        lt = pp.build_target("lull", 1000, [(1500, None), (2000, restart),
                                            (3000, "drop")])
        assert (lt.ms, lt.reason) == (1500, pp.TARGET_NEXT_TRIGGER), restart


def test_the_reach_is_the_effects_own_charge_cap():
    assert pp.PARTNER_REACH_MS == round(PHASE_HOLD_MAX_S * 1000) == 60_000
    at = pp.build_target("charge", 0, [(5000, None), (60_000, "drop")])
    assert (at.ms, at.reason) == (60_000, pp.TARGET_PARTNER)
    past = pp.build_target("charge", 0, [(5000, None), (60_001, "drop")])
    assert (past.ms, past.reason) == (5000, pp.TARGET_NEXT_TRIGGER), \
        "a partner past the reach is no partner — the pre-rule gap stands"
    alone = pp.build_target("charge", 0, [(70_000, "drop")])
    assert (alone.ms, alone.reason) == (70_000, pp.TARGET_NEXT_TRIGGER), \
        "with nothing between, the far drop is still the next trigger, as before"


def test_drop_has_no_build_target_and_input_order_does_not_matter():
    assert pp.build_target("drop", 0, [(1000, None)]).reason == pp.TARGET_NONE
    t = pp.build_target("charge", 5000, [(9000, "drop"), (1000, "lull"),
                                         (5000, "lull"), (6000, None)])
    assert (t.ms, t.reason) == (9000, pp.TARGET_PARTNER), \
        "entries at or before the charge are ignored; order is irrelevant"


def test_partner_rule_classes():
    assert pp.is_partner("charge", "lull") and pp.is_partner("charge", "drop")
    assert pp.is_partner("lull", "drop")
    assert not pp.is_partner("charge", "charge")
    assert not pp.is_partner("lull", "lull") and not pp.is_partner("lull", "charge")
    assert not pp.is_partner("drop", "drop") and not pp.is_partner("charge", None)


# ── 2. the firing path ───────────────────────────────────────────────────────

def _resp(ms, cls, *, source="authored", enabled=True):
    return SpectraTrigger(timestamp_ms=ms, source=source, enabled=enabled,
                          action=FireResponseAction(event_class=cls, intensity=0.5))


def _drive(song: list[SpectraTrigger], *, mode: str = "triggers_only",
           end_ms: int = 80_000) -> list[tuple[str, int, int | None]]:
    """Every fire_response the engine makes over the song, as (class,
    stored timestamp, gap_ms) — ticked every 100 ms like the real poll."""
    from spectra.services.trigger_engine import TriggerEngine

    calls: list[tuple[str, int | None]] = []

    async def fire_response(event_class, intensity, gap_ms=None):
        calls.append((event_class, gap_ms))

    async def noop(*_a, **_k):
        return None

    async def main():
        engine = TriggerEngine(
            list_triggers=lambda uri: song, fire_response=fire_response,
            fire_scene=noop, select_color_set=noop,
            select_scene=lambda _i: "scene-x",
            render_intensity=lambda x: x, scene_change_mode=lambda: mode,
            lead_ms=lambda _t: 0, response_offset_ms=lambda _a: 0)
        await engine.on_track_state("song:partner")
        for pos in range(0, end_ms + 1, 100):
            await engine.tick(pos)

    _run(main())
    ts = iter(sorted(t.timestamp_ms for t in song
                     if t.enabled and t.action.kind == "fire_response"))
    return [(cls, next(ts), gap) for cls, gap in calls]


def test_engine_a_flare_inside_a_charge_no_longer_ends_the_build():
    song = [_resp(1000, "charge"), _resp(3000, "flare"),
            _resp(8000, "lull"), _resp(9000, "drop")]
    got = _drive(song)
    assert got == [("charge", 1000, 7000), ("flare", 3000, None),
                   ("lull", 8000, 1000), ("drop", 9000, None)], \
        "the charge builds 7000 ms to its own lull, not 2000 ms to the flare"


def test_engine_a_scene_change_inside_a_charge_no_longer_ends_the_build():
    for mode in ("triggers_only", "full"):
        song = [_resp(1000, "charge"),
                SpectraTrigger(timestamp_ms=3500,
                               action=FireSceneAction(scene_id="scene-x")),
                SpectraTrigger(timestamp_ms=4500, source="generated",
                               action=FireSceneAction(scene_id=None)),
                _resp(7000, "drop")]
        got = _drive(song, mode=mode)
        assert got == [("charge", 1000, 6000), ("drop", 7000, None)], mode


def test_engine_a_lull_with_an_intervening_flare_builds_to_its_drop():
    song = [_resp(2000, "lull"), _resp(2500, "flare"),
            SpectraTrigger(timestamp_ms=3000,
                           action=SelectColorSetAction(set_id="set-a")),
            _resp(4000, "drop")]
    got = _drive(song)
    assert got[0] == ("lull", 2000, 2000), \
        "the lull hangs 10% of the 2000 ms gap before its own drop, past " \
        "the flare and the colour change"


def test_engine_no_partner_ahead_keeps_the_pre_rule_gap():
    lone = [_resp(1000, "charge"), _resp(3000, "flare"), _resp(5000, "flare")]
    assert _drive(lone)[0] == ("charge", 1000, 2000), \
        "a lone charge still builds into the next flare, as before"
    last = [_resp(1000, "charge")]
    assert _drive(last) == [("charge", 1000, None)], \
        "nothing ahead: no gap, so the flat class default"
    restarted = [_resp(1000, "charge"), _resp(2500, "flare"),
                 _resp(4000, "charge"), _resp(6000, "drop")]
    assert _drive(restarted)[:2] == [("charge", 1000, 1500), ("flare", 2500, None)], \
        "a charge restarted by a later charge keeps the pre-rule gap"
    far = [_resp(1000, "charge"), _resp(5000, "flare"), _resp(70_000, "drop")]
    assert _drive(far)[0] == ("charge", 1000, 4000), \
        "a partner past the 60 s reach is no partner"


def test_engine_a_partner_must_be_one_that_fires():
    """Disabled and mode-muted phase triggers are no partner — the rule
    keeps the engine's 'will actually fire' gate exactly as before."""
    song = [_resp(1000, "charge"), _resp(2000, "flare"),
            _resp(3000, "lull", enabled=False),
            _resp(4000, "drop", source="generated"),
            _resp(6000, "drop")]
    assert _drive(song, mode="triggers_only")[0] == ("charge", 1000, 5000)
    assert _drive(song, mode="full")[0] == ("charge", 1000, 3000)


# ── 3. the light: a flare inside a charge, on the real phase machinery ──────

def test_a_flare_inside_a_charge_no_longer_peaks_the_build_on_the_light(tmp_path):
    """tick() hands the partner gap to the REAL ResponseEngine, which drives
    the vendored blackhole's phase_progress. Charge at 1000 ms, a flare at
    2000 ms, the drop at 6000 ms. Before the rule the build ran 900 ms to the
    flare and sat at full for four seconds; now it is still building when
    the flare lands, reaches full ~90% of the way to its own drop, and hangs
    there until the drop."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Partnered", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="blackhole",
        params={})])
    song = [_resp(1000, "charge"), _resp(2000, "flare"), _resp(6000, "drop")]

    async def main():
        host, virtual = await _host(tmp_path, "partner")
        try:
            with headless.fake_clock() as clock:
                config: dict = {}
                effect = headless.attach_effect(host, virtual, "blackhole", config)
                _executor, conductor, responder, _room = _engine(clock)
                _fire(conductor, scene, config)
                records: dict[str, dict] = {}

                async def fire_response(event_class, intensity, gap_ms=None):
                    records[event_class] = await responder.on_event(
                        event_class, intensity, gap_ms)

                engine = TriggerEngine(
                    list_triggers=lambda uri: song, fire_response=fire_response,
                    render_intensity=lambda x: x,
                    scene_change_mode=lambda: "triggers_only",
                    lead_ms=lambda _t: 0, response_offset_ms=lambda _a: 0)
                await engine.on_track_state("song:light")

                async def play_to(pos_ms: int, step_ms: int = 50) -> None:
                    pos = play_to.at
                    while pos < pos_ms:
                        pos = min(pos_ms, pos + step_ms)
                        await engine.tick(pos)
                        headless.render_frames(virtual, 3, clock=clock, dt=step_ms / 3000)
                    play_to.at = pos
                play_to.at = 0

                await play_to(1000)
                assert records["charge"]["phase"]["gap_ms"] == 5000
                assert records["charge"]["phase"]["ramp_ms"] == 4500
                assert effect._phase == "charge"

                await play_to(2000)          # the flare lands
                assert "flare" in records
                at_flare = float(effect._config["phase_progress"])
                assert 0.1 < at_flare < 0.4, \
                    f"still building at the flare ({at_flare:.2f}), not peaked"
                assert effect._phase == "charge"

                await play_to(5600)          # past 90% of the way to the drop (5500)
                assert float(effect._config["phase_progress"]) == pytest.approx(1.0)
                assert effect._phase == "charge", "hanging at full, waiting"

                await play_to(6000)
                assert records["drop"]["phase"]["ramp_ms"] == 400
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 4. the drop-sequence preview's gaps are partner gaps ─────────────────────

def test_the_sequence_preview_lays_out_partner_gaps():
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import phase_preview

    scene = SceneV2(name="Preview", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="blackhole", params={})])
    tl = asyncio.run(phase_preview.build_timeline(
        scene, 0.6, gaps={"charge": 7000, "lull": 1500}))
    slots = [(m["slot_ms"], m["event_class"]) for m in tl["marks"]]
    for m in tl["marks"]:
        if m["event_class"] == "drop":
            continue
        target = pp.build_target(m["event_class"], m["slot_ms"],
                                 [s for s in slots if s[0] != m["slot_ms"]])
        assert target.reason == pp.TARGET_PARTNER
        assert target.gap_ms(m["slot_ms"]) == m["gap_ms"], m["event_class"]


# ── 5. the library script runs, against a synthetic store ───────────────────

def test_the_library_script_lists_exactly_the_partner_changes(tmp_path):
    """scripts/check_phase_partner_library.py asks the PRE-RULE engine (loaded
    out of git) and the current one about the same store. On a synthetic
    store it must list the sequence charge a flare used to cut short and
    leave the lone charge alone."""
    import json
    import subprocess

    repo = Path(__file__).resolve().parent.parent
    storage = tmp_path / "storage"
    (storage / "spectra").mkdir(parents=True)
    rows = [t.model_dump(mode="json") for t in (
        _resp(10_000, "charge"), _resp(12_000, "flare"), _resp(16_000, "drop"),
        _resp(40_000, "charge"), _resp(43_000, "flare"))]
    (storage / "spectra" / "triggers.json").write_text(
        json.dumps({"spotify:track:synthetic": rows}))
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_phase_partner_library.py"),
         "--storage", str(storage), "--mode", "triggers_only"],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "builds that change: 1 charges, 0 lulls, on 1 songs" in out, out
    assert "old:   1800 ms to flare" in out and "new:   5400 ms to drop" in out, out
    assert "1 have no partner ahead and keep the old next-trigger build" in out, out
