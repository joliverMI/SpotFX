#!/usr/bin/env python3
"""Raise a WLED's REALTIME TIMEOUT so a Spectra restart does not blink it
(house lighting phase 2, spectra/services/house_restart.py).

While house lighting drives the room, a planned Spectra restart no longer
tells the WLEDs to let go: each keeps its last frame for its OWN realtime
timeout (`if.live.timeout`, in 100 ms units) and the restarted stack picks it
back up. His crystal, TV strip and porch rail are at 500 (50 s) — longer than
a restart. The two kitchen sconces are at 25 (2.5 s), so they still drop to
their boot preset (Breathe / Candle) for most of a restart. This sets the
timeout on the fixtures you name.

DRY RUN BY DEFAULT: it reads each fixture's current value and prints what it
would write. `--apply` writes `{"if": {"live": {"timeout": N}}}` to the
fixture's own `json/cfg` and READS IT BACK — a 2xx is not proof (the codebase's
standing rule). It changes a setting stored on the WLED itself; it is an
operator step, not something Spectra runs.

Addresses come from SPECTRA's stored fx-live config (read-only) by device id,
or pass `--address id=host` to name one directly.

  .venv/bin/python scripts/set_wled_realtime_timeout.py
  .venv/bin/python scripts/set_wled_realtime_timeout.py --apply
  .venv/bin/python scripts/set_wled_realtime_timeout.py crystal --tenths 500
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

DEFAULT_DEVICES = ["sconce-kitchen-left", "sconce-kitchen-right"]
DEFAULT_TENTHS = 500          # 50 s, matching the crystal / TV / porch
TIMEOUT_S = 3.0


def stored_addresses() -> dict[str, str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from spectra import config as scfg
    path = scfg.FX_LIVE_CONFIG_DIR / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                             # noqa: BLE001
        print(f"could not read {path}: {exc}")
        return {}
    out = {}
    for d in raw.get("devices") or []:
        cfg = d.get("config") or {}
        if d.get("type") == "wled" and cfg.get("ip_address"):
            out[str(d["id"])] = str(cfg["ip_address"])
    return out


def read_timeout(host: str):
    r = requests.get(f"http://{host}/json/cfg", timeout=TIMEOUT_S)
    r.raise_for_status()
    return ((r.json().get("if") or {}).get("live") or {}).get("timeout")


def write_timeout(host: str, tenths: int) -> None:
    r = requests.post(f"http://{host}/json/cfg",
                      json={"if": {"live": {"timeout": int(tenths)}}},
                      timeout=TIMEOUT_S)
    r.raise_for_status()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("devices", nargs="*", default=DEFAULT_DEVICES)
    ap.add_argument("--tenths", type=int, default=DEFAULT_TENTHS,
                    help="timeout in 100 ms units (WLED's own unit); default 500 = 50 s")
    ap.add_argument("--address", action="append", default=[],
                    help="id=host, overriding the stored config")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args(argv)
    if not 1 <= args.tenths <= 65000:
        print("--tenths must be 1..65000")
        return 2
    addresses = stored_addresses()
    for item in args.address:
        if "=" in item:
            k, v = item.split("=", 1)
            addresses[k.strip()] = v.strip()
    failed = 0
    for did in args.devices:
        host = addresses.get(did)
        if not host:
            print(f"{did}: no address (not a WLED in the stored config; use --address)")
            failed += 1
            continue
        try:
            current = read_timeout(host)
        except Exception as exc:                         # noqa: BLE001
            print(f"{did} ({host}): could not read its config — {exc}")
            failed += 1
            continue
        line = (f"{did} ({host}): realtime timeout {current} "
                f"({(current or 0) / 10:.1f} s) -> {args.tenths} ({args.tenths / 10:.1f} s)")
        if current == args.tenths:
            print(f"{line}: already set")
            continue
        if not args.apply:
            print(f"{line}: DRY RUN, nothing written")
            continue
        try:
            write_timeout(host, args.tenths)
            back = read_timeout(host)
        except Exception as exc:                         # noqa: BLE001
            print(f"{line}: FAILED — {exc}")
            failed += 1
            continue
        if back == args.tenths:
            print(f"{line}: written and read back")
        else:
            print(f"{line}: written but it reads back {back} — NOT confirmed")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
