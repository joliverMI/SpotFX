"""Bootstrap a shape map from a virtual's existing gap/LED segment list.

Decodes the live LedFX segments into the canonical `shape v1` text
(ledfx/shapemap.py), so an already-hand-mapped device (the crystal) gets its
map — pole holes and interleaved strip order included — without re-authoring.

Usage:
  .venv/bin/python scripts/bootstrap_shape_map.py --virtual crystal-mapper
      print the decoded map text
  ... --verify    also recompile the text and assert the regenerated
                  segments equal the live ones exactly (round-trip proof),
                  and dry-run it through the LedFX shape endpoint
  ... --apply     PUT the map to LedFX (idempotent when in sync)
"""

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, "/home/javi/ledfx-src")

from ledfx import shapemap  # noqa: E402

LEDFX = "http://localhost:8888"


def _get(path):
    with urllib.request.urlopen(f"{LEDFX}{path}", timeout=10) as r:
        return json.load(r)


def _put(path, body):
    req = urllib.request.Request(
        f"{LEDFX}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="PUT",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--virtual", default="crystal-mapper")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    vdata = _get(f"/api/virtuals/{args.virtual}")
    v = vdata.get(args.virtual, vdata.get("virtual", vdata))
    segments = v["segments"]
    rows = v["config"]["rows"]
    total = sum(s[2] - s[1] + 1 for s in segments)
    width = total // rows
    print(f"{args.virtual}: {len(segments)} segments, {total} px, "
          f"{width}x{rows} grid", file=sys.stderr)

    shape = shapemap.decode_segments(segments, width, rows)
    print(f"decoded: {shape.n_leds} LEDs, parity={shape.parity}, "
          f"digest={shape.digest}", file=sys.stderr)
    print(shape.text)

    if args.verify:
        regen = [list(s) for s in shape.segments]
        live = [list(s) for s in segments]
        assert regen == live, "round-trip segments differ from live config!"
        print("verify: regenerated segments == live segments ✓", file=sys.stderr)
        res = _put(f"/api/virtuals/{args.virtual}/shape",
                   {"shape_map": shape.text, "dry_run": True})
        assert res.get("status") == "success", f"dry-run failed: {res}"
        s = res["summary"]
        assert s["live"] == shape.n_leds and s["in_sync"], f"dry-run summary: {s}"
        print(f"verify: LedFX dry-run ✓ (live={s['live']}, in_sync={s['in_sync']}, "
              f"truncated={res.get('truncated')})", file=sys.stderr)

    if args.apply:
        res = _put(f"/api/virtuals/{args.virtual}/shape",
                   {"shape_map": shape.text})
        if res.get("status") != "success":
            print(f"apply FAILED: {res}", file=sys.stderr)
            return 1
        print(f"apply: {res['summary']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
