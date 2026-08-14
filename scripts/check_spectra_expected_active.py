"""Validate (and optionally correct) which of storage/spectra/fx-live/
config.json's declared-active virtuals the room genuinely drives — the
"unfalsifiable gate" fix (report gate, 2026-08-14).

fx-live/config.json is seeded VERBATIM from the old LedFX world
(scripts/seed_spectra_fx_live.py) and inherits its dynamic tricks: a
full-span "crystal" duplicate of "crystal-mapper", mask/foreground/
background layer virtuals per mapper, gap-* dummy placeholders, and
contextual rooms (dining, porch, sconces) the old app drove but SPECTRA's
own scene engine may never address. spectra.services.live_host reads
EVERY declared-active virtual (has "effect", not explicitly active:false)
as something the activation gate must see rise — necessary but not
sufficient, so a config carrying stale declarations can refuse a
handover forever on layers that were never supposed to rise.

Ground truth (spectra/services/room_topology.py, the SAME truth
spectra/services/scene_compiler.py resolves real fires against):
storage/device_categories.json's imported category topology (fx.device_
model) unioned with every stored scene's LITERAL virtual targets
(target_kind="virtual"). A declared-active virtual outside that union was
never brought into the room's addressable topology.

This script is diagnostic evidence, not the enforcement point — spectra/
services/live_host.py's LiveLights.activate() already intersects the
declared set against the SAME ground truth at every activation, so a
stale declaration can no longer wedge the gate even before this script
ever runs. --apply here additionally corrects the PERSISTED config (marks
stale declarations active:false) so the file itself stops lying and a
plain read of it matches reality — belt and braces, not the fix itself.

Dry-run by default; --apply writes. Idempotent (a stale id already marked
inactive is left alone; nothing here is ever removed, only flagged).
REFUSES to apply when no ground truth exists (storage/device_categories
.json missing/empty AND zero stored scenes reference a literal virtual) —
an absent ground truth must never be read as "everything is stale."

Run from repo root:
    .venv/bin/python scripts/check_spectra_expected_active.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _classify(vid: str, declared_ids: set[str], devices_by_id: dict) -> str:
    """Best-effort, human-readable characterization for the evidence report
    ONLY — the apply decision is driven purely by ground-truth membership
    (see module docstring), never by this heuristic. Helps a reviewer see
    WHY an id looks stale without re-deriving it by hand."""
    if vid.endswith(("-mask", "-foreground", "-background")):
        return "mask/foreground/background layer virtual (blender composite)"
    if f"{vid}-mapper" in declared_ids:
        return "full-span duplicate of the real mapper virtual"
    if any(part in vid for part in ("dining", "porch", "sconce")):
        return "legacy contextual room (old app's dinner-party/ambient driving)"
    device = devices_by_id.get(vid)
    if device is not None and device.get("type") == "dummy":
        return "dummy-backed virtual (gap placeholder or headless stand-in)"
    return "unclassified — needs owner review"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None,
                        help="fx-live config.json path (default: spectra.config.FX_LIVE_CONFIG_DIR/config.json)")
    parser.add_argument("--apply", action="store_true",
                        help="write the correction (default: dry-run report only)")
    args = parser.parse_args()

    from spectra import config as scfg
    from spectra.services.live_host import _config_expected_active_ids
    from spectra.services.room_topology import genuinely_driven_virtual_ids

    path = Path(args.config) if args.config else scfg.FX_LIVE_CONFIG_DIR / "config.json"
    if not path.exists():
        print(f"no fx-live config at {path} — nothing to validate")
        return
    raw = json.loads(path.read_text())

    declared = _config_expected_active_ids(raw)
    driven = genuinely_driven_virtual_ids()
    devices_by_id = {d.get("id"): d for d in raw.get("devices") or []}

    print(f"config: {path}")
    print(f"  declared-active virtuals: {len(declared)}")
    print(f"  genuinely-driven ground truth: {len(driven)} virtual(s) "
          f"(storage/device_categories.json categories ∪ scenes' literal "
          f"virtual targets)")

    if not driven:
        print("  NO GROUND TRUTH AVAILABLE — storage/device_categories.json "
              "is missing/empty and no stored scene literally targets a "
              "virtual. Cannot distinguish genuinely-driven from stale; "
              "every declared-active id is reported as-is, unclassified, "
              "and --apply is refused (an absent ground truth must never "
              "be read as 'everything is stale').")
        for vid in sorted(declared):
            print(f"    - {vid}")
        if args.apply:
            print("REFUSED: no ground truth — nothing written")
        return

    stale = sorted(declared - driven)
    confirmed = sorted(declared & driven)
    missing = sorted(driven - declared)

    print(f"  confirmed genuinely-driven: {len(confirmed)}")
    for vid in confirmed:
        print(f"    - {vid}")
    print(f"  declared-active but OUTSIDE the driven ground truth "
          f"(candidates for correction): {len(stale)}")
    for vid in stale:
        print(f"    - {vid}: {_classify(vid, declared, devices_by_id)}")
    if missing:
        print(f"  genuinely-driven but NOT declared active in this config "
              f"(possibly under-declared — worth a human look): {len(missing)}")
        for vid in missing:
            print(f"    - {vid}")

    if not stale:
        print("nothing to correct — every declared-active virtual is "
              "genuinely driven")
        return

    if not args.apply:
        print(f"dry-run: would mark {len(stale)} virtual(s) active:false "
              f"in {path} (pass --apply)")
        return

    virtuals = raw.get("virtuals") or []
    corrected = 0
    for v in virtuals:
        if v.get("id") in stale:
            v["active"] = False
            corrected += 1
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    os.replace(tmp, path)
    print(f"wrote {path}: marked {corrected} virtual(s) active:false")


if __name__ == "__main__":
    main()
