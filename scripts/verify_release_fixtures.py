"""Read-only fixture verification for the release fix
(spectra-release-restores-lights) — the exact method firstmate used by hand
against the real bridges/WLED units the night this defect was found
(entertainment session status + literal per-light state over CLIP v2;
`live`/`fps` over WLED's own json/info), packaged so a future release press
can be checked the same way instead of by hand again.

Makes ZERO writes: every call is a plain GET. Safe to run at any time,
against real hardware, without touching a single bulb — this only reads.

For each Hue bridge declared in SPECTRA's own fx-live config
(storage/spectra/fx-live/config.json — the room's own live config already
carries `ip_address`/`username` for every bridge it knows about):
  - GET /clip/v2/resource/entertainment_configuration — confirms every
    entertainment session is inactive (nothing still streaming).
  - GET /clip/v2/resource/light — every light's on/off, brightness, and xy
    colour, so a human can eyeball whether anything still matches a frame
    SPECTRA last rendered. The incident's tell was exactly this: identical
    on=true/brightness/xy across every bulb in a group, unchanged since the
    stream stopped.

For each WLED device declared the same way:
  - GET http://<ip>/json/info — `live` (realtime streaming) should read
    false after a release; `fps` for context.

"Done" (per the task brief) means: after a release, this reports every Hue
light off (or at least not matching a SPECTRA-authored on/brightness/xy) on
BOTH bridges, and every WLED device's `live` is false.

Run from repo root, against the real fx-live config (or point --config at
a copy, e.g. to check a captured snapshot instead of live hardware):
    .venv/bin/python scripts/verify_release_fixtures.py
    .venv/bin/python scripts/verify_release_fixtures.py --config /path/to/config.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

HUE_TIMEOUT = 5.0
WLED_TIMEOUT = 3.0


def _hue_devices(config: dict) -> list[dict]:
    return [d["config"] for d in config.get("devices", []) if d.get("type") == "hue"]


def _wled_devices(config: dict) -> list[dict]:
    return [d["config"] for d in config.get("devices", []) if d.get("type") == "wled"]


def _report_hue_bridge(cfg: dict) -> None:
    ip = cfg["ip_address"]
    headers = {"hue-application-key": cfg["username"]}
    base = f"https://{ip}"
    print(f"\n--- Hue bridge {ip} ---")
    try:
        resp = requests.get(f"{base}/clip/v2/resource/entertainment_configuration",
                            headers=headers, verify=False, timeout=HUE_TIMEOUT)
        resp.raise_for_status()
        for ec in resp.json().get("data", []):
            print(f"  entertainment_configuration {ec.get('id')} "
                  f"({ec.get('metadata', {}).get('name', '?')}): "
                  f"status={ec.get('status')} "
                  f"active_streamer={ec.get('active_streamer')}")
    except Exception as exc:
        print(f"  ERROR reading entertainment_configuration: {exc!r}")

    try:
        resp = requests.get(f"{base}/clip/v2/resource/light",
                            headers=headers, verify=False, timeout=HUE_TIMEOUT)
        resp.raise_for_status()
        for light in resp.json().get("data", []):
            on = light.get("on", {}).get("on")
            dim = light.get("dimming", {}).get("brightness")
            xy = light.get("color", {}).get("xy", {})
            name = light.get("metadata", {}).get("name", "?")
            print(f"  light {light.get('id')} ({name}): "
                  f"on={on} brightness={dim} xy=({xy.get('x')}, {xy.get('y')})")
    except Exception as exc:
        print(f"  ERROR reading light: {exc!r}")


def _report_wled(cfg: dict) -> None:
    ip = cfg["ip_address"]
    print(f"\n--- WLED {ip} ---")
    try:
        resp = requests.get(f"http://{ip}/json/info", timeout=WLED_TIMEOUT)
        resp.raise_for_status()
        info = resp.json()
        print(f"  live={info.get('live')} fps={info.get('fps')} "
              f"name={info.get('name')}")
    except Exception as exc:
        print(f"  ERROR reading json/info: {exc!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None,
                        help="fx-live config.json path (default: "
                             "storage/spectra/fx-live/config.json under "
                             "SPECTRA_STORAGE_DIR)")
    args = parser.parse_args()

    if args.config:
        config_path = Path(args.config)
    else:
        from spectra import config as scfg
        config_path = scfg.FX_LIVE_CONFIG_DIR / "config.json"

    if not config_path.exists():
        print(f"no fx-live config at {config_path} — nothing to check")
        return

    raw = json.loads(config_path.read_text())
    hue = _hue_devices(raw)
    wled = _wled_devices(raw)
    print(f"config: {config_path}")
    print(f"  {len(hue)} Hue device(s), {len(wled)} WLED device(s)")

    seen_bridges: set = set()
    for cfg in hue:
        ip = cfg.get("ip_address")
        if ip in seen_bridges:
            continue
        seen_bridges.add(ip)
        _report_hue_bridge(cfg)

    for cfg in wled:
        _report_wled(cfg)


if __name__ == "__main__":
    main()
