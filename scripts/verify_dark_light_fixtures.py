"""Read-only fixture verification for global Dark/Light mode
(spectra-dark-light-mode-bar, SPECTRA_SPEC.md §9) — the room-proof standing
order 11 requires ("verify at the bridges, not by trusting a success
message"), packaged so the proof can be re-run the same way instead of by
hand each time.

Makes ZERO writes: every call here is a plain GET. Trigger the actual
dark/light toggle separately (the room bar's "Dark mode" checkbox, or
`curl -X PUT {SPOTFX_URL}/api/room-controls -d '{"dark_mode_enabled": true, ...}'`
with the rest of the current GET /api/room-controls body) — then run this
before/after to see the delta independently of whatever the toggle itself
reported.

Reads, in order:
  1. GET {SPECTRA_URL}/spectra/api/liveness — who currently owns the light
     write plane (spot-effects / spectra / handing-over / released), so the
     rest of this output is read in the right context.
  2. GET {SPECTRA_URL}/api/room-controls — dark_mode_enabled and the shield
     lists as SPECTRA's own durable record currently has them.
  3. GET {ledfx_url}/api/virtuals — best-effort, direct to the external
     LedFX service (only reachable pre-handover, while spot-effects owns —
     see fx/light_ownership.py). Per virtual: config.dark_lock and the
     active effect's background_color/background_brightness — the actual
     enforcement mechanism (spectra/services/dark_light.py), read the same
     way spectra/services/fx_seam.get_virtuals() does, just from outside
     the process. If SPECTRA owns instead, this call has nothing to reach
     (the external service is quiesced) — that's reported, not treated as
     a failure; the answer for that posture lives in step 2's next
     PUT /api/room-controls response (`dark_light_result`) since only the
     live process can join the in-process facade.
  4. For every WLED device declared in SPECTRA's fx-live config (storage/
     spectra/fx-live/config.json) — GET http://<ip>/json/info, external
     confirmation independent of both SPECTRA and LedFX's own bookkeeping.

Run from repo root:
    .venv/bin/python scripts/verify_dark_light_fixtures.py
    .venv/bin/python scripts/verify_dark_light_fixtures.py --spectra-url http://127.0.0.1:8010
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

TIMEOUT = 5.0


def _report_liveness(base: str) -> None:
    print(f"\n--- {base}/spectra/api/liveness ---")
    try:
        resp = requests.get(f"{base}/spectra/api/liveness", timeout=TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        print(f"  owner={body.get('owner')} state={body.get('state')} "
             f"healthy={body.get('healthy')}")
    except Exception as exc:
        print(f"  ERROR: {exc!r}")


def _report_room_controls(base: str) -> None:
    print(f"\n--- {base}/api/room-controls ---")
    try:
        resp = requests.get(f"{base}/api/room-controls", timeout=TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        print(f"  dark_mode_enabled={body.get('dark_mode_enabled')}")
        print(f"  dark_light_shield_categories={body.get('dark_light_shield_categories')}")
        print(f"  dark_light_shield_virtuals={body.get('dark_light_shield_virtuals')}")
    except Exception as exc:
        print(f"  ERROR: {exc!r}")


def _report_ledfx_virtuals(ledfx_url: str) -> None:
    print(f"\n--- {ledfx_url}/api/virtuals (direct, pre-handover only) ---")
    try:
        resp = requests.get(f"{ledfx_url}/api/virtuals", timeout=TIMEOUT)
        resp.raise_for_status()
        virtuals = resp.json().get("virtuals", {})
        if not virtuals:
            print("  no virtuals reported")
        for vid, v in sorted(virtuals.items()):
            dark_lock = (v.get("config") or {}).get("dark_lock", False)
            effect = v.get("effect") or {}
            cfg = effect.get("config") or {}
            print(f"  {vid}: dark_lock={dark_lock} effect={effect.get('type')} "
                 f"background_color={cfg.get('background_color')} "
                 f"background_brightness={cfg.get('background_brightness')}")
    except Exception as exc:
        print(f"  ERROR (expected if SPECTRA currently owns — the external "
             f"service is quiesced then): {exc!r}")


def _report_wled(cfg: dict) -> None:
    ip = cfg["ip_address"]
    print(f"\n--- WLED {ip} ---")
    try:
        resp = requests.get(f"http://{ip}/json/info", timeout=3.0)
        resp.raise_for_status()
        info = resp.json()
        print(f"  live={info.get('live')} fps={info.get('fps')} "
             f"name={info.get('name')}")
    except Exception as exc:
        print(f"  ERROR reading json/info: {exc!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spectra-url", default=os.getenv("SPECTRA_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--ledfx-url", default=None,
                        help="default: spectra.config.ledfx_url()")
    parser.add_argument("--fx-live-config", default=None,
                        help="default: storage/spectra/fx-live/config.json under "
                             "SPECTRA_STORAGE_DIR")
    args = parser.parse_args()

    from spectra import config as scfg
    ledfx_url = args.ledfx_url or scfg.ledfx_url()

    _report_liveness(args.spectra_url)
    _report_room_controls(args.spectra_url)
    _report_ledfx_virtuals(ledfx_url)

    config_path = Path(args.fx_live_config) if args.fx_live_config \
        else scfg.FX_LIVE_CONFIG_DIR / "config.json"
    if not config_path.exists():
        print(f"\nno fx-live config at {config_path} — skipping WLED reads")
        return
    raw = json.loads(config_path.read_text())
    wled = [d["config"] for d in raw.get("devices", []) if d.get("type") == "wled"]
    for cfg in wled:
        _report_wled(cfg)


if __name__ == "__main__":
    main()
