"""SAURON'S WORD SHAPE — the shaped iris and its shaped pupil (Word Shapes
plan row W1.5; the Admiral's words for the row: "Sauron: have it's pupil or
something chagne into that shape", and his Q8 C, "BOTH the pupil and the
iris become the shape at once").

The PICTURE — the three clarity bars on his crystal's real mask at every
gaze, the pupil's dark core, nothing jumping, no new white, a surge
mid-hold, the cost — is measured by scripts/check_sauron_word_shape.py on
the real render pipeline and run here as a subprocess (it os._exit()s,
AGENTS.md's rule for a script rendering through fx.headless).

This file holds what the check script cannot:

  1. UNTOLD IS TODAY'S, byte for byte: the module as it was before this row
     (pinned out of git) and today's module, driven through the same clip
     of busy and quiet audio with no told keys, frame for frame identical.
  2. COMPLETE ON THE WORD, through the REAL ResponseEngine: the Words
     band's one write lands the six keys on the live Sauron, and the
     effect's own form fraction reads 1.0 within one rendered frame of
     `edge + form_s`, for a 0.5 s form and a 0.9 s one.
  3. THE EDGES: the SEQ (not the id) is what edges, a stale SEQ on a fresh
     instance never fires, a second word mid-release picks the form up
     from where the shape already is rather than snapping it to zero, a
     clearing write releases from there too, and a form shorter than any
     frame is handled rather than dividing by zero.
  4. THE PLUMBING: the registry gate (the two tuned params registered, the
     six told keys deliberately NOT), ADVANCED_KEYS, and this effect's
     membership of fx.device_model.WORD_SHAPE_EFFECTS.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from random import Random

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx import device_model, facade, headless  # noqa: E402
from fx.effects import sauron as S  # noqa: E402
from fx.effects import word_shape_keys as wsk  # noqa: E402

VID = headless.DEFAULT_VIRTUAL_ID
DT = 1.0 / 60.0
# origin/master just before this row: sauron.py with no word shape at all
PRE_REF = "5db75fe6774437100383b3a0bed31aa90642cce1"
MID_FIRE = ("linear-gradient(90deg, rgb(255,0,0) 0%, rgb(255,143,0) 21%, "
            "rgb(255,143,0) 75%, rgb(255,0,0) 100%)")


def _run(coro):
    return asyncio.run(coro)


# ── the picture, on the real pipeline ──────────────────────────────────────

def test_check_sauron_word_shape_passes_on_the_real_pipeline():
    # the WHOLE script, not --quick: it runs in about 30 s, and every bar
    # it prints is a claim this row is judged on
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_sauron_word_shape.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=1800)
    assert proc.returncode == 0, proc.stdout[-6000:] + proc.stderr[-2000:]
    assert "all checks passed" in proc.stdout


# ── 1 · untold is today's, byte for byte ───────────────────────────────────

def _pinned_sauron() -> str:
    """fx/effects/sauron.py as it was before this row, registered as its
    own effect type (an Effect subclass registers under its module's last
    name segment) so one rig can drive both."""
    name = "sauron_pre_word_shape"
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{PRE_REF}:fx/effects/sauron.py"], cwd=ROOT,
            capture_output=True, text=True, check=True, timeout=60).stdout
    except Exception as exc:                              # noqa: BLE001
        pytest.skip(f"cannot read {PRE_REF}:fx/effects/sauron.py ({exc}) — "
                    f"the byte-identity claim is NOT checked")
    assert "word_shape" not in src, "the pinned module already has the row"
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


_CLIP_N = [0]


def _crystal_mask():
    prof = json.loads((ROOT / "storage" / "device_profiles"
                       / "crystal-mapper.json").read_text())
    mask, value = [], False
    for run in prof["mask_rle"]:
        mask.extend([value] * run)
        value = not value
    return np.array(mask, dtype=bool)


async def _clip(tmp_path, effect_type: str, frames: int = 320,
                seed: int = 5, writes=None):
    """One Sauron (or its pinned copy) through a clip of busy and quiet
    audio on the real crystal mask: every rendered frame.

    Seeded the way scripts/check_sauron.py seeds it — this effect draws its
    gaze wander and its noise field from an UNSEEDED generator at
    construction, so two instances are otherwise never comparable.
    """
    rows, cols = 37, 72
    # a virtual id of its own per run: a deactivated effect leaves a
    # hand-off snapshot keyed by virtual id (fx/effects/particle_handoff),
    # which the next run on the same id would adopt — two clips that are
    # meant to be comparable must each start from nothing
    _CLIP_N[0] += 1
    tag = f"ws{_CLIP_N[0]}-{effect_type}"
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=rows * cols, rows=rows,
        device_id=tag, real_mask=_crystal_mask())
    virtual = host.virtuals.get(tag)
    out = []
    try:
        with headless.fake_clock() as clock:
            eff = headless.attach_effect(host, virtual, effect_type,
                                         {"gradient": MID_FIRE})
            eff._rng = np.random.default_rng(seed)
            eff._wander_seed = float(
                np.random.default_rng(seed).uniform(0.0, 2.0 * np.pi))
            eff.noise.seed = int(seed) * 7919 + 17
            for i in range(frames):
                # busy for the first half (beats and bass), quiet after
                busy = i < frames // 2
                eff.impulse = 0.75 if busy else 0.05
                if busy and i % 10 == 0:
                    eff._beat_pending = True
                for at, params in (writes or {}).items():
                    if at == i:
                        eff.update_config(dict(params))
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
                    out.append(np.asarray(frame, dtype=np.float32).copy())
    finally:
        await host.shutdown()
    return np.array(out), eff


def test_untold_renders_exactly_what_it_rendered_before(tmp_path):
    pinned = _pinned_sauron()

    async def main():
        today, _ = await _clip(tmp_path / "today", "sauron")
        before, _ = await _clip(tmp_path / "before", pinned)
        assert today.shape == before.shape and today.size
        assert today.max() > 0.0, "a dark clip would prove nothing"
        assert len(today) >= 300
        assert np.array_equal(today, before)

    _run(main())


def test_the_told_keys_at_their_defaults_are_untold(tmp_path):
    """Rule 3 of the told keys: a write carrying every key at NOT_TOLD is
    the same as no write at all."""
    async def main():
        plain, _ = await _clip(tmp_path / "plain", "sauron", frames=120)
        cleared, eff = await _clip(
            tmp_path / "cleared", "sauron", frames=120,
            writes={40: dict(wsk.NOT_TOLD)})
        assert np.array_equal(plain, cleared)
        assert eff.last_shape_frac == 0.0

    _run(main())


# ── 2 · complete on the word, through the real engine ──────────────────────

def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["sauron"], "role": None}}))


def _engine(clock):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now, curve_profiles=lambda: {})
    return executor, conductor, responder


def _words_scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Sauron Words",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual",
                                   target=VID, effect_type="sauron")],
        flare_kinds=[FlareKind(name="Shape", type="word_shape")],
        responses={"word": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Shape": 1.0})])})


def _fire(conductor, scene, config):
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": "sauron", "config": dict(config),
        "entry_id": scene.devices[0].id, "color_mode": "set"}])


@pytest.mark.parametrize("form_s,shape", [(0.5, "heart"), (0.9, "star")])
def test_the_shape_is_complete_on_the_word(tmp_path, form_s, shape):
    """The told form is the time LEFT to the word, so the envelope must
    read 1.0 exactly `form_s` after the edge — one rendered frame of
    allowance, the acceptance bar's own."""
    from spectra.services import scene_response as sr

    _categories_fixture(tmp_path)
    scene = _words_scene()

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "eng"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "sauron",
                                                {"gradient": MID_FIRE})
                _executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, {"gradient": MID_FIRE})
                headless.render_frames(virtual, 2, clock=clock, dt=DT)
                assert effect.last_shape_frac == 0.0

                # the real synthetic action the preview path builds, with
                # this case's own form (a frozen dataclass)
                base = sr.preview_word_shape(0.5, shape)
                action = dataclasses.replace(base, form_s=form_s,
                                             hold_s=1.0, release_s=0.75)
                assert action.shape_id == shape
                record = await responder.on_word_shape(action)
                assert record["result"] == "applied"
                assert effect._config[wsk.SHAPE_KEY] == shape

                # the clock starts on the first frame after the edge
                n = int(round(form_s / DT))
                fracs = []
                for _ in range(n + 2):
                    headless.render_frames(virtual, 1, clock=clock, dt=DT)
                    fracs.append(float(effect.last_shape_frac))
                assert fracs[n - 1] == pytest.approx(1.0, abs=1e-6) or \
                    fracs[n] == pytest.approx(1.0, abs=1e-6), fracs[-4:]
                # and it got there smoothly, from zero, without overshoot
                assert fracs[0] < 0.05 and max(fracs) <= 1.0
                assert all(b >= a - 1e-9 for a, b in zip(fracs, fracs[1:]))
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 3 · the edges ──────────────────────────────────────────────────────────

class _Rig:
    """One Sauron, stepped by hand — enough for the clock's own rules."""

    def __init__(self, host, virtual, clock, effect):
        self.host, self.virtual, self.clock, self.effect = (
            host, virtual, clock, effect)

    def step(self, frames=1):
        for _ in range(frames):
            self.effect.impulse = 0.3
            self.clock.advance(DT)
            frame = self.virtual.assemble_frame()
            if frame is not None:
                self.virtual.flush(frame)

    def tell(self, shape, seq, form, hold, release, level=0.5):
        self.effect.update_config(
            wsk.keys_for(shape, seq, form, hold, release, level))


async def _rig(tmp_path, tag="edge", config=None):
    host = await headless.start_headless_host(str(tmp_path / tag))
    virtual = host.virtuals.get(VID)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    effect = headless.attach_effect(host, virtual, "sauron",
                                    {"gradient": MID_FIRE, **(config or {})})
    return _Rig(host, virtual, clock, effect), cm


def test_two_words_of_the_same_shape_both_edge(tmp_path):
    async def main():
        rig, cm = await _rig(tmp_path)
        try:
            rig.tell("heart", 1, 0.3, 0.3, 0.3)
            rig.step(int(round(0.9 / DT)) + 4)
            assert rig.effect.last_shape_frac == 0.0, "it reset itself"
            rig.tell("heart", 2, 0.3, 0.3, 0.3)
            rig.step(2)
            assert rig.effect.last_shape_frac > 0.0, \
                "an effect watches the SEQ, never the id"
        finally:
            cm.__exit__(None, None, None)
            await rig.host.shutdown()

    _run(main())


def test_a_stale_seq_on_a_fresh_instance_never_fires(tmp_path):
    """The creation baseline (fireworks' phase-key rule): a persisted
    config carrying last night's shape must not draw it."""
    async def main():
        rig, cm = await _rig(tmp_path, config=wsk.keys_for(
            "heart", 9, 0.5, 1.0, 0.75, 0.6))
        try:
            rig.step(30)
            assert rig.effect.last_shape_frac == 0.0
            # ... but a NEW seq on the same config does fire
            rig.tell("heart", 10, 0.5, 1.0, 0.75)
            rig.step(5)
            assert rig.effect.last_shape_frac > 0.0
        finally:
            cm.__exit__(None, None, None)
            await rig.host.shutdown()

    _run(main())


def test_a_second_word_mid_release_picks_up_from_where_the_shape_is(tmp_path):
    async def main():
        rig, cm = await _rig(tmp_path)
        try:
            rig.tell("heart", 1, 0.3, 0.1, 0.9)
            rig.step(int(round(0.6 / DT)))       # into the release
            mid = float(rig.effect.last_shape_frac)
            assert 0.05 < mid < 0.95, mid
            rig.tell("heart", 2, 0.5, 1.0, 0.75)
            rig.step(1)
            after = float(rig.effect.last_shape_frac)
            assert after >= mid - 0.02, (mid, after)   # no snap to zero
            rig.step(3)
            assert rig.effect.last_shape_frac > after  # and forming again
        finally:
            cm.__exit__(None, None, None)
            await rig.host.shutdown()

    _run(main())


def test_a_clearing_write_mid_shape_releases_from_where_it_is(tmp_path):
    async def main():
        rig, cm = await _rig(tmp_path)
        try:
            rig.tell("heart", 1, 0.4, 4.0, 0.6)
            rig.step(int(round(0.5 / DT)))
            assert rig.effect.last_shape_frac == pytest.approx(1.0)
            rig.effect.update_config(dict(wsk.NOT_TOLD))
            rig.step(1)
            first = float(rig.effect.last_shape_frac)
            assert 0.9 < first < 1.0, first        # no snap to nothing
            rig.step(int(round(0.6 / DT)) + 3)
            assert rig.effect.last_shape_frac == 0.0
        finally:
            cm.__exit__(None, None, None)
            await rig.host.shutdown()

    _run(main())


def test_a_form_shorter_than_a_frame_is_handled(tmp_path):
    """The engine floors the form, so this write is impossible by
    contract — the effect still must not divide by zero."""
    async def main():
        rig, cm = await _rig(tmp_path)
        try:
            rig.tell("diamond", 1, 0.0, 0.2, 0.0)
            rig.step(2)
            assert rig.effect.last_shape_frac == pytest.approx(1.0)
            rig.step(int(round(0.3 / DT)))
            assert rig.effect.last_shape_frac == 0.0
            assert np.isfinite(np.asarray(rig.effect.matrix,
                                          dtype=np.float32)).all()
        finally:
            cm.__exit__(None, None, None)
            await rig.host.shutdown()

    _run(main())


def test_an_unknown_shape_id_is_simply_not_told(tmp_path):
    """A newer SpotFX's shape must fall through to "no shape", never take
    the rest of the write with it (word_shape_keys' own rule)."""
    async def main():
        rig, cm = await _rig(tmp_path)
        try:
            rig.effect.update_config({wsk.SHAPE_KEY: "trefoil",
                                      wsk.SEQ_KEY: 3, wsk.FORM_KEY: 0.5,
                                      wsk.HOLD_KEY: 1.0,
                                      wsk.RELEASE_KEY: 0.75,
                                      wsk.LEVEL_KEY: 0.5})
            rig.step(10)
            assert rig.effect.last_shape_frac == 0.0
            assert rig.effect._config[wsk.SHAPE_KEY] == "trefoil"
        finally:
            cm.__exit__(None, None, None)
            await rig.host.shutdown()

    _run(main())


# ── 4 · the plumbing ───────────────────────────────────────────────────────

def test_sauron_is_a_word_shape_effect():
    assert "sauron" in device_model.WORD_SHAPE_EFFECTS


def test_the_told_keys_ride_only_the_write():
    schema = {str(k): v for k, v in S.Sauron2d.CONFIG_SCHEMA.schema.items()}
    for key in wsk.KEYS:
        assert key in schema, key
        assert key in S.Sauron2d.ADVANCED_KEYS, key
    registry = json.loads(
        (ROOT / "config" / "effect_params.json").read_text())
    params = registry["effects"]["sauron"]["params"]
    for key in wsk.KEYS:
        assert key not in params, f"{key} must ride only the told write"


def test_the_two_tuned_params_are_registered():
    registry = json.loads(
        (ROOT / "config" / "effect_params.json").read_text())
    block = registry["effects"]["sauron"]
    schema = {str(k): v for k, v in S.Sauron2d.CONFIG_SCHEMA.schema.items()}
    for key, default, lo, hi in (("word_shape_size", 1.0, 0.6, 1.3),
                                 ("word_shape_pupil", 0.4, 0.2, 0.6)):
        assert key in schema
        entry = block["params"][key]
        assert entry["default"] == default
        assert (entry["min"], entry["max"]) == (lo, hi)
        assert entry["help_topic"] == "word-shapes"
        assert block["defaults"][key] == default
        # the schema's own default agrees with the registry's
        assert S.Sauron2d.CONFIG_SCHEMA({})[key] == default


def test_the_pupil_shape_is_floored_to_keep_its_dark_core():
    """The floor is the shape's own inradius: whatever `word_shape_pupil`
    says, the pupil is never drawn so small that its dark core falls below
    SLIT_MIN_DARK_PX rendered pixels."""
    from fx.effects import word_shapes
    for shape_id in word_shapes.SHAPES:
        shape = word_shapes.get(shape_id)
        inr = S.shape_inradius(shape)
        assert 0.0 < inr < 1.0
        # a disc of the floor radius fits inside the shape at that size
        floor = 0.05 / inr
        assert shape.sdf(0.0, 0.0) * floor <= -0.05 + 1e-9
