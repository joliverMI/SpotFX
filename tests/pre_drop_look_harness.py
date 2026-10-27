"""THE PRE-DROP LOOKS' RIG (predrop plan steps 6-8): every member driven
through a whole charge -> lull -> drop with the LULL ARM THE REAL ENGINE
WRITES — read off the production scene_response._drive_phase through
tests/pre_drop_arm_harness.py, never retyped — and, beside them, the same
two modules as they were before their looks (pinned out of git), driven with
today's arm. Shared by tests/test_pre_drop_looks.py and
scripts/render_predrop_storyboards.py, so the proofs and the storyboards
measure one thing.

Times are the effect's own: frame k of a phase sits k x DT into it.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fx.effects import phase_grammar, pre_drop  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72
# origin/master just before the looks: fireworks.py and pulse.py without
# their pre-drop (the engine itself is already there) ...
PRE_REF = "34ce2b14f319a5c4af6a6b8d1bbf5e7f10dcdda0"
# ... and just before step 7's: orbits.py and blackhole.py without theirs
STEP7_REF = "29778cf327f50268408b433fc4f8067ea9afacae"
# ... and just before step 8's: fish.py, radial.py and sauron.py without theirs
STEP8_REF = "ed8b20087520d2b78ddd8f4c0248d946b9ecb09c"
NEW_KEYS = set(pre_drop.KEYS)


def crystal_real_mask() -> Optional[np.ndarray]:
    """His crystal's 976 real cells (storage/device_profiles/
    crystal-mapper.json's run lengths); None when the profile is absent."""
    path = REPO / "storage" / "device_profiles" / "crystal-mapper.json"
    if not path.exists():
        return None
    mask, value = [], False
    for run in json.loads(path.read_text())["mask_rle"]:
        mask.extend([value] * run)
        value = not value
    return np.array(mask, dtype=bool)


def load_pinned(module: str, name: str, must_lack: str,
                ref: str = PRE_REF) -> str:
    """fx/effects/<module>.py at `ref`, registered as `name` (the effect
    registry keys effects by module), so a rig can attach it beside today's.
    Raises RuntimeError when git cannot give it."""
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{ref}:fx/effects/{module}.py"], cwd=REPO,
            capture_output=True, text=True, check=True, timeout=60).stdout
    except Exception as exc:                              # noqa: BLE001
        raise RuntimeError(f"cannot read {ref} out of git: {exc}") from exc
    if must_lack in src:
        raise RuntimeError(f"the pinned {module}.py already has {must_lack!r}")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return name


# ── the engine's own lull arm ─────────────────────────────────────────────

def _scene_dict(matrix: str = "fireworks",
                strips: Optional[str] = None) -> dict:
    from spectra.models.scene import SceneV2
    devices = [{"target_kind": "category", "target": "Matrix",
                "effect_type": matrix}]
    if strips is not None:
        devices.append({"target_kind": "category", "target": "Strips",
                        "effect_type": strips})
    devices.append({"target_kind": "category", "target": "Singles",
                    "effect_type": "pulse"})
    return SceneV2(name="Pre-drop looks",
                   devices=devices).model_dump(mode="json")


@dataclass
class Arm:
    params: dict          # the jump the effect receives at the phase's edge
    ramp_s: float         # what phase_progress then glides over


def engine_arms(effect_type: str, lull_s: float, at_s: Optional[float] = None,
                gap_s: Optional[float] = None, kind: str = "spike",
                intensity: float = 0.8,
                scene: Optional[dict] = None) -> dict[str, Arm]:
    """The charge, lull and drop arms production writes to `effect_type`'s
    virtual for a lull of `lull_s` to its drop, carrying a pre-drop `kind`
    `at_s` into the lull and `gap_s` before the drop when given (`scene`: a
    whole scene to read them from — Star's carries its strip)."""
    from spectra.services.pre_drop_play import PreDropCandidate
    from tests import pre_drop_arm_harness as harness
    if scene is None:
        scene = _scene_dict(effect_type if effect_type != "pulse"
                            else "fireworks")
    out = {}
    for cls in ("charge", "lull", "drop"):
        cand = None
        if cls == "lull" and at_s is not None:
            cand = PreDropCandidate(at_ms=int(round(at_s * 1000)),
                                    gap_ms=int(round(gap_s * 1000)),
                                    kind=kind, key="k")
        gap_ms = int(round(lull_s * 1000)) if cls == "lull" else 3000
        writes = harness.arm_writes(scene, cls, gap_ms, intensity, 0.85,
                                    pre_drop=cand)
        mine = [w for w in writes if w["effect_type"] == effect_type]
        jump = next(w for w in mine if w["kind"] == "jump")
        glide = next((w for w in mine if w["kind"] == "glide"), None)
        out[cls] = Arm(dict(jump["params"]),
                       (glide["duration_ms"] / 1000.0) if glide else 0.0)
    return out


def todays_arm(arm: Arm, effect_type: str) -> Arm:
    """What the code before the looks wrote: the untold member arm without
    the told keys (and without the zero breath a no-breath-hold member gets)
    — tests/test_pre_drop_arm_identity.py proves the two equal."""
    from fx import device_model
    p = {k: v for k, v in arm.params.items() if k not in NEW_KEYS}
    if effect_type not in device_model.BREATH_HOLD_EFFECTS:
        for k in phase_grammar.BREATH_KEYS:
            p.pop(k, None)
    return Arm(p, arm.ramp_s)


# ── a run ────────────────────────────────────────────────────────────────

@dataclass
class Run:
    frames: list = field(default_factory=list)   # rendered output per frame
    phase: list = field(default_factory=list)    # (phase, seconds into it)
    info: list = field(default_factory=list)     # per-frame effect state


def schedule(charge_s: float, lull_s: float, drop_s: float,
             settle_s: float = 1.5):
    return (("none", settle_s), ("charge", charge_s), ("lull", lull_s),
            ("drop", drop_s))


# ── a crystal member on the crystal ──────────────────────────────────────

_TAG = [0]

FIREWORKS_CFG = {"gradient": "linear-gradient(90deg, #00b3ff 0%, #7a00ff 100%)",
                 "spawn_rate": 3.0}
# step 7's members, as the tests and the storyboards both drive them
STEP7_CFG = {
    "orbits": {"gradient": FIREWORKS_CFG["gradient"]},
    "blackhole": {"gradient": FIREWORKS_CFG["gradient"], "horizon_scale": 0.2,
                  "blob_size": 1.75, "swirl": 0.0, "horizon_audio": 0.3,
                  "base_speed": 2.0, "accel": 5.0, "spawn_rate": 30.0,
                  "beat_burst": 0, "spawn_audio": 1.5, "speed_audio": 2.0,
                  "max_blobs": 50, "edge_speed": 0.2, "horizon_hold": 2.8},
}
# what step 7's pinned modules must lack (each look's own constants)
STEP7_LACKS = {"orbits": "PRE_DROP_GROW", "blackhole": "PRE_DROP_RING"}

# step 8's members, with his own scenes' settings (a bound value at intensity
# 0.75, the plan's prototype convention): Fish and Sauron on the crystal;
# Star through star_run, beside the strip it samples
STEP8_CFG = {
    "fish": {"gradient": FIREWORKS_CFG["gradient"], "base_speed": 0.3,
             "big_fish_avoid": 0.0, "brightness_audio": 0.5,
             "color_shift": 1, "flap_amount": 0.45, "horizon_scale": 0.3,
             "impulse_decay": 0.06, "jiggle": 0.5, "quiet_rest": 1.0,
             "radius_scale": 1.8, "roam_scale": 0.75, "rush_chaos": 0.3,
             "school_variation": 0.08, "size_audio": 0.5, "speed_jog": 1,
             "speed_jump": 1, "spin": 0.37, "tail_drive": 1.0,
             "tether_scatter": 0, "blob_size": 1.75, "particle_count": 6},
    "radial": {"edges": 6, "star": 0.3, "spin": 0.55, "polygon": True,
               "twist": 0.0},
    "sauron": {"gradient": FIREWORKS_CFG["gradient"], "flame_audio": 2.0,
               "impulse_decay": 0.06, "speed_audio": 2.9,
               "drift_speed": 0.6875, "flames": 0.5, "snap_hold": 0.4125,
               "snap_threshold": 0.525},
}
STEP8_LACKS = {"fish": "PRE_DROP_DART", "radial": "PRE_DROP_OUTLINE",
               "sauron": "PRE_DROP_GLARE"}


def _fireworks_info(eff) -> dict:
    live = eff.p_rocket[:eff.n] > 0
    clk = getattr(eff, "_pd_clk", None)
    return {"n": int(eff.n), "rockets": int(live.sum()),
            "rocket_bright": (float(eff.p_bright[:eff.n][live].min())
                              if live.any() else None),
            "pd_frac": clk.frac if clk is not None else None}


def _crystal_info(eff) -> dict:
    """What a frame was drawn from: the pre-drop segment and its fraction,
    Orbits' jitter offset and frame gain, and the base render's breath gain
    (both read after the frame, so they are the values it was drawn with)."""
    clk = getattr(eff, "_pd_clk", None)
    pd_gain = getattr(eff, "_pre_drop_gain", None)
    lull = getattr(eff, "_phase", "none") == "lull"
    return {"n": int(getattr(eff, "n", 0)),
            "segment": clk.segment if clk is not None else None,
            "pd_frac": clk.frac if clk is not None else None,
            "jitter": getattr(eff, "_pd_jit", None),
            "pd_gain": pd_gain() if pd_gain is not None else None,
            "breath": (phase_grammar.breath_gain(
                eff._config, eff._phase_t,
                floor=getattr(eff, "BREATH_FLOOR", 0.0)) if lull else 1.0),
            "phase_t": float(getattr(eff, "_phase_t", 0.0)),
            "grid_r": getattr(eff, "grid_r", None)}


def _fish_info(eff) -> dict:
    """The crystal info, plus the lull's keepers: how many, how far the
    furthest is from the centre of view (px), the fish still swimming or
    leaving, the dart's state and the head's look this frame."""
    out = _crystal_info(eff)
    n = int(eff.n)
    mode = eff.p_mode[:n]
    keep = np.flatnonzero(mode == 5)
    d = None
    if keep.size:
        d = float(np.hypot((eff.p_x[keep] - eff.cam_nx) * eff.sx,
                           (eff.p_y[keep] - eff.cam_ny) * eff.sy).max())
    kst = eff._keep or {}
    dart = getattr(eff, "_pd_dart", None) or {}
    out.update({"keepers": int(keep.size), "keep_d_px": d,
                "others": int(np.count_nonzero(mode < 5)),
                "arrived": dart.get("arrived"),
                "look": (float(np.abs(kst["look"]).max())
                         if kst.get("look") is not None and len(kst["look"])
                         else 0.0),
                "turn": kst.get("turn"),
                "body_px": float(eff._body_len_px())})
    return out


def _sauron_info(eff) -> dict:
    """The crystal info, plus the lids, the glare, the drop's slam and
    burst, and how many cells the flames reach this frame (its instrument)."""
    out = _crystal_info(eff)
    flame = getattr(eff, "last_flame", None)
    out.update({"lid": float(eff._lid),
                "glare": bool(getattr(eff, "_pd_glare", False)),
                "slam": bool(eff._drop_slam), "burst": float(eff._burst),
                "flame_cells": (int((flame > 0.1).sum())
                                if flame is not None else 0)})
    return out


async def fireworks_run(tmp: Path, effect_type: str, arms: dict[str, Arm],
                        config: Optional[dict] = None, seed: int = 7,
                        lull_s: float = 3.2, pokes: Optional[dict] = None,
                        real_mask: bool = True) -> Run:
    """One Fireworks (or its pinned copy) through settle -> charge -> lull ->
    drop. `pokes` {(phase, frame): config} lands extra writes (a flare)."""
    return await crystal_run(tmp, effect_type, arms,
                             {**FIREWORKS_CFG, **(config or {})}, seed=seed,
                             lull_s=lull_s, pokes=pokes, real_mask=real_mask,
                             info=_fireworks_info)


async def crystal_run(tmp: Path, effect_type: str, arms: dict[str, Arm],
                      config: dict, seed: int = 7, lull_s: float = 3.2,
                      pokes: Optional[dict] = None, real_mask: bool = True,
                      info=_crystal_info) -> Run:
    """One crystal effect (or its pinned copy) with `config` through settle
    -> charge -> lull -> drop; `info(eff)` is read after every frame."""
    from fx import headless
    _TAG[0] += 1
    tag = f"pdl{_TAG[0]}"
    mask = crystal_real_mask() if real_mask else None
    host = await headless.start_headless_host(
        str(tmp / tag), pixel_count=ROWS * COLS, rows=ROWS, device_id=tag,
        **({"real_mask": mask} if mask is not None else {}))
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, effect_type, dict(config))
    eff._rng = np.random.default_rng(seed)
    if hasattr(eff, "_wander_seed"):
        # Sauron draws its gaze wander and its noise field's seed from an
        # unseeded generator at construction (scripts/check_sauron.py's
        # reseed): fixed here so two runs of one clip render the same bytes
        eff._wander_seed = float(np.random.default_rng(seed).uniform(
            0.0, 2.0 * np.pi))
        eff.noise.seed = int(seed) * 7919 + 17
    run = Run()
    try:
        for ph, secs in schedule(3.0, lull_s, 1.6):
            arm = arms.get(ph)
            if arm is not None:
                eff.update_config(dict(arm.params))
            n = int(round(secs / DT))
            ramp_n = max(1, int(round(arm.ramp_s / DT))) if arm else 0
            for i in range(1, n + 1):
                if arm is not None and i <= ramp_n:
                    eff.update_config({"phase_progress": min(1.0, i / ramp_n)})
                for (pph, k), poke in (pokes or {}).items():
                    if pph == ph and k == i:
                        eff.update_config(dict(poke))
                clock.advance(DT)
                out = virtual.assemble_frame()
                if out is not None:
                    virtual.flush(out)
                run.frames.append(np.asarray(out, dtype=np.float32).copy())
                run.phase.append((ph, i * DT))
                run.info.append(info(eff))
    finally:
        cm.__exit__(None, None, None)
        await host.shutdown()
    return run


# ── Star beside its strip ────────────────────────────────────────────────

STAR_STRIP_CFG = {"gradient": FIREWORKS_CFG["gradient"], "speed": 0.08,
                  "reactivity": 0.3, "blur": 1.0, "brightness": 1.0,
                  "background_brightness": 0.0}


def _star_info(eff) -> dict:
    clk = getattr(eff, "_pd_clk", None)
    snap = eff._snap
    return {"segment": clk.segment if clk is not None else None,
            "pd_frac": clk.frac if clk is not None else None,
            "spin": float(getattr(eff, "_pd_spin", 0.0)),
            "snap": snap is not None,
            "snap_resampled": snap is not None and "g" in snap,
            "phase_t": float(getattr(eff, "_phase_t", 0.0))}


def star_scene() -> dict:
    return _scene_dict("radial", strips="melt")


async def star_run(tmp: Path, star_type: str, arms: dict[str, Arm],
                   strip_arms: dict[str, Arm], config: Optional[dict] = None,
                   lull_s: float = 3.2, pokes: Optional[dict] = None,
                   strip_pokes: Optional[dict] = None,
                   strip_cfg: Optional[dict] = None) -> Run:
    """Star (or its pinned copy) on the crystal and the Melt strip it
    samples (tests/star_harness.StarRoom: the strip rendered and published
    first, a fake clock behind time.time_ns, Star turning at its rig rate),
    each driven with its own arms through settle -> charge -> lull -> drop.
    `strip_pokes` lands writes on the strip (a colour change)."""
    from star_harness import COLS as SC, ROWS as SR
    from star_harness import STAR, STRIP, STRIP_N, StarRoom
    from strip_phase_harness import scene_for
    _TAG[0] += 1
    rcfg = {"source_virtual": STRIP, "background_brightness": 0.0,
            **STEP8_CFG["radial"], **(config or {})}
    mcfg = {**STAR_STRIP_CFG, **(strip_cfg or {})}
    room = StarRoom(str(tmp / f"pds{_TAG[0]}"),
                    {STRIP: ("melt", STRIP_N, 1, mcfg),
                     STAR: (star_type, SC * SR, SR, rcfg)},
                    scene=scene_for({STRIP: "melt", STAR: "radial"}))
    run = Run()
    async with room:
        eff, strip = room.effects[STAR], room.effects[STRIP]
        for ph, secs in schedule(3.0, lull_s, 1.6):
            arm, sarm = arms.get(ph), strip_arms.get(ph)
            if arm is not None:
                eff.update_config(dict(arm.params))
            if sarm is not None:
                strip.update_config(dict(sarm.params))
            n = int(round(secs / DT))
            ramp_n = max(1, int(round(arm.ramp_s / DT))) if arm else 0
            sramp_n = max(1, int(round(sarm.ramp_s / DT))) if sarm else 0
            for i in range(1, n + 1):
                if arm is not None and i <= ramp_n:
                    eff.update_config({"phase_progress": min(1.0, i / ramp_n)})
                if sarm is not None and i <= sramp_n:
                    strip.update_config(
                        {"phase_progress": min(1.0, i / sramp_n)})
                for (pph, k), poke in (pokes or {}).items():
                    if pph == ph and k == i:
                        eff.update_config(dict(poke))
                for (pph, k), poke in (strip_pokes or {}).items():
                    if pph == ph and k == i:
                        strip.update_config(dict(poke))
                room.step(1)
                run.frames.append(np.asarray(room.frames[STAR][-1],
                                             dtype=np.float32))
                run.phase.append((ph, i * DT))
                run.info.append(_star_info(eff))
    return run


def light(frame: np.ndarray, mask: Optional[np.ndarray] = None) -> float:
    """The plan's light (report 3.5): each cell's brightest channel / 255,
    added over the panel (cells at full), over the real cells when known."""
    f = np.asarray(frame, dtype=np.float32).reshape(-1, 3).max(axis=1) / 255.0
    if mask is not None and mask.size == f.size:
        f = f[mask]
    return float(f.sum())


# ── Pulse on one light ───────────────────────────────────────────────────

class PulseRig:
    """One standalone Pulse (today's or the pinned copy) on one pixel, its own
    frame clock (exactly DT a frame), audio frame then render — the order the
    live pipeline delivers them (tests/test_pulse_effect.py's Rig)."""

    def __init__(self, module: str = "fx.effects.pulse", **config):
        mod = sys.modules.get(module) or importlib.import_module(module)
        cfg = {"gradient": "#ff2040", "beat_ms": 500.0, "energy": 0.6}
        cfg.update(config)
        e = mod.PulseAudioEffect(None, cfg)
        e.pixels = np.zeros((1, 3))
        e._active = True

        def log_sec():
            e.now += DT
            e.passed = DT
        e.log_sec = log_sec
        self.e = e

    def frame(self, x: float) -> tuple[float, np.ndarray]:
        self.e.ingest_signal(x, DT)
        self.e._render()
        return self.e.level, self.e.get_pixels()[0].copy()

    def write(self, cfg: dict):
        self.e.update_config(dict(cfg))

    def tween(self, **cfg):
        with self.e.lock:
            self.e._apply_config(cfg, validate=False, fire_event=False)


def signal(t: float) -> float:
    """A steady test signal: a kick every half second on a low bed."""
    return 1.0 if (t % 0.5) < DT * 0.99 else 0.12


def pulse_run(arms: dict[str, Arm], module: str = "fx.effects.pulse",
              lull_s: float = 3.2, pokes: Optional[dict] = None,
              charge_s: float = 3.0, drop_s: float = 2.0) -> Run:
    rig = PulseRig(module)
    run = Run()
    t = 0.0
    for ph, secs in schedule(charge_s, lull_s, drop_s, settle_s=3.0):
        arm = arms.get(ph)
        if arm is not None:
            rig.write(arm.params)
        n = int(round(secs / DT))
        ramp_n = max(1, int(round(arm.ramp_s / DT))) if arm else 0
        for i in range(1, n + 1):
            if arm is not None and i <= ramp_n:
                rig.tween(phase_progress=min(1.0, i / ramp_n))
            for (pph, k), poke in (pokes or {}).items():
                if pph == ph and k == i:
                    rig.write(poke)
            level, px = rig.frame(signal(t))
            t += DT
            run.frames.append(px)
            run.phase.append((ph, i * DT))
            run.info.append({"level": level,
                             "lin": float(level ** rig.e._config["gamma"])})
    return run


def lull_frames(run: Run):
    return [(t, f, inf) for (ph, t), f, inf in zip(run.phase, run.frames,
                                                   run.info) if ph == "lull"]


def run_async(coro):
    return asyncio.run(coro)
