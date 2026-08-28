"""Frame-level proofs for the FISH CAMERA WINDOW (fx/effects/fish.py
`camera_follow`), on the real vendored render pipeline (fx.headless dummy
Matrix host at his crystal-mapper's 72x37 shape, audio silenced).

scripts/check_fish_camera.py is the measured, printed version of the same
runs — this file pins the properties the build has to hold:

  * `camera_follow = 0` never moves the window off the origin — the
    identity claim, proven within-branch and exactly, across the whole arc;
  * ORDINARY SWIMMING with the wake off is byte-identical to the PINNED
    merge-base, so a change to the wake or the phases provably did not
    leak into the fish's own kinematics or body render. That ref is PINNED
    and IMPORTED, never a moving branch: see `_load_master` below for how a
    moving ref silently retired the earlier version of this proof once, and
    why a skip was the wrong answer to it. It was MOVED FORWARD (2026-08-28)
    when the wake rework broke the older, stronger claim's premise — see
    scripts/check_fish_camera.py::BASELINE_REF for that reasoning.
  * the window at rest is the identity mapping, and it is at rest whenever
    the phase is not a charge or a lull;
  * the wake is anchored to the WATER: a moving window streams it past and
    away, and what rolls off an edge is dropped rather than wrapped;
  * every per-frame window step is inside its own cap, across seeds and
    across both charge->roam and lull->roam transitions;
  * the school is never lost.
"""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import fish as FX

REPO = Path(__file__).resolve().parent.parent
DT = 1.0 / 60.0
ROWS, COLS = 37, 72

# his live Matrix entry, at the state he is watching right now
HIS = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.5, "roam_scale": 0.75,
    "tether_scatter": 0.0, "reactivity_scale": 1.0, "speed_jump": 1.0,
    "speed_jog": 1.0, "brightness_audio": 0.5, "size_audio": 0.5,
    "color_shift": 1, "impulse_decay": 0.06, "reverse": False,
}


def _run(coro):
    return asyncio.run(coro)


class _Room:
    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm
        self.frame = None

    def step(self, frames=1, watch=None):
        for _ in range(frames):
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)
                self.frame = np.array(f, copy=True)
            if watch is not None:
                watch(self.effect)

    def ramp(self, phase, seconds, beats_every=None, watch=None):
        eff = self.effect
        eff.update_config({"phase": phase, "phase_progress": 0.0})
        frames = int(seconds / DT)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if beats_every and i % beats_every == 0:
                eff._beat_pending = True
            self.step(1, watch=watch)


async def _room(tmp_path, name, config=None, seed=5, effect_type="fish"):
    host = await headless.start_headless_host(
        str(tmp_path / name), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=name,
    )
    virtual = host.virtuals.get(name)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    effect = headless.attach_effect(
        host, virtual, effect_type, dict(config or HIS)
    )
    effect._rng = np.random.default_rng(seed)
    return _Room(host, virtual, clock, effect, cm)


async def _close(room):
    room._cm.__exit__(None, None, None)
    await room.host.shutdown()


# ── the pre-camera baseline, loaded as a second effect ─────────────────
# WHY THIS IS PINNED, AND WHY IT IS NOT A SKIP (Admiral's ruling, recorded
# here where the pin lives, not only in the PR):
#
#   This loader used to read the MOVING ref `master` and, on finding the
#   camera already there, call `pytest.skip("nothing to compare")`. That
#   named the true predecessor only while the camera lived on a feature
#   branch. Once it merged, the guard fired on EVERY run, forever — the
#   suite read "4 skipped, 0 failed", nobody looked twice, and the
#   guarantee that no edit can leak camera terms into the knob-zero path
#   was simply gone while everything looked healthy.
#
#   A FALSE ALARM IS LOUD AND GETS FIXED; A PERMANENT SKIP IS SILENT AND
#   READS AS GREEN. The skip was the safer-LOOKING choice and the worse
#   outcome. The instinct was reasonable — no blame — but the shape is
#   recorded so it is not repeated: when an instrument's reference moves
#   out from under it, PIN the reference; never silence the instrument.
#
#   The pin itself is IMPORTED from scripts/check_fish_camera.py's own
#   BASELINE_REF — never a second literal of the commit hash. One
#   baseline, one place; two copies drift apart and rebuild the same fault
#   in a new shape.
def _baseline_ref():
    """The pinned pre-camera commit, read from the check script itself."""
    path = REPO / "scripts" / "check_fish_camera.py"
    spec = importlib.util.spec_from_file_location("_fish_camera_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BASELINE_REF


def _load_master(name="fish_master_probe"):
    """Register the PINNED pre-camera fish.py beside the current one.

    An Effect subclass registers itself under its module's last name
    segment, so importing the baseline file under a different module name
    puts it in the registry next to `fish` and `create(type=...)` reaches
    it.
    """
    if name in sys.modules:
        return name
    ref = _baseline_ref()
    try:
        src = subprocess.run(
            ["git", "show", f"{ref}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except Exception as exc:                        # noqa: BLE001
        # A stated skip for a genuinely unavailable input (offline, shallow
        # clone) is fine — unlike the silent one this replaced, it names a
        # missing input rather than retiring the proof.
        pytest.skip(f"cannot read {ref}:fx/effects/fish.py out of git: {exc}")
    # The baseline must genuinely PREDATE this PR: it still has to carry
    # the camera (it is post-#210) and must NOT carry the wake rework. If
    # either is wrong the pin has drifted — a loud FAILURE, never a skip.
    assert "camera_follow" in src, (
        f"the pinned baseline {ref} predates the camera — the pin in "
        "scripts/check_fish_camera.py::BASELINE_REF has slipped backwards"
    )
    assert "_step_wake" not in src, (
        f"the pinned baseline {ref} already carries the wake rework — the "
        "pin in scripts/check_fish_camera.py::BASELINE_REF is wrong; this "
        "proof must fail loudly rather than skip itself into silence"
    )
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


# the whole arc, so the comparison covers ordinary swimming, both phases
# that move the window, the drop, and the settle back to roaming
_SCRIPT = (
    ("swim", 3.0, None),
    ("charge", 4.0, 12),
    ("lull", 3.5, None),
    ("drop", 5.0, None),
    ("swim", 3.0, None),
)


async def _frames(tmp_path, tag, cfg, seed, effect_type, script=None):
    room = await _room(tmp_path, tag, cfg, seed=seed, effect_type=effect_type)
    seq = []

    def grab(_eff=None):
        if room.frame is not None:
            seq.append(room.frame)

    for kind, secs, beats in (script or _SCRIPT):
        if kind == "swim":
            room.step(int(secs / DT), watch=grab)
        else:
            room.ramp(kind, secs, beats_every=beats, watch=grab)
    await _close(room)
    return np.array(seq)


# ── 1. THE IDENTITY CLAIM, and what this PR provably did not touch ─────
_SWIM_ONLY = (("swim", 6.0, None),)


@pytest.mark.parametrize("seed", (3, 5, 11, 17))
def test_the_window_at_zero_never_leaves_the_origin(tmp_path, seed):
    """The window at rest is the identity mapping (screen == world), so at
    `camera_follow = 0` the origin and its velocity must be EXACTLY zero on
    every frame of the whole arc — charge, lull, drop and roam alike, not
    "small"."""
    async def main():
        room = await _room(tmp_path, f"origin{seed}",
                           dict(HIS, particle_count=6, camera_follow=0.0),
                           seed=seed)
        worst = {"cam": 0.0, "vel": 0.0, "frames": 0}

        def grab(_eff=None):
            worst["cam"] = max(worst["cam"], abs(room.effect.cam_px),
                               abs(room.effect.cam_py))
            worst["vel"] = max(worst["vel"], abs(room.effect.cam_vx),
                               abs(room.effect.cam_vy))
            worst["frames"] += 1

        for kind, secs, beats in _SCRIPT:
            if kind == "swim":
                room.step(int(secs / DT), watch=grab)
            else:
                room.ramp(kind, secs, beats_every=beats, watch=grab)
        await _close(room)
        assert worst["frames"] > 500
        assert worst["cam"] == 0.0 and worst["vel"] == 0.0, worst
    _run(main())


def test_the_origin_trace_can_see_a_window_that_moves(tmp_path):
    """... and the trace above is not blind: at the shipped default the
    window really does leave the origin."""
    async def main():
        room = await _room(tmp_path, "origin-on",
                           dict(HIS, particle_count=6, camera_follow=0.8),
                           seed=5)
        worst = [0.0]

        def grab(_eff=None):
            worst[0] = max(worst[0], abs(room.effect.cam_px),
                           abs(room.effect.cam_py))

        room.ramp("charge", 4.0, beats_every=12, watch=grab)
        await _close(room)
        assert worst[0] > 1.0, worst
    _run(main())


@pytest.mark.parametrize("seed", (3, 5, 11, 17))
def test_swimming_with_the_wake_off_is_the_merge_base_bit_for_bit(
    tmp_path, seed
):
    """This PR reworks the wake and the two phases. Ordinary swimming, with
    the wake switched off, must therefore render EXACTLY what the pinned
    merge-base rendered — proven against that commit's OWN module, read out
    of git and registered beside this one, not against this file with a
    constant zeroed."""
    master = _load_master()
    cfg = dict(HIS, particle_count=6, camera_follow=0.0, ripple_amount=0.0)

    async def main():
        a = await _frames(tmp_path, f"m{seed}", cfg, seed, master,
                          script=_SWIM_ONLY)
        b = await _frames(tmp_path, f"z{seed}", cfg, seed, "fish",
                          script=_SWIM_ONLY)
        assert a.shape == b.shape and a.size, (a.shape, b.shape)
        assert np.array_equal(a, b), (
            "this PR changed ordinary swimming, which it must not: "
            f"{int(np.count_nonzero((a != b).any(axis=(1, 2))))} of "
            f"{a.shape[0]} frames differ"
        )
    _run(main())


def test_that_identity_is_not_vacuous_the_wake_is_what_changed(tmp_path):
    """... and with the wake ON, the same run must DIFFER from the
    merge-base, or the comparison above is comparing two blank runs."""
    master = _load_master()
    cfg = dict(HIS, particle_count=6, camera_follow=0.0)

    async def main():
        a = await _frames(tmp_path, "m-wake", cfg, 5, master,
                          script=_SWIM_ONLY)
        b = await _frames(tmp_path, "z-wake", cfg, 5, "fish",
                          script=_SWIM_ONLY)
        assert not np.array_equal(a, b), (
            "the wake rework rendered nothing new against the merge-base"
        )
    _run(main())


def test_the_byte_identity_proof_is_not_vacuous(tmp_path):
    """... and the window must actually do something at the shipped
    default, or the identity proof above says nothing."""
    async def main():
        off = await _frames(tmp_path, "v-off",
                            dict(HIS, particle_count=6, camera_follow=0.0),
                            5, "fish")
        on = await _frames(tmp_path, "v-on",
                           dict(HIS, particle_count=6, camera_follow=0.8),
                           5, "fish")
        assert not np.array_equal(off, on), (
            "camera_follow=0.8 rendered the same frames as 0 — the window "
            "is doing nothing"
        )
    _run(main())


# ── 2. the window moves ONLY during a charge or a lull ──────────────────
def test_the_window_moves_only_during_a_charge_or_a_lull(tmp_path):
    """His rule, literally: the view travels during those two phases and
    nowhere else. Ordinary roaming is the negative control — it must show
    no window motion at all, not merely a little — and the ease home has
    to actually FINISH, landing on exactly zero rather than a residue."""
    async def main():
        room = await _room(tmp_path, "only",
                           dict(HIS, camera_follow=1.0), seed=5)
        eff = room.effect
        moved = {}

        def watcher(key):
            state = {"cam": None, "sum": 0.0}
            moved[key] = state

            def watch(e):
                cam = (e.cam_px, e.cam_py)
                if state["cam"] is not None:
                    state["sum"] += float(np.hypot(
                        cam[0] - state["cam"][0], cam[1] - state["cam"][1]))
                state["cam"] = cam
            return watch

        def ease_home(tag):
            """Release the phase and let the window come back to rest."""
            eff.update_config({"phase": "none", "phase_progress": 0.0})
            for i in range(int(20.0 / DT)):
                room.step(1)
                if eff.cam_px == 0.0 and eff.cam_py == 0.0:
                    return i * DT
            raise AssertionError(
                f"the window never eased home after the {tag}: "
                f"({eff.cam_px:.4f}, {eff.cam_py:.4f})"
            )

        room.step(int(4.0 / DT), watch=watcher("roam"))
        room.ramp("charge", 4.0, beats_every=12, watch=watcher("charge"))
        home_after_charge = ease_home("charge")
        room.step(int(4.0 / DT), watch=watcher("roam-after-charge"))
        room.ramp("lull", 3.5, watch=watcher("lull"))
        lull_end = (eff.cam_px, eff.cam_py)
        home_after_lull = ease_home("lull")
        room.step(int(4.0 / DT), watch=watcher("roam-after-lull"))
        await _close(room)
        for quiet in ("roam", "roam-after-charge", "roam-after-lull"):
            assert moved[quiet]["sum"] == 0.0, (
                f"the window moved while just roaming ({quiet}): "
                f"{moved[quiet]['sum']:.4f}px"
            )
        assert moved["charge"]["sum"] > 5.0, (
            f"the window barely moved during the charge: "
            f"{moved['charge']['sum']:.4f}px"
        )
        # THE LULL NO LONGER HAS A SCHOOL TO FOLLOW. Under his 2026-08-28
        # clock every fish is gone by the first third, so the window's whole
        # job there is to ease home — asserting travel would be asserting
        # the superseded lull. It must simply END at rest.
        assert float(np.hypot(*lull_end)) < 1.0, (
            f"the window did not settle during the lull: {lull_end}"
        )
        assert home_after_charge < 15.0 and home_after_lull < 15.0, (
            f"the ease home dragged: {home_after_charge:.1f}s / "
            f"{home_after_lull:.1f}s"
        )
    _run(main())


# ── 3. the wake is anchored to the WATER ────────────────────────────────
def _wake_centroid(eff):
    w = eff.wake.sum(axis=2)
    tot = float(w.sum())
    if tot <= 0.0:
        return None
    ys, xs = np.mgrid[0:w.shape[0], 0:w.shape[1]]
    return float((xs * w).sum() / tot), float((ys * w).sum() / tot)


def test_the_wake_streams_past_the_window_and_is_never_carried(tmp_path):
    """The whole reason the world frame exists. The wake buffer is SCREEN
    space, so it is rolled every frame by exactly the displacement the
    world->screen mapping moved: a smear is LEFT BEHIND in the water and its
    screen position travels by the window's own travel, never carried along
    with the view.

    Measured on a PLANTED patch with deposits switched off, so nothing new
    lands in the buffer to drag the centroid around.
    """
    async def main():
        room = await _room(tmp_path, "wake",
                           dict(HIS, camera_follow=1.0, ripple_life=4.0,
                                ripple_amount=0.0, ripple_spread=0.0),
                           seed=5)
        eff = room.effect
        room.step(int(4.0 / DT))
        eff.wake[:] = 0.0
        cx, cy = eff.r_width // 2, eff.r_height // 2
        eff.wake[cy - 1:cy + 2, cx - 1:cx + 2, :] = 200.0

        track = {"first_s": None, "first_w": None, "last_s": None,
                 "last_w": None, "frames": 0}

        def watch(e):
            c = _wake_centroid(e)
            if c is None:
                return
            w = (c[0] + e.cam_px, c[1] + e.cam_py)
            if track["first_s"] is None:
                track["first_s"], track["first_w"] = c, w
            track["last_s"], track["last_w"] = c, w
            track["frames"] += 1

        room.ramp("charge", 2.5, beats_every=12, watch=watch)
        await _close(room)
        assert track["frames"] > 100, (
            f"the patch was not followed long enough ({track['frames']})"
        )
        # NET displacement, not path length: the roll is integer with a
        # sub-pixel remainder carried, so a per-frame path length is all
        # quantization jitter and says nothing about where the smear ended
        # up.
        screen = float(np.hypot(
            track["last_s"][0] - track["first_s"][0],
            track["last_s"][1] - track["first_s"][1]))
        world = float(np.hypot(
            track["last_w"][0] - track["first_w"][0],
            track["last_w"][1] - track["first_w"][1]))
        assert screen > 10.0, (
            "the wake never streamed past the window: "
            f"{screen:.2f}px of screen travel"
        )
        assert world < 1.5, (
            "the wake was carried along with the view instead of being left "
            f"in the water: it moved {world:.2f}px through the water while "
            f"travelling {screen:.2f}px across the panel"
        )
    _run(main())


def test_wake_rolled_off_an_edge_is_dropped_not_wrapped(tmp_path):
    """No wraparound artifacts. What the roll pushes past an edge is zeroed,
    so nothing folds back in on the other side — that IS the cull, and it
    needs no pad, because a pixel outside the buffer cannot light anything.
    """
    async def main():
        room = await _room(tmp_path, "cull",
                           dict(HIS, camera_follow=1.0, ripple_life=4.0,
                                ripple_amount=0.0, ripple_spread=0.0),
                           seed=5)
        eff = room.effect
        room.step(int(2.0 / DT))
        eff.wake[:] = 0.0
        eff.wake[:, 1, :] = 200.0          # one bright column, near the edge
        before = float(eff.wake.sum())
        assert before > 0.0
        far_edge_before = float(eff.wake[:, -3:, :].sum())
        # push the water hard to the LEFT for a few frames
        eff._flow_px = -600.0
        eff._flow_py = 0.0
        eff._cam_px_prev = eff.cam_px
        eff._cam_py_prev = eff.cam_py
        for _ in range(3):
            eff._step_wake(DT)
        assert float(eff.wake.sum()) < before * 0.02, (
            "the column survived being pushed off the edge"
        )
        assert float(eff.wake[:, -3:, :].sum()) <= far_edge_before + 1e-6, (
            "content reappeared on the far side — it must never wrap"
        )
        await _close(room)
    _run(main())


# ── 4. smoothness, across seeds and both transitions ────────────────────
@pytest.mark.parametrize("seed", (3, 5, 11, 17))
def test_no_window_step_ever_breaks_its_own_cap(tmp_path, seed):
    """One number bounds a frame's window travel — the pursuit, the ease
    and the leash all land inside it — so a rush, a beat turn or a lunge
    can never whip the view. Measured across the phase AND the ease home
    after it, which is where a snap would otherwise hide."""
    async def main():
        room = await _room(tmp_path, f"cap{seed}",
                           dict(HIS, camera_follow=1.0), seed=seed)
        eff = room.effect
        worst = [0.0]
        prev = {"cam": None}

        def watch(e):
            cam = (e.cam_px, e.cam_py)
            if prev["cam"] is not None:
                worst[0] = max(worst[0], float(np.hypot(
                    cam[0] - prev["cam"][0], cam[1] - prev["cam"][1])))
            prev["cam"] = cam

        room.step(int(3.0 / DT), watch=watch)
        room.ramp("charge", 4.0, beats_every=12, watch=watch)
        room.step(int(3.0 / DT), watch=watch)       # charge -> roam
        room.ramp("lull", 3.5, watch=watch)
        room.step(int(3.0 / DT), watch=watch)       # lull -> roam
        cap = FX.CAM_MAX_SPEED_X * eff.cruise_px * DT
        await _close(room)
        assert worst[0] <= cap + 1e-6, (
            f"a window step of {worst[0]:.4f}px broke its own "
            f"{cap:.4f}px cap"
        )
        assert worst[0] > 0.0, "the window never moved; the cap proves nothing"
    _run(main())


# ── 5. the school is never lost ─────────────────────────────────────────
@pytest.mark.parametrize("seed", (3, 5, 11, 17))
def test_the_school_never_leaves_the_window(tmp_path, seed):
    """The window follows only fish it can SEE, so its target is inside the
    panel by construction and only the lag can put the school off-centre.
    Measured per AXIS against that axis's own half-extent — the panel is
    72x37, so a radial number against the short axis would call a
    perfectly visible sideways offset 'lost'.

    Scoped to the CHARGE: under his 2026-08-28 lull clock there is no
    school in a lull to lose — every fish disperses and is gone by the
    first third, which is what the fish there are SUPPOSED to do. The
    window's lull behaviour is pinned by
    tests/test_fish.py::test_the_lull_window_eases_home_once_there_is_
    nothing_to_follow instead."""
    async def main():
        room = await _room(tmp_path, f"lost{seed}",
                           dict(HIS, particle_count=8, camera_follow=0.8),
                           seed=seed)
        eff = room.effect
        hx, hy = (COLS - 1) / 2.0, (ROWS - 1) / 2.0
        worst = [0.0]

        def watch(e):
            n = e.n
            live = np.flatnonzero(e.p_mode[:n] == 0)
            if live.size == 0:
                return
            cx = float(np.mean(e.p_x[live])) * e.sx - e.cam_px
            cy = float(np.mean(e.p_y[live])) * e.sy - e.cam_py
            worst[0] = max(worst[0], max(abs(cx) / hx, abs(cy) / hy))

        room.step(int(4.0 / DT))
        room.ramp("charge", 4.0, beats_every=12, watch=watch)
        await _close(room)
        assert worst[0] < 1.0, (
            "the school's centroid left the window: "
            f"{worst[0]:.2f} of the panel's half-extent"
        )
    _run(main())


# ── 6. the knob is declared where the app can see it ────────────────────
def test_camera_follow_is_registered_with_an_honest_note():
    import json
    reg = json.loads((REPO / "config" / "effect_params.json").read_text())
    meta = reg["effects"]["fish"]["params"]["camera_follow"]
    assert meta["default"] == 0.8
    assert reg["effects"]["fish"]["defaults"]["camera_follow"] == 0.8
    assert (meta["min"], meta["max"]) == (0.0, 1.0)
    assert meta["help_topic"] == "fish-camera-window"
    schema = FX.Fish2d.CONFIG_SCHEMA.schema
    key = next(k for k in schema if str(k) == "camera_follow")
    assert key.default() == meta["default"], (
        "the registry default and the effect's own schema default must "
        "agree — they are what a scene falls back to"
    )
    help_src = (REPO / "spectra" / "web" / "src" / "help"
                / "helpContent.ts").read_text()
    assert "'fish-camera-window'" in help_src
    linked = (REPO / "spectra" / "web" / "src" / "scenes" / "tabs"
              / "InitialSetTab.tsx").read_text()
    assert 'topic="fish-camera-window"' in linked, (
        "a help topic nothing links to is reachable only by guessing a "
        "search term"
    )
