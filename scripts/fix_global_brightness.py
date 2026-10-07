#!/usr/bin/env python3
"""One-time correction for the stored `global_brightness` the go-day seeder
copied verbatim from the old LedFX world (pixel-brightness-chain report,
§5/§9: "0.96 in storage/spectra/fx-live/config.json dims every fixture 4%
and is editable nowhere in Spectra").

`fx/config.py`'s own schema already defaults `global_brightness` to 1.0 —
nothing in the live render code wants it below 1.0 — but
`scripts/seed_spectra_fx_live.py` writes a VERBATIM copy of whatever the
source LedFX config held (0.96 on his box, a leftover tweak from before
SPECTRA existed), and nothing in SPECTRA exposes a UI or an API to change
it afterward. The seeder's own copy is now normalized too (see its
docstring) so a future re-seed cannot reintroduce this; this script is the
one-time correction for the value ALREADY on disk.

`global_brightness` is a top-level key of `storage/spectra/fx-live/
config.json`, read once into `host.config` at `FxHost` start
(`fx/virtuals.py`'s `assemble_frame`, `np.multiply(frame,
self._ledfx.config["global_brightness"], frame)`) and otherwise untouched
by the render loop — there is no live write path for it anywhere in
`spectra/` (unlike a device or a scene, which have their own `fx.facade`
PUT routes). A plain file edit made while `spectra.service` is RUNNING
risks nothing itself (nobody ever calls `fx.facade`'s own `/api/config` PUT
for this key, so nothing will flush the old in-memory value back over the
file) — BUT the running process's own `host.config["global_brightness"]`
stays at the old value in memory regardless of what the file says, so the
render loop keeps multiplying by 0.96 until the next restart either way.

Run this with `spectra.service` STOPPED, then start it again with the
corrected file in place — the same order `fix_crystal_brightness_ceiling.py`
documents for a stored value with no HTTP surface of its own.

Dry-run by default; `--apply` writes, after backing the file up to
`storage/spectra/fx-live/backups/`, and asserts the written file is
identical to the original except for exactly the one `global_brightness`
key before declaring success. Idempotent: a file already at 1.0, or with
no `global_brightness` key at all, is reported and left untouched.

    .venv/bin/python scripts/fix_global_brightness.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TARGET = 1.0


def _config_path() -> Path:
    from spectra import config as scfg
    return scfg.FX_LIVE_CONFIG_DIR / "config.json"


def plan(raw: dict) -> dict | None:
    """None when there is nothing to do; otherwise a description of the
    one top-level key this script would change."""
    if "global_brightness" not in raw:
        return None
    current = raw["global_brightness"]
    if current == TARGET:
        return None
    return {"from": current, "to": TARGET}


def apply_plan(raw: dict, change: dict) -> dict:
    out = json.loads(json.dumps(raw))  # deep copy, stdlib only
    out["global_brightness"] = change["to"]
    return out


def assert_only_global_brightness_changed(before: dict, after: dict) -> None:
    b_rest = {k: v for k, v in before.items() if k != "global_brightness"}
    a_rest = {k: v for k, v in after.items() if k != "global_brightness"}
    if b_rest != a_rest:
        raise AssertionError(
            "a top-level config key other than global_brightness changed "
            "— refusing")
    if after.get("global_brightness") != TARGET:
        raise AssertionError(
            f"global_brightness did not land at {TARGET} "
            f"(after={after.get('global_brightness')!r})")


def _backup(path: Path) -> Path:
    backups_dir = path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    dest = backups_dir / f"{path.stem}-pre-global-brightness-fix-{int(time.time())}{path.suffix}"
    dest.write_bytes(path.read_bytes())
    return dest


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None,
                    help="fx-live config.json path (default: "
                         "spectra.config.FX_LIVE_CONFIG_DIR/config.json)")
    ap.add_argument("--apply", action="store_true",
                    help="write the correction (default: dry-run, prints "
                         "the plan only)")
    args = ap.parse_args()

    path = Path(args.config) if args.config else _config_path()
    if not path.exists():
        print(f"no fx-live config at {path} — nothing to correct")
        return 0

    raw = json.loads(path.read_text(encoding="utf-8"))
    change = plan(raw)
    if change is None:
        print(f"{path}: global_brightness is already {TARGET} (or absent) "
              f"— nothing to do")
        return 0

    print(f"{path}: global_brightness is {change['from']!r} — will set it "
          f"to {change['to']}")
    if not args.apply:
        print("dry run — pass --apply to write it. Run this with "
              "spectra.service STOPPED (see this script's own docstring: "
              "there is no live write path for global_brightness).")
        return 0

    backup_path = _backup(path)
    print(f"backed up to {backup_path}")
    corrected = apply_plan(raw, change)
    assert_only_global_brightness_changed(raw, corrected)
    _write_atomic(path, corrected)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert_only_global_brightness_changed(raw, written)
    print(f"wrote global_brightness = {change['to']} to {path}. Start "
          f"spectra.service again to pick it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
