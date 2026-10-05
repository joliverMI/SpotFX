"""How many bytes does one crystal-mapper preview frame cost under each wire
encoding?  Renders his REAL Matrix effects offline (fx.headless, dummy device,
no audio device) and sizes each frame.  Indicative: with no audio the effects
run on their own idle motion, which is calmer than a live show.

  .venv/bin/python scripts/preview_perf/encoding_study.py
"""
from __future__ import annotations
import asyncio, base64, json, os, sys, tempfile, zlib
import numpy as np
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
from fx import headless  # noqa: E402

EFFECTS = ["fish", "blackhole", "orbits", "fireworks", "squiggles", "pacman", "eye", "radial"]
ROWS, COLS = 37, 72


def mask() -> np.ndarray:
    prof = json.load(open(os.path.join(REPO, "storage/device_profiles/crystal-mapper.json")))
    runs, out, val = prof["mask_rle"], [], 0
    for r in runs:
        out += [val] * r
        val ^= 1
    m = np.array(out[:ROWS * COLS], dtype=bool)
    if m.sum() != prof["real_pixel_count"]:
        m = ~m
    assert m.sum() == prof["real_pixel_count"], m.sum()
    return m


def stream_deflate(chunks):
    """Per-frame cost with ONE shared deflate context (what permessage-deflate does)."""
    c = zlib.compressobj(1, zlib.DEFLATED, -15)
    return [len(c.compress(b) + c.flush(zlib.Z_SYNC_FLUSH)) for b in chunks]


async def main():
    real = mask()
    rows = []
    for name in EFFECTS:
        tmp = tempfile.mkdtemp(prefix="enc-")
        try:
            host = await headless.start_headless_host(tmp, pixel_count=ROWS * COLS, rows=ROWS)
            v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
            with headless.fake_clock() as clock:
                headless.attach_effect(host, v, name, {})
                frames = headless.render_frames(v, 360, clock=clock, dt=1 / 30)[60:]
        except Exception as exc:
            rows.append((name, f"skipped: {type(exc).__name__}: {str(exc)[:60]}"))
            continue
        u8 = [np.clip(f, 0, 255).astype(np.uint8) for f in frames]
        lit = float(np.mean([(f.max(axis=1) > 8).mean() for f in u8]))
        moved = float(np.mean([(a != b).any(axis=1).mean() for a, b in zip(u8, u8[1:])]))
        raw = [f.tobytes() for f in u8]
        cells = [f[real].tobytes() for f in u8]
        b64json = [json.dumps({"type": "device_preview_frame", "vis_id": "crystal-mapper",
                               "pixels": base64.b64encode(r).decode(), "shape": [ROWS, COLS],
                               "is_device": False}).encode() for r in raw]
        xor = [cells[0]] + [bytes(np.frombuffer(a, np.uint8) ^ np.frombuffer(b, np.uint8))
                            for a, b in zip(cells[1:], cells)]
        rows.append((name, {
            "lit": lit, "moved": moved,
            "today_json_b64": np.mean([len(x) for x in b64json]),
            "today_on_wire_deflate": np.mean(stream_deflate(b64json)),
            "binary_full": 8 + len(raw[0]),
            "binary_full_deflate": np.mean(stream_deflate(raw)),
            "binary_real_cells": 8 + len(cells[0]),
            "binary_real_cells_deflate": np.mean(stream_deflate(cells)),
            "real_cells_xor_delta_deflate": np.mean(stream_deflate(xor)),
        }))
    print("| effect | lit px | px changed / frame | today JSON+base64 | today on the wire (deflate) | "
          "binary, 2664 px | binary, 976 real cells | 976 cells + deflate | 976 cells delta + deflate |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name, r in rows:
        if isinstance(r, str):
            print(f"| {name} | {r} |||||||"); continue
        print(f"| {name} | {r['lit']:.0%} | {r['moved']:.0%} | {r['today_json_b64']:.0f} | "
              f"{r['today_on_wire_deflate']:.0f} | {r['binary_full']} | {r['binary_real_cells']} | "
              f"{r['binary_real_cells_deflate']:.0f} | {r['real_cells_xor_delta_deflate']:.0f} |")
    sys.stdout.flush()
    os._exit(0)

asyncio.run(main())
