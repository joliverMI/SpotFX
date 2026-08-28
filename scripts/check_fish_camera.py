"""Measure the fish CAMERA WINDOW (fx/effects/fish.py `camera_follow`).

Read-only, offline, no live access: drives the real vendored effect through
fx.headless at his crystal-mapper's 72x37 shape and measures, with negative
controls, the four things the window has to be true about.

  1  BYTE-IDENTITY against master. `camera_follow = 0` must render the
     frames master renders — not approximately, bit for bit. Master's own
     `fx/effects/fish.py` is read straight out of git and loaded as a second
     effect, so this compares against the real predecessor rather than
     against this file with a term switched off. NOTE: an inert-at-zero
     identity claim must compare against the predecessor's own module from
     git at a PINNED merge-base commit, never a moving ref (post-merge
     `master` IS the camera code, which false-alarms at its own default)
     and never this file with the term switched off.
  2  THE POINT OF THE FEATURE, measured and reported honestly. The charge
     ALREADY streamed the water past on master — its clamp subtracted the
     school's whole velocity from every fish, which is a window locked
     rigidly to the shoal. So the charge's gain is not "ripples now move",
     it is that the SCHOOL moves too (master pins it), that the window's
     speed is its own rather than the swim speed, and that a beat turn no
     longer snaps the water's direction. The LULL had no window motion at
     all before this, so there the wake scroll really does go from nothing
     to something.
  3  SMOOTHNESS. No per-frame camera step above the cap, across seeds and
     across both charge->roam and lull->roam transitions.
  4  THE SCHOOL IS NEVER LOST. Its centroid stays inside the window for
     every seed, through both phases.

Plus the sweep the shipped default was picked from, run at HIS live scene
state (jiggle 0.5, roam_scale 0.75, particle_count over its intensity-bound
1-8 range).

    .venv/bin/python scripts/check_fish_camera.py
    .venv/bin/python scripts/check_fish_camera.py --baseline <git-ref>
"""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# THE PINNED PREDECESSOR — moved forward 2026-08-28 by
# fm/fish-ripples-charge-lull-rework, and here is why it had to move.
#
# It used to be the PRE-CAMERA commit c1f32a0, and section 1 asserted that
# `camera_follow=0` rendered that commit's frames bit for bit. That claim
# needed a reference differing from this file ONLY by the camera. The wake
# rework changes the render at knob zero (the ripples are a different
# mechanism now) and the charge/lull rework changes those phases, so no such
# reference exists any more: left alone, the instrument would have
# false-alarmed on every run the moment this merged.
#
# So the pin moves to THIS PR's own merge-base, and section 1's claim is
# restated to the two things that ARE still provable and can still fail:
#   1a. the window at rest never leaves the origin — within-branch, exact,
#       across the whole arc (that IS the identity claim);
#   1b. ORDINARY SWIMMING with the wake off is byte-identical to the
#       merge-base — so this PR provably changed nothing about the fish's
#       kinematics or its body render, only the wake and the two phases.
# Both keep the same negative controls. Override with --baseline <ref>.
BASELINE_REF = "801ad9395b618af4681c94c812ea1b47d69b3921"
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


# ── the harness ─────────────────────────────────────────────────────────
class Room:
    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm
        self.frame = None

    def step(self, frames=1):
        for _ in range(frames):
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)
                self.frame = np.array(f, copy=True)

    def phase(self, phase, seconds, beats_every=None, watch=None):
        eff = self.effect
        eff.update_config({"phase": phase, "phase_progress": 0.0})
        frames = int(seconds / DT)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if beats_every and i % beats_every == 0:
                eff._beat_pending = True
            self.step(1)
            if watch is not None:
                watch(eff)


async def room(tag, config=None, seed=5, effect_type="fish"):
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS, device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(
        host, virtual, effect_type, dict(config or HIS)
    )
    eff._rng = np.random.default_rng(seed)
    return Room(host, virtual, clock, eff, cm)


async def close(r):
    r._cm.__exit__(None, None, None)
    await r.host.shutdown()


# ── 1. byte-identity against the real master module ─────────────────────
def load_master_effect(name="fish_master", ref=None):
    """Load the pre-camera baseline's fish.py as a SECOND registered effect.

    An Effect subclass registers itself under its module's last name
    segment, so importing master's file under a different module name puts
    it in the registry beside the current one and `create(type=...)` reaches
    it. Returns the registry key, or None if git cannot produce the ref
    (a STATED skip — never a silent pass).
    """
    ref = ref or BASELINE_REF
    try:
        src = subprocess.run(
            ["git", "show", f"{ref}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
    except Exception as exc:                       # noqa: BLE001
        print(f"  (skipped: cannot read {ref}:fx/effects/fish.py — {exc})")
        return None
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


async def frames_of(tag, cfg, seed, effect_type, script):
    r = await room(tag, cfg, seed=seed, effect_type=effect_type)
    seq = []

    def grab():
        if r.frame is not None:
            seq.append(r.frame)

    for kind, arg, beats in script:
        if kind == "swim":
            for _ in range(int(arg / DT)):
                r.step(1)
                grab()
        else:
            r.phase(kind, arg, beats_every=beats, watch=lambda _e: grab())
    await close(r)
    return np.array(seq)


SCRIPT = [
    ("swim", 4.0, None),
    ("charge", 4.0, 12),
    ("lull", 3.5, None),
    ("drop", 5.0, None),
    ("swim", 3.0, None),
]


SWIM_ONLY = [("swim", 6.0, None)]


def section_one(ref=None):
    """1a: the window at rest never leaves the origin (the identity claim).
    1b: ordinary swimming with the wake OFF is byte-identical to the
        merge-base — so this PR touched the wake and the two phases, and
        nothing about the fish's own kinematics or body render.
    """
    ref = ref or BASELINE_REF
    print("\n1a WINDOW AT REST — camera_follow=0 never leaves the origin")
    residues = []
    for seed in (3, 5, 11, 17):
        rec = camera_origin_trace(seed)
        residues.append(rec)
        print(f"   seed {seed:>2}: {rec['frames']:>4} frames  "
              f"max |cam| = {rec['max']:.3g}  "
              f"max |cam_v| = {rec['maxv']:.3g}")
        if rec["max"] != 0.0 or rec["maxv"] != 0.0:
            raise SystemExit("the window moved at camera_follow=0")
    # the proof must not be vacuous
    on = camera_origin_trace(5, cf=0.8)
    print(f"   control: camera_follow=0.8 -> max |cam| = {on['max']:.2f}px "
          f"(so the trace can see movement)")
    if on["max"] <= 0.0:
        raise SystemExit("the origin trace is blind")

    print(f"\n1b SWIMMING, WAKE OFF  vs merge-base {ref[:12]}")
    master = load_master_effect(ref=ref)
    if master is None:
        return
    off = dict(HIS, particle_count=6, camera_follow=0.0, ripple_amount=0.0)
    for seed in (3, 5, 11, 17):
        a = asyncio.run(frames_of(f"m{seed}", off, seed, master, SWIM_ONLY))
        b = asyncio.run(frames_of(f"z{seed}", off, seed, "fish", SWIM_ONLY))
        same = a.shape == b.shape and np.array_equal(a, b)
        print(f"   seed {seed:>2}: {a.shape[0]:>4} frames  "
              f"{'IDENTICAL' if same else 'DIFFER'}")
        if not same:
            raise SystemExit(
                "this PR changed ordinary swimming — it must not"
            )
    # ... and the wake IS what changed, or the comparison above is vacuous
    on_cfg = dict(HIS, particle_count=6, camera_follow=0.0)
    a = asyncio.run(frames_of("m-wake", on_cfg, 5, master, SWIM_ONLY))
    b = asyncio.run(frames_of("z-wake", on_cfg, 5, "fish", SWIM_ONLY))
    print(f"   control: with the wake ON, the same run differs from the "
          f"merge-base -> {not np.array_equal(a, b)}")
    if np.array_equal(a, b):
        raise SystemExit("the wake rework rendered nothing new")


def camera_origin_trace(seed, cf=0.0):
    """Run the whole arc and report the largest window origin/velocity seen."""
    async def main():
        r = await room(f"origin-{cf}-{seed}",
                       dict(HIS, particle_count=6, camera_follow=cf),
                       seed=seed)
        rec = {"max": 0.0, "maxv": 0.0, "frames": 0}

        def grab(_e=None):
            rec["max"] = max(
                rec["max"], abs(r.effect.cam_px), abs(r.effect.cam_py))
            rec["maxv"] = max(
                rec["maxv"], abs(r.effect.cam_vx), abs(r.effect.cam_vy))
            rec["frames"] += 1

        for kind, arg, beats in SCRIPT:
            if kind == "swim":
                for _ in range(int(arg / DT)):
                    r.step(1)
                    grab()
            else:
                r.phase(kind, arg, beats_every=beats, watch=grab)
        await close(r)
        return rec
    return asyncio.run(main())


# ── 2/3/4. what the window actually does ────────────────────────────────
def observe(cf, seed, phase, seconds, beats=None, count=3, settle=4.0,
            roam_after=0.0):
    """Run one phase (optionally followed by a stretch of ordinary roaming,
    to cover the phase->roam transition) and report what moved, in SCREEN
    px."""
    async def main():
        r = await room(f"o-{phase}-{cf}-{seed}-{count}-{roam_after}", dict(
            HIS, particle_count=count, camera_follow=cf), seed=seed)
        eff = r.effect
        r.step(int(settle / DT))
        rec = {
            "water": 0.0,      # px the water streams past the window
            "school": 0.0,     # px the school travels ACROSS the window
            "cam": 0.0,        # px the window itself travels
            "fish": 0.0,       # px a fish travels through the water
            "step_max": 0.0,   # worst single-frame window step
            "off_max": 0.0,    # worst school offset from the window centre
            "flow_jerk": 0.0,  # worst single-frame change of water velocity
            "frames": 0,
        }
        state = {
            "cam": (eff.cam_px, eff.cam_py),
            "cen": None,
            "wv": (0.0, 0.0),
            "pos": None,
        }

        def watch(e):
            n = e.n
            live = np.flatnonzero(e.p_mode[:n] == 0)
            if live.size == 0:
                live = np.flatnonzero(e.p_mode[:n] < 2)
            hx, hy = (COLS - 1) / 2.0, (ROWS - 1) / 2.0
            cam = (e.cam_px, e.cam_py)
            dcx, dcy = cam[0] - state["cam"][0], cam[1] - state["cam"][1]
            # the water's own screen displacement this frame: the current it
            # is carried by, minus the window's own move
            wx = e._flow_px * DT - dcx
            wy = e._flow_py * DT - dcy
            rec["water"] += float(np.hypot(wx, wy))
            rec["cam"] += float(np.hypot(dcx, dcy))
            rec["step_max"] = max(rec["step_max"], float(np.hypot(dcx, dcy)))
            wv = (wx / DT, wy / DT)
            rec["flow_jerk"] = max(rec["flow_jerk"], float(np.hypot(
                wv[0] - state["wv"][0], wv[1] - state["wv"][1])))
            state["wv"] = wv
            state["cam"] = cam
            if live.size:
                cen = (float(np.mean(e.p_x[live])) * e.sx,
                       float(np.mean(e.p_y[live])) * e.sy)
                scr = (cen[0] - cam[0], cen[1] - cam[1])
                # per AXIS, against that axis's own half-extent: the panel
                # is 72x37, so a radial number against the short axis would
                # call a perfectly visible sideways offset "lost"
                rec["off_max"] = max(rec["off_max"], float(max(
                    abs(scr[0]) / hx, abs(scr[1]) / hy)))
                if state["cen"] is not None:
                    rec["school"] += float(np.hypot(
                        scr[0] - state["cen"][0], scr[1] - state["cen"][1]))
                    rec["fish"] += float(np.hypot(
                        cen[0] - state["pos"][0], cen[1] - state["pos"][1]))
                state["cen"] = scr
                state["pos"] = cen
            rec["frames"] += 1

        r.phase(phase, seconds, beats_every=beats, watch=watch)
        for _ in range(int(roam_after / DT)):
            r.step(1)
            watch(eff)
        rec["cruise"] = eff.cruise_px
        rec["cap"] = FX.CAM_MAX_SPEED_X * eff.cruise_px * DT
        rec["half"] = min((COLS - 1) / 2.0, (ROWS - 1) / 2.0)
        rec["leash"] = FX.CAM_LEASH * rec["half"]
        await close(r)
        return rec
    return asyncio.run(main())


def section_two():
    print("\n2  WHAT MOVES  (px over the phase; his state, seed 5, 3 fish)")
    for phase, secs, beats in (("charge", 4.0, 12), ("lull", 3.5, None)):
        print(f"\n   {phase.upper()}  ({secs:.1f}s)")
        print(f"   {'cam_follow':>10} {'water px':>9} {'window px':>10} "
              f"{'school on screen':>17} {'water px/s':>11} "
              f"{'window px/s':>12}")
        for cf in (0.0, 0.4, 0.8, 1.0):
            g = observe(cf, 5, phase, secs, beats)
            t = g["frames"] * DT
            print(f"   {cf:>10.2f} {g['water']:>9.1f} {g['cam']:>10.1f} "
                  f"{g['school']:>17.1f} {g['water']/t:>11.2f} "
                  f"{g['cam']/t:>12.2f}")
        print(f"   (cruise is {observe(0.0, 5, phase, 0.2)['cruise']:.2f} "
              f"px/s — the speed the shoal swims at)")


def section_three():
    print("\n3  SMOOTHNESS  each run is the phase PLUS 3s of ordinary "
          "roaming after it,\n   so the phase->roam ease home is inside "
          "every number.\n   Worst single-frame window step, and the worst "
          "single-frame\n   change in the water's own apparent step "
          "(camera_follow 0 is the control:\n   master's clamp flips the "
          "water's direction the instant the school turns)")
    print(f"   {'seed':>5} {'phase':>8} {'cam_follow':>10} {'step px':>9} "
          f"{'cap px':>8} {'water d-step px':>16}")
    worst = 0.0
    for seed in (3, 5, 11, 17):
        for phase, secs, beats in (("charge", 4.0, 12), ("lull", 3.5, None)):
            for cf in (0.0, 1.0):
                g = observe(cf, seed, phase, secs, beats, roam_after=3.0)
                if cf > 0:
                    worst = max(worst, g["step_max"] / g["cap"])
                print(f"   {seed:>5} {phase:>8} {cf:>10.2f} "
                      f"{g['step_max']:>9.4f} {g['cap']:>8.4f} "
                      f"{g['flow_jerk'] * DT:>16.4f}")
    print(f"   worst window step / its own cap, every seed and phase: "
          f"{worst:.3f}")
    if worst > 1.0 + 1e-6:
        raise SystemExit("a window step broke its own cap")


def section_four():
    print("\n4  THE SCHOOL IS NEVER LOST  (its centroid, in screen px from "
          "the middle)")
    half = min((COLS - 1) / 2.0, (ROWS - 1) / 2.0)
    print(f"   {'seed':>5} {'phase':>8} {'worst / half':>13} "
          f"{'off panel at':>11} {'verdict':>7}")
    for seed in (3, 5, 11, 17):
        for phase, secs, beats in (("charge", 4.0, 12), ("lull", 3.5, None)):
            g = observe(1.0, seed, phase, secs, beats)
            print(f"   {seed:>5} {phase:>8} {g['off_max']:>13.2f} "
                  f"{1.0:>11.2f} "
                  f"{'ok' if g['off_max'] < 1.0 else 'LOST':>7}")


def section_five():
    print("\n5  THE SWEEP the default was picked from — his live scene "
          "state (jiggle 0.5,\n   roam_scale 0.75), averaged over 3 seeds "
          "x particle_count 1 and 8 (the ends\n   of its intensity-bound "
          "range). "
          "'school px' is how far the shoal travels ACROSS\n   the window; "
          "'water px' is how far the wake streams past it.")
    seeds = (3, 11, 17)
    counts = (1, 8)
    for phase, secs, beats in (("charge", 4.0, 12), ("lull", 3.5, None)):
        print(f"\n   {phase.upper()}")
        print(f"   {'cam_follow':>10} {'school px':>10} {'water px':>9} "
              f"{'window px/s':>12} {'worst / half':>13} {'verdict':>8}")
        for cf in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            school = water = cam = 0.0
            worst = 0.0
            runs = 0
            for seed in seeds:
                for count in counts:
                    g = observe(cf, seed, phase, secs, beats, count=count)
                    school += g["school"]
                    water += g["water"]
                    cam += g["cam"] / (g["frames"] * DT)
                    worst = max(worst, g["off_max"])
                    runs += 1
            print(f"   {cf:>10.2f} {school/runs:>10.1f} {water/runs:>9.1f} "
                  f"{cam/runs:>12.2f} {worst:>13.2f} "
                  f"{'ok' if worst < 1.0 else 'LOST':>8}")


if __name__ == "__main__":
    _baseline = BASELINE_REF
    if "--baseline" in sys.argv:
        _baseline = sys.argv[sys.argv.index("--baseline") + 1]
    print("FISH CAMERA WINDOW — measured, offline, against his own state")
    section_one(_baseline)
    section_two()
    section_three()
    section_four()
    section_five()
    print("\ndone.")
