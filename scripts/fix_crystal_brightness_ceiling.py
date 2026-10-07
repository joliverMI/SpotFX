#!/usr/bin/env python3
"""One-time correction for the stored ceiling the pre-fix adoption bug
wrote, 2026-10-06 (PR fm/crystal-255-followup).

PR #356 (deployed 21:42 EDT) made the crystal's own captured brightness
(34) the ceiling `house_fixtures.py` holds it at. Three minutes later, at
21:45:49, its WLED answered `bri: 255` with no reboot evidence behind it,
and the pre-fix `_drift_check` read the absence of a reboot as proof of a
deliberate Home Assistant raise and ADOPTED 255 into
`HouseState.pre_take["crystal"]["bri"]` as the new ceiling — see
house_fixtures.py's module docstring, "BRIGHTNESS IS NEVER ADOPTED", for
the investigation: River's own HA trace proved Home Assistant never made
that write, and Spectra's own `house fixtures:` log showed no write of any
kind landed in that window either. The fix stops this happening again; it
does not, by itself, undo what the earlier adoption already wrote to
disk — `pre_take["crystal"]["bri"]` is still 255 until something corrects
it, and the fixed code only ever corrects a ceiling DOWN to itself, never
retroactively re-derives what it should have been.

This script is that one-time correction: it sets
`pre_take["crystal"]["bri"]` back to 34 — his real level, confirmed by the
deploy-time read at 21:42:47.947 EDT ("crystal -> on (Spectra holds it on,
never above his own brightness (34)): landed") and unmoved by anything
else before the incident.

`house_state.json` is held in memory by a running `spectra.service`
(`spectra/services/house_store.py`'s module-level `_state` cache, loaded
once and never re-read from disk) and re-persisted by `save_state()`
whenever anything else in the fixtures seam changes — a plain file edit
made while the OLD code is still running risks being silently overwritten
the next time something calls it, and does nothing useful once an already
-running OLD process has already settled on believing the ceiling is 255.
Run this AFTER STOPPING spectra.service and BEFORE STARTING it again with
this fix deployed — the same order `docs/HOUSE_HA_SEAM.md`-adjacent fixes
in this codebase already use for a file with no HTTP surface of its own.

Dry-run by default; `--apply` writes, after backing the file up to
`storage/spectra/backups/`. Idempotent: a `pre_take` already at or below
34, or with no `crystal` entry at all, is reported and left untouched.

    .venv/bin/python scripts/fix_crystal_brightness_ceiling.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parent.parent

DEVICE_ID = "crystal"
HIS_REAL_LEVEL = 34


def _state_path() -> Path:
    from spectra import config as scfg
    return Path(scfg.HOUSE_STATE_FILE)


def plan(raw: dict) -> dict | None:
    """None when there is nothing to do; otherwise a description of the
    one field this script would change."""
    pre_take = raw.get("pre_take")
    if not isinstance(pre_take, dict):
        return None
    entry = pre_take.get(DEVICE_ID)
    if not isinstance(entry, dict):
        return None
    current = entry.get("bri")
    if not isinstance(current, int) or current <= HIS_REAL_LEVEL:
        return None
    return {"device": DEVICE_ID, "from": current, "to": HIS_REAL_LEVEL}


def apply_plan(raw: dict, change: dict) -> dict:
    out = json.loads(json.dumps(raw))  # deep copy, stdlib only
    out["pre_take"][change["device"]]["bri"] = change["to"]
    return out


def _backup(path: Path) -> Path:
    backups_dir = path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    dest = backups_dir / f"{path.stem}-pre-crystal-bri-fix-{int(time.time())}{path.suffix}"
    dest.write_bytes(path.read_bytes())
    return dest


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the correction (default: dry-run, prints the plan only)")
    args = ap.parse_args()

    path = _state_path()
    if not path.exists():
        print(f"no house_state.json at {path} — nothing to correct")
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    change = plan(raw)
    if change is None:
        print(f"{DEVICE_ID}'s stored ceiling is already at or below "
              f"{HIS_REAL_LEVEL} (or has no pre_take entry) — nothing to do")
        return 0

    print(f"{path}: {change['device']}'s pre_take brightness ceiling is "
          f"{change['from']} — will set it to {change['to']}")
    if not args.apply:
        print("dry run — pass --apply to write it")
        return 0

    backup_path = _backup(path)
    print(f"backed up to {backup_path}")
    corrected = apply_plan(raw, change)
    _write_atomic(path, corrected)
    print(f"wrote {change['device']}'s pre_take brightness ceiling back to "
          f"{change['to']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
