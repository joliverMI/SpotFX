#!/usr/bin/env python3
"""GIVE EVERY WLED IN THE FX-LIVE CONFIG ITS IDENTITY — once, up front.

`fx/devices/wled.py` learns a device's MAC the first time it is actually
contacted, and `spectra/services/device_relocation.py` writes it back. That
covers every device from now on and does NOT cover the one case that hurts:
a fixture whose address ALREADY moved cannot be contacted, so there is
nothing to learn an identity from, so it can never be looked up. This script
is the bootstrap for exactly that gap.

Three sources, in order, and every one of them ends in the device's own
`json/info`:

  PINNED     Contact each WLED at the address the config already has. The
             ordinary case, and the only one that needs no judgement.
  PEERS      For a device that did NOT answer: ask every WLED that DID for
             its `json/nodes` (WLEDs discover each other), read `json/info`
             at each address that is not already spoken for, and offer the
             one whose device NAME matches. This is how his relocated
             sconce is found without anyone knowing where it went.
  --mac      An explicit `id=aa:bb:cc:dd:ee:ff`, which always wins. The
             backlog card `spectra-pins-devices-by-address` records his six.

A NAME MATCH IS A PROPOSAL, NOT A FACT — which is why this script is
DRY-RUN BY DEFAULT (the convention of every migration here). It prints the
pairing it would write; `--apply` writes it, after backing the config up.
Nothing else in the file is touched: only `hardware_id`, only on a WLED,
only where it is absent.

    .venv/bin/python scripts/seed_wled_hardware_ids.py
    .venv/bin/python scripts/seed_wled_hardware_ids.py --apply
    .venv/bin/python scripts/seed_wled_hardware_ids.py \\
        --mac sconce-kitchen-left=e0:8c:fe:5c:3a:78 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_identity as ident                    # noqa: E402
from fx.devices.wled import (read_info,          # noqa: E402
                             read_node_addresses)

PROBE_TIMEOUT_S = 1.0


def default_config_path() -> Path:
    from spectra import config as scfg
    return scfg.FX_LIVE_CONFIG_DIR / "config.json"


def wled_entries(raw: dict) -> list[dict]:
    return [e for e in raw.get("devices", [])
            if isinstance(e, dict) and e.get("type") == "wled"
            and isinstance(e.get("config"), dict)]


def parse_overrides(pairs: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--mac needs id=MAC, got {pair!r}")
        device_id, _, raw = pair.partition("=")
        mac = ident.normalize_mac(raw)
        if mac is None:
            raise SystemExit(f"--mac {device_id}: {raw!r} is not a MAC")
        overrides[device_id.strip()] = mac
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None,
                        help="fx-live config.json (default: SPECTRA's own)")
    parser.add_argument("--apply", action="store_true",
                        help="write the file (default: dry run)")
    parser.add_argument("--mac", action="append", default=[],
                        metavar="ID=MAC",
                        help="an explicit identity; always wins")
    parser.add_argument("--no-discover", action="store_true",
                        help="skip the peer/name-match pass")
    args = parser.parse_args()

    path = args.config or default_config_path()
    if not path.exists():
        print(f"no fx-live config at {path}")
        return 1
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = wled_entries(raw)
    overrides = parse_overrides(args.mac)

    print(f"{path}\n{len(entries)} WLED device(s)\n")

    proposals: dict[str, tuple[str, str]] = {}   # id -> (mac, source)
    unresolved: list[dict] = []
    reachable: list[str] = []

    for entry in entries:
        device_id = entry["id"]
        config = entry["config"]
        existing = ident.normalize_mac(config.get("hardware_id"))
        if device_id in overrides:
            if overrides[device_id] != existing:
                proposals[device_id] = (overrides[device_id], "--mac")
            continue
        if existing is not None:
            print(f"  = {device_id:<24} already has {existing}")
            continue
        address = config.get("ip_address")
        mac = ident.mac_from_info(read_info(address, PROBE_TIMEOUT_S))
        if mac is not None:
            proposals[device_id] = (mac, f"answered at {address}")
            reachable.append(address)
        else:
            unresolved.append(entry)

    if unresolved and not args.no_discover:
        print(f"\n  {len(unresolved)} device(s) did not answer — asking the "
              f"ones that did for their peer list")
        known = {e["config"].get("ip_address") for e in entries}
        candidates: list[str] = []
        for address in reachable:
            for peer in read_node_addresses(address, PROBE_TIMEOUT_S):
                if peer not in known and peer not in candidates:
                    candidates.append(peer)
        seen: dict[str, tuple[str, str]] = {}     # name -> (mac, address)
        for candidate in candidates:
            info = read_info(candidate, PROBE_TIMEOUT_S)
            mac = ident.mac_from_info(info)
            if mac is not None:
                seen[str(info.get("name", "")).strip()] = (mac, candidate)
        for entry in unresolved:
            match = seen.get(str(entry["config"].get("name", "")).strip())
            if match is None:
                continue
            proposals[entry["id"]] = (
                match[0], f"NAME MATCH at {match[1]} — check this")

    for entry in entries:
        device_id = entry["id"]
        if device_id in proposals:
            mac, source = proposals[device_id]
            print(f"  + {device_id:<24} {mac}  ({source})")
        elif ident.normalize_mac(entry["config"].get("hardware_id")) is None:
            print(f"  ? {device_id:<24} no identity found — pass "
                  f"--mac {device_id}=<MAC>")

    if not proposals:
        print("\nnothing to do")
        return 0
    if not args.apply:
        print(f"\nDRY RUN — {len(proposals)} identity/identities would be "
              f"written. Re-run with --apply.")
        return 0

    backup = path.with_name(
        f"{path.stem}.pre-hardware-id.{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.copy2(path, backup)
    for entry in entries:
        if entry["id"] in proposals:
            entry["config"]["hardware_id"] = proposals[entry["id"]][0]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    print(f"\nwrote {len(proposals)} identity/identities (backup: "
          f"{backup.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
