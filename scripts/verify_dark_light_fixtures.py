"""Read-only fixture verification for global Dark/Light mode
(spectra-dark-light-mode-bar, SPECTRA_SPEC.md §9) — the room-proof standing
order 11 requires ("verify at the bridges, not by trusting a success
message"), packaged so the proof can be re-run the same way instead of by
hand each time.

HAZARD, learned the hard way (2026-08-15, PR #70): a disposable worktree
isolates the FILESYSTEM ONLY, not the NETWORK. 127.0.0.1:8010 (SPECTRA) and
127.0.0.1:8000 (spot-effects/LedFX) are the SAME live instances whether
you're inside the primary checkout or any throwaway worktree on this host
— there is no such thing as "the localhost in my sandbox" for a loopback
address. A verification script that silently DEFAULTS to those addresses
is therefore a trap: running it as a casual sanity check reaches his real,
live room exactly as surely as a deliberate `curl` would. This script has
NO default target — --spectra-url and --ledfx-url are both REQUIRED, on
purpose, so pointing this at anything (his room included) is something you
had to type, not something that happened by omission. If you actually mean
his live room, say so explicitly and know that you are doing it; there is
no "just try it and see" mode.

Makes ZERO writes: every call here is a plain GET regardless of target.
Trigger the actual display-mode switch separately (the room bar's
Hybrid/Dark/Light select, or
`curl -X PUT {SPOTFX_URL}/api/room-controls -d '{"display_mode": "dark", ...}'`
with the rest of the current GET /api/room-controls body) — then run this
before/after to see the delta independently of whatever the toggle itself
reported. GET-only is a floor, not a licence: only point this at his real
room with his room in hand, same as any other room-proof step.

Reads, in order:
  1. GET {SPECTRA_URL}/spectra/api/liveness — who currently owns the light
     write plane (spot-effects / spectra / handing-over / released), so the
     rest of this output is read in the right context.
  2. GET {SPECTRA_URL}/api/room-controls — display_mode, the light-bg
     colour/brightness, and the shield lists as SPECTRA's own durable
     record currently has them.
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

Run from repo root, both URLs explicit and required — e.g. against a local
throwaway rehearsal stack you started yourself (NOT his real room):
    .venv/bin/python scripts/verify_dark_light_fixtures.py \\
        --spectra-url http://127.0.0.1:9010 --ledfx-url http://127.0.0.1:9888
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
        print(f"  display_mode={body.get('display_mode')}")
        print(f"  display_light_bg_color={body.get('display_light_bg_color')}")
        print(f"  display_light_bg_brightness={body.get('display_light_bg_brightness')}")
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
    # NO defaults on either URL, deliberately — see the module docstring's
    # HAZARD note. A missing --spectra-url/--ledfx-url must refuse loudly,
    # never silently resolve to a real, live address (his room's or
    # anyone else's) via an environment variable or a config helper's own
    # fallback (spectra.config.ledfx_url() defaults to 127.0.0.1:8888/etc,
    # which is exactly the kind of implicit target this script must not
    # have).
    parser.add_argument("--spectra-url", required=True,
                        help="e.g. http://127.0.0.1:9010 — no default, must be explicit")
    parser.add_argument("--ledfx-url", required=True,
                        help="e.g. http://127.0.0.1:9888 — no default, must be explicit")
    parser.add_argument("--fx-live-config", default=None,
                        help="default: storage/spectra/fx-live/config.json under "
                             "SPECTRA_STORAGE_DIR")
    args = parser.parse_args()

    from spectra import config as scfg

    _report_liveness(args.spectra_url)
    _report_room_controls(args.spectra_url)
    _report_ledfx_virtuals(args.ledfx_url)

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
