"""THE SHOALING BURST, BEFORE AND AFTER — the plan's comparison tiles, with
the shipped code (the shoal-burst plan, /home/javi/fleet-spotfx/data/
shoal-burst-plan/report.md; fx/effects/transition_cloud.py's HostFormer is
the binding statement).

For every TIER-A pair it renders the same switch twice on the real vendored
pipeline — once in THIS checkout and once in a `git archive` of the branch's
merge-base, unpacked into a throwaway directory — and stacks them, before
over after, so the two rows differ only by the mechanism. Same seed, same
warm-up, same gradients, same frames.

fx.headless, a 72x37 dummy matrix (the full rectangle, not his crystal's
real cells), silent audio, a fake clock at 60 fps, the default 1.4 s
program. Offline only; nothing live is touched.

    .venv/bin/python scripts/render_shoal_burst.py [out_dir]
    .venv/bin/python scripts/render_shoal_burst.py --tile <tree> <out> <in> <npy>
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
WARM = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"
COOL = "linear-gradient(90deg, #00a0ff 0%, #20ff60 50%, #a040ff 100%)"
WARM_CONFIG = {"squiggles": {"spawn_rate": 4.0}, "fireworks": {"spawn_rate": 6.0}}
PAIRS = (
    ("fish_to_orbits", "fish", "orbits"),
    ("fish_to_squiggles", "fish", "squiggles"),
    ("orbits_to_squiggles", "orbits", "squiggles"),
    ("squiggles_to_orbits", "squiggles", "orbits"),
    ("squiggles_to_fish", "squiggles", "fish"),
    ("orbits_to_fish", "orbits", "fish"),
    ("blackhole_to_orbits", "blackhole", "orbits"),
    ("blackhole_to_fish", "blackhole", "fish"),
    ("blackhole_to_squiggles", "blackhole", "squiggles"),
)
EVERY, N, SEED, COLS = 5, 95, 3, 7


def pin_rng(seed):
    orig = np.random.default_rng
    box = {"k": 0}

    def fake(*a, **k):
        if a or k:
            return orig(*a, **k)
        box["k"] += 1
        return orig(seed * 1000 + box["k"])

    np.random.default_rng = fake


async def tile(out_type, in_type):
    from fx import headless
    from fx.effects import particle_handoff as ph
    from fx.effects import transition_program as tp
    from fx.host import FxHost

    ph._store.clear()
    d = tempfile.mkdtemp()
    headless.write_headless_config(d, pixel_count=72 * 37, rows=37)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    frames = []
    try:
        pin_rng(SEED)
        with headless.fake_clock() as clk:
            headless.attach_effect(
                host, v, out_type,
                {"gradient": WARM, **WARM_CONFIG.get(out_type, {})})
            headless.render_frames(v, 120, clock=clk)
            new = host.effects.create(ledfx=host, type=in_type,
                                      config={"gradient": COOL})
            prog = tp.build(out_type, in_type,
                            {"duration_ms": 1400, "seed": SEED})
            frames.append(headless.render_frames(v, 1, clock=clk)[0])
            v.set_effect(new, activate=False, program=prog)
            for i in range(N):
                f = headless.render_frames(v, 1, clock=clk)[0]
                if i % EVERY == 0:
                    frames.append(f)
    finally:
        await host.shutdown()
    return np.stack([np.clip(f.reshape(37, 72, 3), 0, 255).astype(np.uint8)
                     for f in frames])


def sheet(tiles):
    rows = (len(tiles) + COLS - 1) // COLS
    out = np.zeros((rows * 39, COLS * 74, 3), np.uint8)
    for k, t in enumerate(tiles):
        r, c = divmod(k, COLS)
        out[r * 39:r * 39 + 37, c * 74:c * 74 + 72] = t
    return out


def base_tree():
    base = subprocess.run(["git", "merge-base", "HEAD", "origin/master"],
                          cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    d = Path(tempfile.mkdtemp(prefix="shoal-base-"))
    ar = subprocess.run(["git", "archive", base], cwd=REPO,
                        capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(d)], input=ar.stdout, check=True)
    (d / "scripts").mkdir(exist_ok=True)
    me = Path(__file__)
    (d / "scripts" / me.name).write_text(me.read_text())
    print(f"before = {base[:12]}")
    return d, base


def render_in(tree: Path, out_type, in_type):
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as fh:
        npy = fh.name
    r = subprocess.run([sys.executable, str(tree / "scripts" / Path(__file__).name),
                        "--tile", str(tree), out_type, in_type, npy],
                       cwd=str(REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{out_type}->{in_type} in {tree}:\n{r.stderr[-3000:]}")
    return np.load(npy)


def main() -> None:
    if sys.argv[1:2] == ["--tile"]:
        sys.path.insert(0, str(Path(sys.argv[2]).resolve()))
        np.save(sys.argv[5], asyncio.run(tile(sys.argv[3], sys.argv[4])))
        return
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        REPO / "docs/evidence/shoal-burst")
    out_dir.mkdir(parents=True, exist_ok=True)
    tree, base = base_tree()
    for name, out_type, in_type in PAIRS:
        after = sheet(render_in(REPO, out_type, in_type))
        before = sheet(render_in(tree, out_type, in_type))
        h = before.shape[0] + after.shape[0] + 6
        img = np.zeros((h, max(before.shape[1], after.shape[1]), 3), np.uint8)
        img[:before.shape[0], :before.shape[1]] = before
        img[before.shape[0] + 3:before.shape[0] + 3 + after.shape[0],
            :after.shape[1]] = after
        img[before.shape[0] + 1:before.shape[0] + 2, :] = 60
        Image.fromarray(img).resize((img.shape[1] * 4, img.shape[0] * 4),
                                    Image.NEAREST).save(out_dir / f"{name}.png")
        print("wrote", out_dir / f"{name}.png", "(top: before, bottom: after)")
    (out_dir / "README.md").write_text(
        "# The shoaling burst, before and after\n\n"
        "Each image is ONE pair rendered twice on the real vendored pipeline "
        "with the same seed, warm-up and gradients: the TOP block is the "
        f"branch's merge-base (`{base[:12]}`), the BOTTOM block is this "
        "branch. The first tile of each block is the outgoing effect just "
        "before the switch; every later tile is 5 frames (0.083 s) on.\n\n"
        "Regenerate: `.venv/bin/python scripts/render_shoal_burst.py`.\n\n"
        "The numbers behind them, and what each one is held to, are in "
        "`tests/test_shoal_burst.py`. 72x37 dummy matrix — the full "
        "rectangle, NOT his crystal's 976 real cells; nothing here has been "
        "seen in his room.\n")


if __name__ == "__main__":
    main()
