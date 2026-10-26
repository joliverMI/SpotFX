"""TIER B IS UNCHANGED — the driver that proves it, by running the SAME
program in TWO SOURCE TREES (the shoal-burst plan scoped the build to tier
A, 8 pairs, on the Admiral's "for scope, dont do B").

It renders a registered pair on the real vendored pipeline and prints one
sha256 over every frame. tests/test_shoal_burst.py runs it once against this
checkout and once against a `git archive` of the branch's merge-base,
unpacked into a throwaway directory — so "before" is genuinely before, not a
fingerprint committed after the fact.

Self-contained on purpose: the merge-base tree does not have the harness.

    python tests/shoal_tier_b_driver.py <tree> <out> <in> [seed] [req-json]

`req-json` is a program request the OLD tree simply ignores keys it has
never heard of — which is what makes "transition_burst_px = 0 reproduces
today's orbits -> fish frame for frame" a real before/after rather than a
claim about the new code alone.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

PIXELS, ROWS = 72 * 37, 37
WARM = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"
WARM_UP = {"squiggles": {"spawn_rate": 4.0}, "fireworks": {"spawn_rate": 6.0}}
WARM_FRAMES = 120
# The fish's wake is held at its old colour and blend (fx/effects/fish.py's
# WAKE COLOUR block): these proofs are about the programs, not the wake, and
# the merge-base tree may predate both settings (an effect's schema allows
# keys it has never heard of, so an older tree simply ignores them).
HOLD = {"fish": {"wake_hue": "opposite", "wake_blend": "add"}}


def _released(prog):
    """The outgoing form's own objects, straight off the snapshot the
    program captured — the same filter every release uses."""
    snap = getattr(prog, "snap", None)
    if not snap or snap.get("px") is None:
        return None
    px = np.asarray(snap["px"], np.float32)
    py = np.asarray(snap["py"], np.float32)
    br = np.clip(np.asarray(snap["bright"], np.float32), 0.0, 1.0)
    keep = np.isfinite(px) & np.isfinite(py) & (br > 0.03)
    return (px[keep], py[keep]) if keep.any() else None


def _birth_px(inc, rel):
    """How far the incoming form's objects are born from the released ones,
    median over the incoming objects, on the program's first frame."""
    fn = getattr(inc, "_formation_points", None)
    if fn is None:
        return None
    try:
        qx, qy = fn()
    except Exception:
        return None
    qx = np.asarray(qx, np.float32)
    if qx.size == 0:
        return None
    qy = np.asarray(qy, np.float32)
    d = np.hypot(qx[:, None] - rel[0][None, :], qy[:, None] - rel[1][None, :])
    return float(np.median(d.min(axis=1)))


def pin_rng(seed):
    orig = np.random.default_rng
    box = {"k": 0}

    def fake(*a, **k):
        if a or k:
            return orig(*a, **k)
        box["k"] += 1
        return orig(seed * 1000 + box["k"])

    np.random.default_rng = fake


async def main(out_type, in_type, seed, req=None):
    from fx import headless
    from fx.effects import particle_handoff as ph
    from fx.effects import transition_program as tp
    from fx.host import FxHost

    ph._store.clear()
    d = tempfile.mkdtemp()
    headless.write_headless_config(d, pixel_count=PIXELS, rows=ROWS)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    v._config["transition_mode"] = "Add"
    v._config["transition_time"] = 0.5
    h = hashlib.sha256()
    frames = 0
    birth = None
    try:
        pin_rng(seed)
        with headless.fake_clock() as clk:
            headless.attach_effect(
                host, v, out_type,
                {"gradient": WARM, **WARM_UP.get(out_type, {}),
                 **HOLD.get(out_type, {})})
            headless.render_frames(v, WARM_FRAMES, clock=clk)
            new = host.effects.create(
                ledfx=host, type=in_type,
                config={"gradient": WARM, **HOLD.get(in_type, {})})
            prog = tp.build(out_type, in_type, {"seed": seed, **(req or {})})
            assert prog is not None, (out_type, in_type)
            v.set_effect(new, activate=False, program=prog)
            # prog.capture() ran inside set_effect, so the snapshot is here
            rel = _released(prog)
            while not prog.done and frames < 300:
                f = headless.render_frames(v, 1, clock=clk)[0]
                h.update(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
                frames += 1
                if frames == 1 and rel is not None:
                    birth = _birth_px(new, rel)
            for f in headless.render_frames(v, 20, clock=clk):
                h.update(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
            cls = type(prog).__name__
            former = type(getattr(prog, "former", None)).__name__
    finally:
        await host.shutdown()
    print(json.dumps({"digest": h.hexdigest(), "frames": frames,
                      "cls": cls, "former": former, "birth_px": birth}))


if __name__ == "__main__":
    tree = sys.argv[1]
    sys.path.insert(0, str(Path(tree).resolve()))
    asyncio.run(main(sys.argv[2], sys.argv[3],
                     int(sys.argv[4]) if len(sys.argv) > 4 else 3,
                     json.loads(sys.argv[5]) if len(sys.argv) > 5 else None))
