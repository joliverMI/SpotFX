"""Render the thematic transition programs (fx/effects/transition_program.py)
on the real vendored pipeline as contact sheets, for the eye.

fx.headless, a 72x37 dummy matrix (the full rectangle, not his crystal's
real cells), silent audio, a fake clock at 60 fps, the default 1.4 s
program. The first tile is the outgoing effect just before the switch;
every later tile is 5 frames (0.083 s) on. Two synthetic gradients (warm
out, cool in) make the colour hand-over visible. Offline only.

    .venv/bin/python scripts/render_transition_programs.py [out_dir]
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402
from fx.host import FxHost  # noqa: E402

WARM = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"
COOL = "linear-gradient(90deg, #00a0ff 0%, #20ff60 50%, #a040ff 100%)"
RUNS = (
    ("infall_orbits_to_blackhole", "orbits", "blackhole", False),
    ("eruption_blackhole_to_orbits", "blackhole", "orbits", False),
    ("eruption_blackhole_to_fish", "blackhole", "fish", False),
    ("eruption_on_the_mark_blackhole_to_orbits", "blackhole", "orbits", True),
)


async def render(out_dir: Path, name, out_type, in_type, on_mark,
                 every=5, n=100):
    d = tempfile.mkdtemp()
    headless.write_headless_config(d, pixel_count=72 * 37, rows=37)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    frames = []
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, {"gradient": WARM})
            headless.render_frames(v, 120, clock=clk)
            new = host.effects.create(ledfx=host, type=in_type,
                                      config={"gradient": COOL})
            prog = tp.build(out_type, in_type,
                            {"duration_ms": 1400, "on_mark": on_mark, "seed": 1})
            frames.append(headless.render_frames(v, 1, clock=clk)[0])
            v.set_effect(new, activate=False, program=prog)
            for i in range(n):
                f = headless.render_frames(v, 1, clock=clk)[0]
                if i % every == 0:
                    frames.append(f)
    finally:
        await host.shutdown()
    tiles = [np.clip(f.reshape(37, 72, 3), 0, 255).astype(np.uint8) for f in frames]
    cols = 7
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.zeros((rows * 39, cols * 74, 3), np.uint8)
    for k, t in enumerate(tiles):
        r, c = divmod(k, cols)
        sheet[r * 39:r * 39 + 37, c * 74:c * 74 + 72] = t
    img = Image.fromarray(sheet).resize((sheet.shape[1] * 4, sheet.shape[0] * 4),
                                        Image.NEAREST)
    img.save(out_dir / f"{name}.png")


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "docs/evidence/transition-programs")
    out_dir.mkdir(parents=True, exist_ok=True)
    for run in RUNS:
        asyncio.run(render(out_dir, *run))
        print("wrote", out_dir / f"{run[0]}.png")


if __name__ == "__main__":
    main()
