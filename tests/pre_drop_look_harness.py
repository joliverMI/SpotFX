"""THE PRE-DROP LOOKS' RIG (predrop plan step 6): Fireworks and Pulse driven
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
# their pre-drop (the engine itself is already there)
PRE_REF = "34ce2b14f319a5c4af6a6b8d1bbf5e7f10dcdda0"
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


def load_pinned(module: str, name: str, must_lack: str) -> str:
    """fx/effects/<module>.py at PRE_REF, registered as `name` (the effect
    registry keys effects by module), so a rig can attach it beside today's.
    Raises RuntimeError when git cannot give it."""
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{PRE_REF}:fx/effects/{module}.py"], cwd=REPO,
            capture_output=True, text=True, check=True, timeout=60).stdout
    except Exception as exc:                              # noqa: BLE001
        raise RuntimeError(f"cannot read {PRE_REF} out of git: {exc}") from exc
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

def _scene_dict() -> dict:
    from spectra.models.scene import SceneV2
    return SceneV2(name="Pre-drop looks", devices=[
        {"target_kind": "category", "target": "Matrix",
         "effect_type": "fireworks"},
        {"target_kind": "category", "target": "Singles",
         "effect_type": "pulse"}]).model_dump(mode="json")


@dataclass
class Arm:
    params: dict          # the jump the effect receives at the phase's edge
    ramp_s: float         # what phase_progress then glides over


def engine_arms(effect_type: str, lull_s: float, at_s: Optional[float] = None,
                gap_s: Optional[float] = None, kind: str = "spike",
                intensity: float = 0.8) -> dict[str, Arm]:
    """The charge, lull and drop arms production writes to `effect_type`'s
    virtual for a lull of `lull_s` to its drop, carrying a pre-drop `kind`
    `at_s` into the lull and `gap_s` before the drop when given."""
    from spectra.services.pre_drop_play import PreDropCandidate
    from tests import pre_drop_arm_harness as harness
    scene = _scene_dict()
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


# ── Fireworks on the crystal ─────────────────────────────────────────────

_TAG = [0]


async def fireworks_run(tmp: Path, effect_type: str, arms: dict[str, Arm],
                        config: Optional[dict] = None, seed: int = 7,
                        lull_s: float = 3.2, pokes: Optional[dict] = None,
                        real_mask: bool = True) -> Run:
    """One Fireworks (or its pinned copy) through settle -> charge -> lull ->
    drop. `pokes` {(phase, frame): config} lands extra writes (a flare)."""
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
    cfg = {"gradient": "linear-gradient(90deg, #00b3ff 0%, #7a00ff 100%)",
           "spawn_rate": 3.0}
    cfg.update(config or {})
    eff = headless.attach_effect(host, virtual, effect_type, cfg)
    eff._rng = np.random.default_rng(seed)
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
                live = eff.p_rocket[:eff.n] > 0
                clk = getattr(eff, "_pd_clk", None)
                run.info.append({
                    "n": int(eff.n), "rockets": int(live.sum()),
                    "rocket_bright": (float(eff.p_bright[:eff.n][live].min())
                                      if live.any() else None),
                    "pd_frac": clk.frac if clk is not None else None})
    finally:
        cm.__exit__(None, None, None)
        await host.shutdown()
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
