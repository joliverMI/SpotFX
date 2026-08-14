"""Render-plane GIL probe — the process-split frame-rate proof's moving part.

Runs the vendored pipeline's REAL render thread (fx/headless live mode:
dummy device, orbits effect, silence_audio) and measures per-frame flush
gaps by stamping DummyDevice.flush, which Device.update_pixels calls
synchronously ON the render thread — no event-loop involvement, so the
measurement stays honest even when this process's loop is deliberately
frozen.

Two roles for tests/test_process_split.py:
  - subprocess (`python tests/gil_probe.py --burst none|inline`): the render
    process. `inline` reproduces the 2026-08-13 disease — the synthetic GIL
    burst runs on this process's own event loop beside the render thread
    (the shared-interpreter world). `none` is the split world: the render
    process does nothing but render; the test process bursts beside it.
  - import (`make_blob`/`burn`): the burst itself, shared verbatim by both
    arms. json.loads of a multi-megabyte document is ONE uninterruptible
    C-level GIL hold (the scanner builds PyObjects throughout and never
    releases) — the same hold shape as the diagnosed analysis-ingest and
    shape-index bursts, ~250 ms per parse at BLOB_ITEMS, repeated
    back-to-back for the burst duration.

Prints one JSON line on stdout: {"frames", "fps", "gap_p50_ms",
"gap_p95_ms", "gap_max_ms"}.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BLOB_ITEMS = 3_000_000     # ~26 MB JSON, ~250 ms per parse (calibrated)
PIXELS = 2664              # the live crystal-mapper workload (diagnosis §a)
ROWS = 37


def make_blob(items: int = BLOB_ITEMS) -> str:
    return json.dumps(list(range(items)))


def burn(blob: str, seconds: float) -> int:
    """C-level GIL holds back-to-back for `seconds`. Returns parse count."""
    deadline = time.monotonic() + seconds
    parses = 0
    while time.monotonic() < deadline:
        json.loads(blob)
        parses += 1
    return parses


async def probe(burst: str, warmup_s: float, measure_s: float) -> dict:
    from fx import headless

    blob = make_blob() if burst == "inline" else None
    config_dir = tempfile.mkdtemp(prefix="gil-probe-")
    host = await headless.start_headless_host(
        config_dir, pixel_count=PIXELS, rows=ROWS,
        initial_effect={"type": "orbits", "config": {}})
    device = next(iter(host.devices.values()))
    stamps: list[float] = []
    original_flush = device.flush

    def tap(data):
        stamps.append(time.monotonic())
        return original_flush(data)

    device.flush = tap
    try:
        await asyncio.sleep(warmup_s)
        stamps.clear()
        # Sync marker: the test process starts its foreign-interpreter burst
        # the moment the measurement window opens.
        print("MEASURING", flush=True)
        if burst == "inline":
            burn(blob, measure_s)          # blocks THIS loop — the disease
        else:
            await asyncio.sleep(measure_s)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        result = {"frames": len(stamps),
                  "fps": round(len(stamps) / measure_s, 1)}
        # The shared-interpreter arm can starve the render thread so hard
        # that ZERO or ONE frame lands in the whole window (the live 5.3 s
        # full freeze, reproduced) — then there are no gaps to report and
        # the frames/fps numbers ARE the finding.
        if gaps:
            gaps_ms = sorted(g * 1000 for g in gaps)
            result.update(
                gap_p50_ms=round(statistics.median(gaps_ms), 1),
                gap_p95_ms=round(gaps_ms[int(0.95 * (len(gaps_ms) - 1))], 1),
                gap_max_ms=round(gaps_ms[-1], 1),
            )
        return result
    finally:
        device.flush = original_flush
        await host.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--burst", choices=("none", "inline"), default="none")
    parser.add_argument("--warmup", type=float, default=2.0)
    parser.add_argument("--measure", type=float, default=5.0)
    args = parser.parse_args()
    result = asyncio.run(probe(args.burst, args.warmup, args.measure))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
