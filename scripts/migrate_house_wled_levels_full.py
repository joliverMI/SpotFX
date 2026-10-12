#!/usr/bin/env python3
"""D3a — every WLED fixture row's house-mode levels go to 100%, ONCE, at ship.

The Admiral, 2026-10-12 (data/wled-bri-audit/report.md, "do all recs on
wled brightness card"): a WLED's master brightness is Home Assistant's, and
Spectra never writes it. The house modes' per-fixture Levels were seeded to
STAND IN for that brightness (the crystal at 12% / 13% / 3% / 6% / 1.2% —
HA's own WLED preset values), but they are pixel brightness, and now they
MULTIPLY with Home Assistant's: left alone, every mode would look Home
Assistant's brightness times darker (Standard's crystal at 12% of 34/255 is
about 1.6% of full). D3a: set the WLED rows to 100% at ship, let Home
Assistant carry per-mode / time-of-day brightness, then tune together.

WHAT CHANGES: in every mode, every FIXTURE row (`target.kind == "fixture"`)
naming a WLED device that is not `off` has its `level` and `music_level`
set to 100 wherever they are set to anything else. A row that is `off`
stays off. Hue rows, dummies and anything not a WLED are untouched. A
CATEGORY or EVERYTHING row carrying a level is NAMED and left alone — it may
reach Hue or non-WLED fixtures too, so moving it is his call, not this
script's (his seeded modes have none).

HOW: through the live service only — `GET /api/house/modes` and
`GET /api/devices` (which fixtures are WLEDs) to plan, `POST
/api/house/modes` per changed mode to apply, the same writer the House page
uses, so an edit to the live mode lands at once (the route re-ticks it).
The modes as read are written to storage/spectra/backups/ first. Dry run by
default; `--apply` writes. Idempotent: a second run finds nothing to do.

Run from repo root, after the deploy that ships the WLED-brightness fix:
    .venv/bin/python scripts/migrate_house_wled_levels_full.py \\
        --spectra-url http://127.0.0.1:8010            # dry run
    .venv/bin/python scripts/migrate_house_wled_levels_full.py \\
        --spectra-url http://127.0.0.1:8010 --apply
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FULL = 100.0
LEVEL_KEYS = ("level", "music_level")


def plan_modes(modes: list[dict], wled_ids: set[str]
               ) -> tuple[list[dict], list[dict], list[dict]]:
    """(modes to write, one line per changed value, rows left alone and
    named). Pure: nothing is read or written here."""
    to_write: list[dict] = []
    changes: list[dict] = []
    left: list[dict] = []
    for mode in modes:
        new = copy.deepcopy(mode)
        moved = False
        for row in new.get("fixtures") or []:
            target = row.get("target") or {}
            kind, tid = target.get("kind"), target.get("id")
            levels = {k: row.get(k) for k in LEVEL_KEYS
                      if row.get(k) is not None}
            if kind != "fixture":
                if levels:
                    left.append({"mode": mode.get("name"), "target": target,
                                 **levels,
                                 "why": "a category/everything row may reach "
                                        "Hue or non-WLED fixtures — his call"})
                continue
            if tid not in wled_ids or row.get("off"):
                continue
            for key, value in levels.items():
                if float(value) != FULL:
                    changes.append({"mode": mode.get("name"), "fixture": tid,
                                    "field": key, "from": value, "to": FULL})
                    row[key] = FULL
                    moved = True
        if moved:
            to_write.append(new)
    return to_write, changes, left


def _get(base: str, path: str) -> dict:
    import requests
    url = f"{base}{path}"
    try:
        resp = requests.get(url, timeout=10.0)
    except requests.RequestException as exc:
        raise SystemExit(f"FATAL: could not reach {url} ({exc}) — is "
                         f"--spectra-url right and spectra.service running?")
    if resp.status_code != 200:
        raise SystemExit(f"FATAL: {url} answered HTTP {resp.status_code}: "
                         f"{resp.text}")
    return resp.json()


def _post_mode(base: str, mode: dict) -> dict:
    import requests
    url = f"{base}/api/house/modes"
    resp = requests.post(url, json=mode, timeout=10.0)
    if resp.status_code != 200:
        raise SystemExit(f"FATAL: the live service refused mode "
                         f"{mode.get('name')!r} (HTTP {resp.status_code}: "
                         f"{resp.text}) — the modes before it were written; "
                         f"re-running is safe")
    return resp.json()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spectra-url", required=True,
                    help="the live SPECTRA service, e.g. http://127.0.0.1:8010")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--root", type=Path, default=REPO,
                    help="where storage/spectra/backups/ lives")
    args = ap.parse_args(argv)
    base = args.spectra_url.rstrip("/")
    modes = _get(base, "/api/house/modes").get("modes") or []
    devices = _get(base, "/api/devices").get("devices") or []
    wled_ids = {str(d.get("id")) for d in devices
                if str(d.get("type") or "").lower() == "wled"}
    to_write, changes, left = plan_modes(modes, wled_ids)

    print(f"WLED fixtures: {', '.join(sorted(wled_ids)) or '(none found)'}")
    for c in changes:
        print(f"  {c['mode']}: {c['fixture']} {c['field']} {c['from']} -> {c['to']:g}")
    for row in left:
        print(f"  LEFT ALONE {row['mode']}: {row['target']} — {row['why']}")
    if not changes:
        print("nothing to change — every WLED row is already at 100%")
        return 0
    if not args.apply:
        print(f"dry run: {len(changes)} value(s) in {len(to_write)} mode(s) "
              f"would move to 100% — pass --apply to write")
        return 0
    backups = args.root / "storage" / "spectra" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"house_modes-pre-wled-full-{time.strftime('%Y%m%d-%H%M%S')}.json"
    tmp = backup.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"modes": modes}, indent=2), encoding="utf-8")
    os.replace(tmp, backup)
    print(f"backed up the modes as read to {backup}")
    for mode in to_write:
        _post_mode(base, mode)
        print(f"  wrote {mode.get('name')}")
    _w, again, _l = plan_modes(
        _get(base, "/api/house/modes").get("modes") or [], wled_ids)
    if again:
        print(f"FAILED: {len(again)} value(s) still not at 100% after the write")
        return 1
    print(f"done: {len(changes)} value(s) in {len(to_write)} mode(s) now at 100%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
