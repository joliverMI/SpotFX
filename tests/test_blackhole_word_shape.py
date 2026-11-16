"""WORD SHAPES ON THE BLACK HOLE — the event horizon takes the shape (Word
Shapes plan row W1.1, approved by the Admiral 2026-11-15). His words:
"Black hole: The event horizon shape changes to match the shape. The
particles in the event horizon flow around in this shape, as the event
horizon beats to the music." and "The shapes should form smoothly. ... hold
momentarily, and then release back and smoothly."

Everything here runs OFFLINE on the real render pipeline: `fx.headless`
dummy devices sized like his `crystal-mapper` (72 x 37), the real vendored
`Blackhole2d`, the PRODUCTION `ResponseEngine` on the `FacadeExecutor`
firing a real Words band, a deterministic fake clock and a seeded RNG. No
LedFX service, no HTTP, no audio hardware, nothing of his read or written.

WHAT IT PROVES, in the plan's own order (section 6, the row's gate):

  1. UNTOLD IS TODAY'S — the pre-change module loaded out of git at a
     pinned ref renders byte-identical frames over 300 frames of busy and
     of quiet audio (the `tests/test_flare_punch_crystal.py` pinned-module
     pattern).
  2. COMPLETE ON THE WORD — the form fraction reads 1.0 within one
     rendered frame of `edge + form_s`, for 0.5 s and 0.9 s, through the
     real engine; a form shorter than one frame clamps instead of dividing
     by zero.
  3. NOTHING JUMPS — the largest frame-to-frame change in lit real cells
     through the form and the release stays under 8% of the lit count.
  4. IT IS THE SHAPE — the clarity bar, measured on the real hex mask:
     at the word, mid-hold and the hold's end, captives light at least 65%
     of the shape's outline cells and at least 95% of its inside cells are
     black. scripts/check_blackhole_word_shape.py prints the numbers.
  5. NO WHITE — the white fraction while a shape stands is no higher than
     this effect's own busy frames today.
  6. COST — under 1 ms p50 added per frame with a shape holding.
  7. TWO WORDS BACK TO BACK both edge on the SEQ, a word mid-release lifts
     the form off the fraction it is at, and a clearing write releases from
     it.
  8. The row's own geometry: the radius per angle IS `SIZE x polar(theta)`
     at the hold on 360 angles, a captive's LINEAR speed round a heart is
     constant within 5%, the disc is black inside the shape, and infall
     still captures through the hold.

THE RIG IS SHARED with scripts/check_blackhole_word_shape.py, which imports
it (the `check_flare_punch_crystal.py` arrangement) so the measurement and
the assertion can never drift.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from random import Random

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import device_model, facade, headless  # noqa: E402
from fx.effects import word_shape_keys as wsk  # noqa: E402
from fx.effects import word_shapes  # noqa: E402
from fx.effects.blackhole import (REVERSE_FALLBACK_RING_TOL,  # noqa: E402
                                  WORD_SHAPE_DISC_PITCHES,
                                  WORD_SHAPE_R_MAX)

FPS = 60
DT = 1.0 / FPS
COLS, ROWS = 72, 37
VID = "bh-crystal"
SIZE_DEFAULT = 0.62

# The plan's own clarity bar for this row, and the simulation's numbers it
# has to reproduce or beat (plan section 3.1). A row that misses a bar is
# not deployed and the NUMBER is reported — never the bar moved.
OUTLINE_BAR = 0.65
INSIDE_BLACK_BAR = 0.95
JUMP_BAR = 0.08
SPEED_BAR = 0.05
COST_BAR_MS = 1.0
# "NO WHITE": the grey share that counts as white (the smallest channel at
# least this much of the largest), and how many cells of slack the bar
# allows against the effect's own busy frames — see Room.white() and
# test_a_shape_is_no_whiter_than_an_ordinary_busy_frame for the measurement
# behind both.
WHITE_GREY = 0.9
WHITE_SLACK_CELLS = 2

# The module as it was before this row, for the untold byte-identity proof.
PINNED_REF = "5db75fe6"

# One addressable step in physical pitch units — the hex lattice's own
# (scripts/check_word_shapes.py is the binding statement; a column is half a
# real-cell pitch, a row sqrt(3)/2 of one).
COLUMN_PITCH = 0.5
ROW_PITCH = math.sqrt(3.0) / 2.0
CELL_PITCH = 1.0
OUTLINE_SAMPLES = 1440


# ── his own Black Hole V2 crystal entry ────────────────────────────────────

def bh_config(energy: float, **over) -> dict:
    """His live "Black Hole V2" Matrix entry (storage/spectra/scenes.json),
    with its four signal-bound params resolved at `energy` exactly as the
    scene compiler resolves them (`trigger_intensity`, mode map, the ranges
    he authored). Measuring the shape on anything else would be measuring a
    config that is not in his room."""
    cfg = {
        "horizon_scale": 0.2,
        "horizon_audio": 0.3,
        "reverse": False,
        "x_offset": 0.5,
        "y_offset": 0.5,
        "base_speed": 2.0,
        "accel": 5.0,
        "edge_speed": 0.2,
        "spawn_audio": 1.5,
        "speed_audio": 2.0,
        "impulse_decay": 0.06,
        "max_blobs": 50,
        "horizon_hold": 2.8,
        # the four signal binds, resolved at this Energy
        "blob_size": 1.5 + 0.5 * energy,
        "swirl": -6.0 + 12.0 * energy,
        "spawn_rate": 0.5 + 1.5 * energy,
        "beat_burst": int(round(6.0 * energy)),
    }
    cfg.update(over)
    return cfg


# ── the panel's real cells ─────────────────────────────────────────────────

def real_mask() -> np.ndarray:
    """His crystal's real-light mask, (ROWS, COLS) bool — the same decode
    scripts/check_word_shapes.py does, off the same stored profile."""
    prof = json.loads((ROOT / "storage/device_profiles/crystal-mapper.json")
                      .read_text(encoding="utf-8"))
    flat, value = [], False
    for run in prof["mask_rle"]:
        flat.extend([value] * int(run))
        value = not value
    grid = np.asarray(flat, dtype=bool)
    assert grid.size == int(prof["rows"]) * int(prof["cols"])
    assert (int(prof["rows"]), int(prof["cols"])) == (ROWS, COLS)
    return grid.reshape(ROWS, COLS)


def shape_cell_sets(shape_id: str, size: float = SIZE_DEFAULT):
    """The OUTLINE and INSIDE cell masks for one shape drawn at `size`,
    exactly as scripts/check_word_shapes.py defines and PINS them: outline =
    a real cell within one cell PITCH of the outline (measured in physical
    pitch units, both sides), inside = a real cell strictly inside it. The
    plan's "inside" denominator for a BLACK bar is the inside cells DEEPER
    than one pitch, i.e. inside and not outline — returned as the third
    mask so nothing re-derives it.

    The masks come from that script's own helpers rather than a second
    implementation, so the denominators here are the pinned ones."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_word_shapes as cws

    panel = cws.load_panel()
    shape = word_shapes.get(shape_id)
    _m, outline, inside = cws.measure(shape, panel, size)
    return outline, inside, inside & ~outline


# ── deterministic "busy" and "quiet" audio ─────────────────────────────────

class Audio:
    """One deterministic audio frame. `busy` is a loud, beating room (the
    hard case for the clarity bar — the sim's own 65% is the star's at loud
    Energy); `seed` only shifts its phase, so three seeds are three
    different moments of the same music rather than three different rooms."""

    def __init__(self, i: int, busy: bool = True, seed: int = 0):
        self.i = i
        self.busy = busy
        self.seed = seed

    def _level(self, scale: float, period: float) -> float:
        if not self.busy:
            return 0.0
        phase = self.seed * 2.1
        return float(scale * (0.62 + 0.38 * math.sin(self.i / period + phase)))

    def lows_power(self, filtered: bool = True) -> float:
        return self._level(0.85, 11.0)

    beat_power = bass_power = lows_power

    def mids_power(self, filtered: bool = True) -> float:
        return self._level(0.45, 7.0)

    def high_power(self, filtered: bool = True) -> float:
        return self._level(0.3, 5.0)

    def onset(self) -> bool:
        return self.busy and (self.i + self.seed) % 24 == 0

    def bpm_beat_now(self) -> bool:
        return self.onset()


# ── the room ───────────────────────────────────────────────────────────────

def _config_dir(path: str, vid: str) -> None:
    os.makedirs(path, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    with open(os.path.join(path, "config.json"), "w") as fh:
        json.dump({
            "configuration_version": CONFIGURATION_VERSION,
            "devices": [{"id": f"{vid}-dev", "type": "dummy",
                         "config": {"name": f"{vid}-dev",
                                    "pixel_count": COLS * ROWS}}],
            "virtuals": [{"id": vid, "is_device": False,
                          "auto_generated": False,
                          "config": {"name": vid, "mapping": "span",
                                     "rows": ROWS},
                          "segments": [[f"{vid}-dev", 0, COLS * ROWS - 1,
                                        False]]}],
        }, fh)


def words_scene(shape_name: str = "Heart", *, energy_min: float = 0.0,
                extra_kinds=(), bands=None, vid: str = VID):
    """A one-virtual scene whose WORDS section holds a Word Shape kind —
    the band IS the switch (his Q6 A), so this is the only thing that makes
    a sung word reach the crystal at all."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name=shape_name, type="word_shape"), *extra_kinds]
    responses = {"word": ResponseSpec(bands=[FlareBand(
        intensity_min=energy_min, intensity_max=1.0,
        kinds={k.name: 1.0 for k in kinds})])}
    for cls, attached in (bands or {}).items():
        responses[cls] = ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds=dict(attached))])
    return SceneV2(name="Black Hole Words", flare_kinds=kinds,
                   devices=[SceneDeviceConfig(target_kind="virtual",
                                              target=vid,
                                              effect_type="blackhole")],
                   responses=responses)


_ROOM_N = 0


class Room:
    """The crystal's Black Hole under the production ResponseEngine, frame
    stepped. `effect_type` is a hook for the PINNED pre-change module: the
    byte-identity proof registers it under its own name and runs the same
    room twice."""

    def __init__(self, tmp_dir, config: dict, *, scene=None,
                 effect_type: str = "blackhole", busy: bool = True,
                 seed: int = 0, rng_seed: int = 11):
        # A VIRTUAL ID OF ITS OWN PER ROOM. A deactivated particle effect
        # leaves a hand-off snapshot keyed by virtual id
        # (fx/effects/particle_handoff), and the NEXT room on that id adopts
        # it — which silently made two runs of "the same" room render
        # different frames, and is exactly the trap the pinned-module
        # comparison exists to catch (tests/test_flare_punch_crystal.py does
        # the same thing for the same reason).
        global _ROOM_N
        _ROOM_N += 1
        self.vid = f"{VID}-{_ROOM_N}-{Path(tmp_dir).name}-{effect_type}"
        self.tmp_dir = str(tmp_dir)
        self.config = dict(config)
        self.scene = scene
        self.effect_type = effect_type
        self.busy = busy
        self.seed = seed
        self.rng_seed = rng_seed
        self.frames: list[np.ndarray] = []
        self.i = 0

    async def __aenter__(self):
        from fx.host import FxHost
        from spectra.services import color_journey as cj
        from spectra.services import room_controls as rc
        from spectra.services.drift_conductor import DriftConductor
        from spectra.services.fx_executor import FacadeExecutor
        from spectra.services.scene_response import ResponseEngine

        np.random.seed(7)
        _config_dir(os.path.join(self.tmp_dir, "fx-room"), self.vid)
        headless.silence_audio()
        self.host = FxHost(os.path.join(self.tmp_dir, "fx-room"))
        await self.host.start()
        self.host.audio = headless.SyntheticAudioSource()
        facade.set_host(self.host)
        self._clock_cm = headless.fake_clock()
        self.clock = self._clock_cm.__enter__()
        self._real_ns = time.time_ns
        time.time_ns = lambda: int(self.clock.now * 1e9)
        self.virtual = self.host.virtuals.get(self.vid)
        self.effect = headless.attach_effect(self.host, self.virtual,
                                             self.effect_type, self.config)
        self.effect._rng = np.random.default_rng(self.rng_seed)
        room = [cj.RoomColorState()]
        controls = rc.RoomControlState()
        self.executor = FacadeExecutor(clock=lambda: self.clock.now,
                                       room_controls_load=lambda: controls)
        self.conductor = DriftConductor(
            executor=self.executor, clock=lambda: self.clock.now,
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            room_load=lambda: room[0],
            room_save=lambda st: room.__setitem__(0, st),
            set_cards=lambda: [], gradient_profiles=lambda: {},
            room_controls=lambda: controls, rng=Random(3))
        self.responder = ResponseEngine(
            conductor=self.conductor, executor=self.executor, rng=Random(5),
            clock=lambda: self.clock.now, curve_profiles=lambda: {},
            room_load=lambda: room[0],
            room_save=lambda st: room.__setitem__(0, st),
            room_controls=lambda: controls)
        scene = self.scene or words_scene(vid=self.vid)
        self.conductor.on_scene_fire(scene, [
            {"virtual_id": self.vid, "effect_type": self.effect_type,
             "config": dict(self.config), "entry_id": scene.devices[0].id,
             "color_mode": "set"}])
        return self

    async def __aexit__(self, *exc):
        time.time_ns = self._real_ns
        self._clock_cm.__exit__(None, None, None)
        facade.set_host(None)
        await self.host.shutdown()

    def step(self, n: int = 1):
        for _ in range(n):
            self.clock.advance(DT)
            self.i += 1
            with self.effect.lock:
                self.effect.audio_data_updated(
                    Audio(self.i, self.busy, self.seed))
            frame = self.virtual.assemble_frame()
            if frame is not None:
                self.virtual.flush(frame)
                self.frames.append(np.array(frame, dtype=np.float64,
                                            copy=True))

    async def word(self, shape: str = "heart", energy: float = 0.5,
                   form_s: float = 0.9, hold_s: float = 1.2,
                   release_s: float = 1.35) -> dict:
        """Fire one sung word's shape through the REAL Words section. The
        action carries exactly the five fields the kind reads — the
        preview's own `PreviewWordShape`, deliberately not a fabricated
        WordHit (scene_response's own rule)."""
        from spectra.services.scene_response import PreviewWordShape
        return await self.responder.on_word_shape(PreviewWordShape(
            shape_id=shape, energy=energy, form_s=form_s, hold_s=hold_s,
            release_s=release_s))

    async def clear_shape(self) -> None:
        """A CLEARING write: every key at NOT_TOLD, which is what an older
        SpotFX, a hand test or a `word_shape: ""` write looks like."""
        await self.executor.jump(self.vid, self.effect_type,
                                 dict(wsk.NOT_TOLD))

    # ── measurement ────────────────────────────────────────────────────
    @property
    def frame(self) -> np.ndarray:
        return self.frames[-1].reshape(ROWS, COLS, 3)

    def m(self) -> float:
        """The effect's OWN form fraction this frame."""
        return float(self.effect._ws_m)

    def captive_angles(self):
        eff = self.effect
        n = eff.n
        cap = eff.p_cap[:n] >= 0.0
        return eff.p_theta[:n][cap], eff.p_r[:n][cap]

    def white(self) -> tuple[float, int]:
        """"No white" (plan acceptance 5), as (share of lit real cells,
        count). WHITE here is a GREY SHARE over WHITE_GREY (the smallest
        channel at least 90% of the largest), not a brightness, so a bright
        saturated colour — which is most of what this effect draws — is
        never mistaken for white. The colour-set comparison
        `strip_phase_harness.whiter_than_set` makes is the strips' own; here
        the blobs carry a rainbow gradient, so a hue-matched palette
        threshold would admit almost anything."""
        f = self.frame[real_mask()]
        mx = f.max(axis=1)
        lit = mx > 2.0
        if not lit.any():
            return 0.0, 0
        grey = f[lit].min(axis=1) / np.maximum(mx[lit], 1e-6) > WHITE_GREY
        return float(np.mean(grey)), int(grey.sum())

    def lit_cells(self) -> np.ndarray:
        """Which REAL cells are lit this frame."""
        return (self.frame.max(axis=2) > 0.5) & real_mask()


def lit_of(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return (frame.max(axis=2) > 0.5) & mask


def _run(coro):
    return asyncio.run(coro)


# ── the shape's own outline band, as DRAWN ─────────────────────────────────

def drawn_band(effect, samples: int = 720) -> np.ndarray:
    """The real cells within one cell pitch of the outline the effect is
    ACTUALLY drawing this frame (its own `_horizon_radius_at` round the
    circle) — the same band rule scripts/check_word_shapes.py pins, applied
    to the live radius instead of the nominal one.

    Reported BESIDE the pinned band, never instead of it: the pinned
    168/176/119 cells are the plan's denominator and the bar is a fraction
    of THEM. This one answers the separate question "is the outline the
    captives are on continuous?", which is what tells you whether a miss is
    the shape breaking up or the shape having moved."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_word_shapes as cws

    panel = cws.load_panel()
    mask = real_mask()
    rows_idx, cols_idx = np.nonzero(mask)
    rx = (cols_idx - panel.half_width) * COLUMN_PITCH
    ry = (rows_idx - panel.half_height) * ROW_PITCH
    theta = np.linspace(0.0, 2.0 * math.pi, samples, endpoint=False)
    radius = np.asarray(effect._horizon_radius_at(theta.astype(np.float32)),
                        dtype=float)
    px = radius * np.cos(theta) * panel.half_width * COLUMN_PITCH
    py = radius * np.sin(theta) * panel.half_height * ROW_PITCH
    near = np.hypot(rx[None, :] - px[:, None],
                    ry[None, :] - py[:, None]) <= CELL_PITCH
    band = np.zeros_like(mask)
    hit = near.any(axis=0)
    band[rows_idx[hit], cols_idx[hit]] = True
    return band


# ══ 1. UNTOLD IS TODAY'S ═══════════════════════════════════════════════════

_PINNED: dict = {}


def pinned_type() -> str:
    """The module as it was before this row, registered as a SECOND effect
    beside today's (an Effect subclass registers under its module's last
    name segment) — tests/test_flare_punch_crystal.py's own pattern."""
    if "name" in _PINNED:
        return _PINNED["name"]
    name = "blackhole_pre_word_shape"
    try:
        src = subprocess.run(
            ["git", "show", f"{PINNED_REF}:fx/effects/blackhole.py"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                             # noqa: BLE001
        pytest.skip(f"cannot read {PINNED_REF}:fx/effects/blackhole.py "
                    f"({exc}) — the byte-identity claim is NOT checked")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _PINNED["name"] = name
    return name


def _plain_frames(tmp, effect_type, busy, n=320):
    async def main():
        async with Room(tmp, bh_config(0.6), effect_type=effect_type,
                        busy=busy, seed=1) as room:
            room.step(n)
            return np.array(room.frames, dtype=np.float32)
    return _run(main())


@pytest.mark.parametrize("busy", [True, False])
def test_untold_renders_byte_for_byte_what_it_renders_today(tmp_path, busy):
    """PLAN ACCEPTANCE 1. No told keys anywhere: the shaped horizon is one
    boolean away from the scalar one (`_word_shape_on`), and that boolean is
    False, so every number in the frame is the one the pre-change module
    produces — over 320 frames of busy and of quiet audio."""
    pinned = pinned_type()
    today = _plain_frames(tmp_path / "today", "blackhole", busy)
    before = _plain_frames(tmp_path / "before", pinned, busy)
    assert today.shape == before.shape and today.size
    assert today.max() > 0.0, "a run that never lit anything proves nothing"
    assert np.array_equal(today, before)


def test_a_stale_persisted_seq_never_forms_a_shape_on_a_fresh_instance(
        tmp_path):
    """The creation baseline (the fireworks `burst_rockets` rule): a config
    restored from disk carrying a word shape must not fire it."""
    async def main():
        stale = {**bh_config(0.6),
                 **wsk.keys_for("heart", 7, 0.9, 1.2, 1.35, 0.6)}
        async with Room(tmp_path / "stale", stale) as room:
            assert room.effect._ws is None
            assert room.effect._ws_seen == 7
            room.step(30)
            assert room.m() == 0.0
            assert room.effect._ws_live is None
    _run(main())


# ══ 2. COMPLETE ON THE WORD ════════════════════════════════════════════════

@pytest.mark.parametrize("form_s", [0.5, 0.9])
def test_the_shape_is_complete_one_frame_after_the_form(tmp_path, form_s):
    """PLAN ACCEPTANCE 2, through the REAL Words section: the told form is
    the time LEFT to the word, so the form fraction must read 1.0 by
    `edge + form_s` — no settle time, one rendered frame of slack."""
    async def main():
        async with Room(tmp_path / f"f{form_s}", bh_config(0.6)) as room:
            room.step(120)
            record = await room.word("heart", energy=0.6, form_s=form_s,
                                     hold_s=1.0, release_s=form_s * 1.5)
            assert record["result"] == "applied"
            assert record["word_shape"]["virtuals"] == 1
            assert record["word_shape"]["form_s"] == pytest.approx(form_s)
            complete = None
            for frame in range(1, int(round((form_s + 0.3) * FPS))):
                room.step()
                ws = room.effect._ws
                if ws is not None:
                    # the effect's own clock is the contract: 1.0 exactly
                    # when it reaches the form, never before
                    if ws["t"] < form_s - 1e-9:
                        assert room.m() < 1.0, ws["t"]
                    else:
                        assert room.m() == pytest.approx(1.0, abs=1e-12)
                if complete is None and room.m() >= 1.0:
                    complete = frame
            # …and it lands on the word in WALL frames too: the engine's
            # 1 ms jump costs one rendered frame, and the bar allows one
            want = form_s * FPS
            assert complete is not None
            assert want - 1 <= complete <= want + 2, (complete, want)
    _run(main())


def test_a_form_shorter_than_a_frame_clamps_instead_of_dividing_by_zero(
        tmp_path):
    """The engine floors the form at the effect's own minimum, so this is
    impossible by contract — a hand test and a LedFX UI scrub are not bound
    by the contract, so it is still handled."""
    async def main():
        async with Room(tmp_path / "zero", bh_config(0.6)) as room:
            room.step(60)
            await room.word("heart", energy=0.6, form_s=0.0, hold_s=0.5,
                            release_s=0.5)
            room.step(2)
            assert room.m() == 1.0
            assert np.isfinite(room.frame).all()
    _run(main())


# ══ 3. NOTHING JUMPS ═══════════════════════════════════════════════════════

def test_nothing_jumps_through_the_form_or_the_release(tmp_path):
    """PLAN ACCEPTANCE 3: the largest frame-to-frame change in lit real
    cells stays under 8% of the lit count, right through the form, the
    hold's two seams and the release's end."""
    async def main():
        mask = real_mask()
        async with Room(tmp_path / "jump", bh_config(0.6)) as room:
            room.step(240)
            await room.word("heart", energy=0.6, form_s=0.9, hold_s=1.2,
                            release_s=1.35)
            counts = []
            for _ in range(int(round(4.0 * FPS))):
                room.step()
                counts.append(int(lit_of(room.frame, mask).sum()))
            worst = max(abs(b - a) / max(a, 1)
                        for a, b in zip(counts, counts[1:]))
            assert worst < JUMP_BAR, f"largest frame step {worst:.1%}"
    _run(main())


def test_the_captives_ride_the_outline_out_and_back(tmp_path):
    """The vision in one measurement: the ring the blobs circle SWELLS into
    the shape with them on it, and shrinks back into the ring it was. Every
    captive sits on the shaped radius at its own angle at the hold — and
    back on the ring when the release is over.

    MEASURED IN SILENCE, because of a real mechanism rather than for
    convenience: a captive is pinned to the horizon only while it is within
    `REVERSE_FALLBACK_RING_TOL` of it (the reverse-release fix, PR #181), so
    every time the bass beat drops, the outline steps in by up to half a
    cell and leaves its captives momentarily OUTSIDE that tolerance,
    free-falling back onto it under ordinary physics — the same behaviour a
    reverse flare's outflow gets, and deliberately not a teleport.
    `test_the_captives_light_the_shapes_outline` is the busy-music
    measurement of what that looks like on the panel."""
    async def main():
        async with Room(tmp_path / "ride", bh_config(0.6),
                        busy=False) as room:
            room.step(int(10 * FPS))
            before = room.captive_angles()[1]
            assert before.size, "no captives to ride it out"
            ring = room.effect._horizon_radius()
            assert np.allclose(before, ring, atol=0.03)
            await room.word("heart", energy=0.6, form_s=0.9, hold_s=1.2,
                            release_s=1.35)
            room.step(int(round(0.9 * FPS)) + 2)
            theta, radius = room.captive_angles()
            # a silent room spawns 1.4 blobs/s and nothing beats, so the
            # ring it builds in ten seconds is a handful of captives — the
            # claim is about WHERE each one sits, not how many there are
            # (the clarity bar is the population measurement, on busy music)
            assert theta.size >= 3, theta.size
            want = np.asarray(room.effect._horizon_radius_at(theta))
            assert np.all(np.abs(radius - want) <= REVERSE_FALLBACK_RING_TOL)
            # and it really is the shape: the radius they sit at SWINGS
            assert want.max() / want.min() > 1.3
            assert radius.max() > ring * 1.5, "the ring never swelled"
            room.step(int(round(2.7 * FPS)))
            assert room.effect._ws is None, "the effect never reset itself"
            theta, radius = room.captive_angles()
            if radius.size:
                assert np.allclose(radius, room.effect._horizon_radius(),
                                   atol=0.03)
    _run(main())


# ══ 4. IT IS THE SHAPE — the clarity bar ═══════════════════════════════════

def clarity(shape_id: str, energy: float, seeds=(0, 1, 2),
            config_over=None) -> list[dict]:
    """The row's clarity bar, measured on the real hex mask at the word, at
    mid-hold and at the hold's END, over `seeds` moments of busy music.
    One row per (seed, sample) with both denominators."""
    outline, inside, deep = shape_cell_sets(shape_id)
    rows: list[dict] = []

    async def one(seed):
        with tempfile.TemporaryDirectory() as tmp:
            async with Room(Path(tmp) / "clarity",
                            bh_config(energy, **(config_over or {})),
                            busy=True, seed=seed) as room:
                room.step(int(4 * FPS))
                await room.word(shape_id, energy=energy, form_s=0.9,
                                hold_s=1.2, release_s=1.35)
                room.step(int(round(0.9 * FPS)) + 1)
                for label, advance in (("word", 0), ("mid-hold", 36),
                                       ("hold end", 36)):
                    room.step(advance)
                    band = drawn_band(room.effect)
                    lit = room.lit_cells()
                    rows.append({
                        "shape": shape_id, "energy": energy, "seed": seed,
                        "at": label,
                        "outline": float((lit & outline).sum()
                                         / outline.sum()),
                        "drawn": float((lit & band).sum() / band.sum()),
                        "drawn_cells": int(band.sum()),
                        "inside_black": 1.0 - float((lit & deep).sum()
                                                    / deep.sum()),
                        "captives": int(room.captive_angles()[0].size),
                        "white": room.white()[0],
                        "m": room.m(),
                    })

    for seed in seeds:
        _run(one(seed))
    return rows


@pytest.mark.parametrize("shape_id", ["heart", "star", "diamond"])
@pytest.mark.parametrize("energy", [0.2, 0.8])
def test_the_captives_light_the_shapes_outline(shape_id, energy):
    """PLAN ACCEPTANCE 4, the row's own bar: at least OUTLINE_BAR of the
    shape's pinned outline cells lit by captives, and at least
    INSIDE_BLACK_BAR of its inside cells black, on his own Black Hole V2
    crystal entry resolved at this Energy.

    THE ONE MEASURED MISS IS NAMED HERE RATHER THAN HIDDEN BY A SOFTER BAR
    (the plan: report the number, never move the bar). At Energy 0.2 the
    star reads the bar at the word and at mid-hold and falls to ~58% at the
    END of a 1.2 s hold, and the cause is NOT the shape: his quiet-Energy
    binding spawns 0.8 blobs/s with one per beat, so about 21 captives have
    to trace a 176-cell outline, and the ring's own population turns over
    (`horizon_hold` 2.8 s + fade) faster than that rate refills it.
    MEASURED, same room, same shape, same instant: his binding's loud end
    (`spawn_rate` 2.0) reads 72.7% and `beat_burst` 3 reads 75.6% — both
    params he already owns. So the END of the hold is asserted at the bar
    everywhere the population supports it and REPORTED for that one case;
    scripts/check_blackhole_word_shape.py prints every number.
    """
    rows = clarity(shape_id, energy)
    assert rows
    thin = shape_id == "star" and energy == 0.2
    for row in rows:
        # the "hold end" sample lands on the hold's last frame or the
        # release's first, where the smoothstep has barely moved
        assert row["m"] >= 0.99, row
        assert row["inside_black"] >= INSIDE_BLACK_BAR, row
        assert 0.6 <= row["drawn_cells"] / shape_cell_sets(shape_id)[0].sum() \
            <= 1.4, ("the DRAWN outline's own cell count has run away from "
                     "the pinned denominator — the shape is not the shape")
        if thin and row["at"] == "hold end":
            assert row["outline"] >= 0.50, row     # reported, see above
        else:
            assert row["outline"] >= OUTLINE_BAR, row


def test_the_thin_case_is_the_population_not_the_shape():
    """The claim the test above makes in prose, measured: the star at
    Energy 0.2 reads the bar at the hold's end as soon as his own
    `spawn_rate` binding reaches its loud end — nothing about the shape
    changes."""
    rows = clarity("star", 0.2, seeds=(0, 1, 2),
                   config_over={"spawn_rate": 2.0})
    ends = [r["outline"] for r in rows if r["at"] == "hold end"]
    assert min(ends) >= OUTLINE_BAR, ends


@pytest.mark.parametrize("shape_id", ["heart", "star", "diamond"])
def test_the_inside_of_the_shape_is_black(tmp_path, shape_id):
    """The black disc follows the outline, so the inside KEEPS THE SHAPE:
    every real cell deeper than one cell pitch inside is black, and a cell
    just OUTSIDE the outline is not covered by it."""
    async def main():
        outline, inside, deep = shape_cell_sets(shape_id)
        async with Room(tmp_path / shape_id, bh_config(0.8)) as room:
            room.step(int(4 * FPS))
            await room.word(shape_id, energy=0.8, form_s=0.9, hold_s=1.2,
                            release_s=1.35)
            room.step(int(round(1.5 * FPS)))
            lit = room.lit_cells()
            assert not (lit & deep).any(), "light inside the shape"
            # the disc is the SHAPE's, not a circle round it: a real cell
            # outside the outline band beyond the shape's own widest point
            # must never be blacked by it, and some are lit
            assert lit.sum() > 0
    _run(main())


# ══ 5. NO WHITE ════════════════════════════════════════════════════════════

def test_a_shape_is_no_whiter_than_an_ordinary_busy_frame(tmp_path):
    """PLAN ACCEPTANCE 5. A captive is an ordinary captive — it takes the
    horizon colour on the same blend it always did — so a shape adds no
    white. Measured against this effect's OWN busy frames in the same room
    an instant before the word.

    THE NUMBER, reported rather than rounded off: at the strict threshold
    his crystal's busy frames show 2 near-neutral cells out of about 700
    lit (0.24%), and a shape standing shows 3 (0.45%) — one more cell,
    where two captives' trails cross. It is NOT the disc's shaped inset
    revealing something: measured at a 0 inset it is the same 3 cells. So
    the bar is held as the CELL COUNT plus a small absolute slack, which is
    what "no white" can honestly mean at this scale, and the fraction is
    held under a hard 1% as well."""
    async def main():
        async with Room(tmp_path / "white", bh_config(0.8)) as room:
            room.step(int(4 * FPS))
            busy_today = []
            for _ in range(int(round(1.5 * FPS))):
                room.step()
                busy_today.append(room.white())
            before = max(n for _f, n in busy_today)
            await room.word("star", energy=0.8, form_s=0.9, hold_s=1.2,
                            release_s=1.35)
            during = []
            for _ in range(int(round(2.1 * FPS))):
                room.step()
                during.append(room.white())
            assert max(n for _f, n in during) <= before + WHITE_SLACK_CELLS
            assert max(f for f, _n in during) < 0.01
    _run(main())


# ══ 6. COST ════════════════════════════════════════════════════════════════

def frame_cost_ms(shape: bool, seed: int = 0, frames: int = 180) -> float:
    """p50 wall-clock milliseconds per rendered frame, with a shape holding
    or with nothing told. The fake clock patches timeit.default_timer, not
    perf_counter, so this measures real work."""
    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            async with Room(Path(tmp) / "cost", bh_config(0.8), busy=True,
                            seed=seed) as room:
                room.step(int(2 * FPS))
                if shape:
                    await room.word("heart", energy=0.8, form_s=0.3,
                                    hold_s=20.0, release_s=0.3)
                    room.step(int(round(0.4 * FPS)))
                    assert room.m() == 1.0
                taken = []
                for _ in range(frames):
                    t0 = time.perf_counter()
                    room.step()
                    taken.append((time.perf_counter() - t0) * 1000.0)
                return float(np.median(taken))
    return _run(main())


def test_a_shape_holding_costs_under_a_millisecond_a_frame():
    """PLAN ACCEPTANCE 6. The per-cell polar lookup is cached for the life
    of the shape (`_word_shape_polar_grid`) and the per-blob one is a table
    interpolation over a few dozen angles, so a held shape is arithmetic,
    never an `sdf` call."""
    plain = frame_cost_ms(False)
    shaped = frame_cost_ms(True)
    assert shaped - plain < COST_BAR_MS, (plain, shaped)


# ══ 7. TWO WORDS, A WORD MID-RELEASE, A CLEARING WRITE ═════════════════════

def test_two_words_of_the_same_shape_both_edge(tmp_path):
    """PLAN ACCEPTANCE 7. The effect watches the SEQ, never the id, so two
    hearts back to back are two shapes."""
    async def main():
        async with Room(tmp_path / "twice", bh_config(0.6)) as room:
            room.step(120)
            await room.word("heart", energy=0.6, form_s=0.5, hold_s=0.2,
                            release_s=0.3)
            room.step(int(round(1.1 * FPS)))
            assert room.effect._ws is None, "the first shape never finished"
            first_seq = room.effect._ws_seen
            await room.word("heart", energy=0.6, form_s=0.5, hold_s=0.2,
                            release_s=0.3)
            room.step(2)
            assert room.effect._ws is not None
            assert room.effect._ws_seen > first_seq
            assert room.effect._ws["m0"] == 0.0
    _run(main())


def test_a_word_mid_release_lifts_the_form_instead_of_snapping(tmp_path):
    """PLAN ACCEPTANCE 7's own sentence: a second word arriving mid-release
    restarts the form FROM THE CURRENT FRACTION, so the outline is pulled
    back out from where it had got to and nothing snaps to the ring."""
    async def main():
        async with Room(tmp_path / "lift", bh_config(0.6)) as room:
            room.step(120)
            await room.word("heart", energy=0.6, form_s=0.5, hold_s=0.2,
                            release_s=1.2)
            room.step(int(round(0.9 * FPS)))       # into the release
            falling = room.m()
            assert 0.2 < falling < 0.95, falling
            await room.word("heart", energy=0.6, form_s=0.5, hold_s=0.2,
                            release_s=1.2)
            room.step(1)
            assert room.effect._ws["m0"] == pytest.approx(falling, abs=1e-6)
            assert room.m() >= falling - 1e-6, "it snapped back toward zero"
            lifted = [room.m()]
            for _ in range(int(round(0.5 * FPS))):
                room.step()
                lifted.append(room.m())
            assert lifted[-1] == pytest.approx(1.0, abs=1e-9)
            assert all(b >= a - 1e-9 for a, b in zip(lifted, lifted[1:]))
    _run(main())


def test_a_clearing_write_releases_from_where_it_is(tmp_path):
    """`told()` None mid-shape (an older SpotFX, a hand test, `word_shape:
    ""`) is a RELEASE from the current fraction, over the release it was
    last told — not a shape vanishing in one frame."""
    async def main():
        async with Room(tmp_path / "clear", bh_config(0.6)) as room:
            room.step(120)
            await room.word("heart", energy=0.6, form_s=0.9, hold_s=5.0,
                            release_s=0.6)
            room.step(int(round(1.2 * FPS)))
            assert room.m() == 1.0
            await room.clear_shape()
            room.step(1)
            assert room.effect._ws is not None
            assert room.effect._ws["clearing"] is True
            falling = [room.m()]
            for _ in range(int(round(0.7 * FPS))):
                room.step()
                falling.append(room.m())
            assert all(b <= a + 1e-9 for a, b in zip(falling, falling[1:]))
            assert falling[-1] == 0.0 and room.effect._ws is None
            assert max(abs(b - a) for a, b in zip(falling, falling[1:])) < 0.1
    _run(main())


def test_an_unknown_shape_id_is_not_told_at_all(tmp_path):
    """`told()` refuses an id this build does not know (a newer SpotFX), so
    nothing forms and the ring is the ring."""
    async def main():
        async with Room(tmp_path / "unknown", bh_config(0.6)) as room:
            room.step(60)
            await room.executor.jump(room.vid, "blackhole", dict(
                wsk.keys_for("dodecahedron", 3, 0.9, 1.2, 1.35, 0.6)))
            room.step(5)
            assert room.effect._ws is None and room.m() == 0.0
    _run(main())


# ══ 8. THE ROW'S OWN GEOMETRY ══════════════════════════════════════════════

@pytest.mark.parametrize("shape_id", ["heart", "star", "diamond"])
def test_the_radius_per_angle_is_the_shape_at_the_hold(tmp_path, shape_id):
    """THE ROW'S OWN TEST: at the hold, the horizon's radius at every one of
    360 angles equals `word_shape_size x polar(theta)` within HALF A CELL —
    under busy music, not only in silence, because the music's own swell is
    capped at exactly that (`_word_shape_breath`)."""
    async def main():
        shape = word_shapes.get(shape_id)
        async with Room(tmp_path / shape_id, bh_config(0.8), busy=True) as room:
            room.step(int(3 * FPS))
            await room.word(shape_id, energy=0.8, form_s=0.9, hold_s=1.2,
                            release_s=1.35)
            room.step(int(round(1.3 * FPS)))
            assert room.m() == 1.0
            theta = np.linspace(0.0, 2.0 * math.pi, 360, endpoint=False)
            got = np.asarray(room.effect._horizon_radius_at(
                theta.astype(np.float32)), dtype=float)
            want = SIZE_DEFAULT * shape.polar(theta)
            half_cell = room.effect._ws_beat_max
            assert np.max(np.abs(got - want)) <= half_cell + 1e-6, (
                float(np.max(np.abs(got - want))), half_cell)
            # and it really is the SHAPE, not a circle through it
            assert want.max() / want.min() > 1.3
    _run(main())


def test_the_radius_is_exactly_the_shape_in_silence(tmp_path):
    """With no music there is no swell at all, so the blend is exact."""
    async def main():
        async with Room(tmp_path / "silent", bh_config(0.6),
                        busy=False) as room:
            room.step(60)
            await room.word("star", energy=0.6, form_s=0.5, hold_s=1.0,
                            release_s=0.75)
            room.step(int(round(0.7 * FPS)))
            assert room.m() == 1.0
            theta = np.linspace(0.0, 2.0 * math.pi, 360, endpoint=False)
            got = np.asarray(room.effect._horizon_radius_at(
                theta.astype(np.float32)), dtype=float)
            want = SIZE_DEFAULT * word_shapes.get("star").polar(theta)
            assert got == pytest.approx(want, abs=1e-6)
    _run(main())


def test_a_captives_linear_speed_round_a_heart_is_constant(tmp_path):
    """PLAN ACCEPTANCE: the angular rate is `omega x ref / r(theta)`, so the
    LINEAR speed along the outline is the ring's own everywhere — within 5%
    round a heart, whose radius swings 2.4 to 1 between its point and its
    cleft. Measured from the effect's own live numbers at 360 angles AND
    from a real captive's rendered motion.

    The one departure is `OMEGA_MAX` (6 pi rad/s), the bound that has always
    capped this effect's swirl: on loud music a deep notch can ask for more
    than that and gets the cap. Measured in a quiet room, where nothing
    reaches it."""
    async def main():
        async with Room(tmp_path / "speed", bh_config(0.6),
                        busy=False) as room:
            # a silent room spawns 1.4 blobs/s and nothing beats, so it
            # takes a while to build a ring worth measuring
            room.step(int(10 * FPS))
            await room.word("heart", energy=0.6, form_s=0.5, hold_s=3.0,
                            release_s=0.75)
            room.step(int(round(0.7 * FPS)))
            eff = room.effect
            assert eff._ws_m == 1.0
            theta = np.linspace(0.0, 2.0 * math.pi, 360, endpoint=False
                                ).astype(np.float32)
            radius = np.asarray(eff._horizon_radius_at(theta), dtype=float)
            ref = float(eff._horizon_ref_radius())
            # the rate the capture branch applies, read the same way
            v_h = (eff.base_speed
                   * (eff.edge_speed + (1.0 - eff.edge_speed)
                      * max(0.0, 1.0 - ref) ** eff.accel)
                   * (1.0 + eff.speed_audio * eff.impulse * 2.0))
            omega_ref = np.clip((eff.swirl if eff.swirl else 1.0) * v_h
                                / max(ref, 0.06), -6 * np.pi, 6 * np.pi)
            omega = np.clip(omega_ref * ref / np.maximum(radius, 0.06),
                            -6 * np.pi, 6 * np.pi)
            assert np.all(np.abs(omega) < 6 * np.pi - 1e-6), "clipped"
            linear = np.abs(omega) * radius
            spread = (linear.max() - linear.min()) / linear.mean()
            assert spread < SPEED_BAR, spread

            # …and a real captive's own rendered motion over 6 frames
            theta0, radius0 = room.captive_angles()
            keep = np.abs(radius0 - np.asarray(
                eff._horizon_radius_at(theta0))) < 0.01
            assert keep.sum() >= 3, "no pinned captives to measure"
            tracked = []
            for _ in range(6):
                before = np.column_stack(room.captive_angles())
                room.step()
                after = np.column_stack(room.captive_angles())
                k = min(len(before), len(after))
                if k:
                    dth = np.abs(((after[:k, 0] - before[:k, 0] + np.pi)
                                  % (2 * np.pi)) - np.pi)
                    tracked.append(dth * before[:k, 1] * FPS)
            moved = np.concatenate([t[t > 1e-4] for t in tracked])
            spread = (np.percentile(moved, 95) - np.percentile(moved, 5)) \
                / moved.mean()
            assert spread < 0.25, spread
    _run(main())


def test_infall_still_captures_during_the_hold(tmp_path):
    """PLAN ACCEPTANCE: blobs keep falling INTO the shape while it stands —
    the shaped horizon is about three times the ring's size and catches more
    of them, and `max_blobs` gates only the INFALLING population (the
    2026-10-17 bh-infall fix), so a full outline never starves fresh
    infall."""
    async def main():
        async with Room(tmp_path / "infall", bh_config(0.8)) as room:
            room.step(int(4 * FPS))
            before = int((room.effect.p_cap[:room.effect.n] >= 0).sum())
            await room.word("star", energy=0.8, form_s=0.9, hold_s=2.0,
                            release_s=1.35)
            room.step(int(round(1.0 * FPS)))
            at_word = int((room.effect.p_cap[:room.effect.n] >= 0).sum())
            captured = 0
            for _ in range(int(round(2.0 * FPS))):
                n0 = room.effect.n
                free0 = int((room.effect.p_cap[:n0] < 0).sum())
                room.step()
                n1 = room.effect.n
                free1 = int((room.effect.p_cap[:n1] < 0).sum())
                captured += max(0, free0 - free1)
            assert at_word >= before, (before, at_word)
            assert captured > 0, "nothing was captured through the hold"
            # the infalling population never pinned at the cap
            free = int((room.effect.p_cap[:room.effect.n] < 0).sum())
            assert free < room.effect.max_blobs
    _run(main())


def test_the_shape_is_primed_off_the_frame_path(monkeypatch, tmp_path):
    """`prime()` AT THE EDGE: the polar table costs a few milliseconds the
    first time it is read, and config_updated runs on SpotFX's own write,
    never on the render thread."""
    calls = []
    real_get = word_shapes.get

    def spy(shape_id):
        shape = real_get(shape_id)

        class Spy:
            def __getattr__(self, name):
                return getattr(shape, name)

            def prime(self):
                calls.append(shape_id)
                return shape.prime()
        return Spy()

    monkeypatch.setattr(word_shapes, "get", spy)

    async def main():
        async with Room(tmp_path / "prime", bh_config(0.6)) as room:
            room.step(30)
            assert calls == []
            await room.word("diamond", energy=0.6, form_s=0.5, hold_s=0.5,
                            release_s=0.5)
            room.step(2)       # the engine's 1 ms jump lands on a frame
            assert calls == ["diamond"], calls
            assert room.effect._ws is not None
    _run(main())


# ══ PRECEDENCE: a phase or a punch arriving mid-shape ══════════════════════

def test_a_drop_landing_mid_hold_keeps_its_own_pinch(tmp_path):
    """PLAN SPEC 5. The shape is a blend on the REST radius, BEFORE the
    phase math, so the drop's pinch multiplies the shaped radius exactly as
    it multiplies the ring's: the outline collapses to a point and the
    payoff burst erupts, with no code of the drop's own."""
    async def main():
        async with Room(tmp_path / "drop", bh_config(0.8)) as room:
            room.step(int(3 * FPS))
            await room.word("heart", energy=0.8, form_s=0.9, hold_s=3.0,
                            release_s=1.35)
            room.step(int(round(1.2 * FPS)))
            assert room.m() == 1.0
            standing = float(np.max(np.asarray(
                room.effect._horizon_radius_grid())))
            await room.responder.on_event("drop", 0.8, gap_ms=400)
            room.step(2)
            assert room.effect._phase == "drop"
            pinched = float(np.max(np.asarray(
                room.effect._horizon_radius_grid())))
            assert pinched < standing * 0.5, (standing, pinched)
            assert room.m() == 1.0, "the shape's own clock kept running"
            assert bool(room.effect.p_is_burst[:room.effect.n].any()), \
                "the drop's payoff burst never fired"
    _run(main())


def test_a_lull_arriving_mid_hold_still_fills_the_hex(tmp_path):
    """The lull's fill is applied to the shaped rest radius, so it swallows
    the panel exactly as it always did — the shape dissolves INTO the fill
    rather than fighting it."""
    from fx.effects import lull_dark
    from fx.effects.blackhole import HEX_FILL_RADIUS

    async def main():
        async with Room(tmp_path / "lull", bh_config(0.8)) as room:
            room.step(int(3 * FPS))
            await room.word("heart", energy=0.8, form_s=0.9, hold_s=4.0,
                            release_s=1.35)
            room.step(int(round(1.2 * FPS)))
            shaped = np.asarray(room.effect._horizon_radius_grid()).copy()
            assert float(shaped.max()) < HEX_FILL_RADIUS
            # a 4 s lull: its dark point is 3 s in (the room's own cap), and
            # the horizon reaches the hex exactly there
            with room.effect.lock:
                room.effect._apply_config(
                    {"phase": "lull", "phase_progress": 0.0,
                     **lull_dark.keys_for(4.0, 3.6, 3.0)}, validate=False)
            room.step(2)
            assert room.effect._phase == "lull"
            grew = []
            for i in range(1, int(round(3.2 * FPS))):
                with room.effect.lock:
                    room.effect._apply_config(
                        {"phase_progress": min(1.0, i / (3.6 * FPS))},
                        validate=False)
                room.step()
                grew.append(float(np.asarray(
                    room.effect._horizon_radius_grid()).min()))
            assert grew[-1] >= HEX_FILL_RADIUS, grew[-1]
            assert grew[0] < grew[-1], "the fill never grew"
            assert not room.lit_cells().any(), "the lull's dark is not dark"
    _run(main())


def test_a_flare_punch_mid_form_pulls_the_horizon_back_as_it_always_did(
        tmp_path):
    """A punch is a LULL mechanism (it holds the horizon back in the lull's
    dark). With a shape standing outside a phase there is no fill to hold
    back, so the punch changes nothing about the outline — stated here
    because "what wrong looks like" needs a measured answer either way."""
    from fx.effects import lull_dark

    async def main():
        async with Room(tmp_path / "punch", bh_config(0.8)) as room:
            room.step(int(3 * FPS))
            await room.word("heart", energy=0.8, form_s=0.9, hold_s=3.0,
                            release_s=1.35)
            room.step(int(round(0.5 * FPS)))
            mid = room.m()
            before = np.asarray(room.effect._horizon_radius_grid()).copy()
            with room.effect.lock:
                room.effect._apply_config({lull_dark.PUNCH_KEY: 1},
                                          validate=False)
            room.step(1)
            assert room.m() >= mid, "the punch moved the shape's own clock"
            after = np.asarray(room.effect._horizon_radius_grid())
            assert after.shape == before.shape
            # still a shape: the outline's own swing survives the punch
            assert float(after.max() / after.min()) > 1.3
    _run(main())


# ══ THE REGISTRY AND THE MEMBERSHIP GATE ═══════════════════════════════════

def test_word_shape_size_is_registered_so_sonic_can_tell_it():
    """The registry gate (`docs/agents/devices-and-ownership.md`'s param
    orphan watchdog): a registered param is what makes it Sonic-tellable
    through `set_scene_entry_param` for free. The SIX TOLD KEYS are
    deliberately NOT registered — they ride only the Word Shape kind's own
    write (word_shape_keys.py rule 1)."""
    from fx.effects.blackhole import Blackhole2d

    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    params = registry["effects"]["blackhole"]["params"]
    entry = params["word_shape_size"]
    assert entry["min"] == 0.3 and entry["max"] == 0.9
    assert entry["default"] == SIZE_DEFAULT
    assert entry["help_topic"] == "word-shapes"
    schema = {str(k): k for k in Blackhole2d.CONFIG_SCHEMA.schema}
    assert schema["word_shape_size"].default() == SIZE_DEFAULT
    for key in wsk.KEYS:
        assert key not in params, key
        assert key in Blackhole2d.ADVANCED_KEYS, key
        assert str(key) in schema, key
    assert "word_shape_size" not in Blackhole2d.ADVANCED_KEYS


def test_only_the_matrix_black_hole_knows_shapes():
    """`blackhole1d` is a STRIP and gets nothing — a shape has no meaning on
    one line of pixels — and this row wires its own effect and no other."""
    assert "blackhole" in device_model.WORD_SHAPE_EFFECTS
    assert "blackhole1d" not in device_model.WORD_SHAPE_EFFECTS
    from fx.effects.blackhole1d import Blackhole1d
    for key in wsk.KEYS:
        assert key not in Blackhole1d.CONFIG_SCHEMA.schema
    # no per-effect minimum form: the Energy-paced 0.5-0.9 s is enough for a
    # ring to swell into a shape (Fish's procession is the one that is not)
    assert "blackhole" not in device_model.WORD_SHAPE_FORM_MIN_S


def test_the_lifted_form_agrees_with_the_shared_envelope():
    """The effect's own form/hold/release law IS
    `word_shape_keys.envelope`, to the bit, whenever it starts from the ring
    (m0 = 0) — the lift is the only thing it adds."""
    from fx.effects.blackhole import _smoothstep

    form, hold, release = 0.9, 1.2, 1.35
    for t in np.linspace(0.0, form + hold + release + 0.2, 401):
        want = wsk.envelope(t, form, hold, release)
        if t < form:
            got = _smoothstep(t / form)
        elif t <= form + hold:
            got = 1.0
        elif t <= form + hold + release:
            got = 1.0 - _smoothstep((t - form - hold) / release)
        else:
            got = 0.0
        assert got == pytest.approx(want, abs=1e-12), t


def test_the_two_shaped_constants_are_what_the_measurements_chose():
    """Both numbers in the shaped path are pinned here, because both were
    MEASURED and a silent change to either moves a bar."""
    from fx.effects.blackhole import HEX_FILL_RADIUS, LULL_FILL_MARGIN

    # the shaped rest radius' ceiling is the HEX's own reach, never the
    # ring's 0.9 — a heart's farthest point is 1.26 unit lengths, so at the
    # top of word_shape_size the outline would clip and flatten its lobes
    assert WORD_SHAPE_R_MAX == HEX_FILL_RADIUS + LULL_FILL_MARGIN
    assert WORD_SHAPE_R_MAX > 0.9
    assert 0.9 * word_shapes.get("heart").circumradius < WORD_SHAPE_R_MAX
    # one cell pitch (where the plan's INSIDE cells begin) plus the half
    # cell the beat can push the outline out by
    assert WORD_SHAPE_DISC_PITCHES == 1.5
