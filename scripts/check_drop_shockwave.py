"""THE DROP SHOCKWAVE + THE BREATH-HOLD, measured on the real pipeline.

fx/effects/phase_grammar.py is the binding statement; this is its headless
proof on his crystal (fx.headless, the real 976-cell mask from
storage/device_profiles/crystal-mapper.json, audio silenced, a fake clock).
Every member (fx.device_model.DROP_SHOCK_EFFECTS) runs a charge, a told lull
and a told drop exactly the way spectra scene_response._drive_phase writes
them, twice from one seed — once with the Shockwave on, once with
`drop_shock: 0` — and the script reports, per effect:

- BREATH: the brightest real cell over the breath-hold window (the last
  `lull_breath_hold_s` of the lull) — 0 means TRUE BLACK — beside the same
  window with no breath told;
- RIM vs PERIMETER at the mark: the mean brightest channel on the eye's own
  rim band and on the crystal's outermost real cells on the drop's first
  frame (the wave is born on the rim, never the panel's edge), and the
  first moment the perimeter rises above 40 (when the front arrives);
- MORE COLOUR, NO WHITE: mean lit real cells over the drop's first second
  with and without the Shockwave, and the most real cells with every
  channel above 200 on any drop frame (the white guard) — with a SOLID set
  colour that is the plan's own "0 on every drop frame".

    .venv/bin/python scripts/check_drop_shockwave.py [effect ...]

Never Fireworks (his word) — it is asserted absent from the members.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from fx import device_model, headless  # noqa: E402
from fx.effects import lull_dark, lull_handoff, phase_grammar  # noqa: E402

ROWS, COLS = 37, 72
DT = 1.0 / 30.0
LIT = 20.0
WHITE = 200.0

NORMAL_S = 1.0
CHARGE_S = 2.0
LULL_S = 4.0
DROP_S = 2.5
BREATH_S = phase_grammar.DEFAULT_BREATH_S
MAX_DARK_S = lull_dark.DEFAULT_MAX_DARK_S

# a solid set colour (the white guard's own case) and one of his real-shaped
# multi-colour sets (the "more colour" case)
SOLID = "#ff3c00"
SET = ("linear-gradient(90deg, rgb(255,0,90) 0%, rgb(255,140,0) 33%, "
       "rgb(0,180,255) 66%, rgb(120,0,255) 100%)")

CONFIGS = {
    "blackhole": {"reverse": False, "horizon_scale": 0.2, "spawn_rate": 2.0,
                  "beat_burst": 2, "max_blobs": 40},
    # his live Orbits V2 / Fish geometry (storage/spectra/scenes.json)
    "orbits": {"particle_count": 6, "horizon_scale": 0.19,
               "radius_scale": 1.8},
    "sauron": {},
    "eye": {},
    "fish": {"particle_count": 5, "horizon_scale": 0.3, "radius_scale": 1.8},
}


def crystal_real_mask() -> np.ndarray:
    prof = json.loads((REPO / "storage" / "device_profiles"
                       / "crystal-mapper.json").read_text())
    mask, value = [], False
    for run in prof["mask_rle"]:
        mask.extend([value] * run)
        value = not value
    return np.array(mask, dtype=bool)


REAL = crystal_real_mask()
REAL2 = REAL.reshape(ROWS, COLS)


def outer_ring() -> np.ndarray:
    """The crystal's outermost real cells (check_sauron.py's own rule)."""
    ring = np.zeros_like(REAL2)
    rows = [r for r in range(ROWS) if REAL2[r].any()]
    for r in rows:
        c = np.flatnonzero(REAL2[r])
        ring[r, c[0]] = ring[r, c[-1]] = True
    for r in (rows[0], rows[-1]):
        ring[r] = REAL2[r]
    return ring


RING = outer_ring()
_N = [0]


def _lull_arm(effect_type: str, breath: bool) -> dict:
    """The lull arm _drive_phase writes for this member."""
    arm = {"phase": "lull", "phase_progress": 0.0}
    ramp = LULL_S * 0.9
    if effect_type in device_model.LULL_DARK_EFFECTS:
        arm.update(lull_dark.keys_for(LULL_S, ramp, MAX_DARK_S))
    if effect_type in device_model.LULL_HANDOFF_EFFECTS:
        arm.update(lull_handoff.keys_for(lull_handoff.DEFAULT_KEEP, "",
                                         LULL_S))
    if breath:
        arm.update(phase_grammar.breath_keys_for(LULL_S, BREATH_S,
                                                 MAX_DARK_S))
    return arm


async def run_sequence(effect_type: str, *, shock: bool = True,
                       breath: bool = True, intensity: float = 0.9,
                       gradient: str = SET, seed: int = 7,
                       extra: dict | None = None,
                       drop_arm: dict | None = None) -> dict:
    """One member through normal -> charge -> told lull -> told drop.
    Returns the per-frame real-cell frames (rows x cols x 3) and the frame
    index of the drop mark and of the lull's start."""
    _N[0] += 1
    tag = f"shock-{effect_type}-{_N[0]}"
    td = tempfile.mkdtemp()
    headless.silence_audio()
    host = await headless.start_headless_host(
        str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag, real_mask=REAL)
    virtual = host.virtuals.get(tag)
    frames = []
    try:
        with headless.fake_clock() as clock:
            np.random.seed(seed)
            cfg = dict(CONFIGS.get(effect_type, {}))
            cfg["gradient"] = gradient
            cfg["drop_shock"] = 1.0 if shock else 0.0
            cfg.update(extra or {})
            eff = headless.attach_effect(host, virtual, effect_type, cfg)
            eff._rng = np.random.default_rng(seed)

            def step(n):
                for _ in range(n):
                    clock.advance(DT)
                    f = virtual.assemble_frame()
                    if f is not None:
                        virtual.flush(f)
                        a = np.array(f, dtype=np.float32).reshape(
                            ROWS, COLS, 3)
                        frames.append(np.where(REAL2[..., None], a, 0.0))

            step(int(NORMAL_S / DT))
            eff.update_config({"phase": "charge", "phase_progress": 0.0})
            n = int(CHARGE_S / DT)
            for i in range(n):
                eff.update_config({"phase_progress": (i + 1) / n})
                step(1)
            lull_at = len(frames)
            eff.update_config(_lull_arm(effect_type, breath))
            n = int(LULL_S / DT)
            ramp_n = int(0.9 * n)
            for i in range(n):
                eff.update_config({"phase_progress": min(1.0,
                                                         (i + 1) / ramp_n)})
                step(1)
            drop_at = len(frames)
            arm = {"phase": "drop", "phase_progress": 0.0}
            if effect_type in device_model.DROP_INTENSITY_EFFECTS:
                arm.update(lull_handoff.drop_keys_for(intensity))
            arm.update(drop_arm or {})      # e.g. SpotFX's drop_shock_on
            eff.update_config(arm)
            step(int(DROP_S / DT))
            rim = eff.shock_rim() if eff.DROP_SHOCK else None
    finally:
        await host.shutdown()
    return {"frames": frames, "lull_at": lull_at, "drop_at": drop_at,
            "rim": rim}


def rim_band(rim, half_px: float = 1.6) -> np.ndarray:
    cx, cy, rx, ry = rim
    yi, xi = np.indices((ROWS, COLS))
    th = np.arctan2((yi - cy) / max(ry, 1e-3), (xi - cx) / max(rx, 1e-3))
    ex = cx + rx * np.cos(th)
    ey = cy + ry * np.sin(th)
    return (np.hypot(xi - ex, yi - ey) <= half_px) & REAL2


def bright(frame: np.ndarray) -> np.ndarray:
    return frame.max(axis=-1)


def measure(effect_type: str, **kw) -> dict:
    on = asyncio.run(run_sequence(effect_type, shock=True, **kw))
    off = asyncio.run(run_sequence(effect_type, shock=False, breath=False,
                                   **kw))
    d = on["drop_at"]
    fr_on, fr_off = on["frames"], off["frames"]
    breath_n = int(round(BREATH_S / DT))
    win_on = fr_on[d - breath_n + 1:d]
    win_off = fr_off[d - breath_n + 1:d]
    band = rim_band(on["rim"])
    mark = fr_on[d]
    first_edge = None
    for i, f in enumerate(fr_on[d:]):
        if bright(f)[RING].mean() > 40.0:
            first_edge = round(i * DT, 3)
            break
    one_s = int(1.0 / DT)
    first_edge_off = None
    for i, f in enumerate(fr_off[d:]):
        if bright(f)[RING].mean() > 40.0:
            first_edge_off = round(i * DT, 3)
            break
    late = slice(d + int(0.6 / DT), d + int(1.6 / DT))

    def energy(fr):
        return float(np.mean([bright(f)[REAL2].sum() for f in fr]))

    def lit(fr):
        return float(np.mean([np.count_nonzero(bright(f)[REAL2] > LIT)
                              for f in fr]))

    return {
        "effect": effect_type,
        "breath_max": float(max(bright(f).max() for f in win_on)),
        "breath_off_max": float(max(bright(f).max() for f in win_off)),
        "rim_at_mark": round(float(bright(mark)[band].mean()), 1),
        "perimeter_at_mark": round(float(bright(mark)[RING].mean()), 1),
        "perimeter_first_above_40_s": first_edge,
        "perimeter_first_above_40_s_off": first_edge_off,
        "energy_after_front_on": round(energy(fr_on[late])),
        "energy_after_front_off": round(energy(fr_off[late])),
        "lit_drop_1s_on": round(lit(fr_on[d:d + one_s]), 1),
        "lit_drop_1s_off": round(lit(fr_off[d:d + one_s]), 1),
        "white_max_on": max(phase_grammar.white_cells(f, WHITE)
                            for f in fr_on[d:]),
        "white_max_off": max(phase_grammar.white_cells(f, WHITE)
                             for f in fr_off[d:]),
    }


def main(argv) -> int:
    assert "fireworks" not in device_model.DROP_SHOCK_EFFECTS
    effects = argv or sorted(device_model.DROP_SHOCK_EFFECTS)
    ok = True
    for e in effects:
        m = measure(e)
        s = measure(e, gradient=SOLID)
        m["white_max_on_solid"] = s["white_max_on"]
        print(json.dumps(m))
        good = (m["breath_max"] == 0.0
                and m["rim_at_mark"] > m["perimeter_at_mark"]
                and (m["lit_drop_1s_on"] > m["lit_drop_1s_off"]
                     or m["energy_after_front_on"]
                     > m["energy_after_front_off"])
                and s["white_max_on"] == 0)
        ok &= good
        print(f"  {e}: {'PASS' if good else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
