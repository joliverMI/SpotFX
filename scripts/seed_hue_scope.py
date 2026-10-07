#!/usr/bin/env python3
"""Write SPECTRA's Hue allow-list (fx/hue_scope.py) from the bridges.

The allow-list is HIS data: the Hue bulbs SPECTRA may write over the bridge
REST API — his living-room and dining bulbs. This reads both entertainment
areas SPECTRA streams to (storage/spectra/fx-live/config.json's Hue devices)
with GET requests only, takes every member bulb of each, and writes
storage/spectra/hue_scope.json:

  {"lights": {"<light resource id>": "<bulb name>", ...},
   "excluded": {"<id>": "<name>", ...}, "written_at": "...", "source": "..."}

Every bulb in a streamed entertainment area is allowed by default — they
are ordinary bulbs of his Spectra home, not Home Assistant's (his own
correction, 2026-10-06, after an earlier build wrongly carved the Loft
Ceiling Uplight and the three Ledge lights out of the Music Group area as
"left alone"). `--exclude` is still available for a FUTURE bulb he actually
wants Home Assistant to keep, never a default.

Dry run by default (prints the list); --apply writes, backing up any
existing file to storage/spectra/backups/ first. A bulb name in --exclude
that no area contains is refused (a typo would silently allow a bulb).
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_EXCLUDE: tuple[str, ...] = ()


def _get(ip: str, key: str, path: str) -> list:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE           # the bridge's self-signed cert
    req = urllib.request.Request(f"https://{ip}{path}",
                                 headers={"hue-application-key": key})
    with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
        return json.load(resp)["data"]


def area_members(cfg: dict) -> list[tuple[str, str]]:
    """(light id, name) for every bulb in one entertainment area — the same
    entertainment -> device -> light walk ambient.py and release_fade.py
    use, read-only."""
    ip, key = cfg["ip_address"], cfg["username"]
    ent_owner = {e["id"]: e["owner"]["rid"] for e in _get(ip, key, "/clip/v2/resource/entertainment")}
    lights = _get(ip, key, "/clip/v2/resource/light")
    dev_light = {l["owner"]["rid"]: l for l in lights}
    ec = _get(ip, key, f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}")[0]
    out, seen = [], set()
    for channel in ec.get("channels", []):
        for member in channel.get("members", []):
            svc = member.get("service", {})
            if svc.get("rtype") == "entertainment":
                light = dev_light.get(ent_owner.get(svc.get("rid")))
                if light and light["id"] not in seen:
                    seen.add(light["id"])
                    out.append((light["id"], (light.get("metadata") or {}).get("name") or light["id"]))
                break
    return out


def build(config_path: Path, exclude: list[str]) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    allowed: dict[str, str] = {}
    excluded: dict[str, str] = {}
    want_out = {n.strip().lower() for n in exclude}
    for dev in cfg.get("devices") or []:
        if dev.get("type") != "hue":
            continue
        for rid, name in area_members(dev["config"]):
            (excluded if name.strip().lower() in want_out else allowed)[rid] = name
    missing = want_out - {n.strip().lower() for n in excluded.values()}
    if missing:
        raise SystemExit(f"REFUSED: no Hue area contains {sorted(missing)} — "
                         "check the spelling before anything is written")
    return {"lights": dict(sorted(allowed.items(), key=lambda kv: kv[1])),
            "excluded": dict(sorted(excluded.items(), key=lambda kv: kv[1])),
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "scripts/seed_hue_scope.py (read from the bridges)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--exclude", action="append", default=None,
                    help="a bulb name to leave to Home Assistant (repeatable)")
    args = ap.parse_args(argv)
    exclude = args.exclude if args.exclude is not None else list(DEFAULT_EXCLUDE)
    config_path = args.root / "storage" / "spectra" / "fx-live" / "config.json"
    out = build(config_path, exclude)
    for rid, name in out["lights"].items():
        print(f"  allow  {name}  ({rid})")
    for rid, name in out["excluded"].items():
        print(f"  LEAVE  {name}  ({rid}) — Home Assistant's")
    target = args.root / "storage" / "spectra" / "hue_scope.json"
    if not args.apply:
        print(f"dry run — {target} not written (pass --apply)")
        return 0
    if target.exists():
        backups = args.root / "storage" / "spectra" / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        dest = backups / f"hue_scope-{time.strftime('%Y%m%d-%H%M%S')}.json"
        dest.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backup: {dest}")
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".hue_scope", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    os.replace(tmp, target)
    print(f"written: {target} ({len(out['lights'])} bulbs allowed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
