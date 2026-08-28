"""Frame-level proofs for the FISH CAMERA WINDOW (fx/effects/fish.py
`camera_follow`), on the real vendored render pipeline (fx.headless dummy
Matrix host at his crystal-mapper's 72x37 shape, audio silenced).

scripts/check_fish_camera.py is the measured, printed version of the same
runs — this file pins the properties the build has to hold:

  * `camera_follow = 0` renders what MASTER renders, bit for bit. Not this
    file with a term switched off — master's own `fx/effects/fish.py`, read
    out of git and loaded as a second registered effect, so the control is
    the real predecessor.
  * the window at rest is the identity mapping, and it is at rest whenever
    the phase is not a charge or a lull;
  * ripples are anchored to the WATER: a moving window streams them past
    and away, and one far off-window is culled rather than wrapped;
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


# ── master, loaded as a second effect ───────────────────────────────────
def _load_master(name="fish_master_probe"):
    """Register master's own fish.py beside the current one.

    An Effect subclass registers itself under its module's last name
    segment, so importing master's file under a different module name puts
    it in the registry next to `fish` and `create(type=...)` reaches it.
    """
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", "master:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except Exception as exc:                        # noqa: BLE001
        pytest.skip(f"cannot read master's fish.py out of git: {exc}")
    if "camera_follow" in src:
        pytest.skip("master already carries the window; nothing to compare")
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


async def _frames(tmp_path, tag, cfg, seed, effect_type):
    room = await _room(tmp_path, tag, cfg, seed=seed, effect_type=effect_type)
    seq = []

    def grab(_eff=None):
        if room.frame is not None:
            seq.append(room.frame)

    for kind, secs, beats in _SCRIPT:
        if kind == "swim":
            room.step(int(secs / DT), watch=grab)
        else:
            room.ramp(kind, secs, beats_every=beats, watch=grab)
    await _close(room)
    return np.array(seq)


# ── 1. THE NEGATIVE CONTROL: camera_follow 0 IS master ──────────────────
@pytest.mark.parametrize("seed", (3, 5, 11, 17))
def test_camera_follow_zero_is_master_bit_for_bit(tmp_path, seed):
    """The window at rest is the identity mapping, so at 0 every expression
    it touches must reduce to the one it replaced. Proven against master's
    OWN module — not this file with a constant zeroed — over the whole arc.
    """
    master = _load_master()

    async def main():
        a = await _frames(tmp_path, f"m{seed}", dict(HIS, particle_count=6),
                          seed, master)
        b = await _frames(tmp_path, f"z{seed}",
                          dict(HIS, particle_count=6, camera_follow=0.0),
                          seed, "fish")
        assert a.shape == b.shape and a.size, (a.shape, b.shape)
        assert np.array_equal(a, b), (
            "camera_follow=0 must render exactly what master rendered: "
            f"{int(np.count_nonzero((a != b).any(axis=(1, 2))))} of "
            f"{a.shape[0]} frames differ"
        )
    _run(main())


def test_the_byte_identity_proof_is_not_vacuous(tmp_path):
    """... and the window must actually do something at the shipped
    default, or the proof above says nothing."""
    async def main():
        off = await _frames(tmp_path, "v-off",
                            dict(HIS, particle_count=6, camera_follow=0.0),
                            5, "fish")
        on = await _frames(tmp_path, "v-on",
                           dict(HIS, particle_count=6, camera_follow=0.8),
                           5, "fish")
        assert not np.array_equal(off, on), (
            "camera_follow=0.8 rendered the same frames as 0 — the window "
            "never moved"
        )
    _run(main())


def test_the_window_never_leaves_the_origin_at_zero(tmp_path):
    """Structural, alongside the frames: at 0 the camera is not merely
    small, it is exactly zero, so the mapping is the identity and not an
    approximation of one."""
    async def main():
        room = await _room(tmp_path, "cam0",
                           dict(HIS, camera_follow=0.0), seed=5)
        eff = room.effect
        worst = [0.0]

        def watch(e):
            worst[0] = max(worst[0], abs(e.cam_px), abs(e.cam_py),
                           abs(e.cam_vx), abs(e.cam_vy))

        room.step(int(3.0 / DT), watch=watch)
        room.ramp("charge", 4.0, beats_every=12, watch=watch)
        room.ramp("lull", 3.5, watch=watch)
        assert worst[0] == 0.0, f"the window moved at camera_follow=0: {worst[0]}"
        assert eff.cam_px == 0.0 and eff.cam_py == 0.0
        await _close(room)
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
        home_after_lull = ease_home("lull")
        room.step(int(4.0 / DT), watch=watcher("roam-after-lull"))
        await _close(room)
        for quiet in ("roam", "roam-after-charge", "roam-after-lull"):
            assert moved[quiet]["sum"] == 0.0, (
                f"the window moved while just roaming ({quiet}): "
                f"{moved[quiet]['sum']:.4f}px"
            )
        for phase in ("charge", "lull"):
            assert moved[phase]["sum"] > 5.0, (
                f"the window barely moved during the {phase}: "
                f"{moved[phase]['sum']:.4f}px"
            )
        assert home_after_charge < 15.0 and home_after_lull < 15.0, (
            f"the ease home dragged: {home_after_charge:.1f}s / "
            f"{home_after_lull:.1f}s"
        )
    _run(main())


# ── 3. ripples are anchored to the WATER ────────────────────────────────
def test_ripples_stream_past_the_window_and_are_never_carried(tmp_path):
    """The whole reason the world frame exists. A ring's STORED position is
    world, so when the window pans it is LEFT BEHIND in the water and its
    screen position moves by the window's own travel — never carried along
    with the view.

    Followed by planting one ring with a sentinel colour and finding it
    again each frame: the ripple buffer emits and compacts constantly, so
    matching by index would silently compare two different rings.
    """
    async def main():
        room = await _room(tmp_path, "wake",
                           dict(HIS, camera_follow=1.0, ripple_life=4.0),
                           seed=5)
        eff = room.effect
        room.step(int(4.0 / DT))
        mark = np.float32(0.123456)
        eff._emit_ripples(
            [0], np.array([eff.cx], dtype=np.float32),
            np.array([eff.cy], dtype=np.float32),
            np.array([1.0], dtype=np.float32),
            np.array([2.0], dtype=np.float32),
            np.array([0.0], dtype=np.float32),
            np.array([mark], dtype=np.float32),
        )
        track = {"w": None, "s": None, "world": 0.0, "screen": 0.0,
                 "frames": 0}

        def watch(e):
            hit = np.flatnonzero(e.r_grad[: e.rn] == mark)
            if hit.size != 1:
                return
            i = int(hit[0])
            w = (float(e.r_x[i]), float(e.r_y[i]))
            sc = (w[0] - e.cam_px, w[1] - e.cam_py)
            if track["w"] is not None:
                track["world"] += float(np.hypot(
                    w[0] - track["w"][0], w[1] - track["w"][1]))
                track["screen"] += float(np.hypot(
                    sc[0] - track["s"][0], sc[1] - track["s"][1]))
                track["frames"] += 1
            track["w"], track["s"] = w, sc

        room.ramp("charge", 4.0, beats_every=12, watch=watch)
        await _close(room)
        assert track["frames"] > 100, (
            f"the marked ring was not followed long enough "
            f"({track['frames']} frames)"
        )
        # at camera_follow=1 nothing pushes the water at all: the ring sits
        # exactly where it was dropped, for its whole life
        assert track["world"] == 0.0, (
            "a ripple moved through the water — it must be anchored to it: "
            f"{track['world']:.4f}px"
        )
        assert track["screen"] > 10.0, (
            "the wake never streamed past the window: "
            f"{track['screen']:.4f}px of screen travel"
        )
    _run(main())


def test_a_ripple_far_off_window_is_culled_not_wrapped(tmp_path):
    """No wraparound artifacts. A ring the window has left far behind is
    dropped from the buffer; nothing folds it back on the other side."""
    async def main():
        room = await _room(tmp_path, "cull",
                           dict(HIS, camera_follow=1.0, ripple_life=4.0),
                           seed=5)
        eff = room.effect
        room.step(int(4.0 / DT))
        # plant a ring far outside any window this run can reach
        far = eff.r_width * 40.0
        eff._emit_ripples(
            [0], np.array([far], dtype=np.float32),
            np.array([0.0], dtype=np.float32),
            np.array([1.0], dtype=np.float32),
            np.array([2.0], dtype=np.float32),
            np.array([0.0], dtype=np.float32),
            np.array([0.5], dtype=np.float32),
        )
        assert np.any(np.isclose(eff.r_x[: eff.rn], far))
        room.step(2)
        assert not np.any(np.isclose(eff.r_x[: eff.rn], far)), (
            "an off-window ripple survived — it must be culled"
        )
        # ... and nothing reappeared on the other side
        screen = eff.r_x[: eff.rn] - eff.cam_px
        assert np.all(np.abs(screen) < eff.r_width + FX.RIPPLE_CULL_PAD + 1)
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
    perfectly visible sideways offset 'lost'."""
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
        room.ramp("lull", 3.5, watch=watch)
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
