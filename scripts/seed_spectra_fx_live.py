"""Seed SPECTRA's live fx config dir (storage/spectra/fx-live) from the live
LedFX config — the go-day step that gives the S3 device layer its real
device/virtual definitions (docs/SPECTRA_HANDOVER.md, preparation).

Reads the source config READ-ONLY, validates it against the vendored
CORE_CONFIG_SCHEMA, reports device types (flagging any outside the vendored
driver set — those are skipped by the device registry at start with a
warning, not an error), and writes a verbatim copy. It never touches
~/.ledfx itself and never starts a host — starting real devices is the
handover orchestrator's job, behind the ownership gate.

Dry-run by default; --apply writes. Idempotent (a re-run overwrites with the
fresh source state).

Run from repo root:
    .venv/bin/python scripts/seed_spectra_fx_live.py [--source ~/.ledfx/config.json] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",
                        default=str(Path.home() / ".ledfx" / "config.json"))
    parser.add_argument("--apply", action="store_true",
                        help="write the config (default: dry-run report only)")
    args = parser.parse_args()

    from fx.config import CORE_CONFIG_SCHEMA
    from fx.host import VENDORED_DEVICE_TYPES
    from spectra import config as scfg

    source = Path(args.source).expanduser()
    raw = json.loads(source.read_text())
    validated = CORE_CONFIG_SCHEMA(raw)

    devices = raw.get("devices", [])
    virtuals = raw.get("virtuals", [])
    foreign = sorted({d.get("type") for d in devices} - VENDORED_DEVICE_TYPES)
    print(f"source: {source}")
    print(f"  configuration_version: {raw.get('configuration_version')}")
    print(f"  devices: {len(devices)} "
          f"({sorted({d.get('type') for d in devices})})")
    print(f"  virtuals: {len(virtuals)}")
    if foreign:
        print(f"  WARNING: device types outside the vendored set (skipped at "
              f"host start): {foreign}")
    print(f"  schema: valid ({len(validated)} top-level keys)")

    dest = scfg.FX_LIVE_CONFIG_DIR / "config.json"
    if not args.apply:
        print(f"dry-run: would write {dest} (pass --apply)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    os.replace(tmp, dest)
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
