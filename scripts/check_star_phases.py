"""Star (fx/effects/radial.py) — the star plan's measurements, printed.

Offline, on the real render pipeline (tests/star_harness.py: a real Melt
strip under a real Radial, the production ResponseEngine): lull B's lit
cells / falling / kept pieces every 0.1 s of a 5 s lull (dark point 2.5 s),
D3's lit cells after the drop, and every transition program out of Star
(largest frame-to-frame change, white cells). No live room, no storage.

    .venv/bin/python scripts/check_star_phases.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx.effects import transition_program as tp  # noqa: E402
from star_harness import (PALETTE, STAR, lit_cells, star_room,  # noqa: E402
                          white_cells)
from strip_phase_harness import run  # noqa: E402


async def lull_and_drop(tmp, layer):
    async with star_room(tmp, layer=layer) as room:
        room.step(room.secs(1.0))
        await room.phase("lull", gap_ms=5000, intensity=0.7)
        rows = []
        for i in range(30):
            room.step(room.secs(0.1))
            st, held = room.star._bands, room.star._held
            rows.append((round(0.1 * (i + 1), 1), lit_cells(room.matrix()),
                         0 if st is None else st["u"].size,
                         0 if held is None else held["u0"].size))
        await room.phase("drop", intensity=0.8)
        drop = []
        for _ in range(15):
            room.step(room.secs(0.1))
            drop.append((lit_cells(room.matrix()), white_cells(room.matrix())))
        return rows, drop


async def program(tmp, inc):
    async with star_room(tmp, layer=False) as room:
        room.step(room.secs(1.0))
        v = room.virtuals[STAR]
        new = room.host.effects.create(ledfx=room.host, type=inc,
                                       config={"gradient": PALETTE})
        prog = tp.build("radial", inc, {"seed": 3})
        v.set_effect(new, activate=False, program=prog)
        room.effects[STAR] = new
        prev, worst, white = None, 0.0, 0
        while not prog.done:
            room.step(1)
            m = np.asarray(new.matrix, dtype=np.float64)
            white = max(white, white_cells(m))
            if prev is not None:
                worst = max(worst, float(np.abs(m - prev).mean()))
            prev = m
        return prog.name, worst, white


def main() -> int:
    for layer in (False, True):
        with tempfile.TemporaryDirectory() as d:
            rows, drop = run(lull_and_drop(d, layer))
        print(f"LULL B (strip phase layer {'on' if layer else 'off'}; "
              "dark point 2.5 s): t, lit, falling, kept")
        for r in rows:
            print("  ", r)
        print("  DROP D3 lit/white every 0.1 s:", drop)
    for inc in sorted(tp.STAR_OUT):
        with tempfile.TemporaryDirectory() as d:
            name, worst, white = run(program(d, inc))
        print(f"radial -> {inc:10s} {name:9s} largest frame change "
              f"{worst:5.1f}  white cells {white}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
