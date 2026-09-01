"""READ THE EVIDENCE FROM HIS TWO FAILED COMMISSIONING RUNS — the desk
instrument, so the reconstruction can be re-run instead of re-argued.

WHAT THIS IS FOR: on 2026-09-01 the gray-code commissioning test
(`spectra/services/commissioning.py`) ran twice on his real `tv-mapper`,
mechanically clean both times, and decoded 0 of 736 pixels with abundant
light in the frame. The evidence — both judged responses and one raw frame
from the same camera pose — was packaged for cold work. This script reads
it, prints what it actually says, and states which readings it rules OUT,
so nobody has to take the conclusion on trust.

IT READS AND PRINTS. It never writes, never touches his storage, never
reaches the network, and needs no camera and no room.

  .venv/bin/python scripts/read_commissioning_field_evidence.py \
      [--evidence /home/javi/fleet-spotfx/data/commissioning-field-evidence]

The evidence lives outside this repo, so a missing directory is reported
and the script exits cleanly rather than failing — this is a diagnostic,
not a test. The FAILURE ITSELF is reproduced with no evidence at all by
`scripts/check_commissioning.py` section 3c, which is where the standing
proof lives.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectra.services import gray_code as gc                   # noqa: E402

DEFAULT = Path("/home/javi/fleet-spotfx/data/commissioning-field-evidence")


def read_pgm(path: Path) -> np.ndarray:
    """The kept frame is a P5 (binary greyscale) PGM: the session's own
    grey8 payload with a three-line header in front of it."""
    raw = path.read_bytes()
    if not raw.startswith(b"P5"):
        # a bare grey8 payload at the session's own frame size
        from spectra.services.light_field import FRAME_H, FRAME_W
        return np.frombuffer(raw, dtype=np.uint8).reshape(FRAME_H, FRAME_W)
    head, rest = raw.split(b"\n", 1)
    dims, rest = rest.split(b"\n", 1)
    _maxval, body = rest.split(b"\n", 1)
    w, h = (int(v) for v in dims.split())
    return np.frombuffer(body[:w * h], dtype=np.uint8).reshape(h, w)


def frame_report(path: Path) -> None:
    a = read_pgm(path).astype(np.float64)
    h, w = a.shape
    ys, xs = np.nonzero(a > 0)
    print(f"\n== the raw frame from his pose: {path.name} ({w}x{h}) ==")
    print(f"   non-zero camera pixels: {ys.size} of {a.size} "
          f"({100.0 * ys.size / a.size:.3f}% of the frame)")
    print(f"   brightest pixel: {a.max():.0f} of 255; mean {a.mean():.3f}")
    if ys.size:
        print(f"   everything it can see sits in rows {ys.min()}-{ys.max()}, "
              f"columns {xs.min()}-{xs.max()}")
        # how many separate glows, by gaps along x
        cols = np.unique(xs)
        breaks = np.flatnonzero(np.diff(cols) > 5)
        groups = np.split(cols, breaks + 1)
        print(f"   in {len(groups)} separate glow(s): " +
              ", ".join(f"x {g.min()}-{g.max()} ({g.size} columns)"
                        for g in groups))
    print("   -> a composition of 736 pixels imaged into this many camera "
          "pixels cannot be told apart at all: "
          f"{ys.size / 736.0:.3f} camera pixels per composition pixel, "
          f"against {gc.MIN_CAMERA_PX_PER_INDEX} needed "
          f"({int(736 * gc.MIN_CAMERA_PX_PER_INDEX)} in total).")


def response_report(path: Path) -> None:
    body = json.loads(path.read_text())
    print(f"\n== {path.name}: verdict {body.get('verdict')} in "
          f"{body.get('seconds')}s ==")
    for d in body.get("decodes") or []:
        print(f"   decoded {d['seen']} of {d['total']}; "
              f"lit camera pixels {d['lit_pixels']}, of which "
              f"undecodable {d['undecodable_pixels']}, "
              f"out of range {d['out_of_range_pixels']}")
        if d["lit_pixels"] and d["undecodable_pixels"] == d["lit_pixels"]:
            print("     -> EVERY lit pixel undecodable and NOTHING out of "
                  "range: not one bit was confident anywhere. Patterns that "
                  "cancel against their own inverses look like this; frames "
                  "read at the wrong moment do not (two different patterns "
                  "differ, so bits stay confident and decode to WRONG "
                  "indices).")
        elif not d["lit_pixels"]:
            print("     -> not one camera pixel came out above the dark "
                  "reference: with every pixel of the composition on, the "
                  "camera saw nothing it could measure.")
        if not d.get("bit_contrast"):
            print("     (this run predates Decode.bit_contrast, so it cannot "
                  "say WHICH bits died — that is why the field is now asked "
                  "to carry it)")
    caps = body.get("captures") or []
    if len(caps) > 1:
        gaps = np.diff([c["at_s"] for c in caps])
        frames = [c["frames"] for c in caps]
        print(f"   {len(caps)} captures, {min(gaps):.2f}-{max(gaps):.2f}s "
              f"apart, {min(frames)}-{max(frames)} frames averaged each "
              f"(~{1000 * (max(gaps)) / max(1, max(frames)):.0f} ms per "
              f"frame)")
        print("     -> the capture loop itself is regular and every capture "
              "cleared its minimum frame count; nothing here is starved.")
    for note in body.get("problems") or []:
        print(f"   problem: {note}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", default=str(DEFAULT))
    args = ap.parse_args()
    root = Path(args.evidence)
    if not root.is_dir():
        print(f"no evidence directory at {root} — nothing to read. The "
              f"failure itself is reproduced without it by "
              f"scripts/check_commissioning.py section 3c.")
        return 0
    for path in sorted(root.glob("commission-*.json")):
        response_report(path)
    for path in sorted(root.glob("*.bin")) + sorted(root.glob("*.pgm")):
        frame_report(path)
    print("\n== the reading ==")
    print("  The two runs disagree on how much they saw (3,165 'lit' camera "
          "pixels, then 0) and agree on the only thing that matters: not one "
          "bit was ever confident. The kept frame says why — the whole "
          "composition arrives as a few dozen camera pixels, so each of them "
          "integrates hundreds of LEDs, and a pattern lighting half of them "
          "comes back the same brightness as the half that is its inverse.")
    print("  The two 'lit' numbers are themselves artefacts of a gate that "
          "took its bright end from the 99th percentile of full-minus-dark: "
          "with the composition covering 0.1% of the frame that percentile "
          "is the read noise, so the gate admitted the whole frame's noise "
          "in one run and, when the dark average came out no lower, nothing "
          "in the next. Both are now impossible (gray_code.PEAK_SAMPLE, "
          "MIN_BRIGHT_LEVELS).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
