"""THE PHASE GRAMMAR (fx/effects/phase_grammar.py) — the drop's SHOCKWAVE and
the lull's BREATH-HOLD (transitions-drop plan, phase 1).

His rulings this holds: the wave is born on "the perimeter of the eye, not
the center of the screen"; "don't do the shockwave for fireworks"; no white
in the drop ("adding more color, increasing the brightness of the colors,
and having more baseline effects"); Q2 "a 0.4 s true black just before the
drop, as a setting".

- the pure curves and keys (the breath stays inside the lull's dark rule, 0
  when the gap is unknowable; the lean never leaves the colour set);
- the painter: a solid colour set's overlay is that colour scaled, never
  white; the wave starts on the rim and reaches the wall later;
- membership: DROP_SHOCK_EFFECTS is exactly the classes that opt in, never
  Fireworks, and every member is told the drop's intensity;
- the registry: every Shockwave setting is registered (Sonic reaches it)
  with the schema's own default, on every member;
- the arm write: SpotFX tells members (only) the breath on the lull arm,
  from the room's own setting;
- not opted in / turned off: the base render leaves the frame alone, and an
  untold Black Hole drop bursts exactly PHASE_BURST_N blobs;
- the real pipeline: scripts/check_drop_shockwave.py on every member.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx import device_model  # noqa: E402
from fx.effects import lull_dark, lull_handoff, phase_grammar as pg  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response as sr  # noqa: E402


# ── the breath-hold ─────────────────────────────────────────────────────────

def test_the_breath_is_the_setting_inside_the_lulls_dark_rule():
    keys = pg.breath_keys_for(8.0, 0.4, 3.0)
    assert keys[pg.BREATH_KEY] == pytest.approx(0.4)
    assert keys[pg.BREATH_AT_KEY] == pytest.approx(7.6)
    # never longer than the dark hold: half a short lull ...
    assert pg.breath_keys_for(0.5, 0.4, 3.0)[pg.BREATH_KEY] == pytest.approx(
        lull_dark.dark_hold_s(0.5, 3.0)) == pytest.approx(0.25)
    # ... or the room's dark cap
    assert pg.breath_keys_for(20.0, 3.0, 1.0)[pg.BREATH_KEY] == 1.0
    assert pg.breath_keys_for(20.0, 0.4, 0.0)[pg.BREATH_KEY] == 0.0
    # 0 disables; an unknowable gap has no mark to breathe before
    assert pg.breath_keys_for(8.0, 0.0, 3.0)[pg.BREATH_KEY] == 0.0
    assert pg.breath_keys_for(None, 0.4, 3.0) == {
        pg.BREATH_AT_KEY: 0.0, pg.BREATH_KEY: 0.0}


def test_breath_gain_is_true_black_for_the_breath_and_comes_back():
    cfg = pg.breath_keys_for(4.0, 0.4, 3.0)          # at 3.6 s for 0.4 s
    assert pg.breath_gain(cfg, 1.0) == 1.0
    assert 0.0 < pg.breath_gain(cfg, 3.6 - pg.BREATH_FADE_S / 2) < 1.0
    for t in (3.6, 3.8, 3.99):
        assert pg.breath_gain(cfg, t) == 0.0
    # a drop that never comes: the lull picture returns
    assert pg.breath_gain(cfg, 4.0 + pg.BREATH_OVERRUN_S + 0.01) == 1.0
    assert pg.breath_gain({}, 3.9) == 1.0                  # not told


def test_the_room_setting_is_04_and_sonic_editable():
    assert rc.RoomControlState().lull_breath_hold_s == pg.DEFAULT_BREATH_S
    assert rc.field_bounds("lull_breath_hold_s") == (0.0, 3.0)
    from spectra.services import settings_console as sc
    assert "lull_breath_hold_s" in sc.SETTINGS_REGISTRY


# ── the painter ─────────────────────────────────────────────────────────────

def _solid(rgb):
    def sample(pos):
        n = np.atleast_1d(pos).size
        return np.tile(np.asarray([rgb], np.float32), (n, 1))
    return sample


def _rainbow(pos):
    pos = np.atleast_1d(np.asarray(pos, np.float32))
    stops = np.array([[255, 0, 90], [255, 140, 0], [0, 180, 255],
                      [120, 0, 255]], np.float32)
    i = np.floor(pos * 4).astype(int) % 4
    return stops[i]


def _wave(sample=_solid((255, 60, 0)), **cfg):
    f = pg.panel_field(72, 37)
    rim = (35.5, 18.0, 0.2 * 35.5, 0.2 * 18.0)
    return f, pg.Shockwave(f, rim, sample, cfg, 0.9,
                           rng=np.random.default_rng(3))


def test_a_solid_sets_shockwave_is_that_colour_never_white():
    colour = np.array([255, 60, 0], np.float32)
    f, sw = _wave()
    for _ in range(80):
        o = sw.overlay()
        lit = o.max(axis=-1) > 1.0
        assert pg.white_cells(o) == 0
        if lit.any():
            # every lit overlay cell is the set colour scaled (max-composed
            # layers of one colour stay that colour)
            ratio = o[lit][:, :2] / colour[:2]
            assert np.allclose(ratio, ratio[:, :1], atol=0.02)
            assert (ratio <= 1.0 + 1e-4).all()
            assert (o[lit][:, 2] == 0.0).all()
        sw.step(1 / 30)


def test_a_multicolour_overlay_only_ever_draws_set_colours_scaled():
    f, sw = _wave(_rainbow)
    stops = np.array([[255, 0, 90], [255, 140, 0], [0, 180, 255],
                      [120, 0, 255]], np.float32)
    for _ in range(60):
        o = sw.overlay()
        lit = o.max(axis=-1) > 30.0
        # each lit cell is max-composed set colours: never brighter on any
        # channel than the set's own brightest value on that channel
        assert (o[lit] <= stops.max(axis=0) + 1e-3).all()
        sw.step(1 / 30)


def test_the_lean_never_leaves_the_colour_set():
    pos = np.linspace(0, 1, 50, endpoint=False)
    out = pg.lean_positions(pos, 0.9, 0.5)
    assert ((out >= 0) & (out < 1)).all()
    assert np.allclose(pg.lean_positions(pos, 0.9, 1.0), 0.9)
    assert np.allclose(pg.lean_positions(pos, 0.9, 0.0), pos)


def test_the_wave_is_born_on_the_rim_and_reaches_the_wall_later():
    f, sw = _wave()
    o = sw.overlay().max(axis=-1)
    on_rim = np.abs(sw.s) < 0.04
    assert o[on_rim].mean() > 150.0                 # the bloom on the mark
    assert o[f.wall].max() < 5.0                    # nothing on the wall yet
    hit = None
    for i in range(60):
        sw.step(1 / 30)
        if sw.overlay().max(axis=-1)[f.wall].mean() > 20.0:
            hit = (i + 1) / 30
            break
    assert hit is not None and hit > 0.3


def test_debris_count_rises_with_intensity_and_the_black_hole_boost():
    f = pg.panel_field(72, 37)
    rim = (35.5, 18.0, 7.0, 3.6)

    def n(intensity, boost=1.0):
        return pg.Shockwave(f, rim, _solid((255, 0, 0)), {}, intensity,
                            boost=boost, rng=np.random.default_rng(0)
                            ).d_th.size

    assert n(0.2) < n(0.75) < n(1.0)
    assert n(0.75) == pg.SHOCK_DEFAULTS["drop_debris_n"]   # the ceiling
    assert n(0.75, boost=1.6) > n(0.75)
    from fx.effects import blackhole
    assert blackhole.Blackhole2d.SHOCK_DEBRIS_BOOST > 1.0


def test_drop_shock_zero_paints_nothing():
    f, sw = _wave(drop_shock=0.0)
    assert sw.done
    assert sw.overlay().max() == 0.0


# ── membership and the registry ────────────────────────────────────────────

def _member_classes():
    from fx.effects import blackhole, eye, fish, orbits, sauron
    return {"blackhole": blackhole.Blackhole2d, "orbits": orbits.Orbits2d,
            "sauron": sauron.Sauron2d, "eye": eye.Eye2d, "fish": fish.Fish2d}


def test_members_are_exactly_the_opted_in_classes_never_fireworks():
    from fx.effects import fireworks
    assert set(_member_classes()) == device_model.DROP_SHOCK_EFFECTS
    assert "fireworks" not in device_model.DROP_SHOCK_EFFECTS
    assert not fireworks.Fireworks2d.DROP_SHOCK
    assert device_model.DROP_SHOCK_EFFECTS <= device_model.PHASE_EFFECTS
    assert device_model.DROP_SHOCK_EFFECTS <= \
        device_model.DROP_INTENSITY_EFFECTS
    for name, cls in _member_classes().items():
        assert cls.DROP_SHOCK, name
        assert cls.SHOCK_DEBRIS_FATE in ("return", "fade"), name
        keys = {str(k) for k in cls.CONFIG_SCHEMA.schema}
        assert set(pg.SHOCK_KEYS) | set(pg.BREATH_KEYS) | {
            lull_handoff.DROP_KEY} <= keys, name
        assert set(pg.BREATH_KEYS) | {lull_handoff.DROP_KEY} <= set(
            cls.ADVANCED_KEYS), name


def test_every_shockwave_setting_is_registered_with_the_schemas_default():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    want = pg.registry_params()
    for name, cls in _member_classes().items():
        entry = registry["effects"][name]
        schema = cls.schema()({})
        for key, meta in want.items():
            assert entry["params"][key] == meta, (name, key)
            assert entry["defaults"][key] == schema[key] == meta["default"]
        # the phase-write keys never reach the registry
        for key in (*pg.BREATH_KEYS, lull_handoff.DROP_KEY):
            assert key not in entry["params"]
    assert "fireworks" in registry["effects"]
    assert "drop_shock" not in registry["effects"]["fireworks"]["params"]


# ── the arm write ─────────────────────────────────────────────────────────

class _Exec:
    def __init__(self):
        self.jumps = []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, dict(params)))

    async def glide(self, vid, et, params, ms):
        pass


def _responder(effects, **room):
    ex = _Exec()
    conductor = SimpleNamespace(scene=None, virtuals={
        vid: SimpleNamespace(effect_type=et) for vid, et in effects.items()})
    eng = sr.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(**room),
        song_position=lambda: (None, None))
    return eng, ex


def test_the_lull_arm_tells_members_the_breath_from_the_room_setting():
    eng, ex = _responder({"bh": "blackhole", "orb": "orbits",
                          "fw": "fireworks", "sq": "squiggles"},
                         lull_breath_hold_s=0.5)
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=6_000, intensity=0.5))
    told = dict(ex.jumps)
    for vid in ("bh", "orb"):
        assert told[vid][pg.BREATH_KEY] == pytest.approx(0.5)
        assert told[vid][pg.BREATH_AT_KEY] == pytest.approx(5.5)
    for vid in ("fw", "sq"):
        assert pg.BREATH_KEY not in told[vid]
    assert rec["lull_breath_s"] == pytest.approx(0.5)


def test_an_unknowable_gap_tells_no_breath():
    eng, ex = _responder({"orb": "orbits"})
    asyncio.run(eng._drive_phase("lull", gap_ms=None, intensity=0.5))
    assert dict(ex.jumps)["orb"][pg.BREATH_KEY] == 0.0


def test_the_drop_arm_tells_every_member_the_intensity():
    eng, ex = _responder({vid: vid for vid in device_model.DROP_SHOCK_EFFECTS}
                         | {"fireworks": "fireworks"})
    asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.6))
    told = dict(ex.jumps)
    for vid in device_model.DROP_SHOCK_EFFECTS:
        assert told[vid][lull_handoff.DROP_KEY] == pytest.approx(0.6)
    assert lull_handoff.DROP_KEY not in told["fireworks"]


# ── the effects ────────────────────────────────────────────────────────────

def test_black_hole_burst_is_unchanged_untold_and_grows_on_a_loud_drop():
    from fx.effects import blackhole as bh
    eff = SimpleNamespace(_config={})
    assert bh.Blackhole2d._burst_count(eff) == bh.PHASE_BURST_N
    eff._config = lull_handoff.drop_keys_for(0.3)
    assert bh.Blackhole2d._burst_count(eff) == bh.PHASE_BURST_N   # never less
    eff._config = lull_handoff.drop_keys_for(1.0)
    assert bh.Blackhole2d._burst_count(eff) > bh.PHASE_BURST_N


def test_the_base_render_leaves_an_untouched_frame_alone():
    from PIL import Image
    from fx.effects.twod import Twod
    eff = SimpleNamespace(_config={}, _phase="none", _shock=None,
                          _shock_pending=False)
    eff.matrix = Image.new("RGB", (4, 3), (10, 20, 30))
    before = eff.matrix
    Twod._phase_grammar_post(eff)
    assert eff.matrix is before                 # not even re-encoded


def test_a_stale_shock_from_an_earlier_drop_never_bleeds_into_the_next_breath_hold():
    # His drop fired, a Shockwave began and is still alive (debris/afterglow
    # can outlast the "drop" phase itself) when the room completes a whole
    # new charge-lull cycle and tells THIS member a breath-hold for it — the
    # stale wave must never light that true-black window.
    from PIL import Image
    from fx.effects.twod import Twod

    f, sw = _wave()                       # a live, not-yet-done Shockwave
    assert not sw.done
    cfg = pg.breath_keys_for(4.0, 0.4, 3.0)      # told at 3.6s for 0.4s
    eff = SimpleNamespace(_config=cfg, _phase="lull", _phase_t=3.8,
                          _shock=sw, _shock_pending=False,
                          _shock_fresh=False, passed=1 / 30)
    eff.matrix = Image.new("RGB", (72, 37), (10, 20, 30))
    Twod._phase_grammar_post(eff)
    assert np.asarray(eff.matrix).max() == 0     # true black, not the stale wave
    assert eff._shock is None                    # discarded, not merely hidden


def test_a_stale_shock_is_discarded_on_a_new_charge_too():
    # Charge has no breath-hold of its own, but a leftover wave from the
    # previous drop must not paint over a new charge's own, untouched
    # picture either — the fix clears it on entering EITHER phase.
    from PIL import Image
    from fx.effects.twod import Twod

    f, sw = _wave()
    assert not sw.done
    eff = SimpleNamespace(_config={}, _phase="charge", _phase_t=0.1,
                          _shock=sw, _shock_pending=False,
                          _shock_fresh=False, passed=1 / 30)
    eff.matrix = Image.new("RGB", (72, 37), (10, 20, 30))
    before = eff.matrix
    Twod._phase_grammar_post(eff)
    assert eff.matrix is before                  # left untouched, not re-painted
    assert eff._shock is None                     # discarded, not merely hidden


# ── the real pipeline ──────────────────────────────────────────────────────

@pytest.mark.parametrize("effect", sorted(device_model.DROP_SHOCK_EFFECTS))
def test_on_the_real_pipeline(effect):
    import scripts.check_drop_shockwave as check
    m = check.measure(effect)
    # the breath-hold is true black
    assert m["breath_max"] == 0.0, m
    # born on the eye's rim, not the panel's edge
    assert m["rim_at_mark"] > 100.0 > m["perimeter_at_mark"] * 4, m
    # more colour / activity on the drop
    assert (m["lit_drop_1s_on"] > m["lit_drop_1s_off"]
            or m["energy_after_front_on"] > m["energy_after_front_off"]), m
    # adds no white to his multicolour set ...
    assert m["white_max_on"] <= m["white_max_off"], m
    # ... and a solid set's drop has none at all (the plan's own bar)
    s = check.measure(effect, gradient=check.SOLID)
    assert s["white_max_on"] == 0, s
