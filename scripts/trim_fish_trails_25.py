"""Apply his 2026-09-17 word to the LIVE Fish effect: trails 25% shorter,
25% narrower, colour untouched.

    trail_decay:  0.4  -> 0.29   (smear half-life 0.22s -> 0.165s, -25%)
    ripple_life:  0.9  -> 0.675  (wake fades 25% sooner)
    ripple_width: 1.3  -> 0.975  (wake deposits 25% narrower)

These three values are also the new schema/registry defaults as of this
change (fx/effects/fish.py, config/effect_params.json) — a FRESH Fish
instance already lands here. This script exists only to bring the
CURRENTLY RUNNING instance forward without waiting for a restart or a
re-fire, since his live fx-live config carries the OLD values explicitly.

No live effects-config write API. Checked before writing this: SPECTRA
does not expose a generic "PUT this virtual's effect config" HTTP route to
external callers — `spectra/app.py` mounts no `/api/virtuals/{id}/effects`
router, and the legacy-compatible route of that shape
(`api/ledfx_client.py`, root spot-effects) only reaches the real external
LedFX process, which the ownership split keeps deliberately stopped
whenever SPECTRA owns the room (which is exactly when the fish scene's
fx-live config would be SPECTRA's own). So this writes
`storage/spectra/fx-live/config.json` directly, under a timestamped
backup, the same shape scripts/repair_copy_carrier_active_flags.py uses.

THIS ONLY TAKES EFFECT ON THE NEXT `spectra.service` RESTART (or the next
time the Fish scene builds a fresh effect instance some other way — a
type-switch write, a scene re-fire that doesn't already carry these three
keys). A config-file edit alone does not reach an already-running Python
effect object; the live process only re-reads this file at config load.
Say so plainly, don't imply otherwise.

Dry-run by default; --apply writes (atomic tmp+replace) AFTER copying the
config to a timestamped backup, then reads the file back and prints the
landed values for the touched virtual(s).

Run from repo root:
    .venv/bin/python scripts/trim_fish_trails_25.py [--config PATH] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EFFECT_TYPE = "fish"  # fx/effects/fish.py's registry key (module basename)

TARGETS = {
    "trail_decay": 0.29,
    "ripple_life": 0.675,
    "ripple_width": 0.975,
}


def fish_virtuals(virtuals: list[dict]) -> list[dict]:
    out = []
    for v in virtuals:
        effect = v.get("effect") or {}
        if str(effect.get("type") or "") == EFFECT_TYPE:
            out.append(v)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None,
                        help="fx-live config.json path (default: "
                             "spectra.config.FX_LIVE_CONFIG_DIR/config.json)")
    parser.add_argument("--apply", action="store_true",
                        help="write the change (default: dry-run report)")
    args = parser.parse_args()

    if args.config:
        path = Path(args.config)
    else:
        from spectra import config as scfg
        path = scfg.FX_LIVE_CONFIG_DIR / "config.json"

    if not path.exists():
        print(f"no fx config at {path} — pass --config PATH")
        return 2

    original = json.loads(path.read_text(encoding="utf-8"))
    virtuals = original.get("virtuals") or []
    print(f"config: {path}")
    print(f"  {len(virtuals)} virtuals")

    targets = fish_virtuals(virtuals)
    if not targets:
        print(f"  no virtual with effect.type == {EFFECT_TYPE!r} found — "
              f"nothing to do")
        return 0

    print(f"\n  {len(targets)} fish virtual(s) found:")
    for v in targets:
        cfg = (v.get("effect") or {}).get("config") or {}
        current = {k: cfg.get(k) for k in TARGETS}
        print(f"    {v.get('id')}: current {current} -> target {TARGETS}")

    if not args.apply:
        print(f"\ndry-run: would set {list(TARGETS)} on "
              f"{[v.get('id') for v in targets]} in {path} (pass --apply). "
              f"Only those three keys change; every other key (colour, "
              f"every other param) keeps its stored value. This edits the "
              f"config file only — the change reaches the room on the "
              f"next spectra.service restart, not immediately.")
        return 0

    # Build the patched config on a fresh copy of the raw dict.
    patched = json.loads(json.dumps(original))
    patched_ids = set()
    for v in patched.get("virtuals") or []:
        effect = v.get("effect") or {}
        if str(effect.get("type") or "") != EFFECT_TYPE:
            continue
        effect.setdefault("config", {})
        effect["config"].update(TARGETS)
        patched_ids.add(str(v.get("id")))

    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"{path.stem}-fish-trails-{stamp}.json"
    shutil.copy2(path, backup_path)
    print(f"\nbacked up {path} -> {backup_path}")

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(patched, ensure_ascii=False, sort_keys=True,
                              indent=4), encoding="utf-8")
    os.replace(tmp, path)

    # Re-read what actually landed.
    written = json.loads(path.read_text(encoding="utf-8"))
    if written != patched:
        raise SystemExit("FATAL: the written file does not match the "
                         "planned config — check the backup at "
                         + str(backup_path))

    print(f"wrote {path}. Landed values for each touched virtual "
          f"(read back from disk):")
    for v in written.get("virtuals") or []:
        if str(v.get("id")) not in patched_ids:
            continue
        cfg = (v.get("effect") or {}).get("config") or {}
        landed = {k: cfg.get(k) for k in TARGETS}
        print(f"    {v.get('id')}: {landed}")

    print("\nNOTE: this is a config-file write only. Restart "
          "spectra.service (systemctl --user restart spectra) for the "
          "running Fish effect instance to pick these values up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
