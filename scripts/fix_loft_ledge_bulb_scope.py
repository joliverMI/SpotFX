#!/usr/bin/env python3
"""One-time catch-up for the room state the code-default fixes in
scripts/seed_hue_scope.py and scripts/seed_house_lighting.py do not
themselves correct.

His order, 2026-10-06 ~20:15 EDT, relayed by the main firstmate, verbatim:
"i want the loft and ledge bulbs to be part of the living room hues, they
should be part of the spectra home. they shouldnt be treated differently.
that was an incorrect assumption yall made."

The code fix (fx/hue_scope.py's module docstring, AGENTS.md's "THE FOUR
BULBS ARE ORDINARY") changed only what a FRESH seeder run would write
going forward — scripts/seed_hue_scope.py's DEFAULT_EXCLUDE is now empty,
and scripts/seed_house_lighting.py no longer seeds HUE_LEFT_ALONE. Neither
touches what a PRIOR run of either already wrote to his real room:

  storage/spectra/hue_scope.json          the Loft Ceiling Uplight and the
                                          three Ledge bulbs sit in
                                          "excluded", not the "lights"
                                          allow-list fx/hue_scope.put()
                                          and fx/devices/hue.py's stream
                                          guard actually read
  HouseSettings.hue_excluded_lights        (storage/spectra/
                                          house_modes.json) still names the
                                          same four, which keeps every
                                          house-mode write away from them

Both files are gitignored/untracked and are re-read fresh on every call —
nothing on load migrates or clears either (grep-confirmed: neither
spectra/services/house.py nor house_store.py nor fx/hue_scope.py's own
read path mentions a migration), so a deploy restart alone (his own
standing order 35: a restart with its usual announcements is fine) leaves
both exactly as a prior --apply run wrote them.

TWO HALVES, deliberately different write paths:

(a) hue_scope.json has no HTTP surface of its own — fx/hue_scope.py reads
    it straight off disk on every write, same as scripts/seed_hue_scope.py
    itself writes it — so this half is a plain, backed-up, atomic file
    edit: move the four bulbs from "excluded" into "lights". Safe to run
    whether or not spectra.service is up, for the same reason
    seed_hue_scope.py's own direct file write already is.

(b) HouseSettings.hue_excluded_lights must be reached ONLY through the
    live service's own PUT /api/house/settings
    (spectra/services/house.py::apply_settings_patch — the ONE writer,
    shared with Sonic's house_console.py). A direct edit to
    house_modes.json would race the running service's own reconcilers,
    which need to re-tick through that same function on every settings
    save (apply_settings_patch re-applies immediately when
    hue_excluded_lights moves) — editing the file out from under a live
    process skips that re-tick entirely. So this half REQUIRES
    --spectra-url and REFUSES (non-zero exit, nothing written) if --apply
    is passed without it, rather than silently skipping it.

Both halves are idempotent: a bulb already in "lights", or a name already
absent from hue_excluded_lights, is reported as already-correct with no
further write. Dry-run by default; --apply writes. The hue_scope.json half
is backed up to storage/spectra/backups/ first, matching
scripts/seed_hue_scope.py's own --apply convention.

Run from repo root, after restarting spectra.service:
    .venv/bin/python scripts/fix_loft_ledge_bulb_scope.py \
        --spectra-url http://127.0.0.1:8010 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parent.parent

#: His own bulb names, exactly as scripts/seed_house_lighting.py's retired
#: HUE_LEFT_ALONE and the 2026-10-06 docs named them.
BULB_NAMES = ("Loft Ceiling Uplight", "Ledge Left", "Ledge Right",
             "Ledge Center")
_WANT = {n.lower() for n in BULB_NAMES}


def plan_scope(scope: dict) -> dict[str, str]:
    """Which (light resource id -> name) pairs currently sit in `excluded`
    and match one of his four names — the only ones this script ever
    moves. A bulb already in `lights` (by either half's prior run, or a
    fresh scripts/seed_hue_scope.py run under the fixed default) is not
    re-planned."""
    excluded = scope.get("excluded") if isinstance(scope, dict) else None
    if not isinstance(excluded, dict):
        return {}
    return {str(rid): str(name) for rid, name in excluded.items()
           if str(name).strip().lower() in _WANT}


def apply_scope(scope: dict, to_move: dict[str, str]) -> dict:
    """Move exactly `to_move`'s pairs from `excluded` to `lights`,
    byte-for-byte for everything else — mirrors
    scripts/seed_hue_scope.py's own sorted-by-name write shape."""
    lights = dict(scope.get("lights") or {})
    excluded = dict(scope.get("excluded") or {})
    for rid, name in to_move.items():
        lights[rid] = name
        excluded.pop(rid, None)
    out = dict(scope)
    out["lights"] = dict(sorted(lights.items(), key=lambda kv: kv[1]))
    out["excluded"] = dict(sorted(excluded.items(), key=lambda kv: kv[1]))
    return out


def plan_hue_excluded_lights(current: list) -> list[str]:
    """The settings value with his four names removed, case-insensitively
    — mirrors HouseSettings's own `_light_names` validator's
    case-insensitive comparison."""
    return [n for n in (current or []) if str(n).strip().lower() not in _WANT]


def _write_scope_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def apply_house_settings(spectra_url: str, new_excluded: list[str]) -> dict:
    """Clear the four names through the live service's own settings PUT —
    the exact call spectra/api/house.py::put_settings makes, so the
    running process's own reconcilers (apply_settings_patch's immediate
    re-tick on hue_excluded_lights moving) see it, rather than a file
    edit the live process would never notice."""
    import requests
    base = spectra_url.rstrip("/")
    url = f"{base}/api/house/settings"
    try:
        resp = requests.put(url, json={"hue_excluded_lights": new_excluded},
                            timeout=10.0)
    except requests.RequestException as exc:
        raise SystemExit(
            f"FATAL: could not reach the live service at {url} to clear "
            f"hue_excluded_lights ({exc}) — is --spectra-url correct, and "
            f"is spectra.service actually running?")
    if resp.status_code != 200:
        raise SystemExit(
            f"FATAL: the live service refused the settings update at "
            f"{url} (HTTP {resp.status_code}: {resp.text}) — nothing "
            f"further was applied")
    return resp.json()


def get_house_settings(spectra_url: str) -> dict:
    import requests
    base = spectra_url.rstrip("/")
    url = f"{base}/api/house/settings"
    try:
        resp = requests.get(url, timeout=10.0)
    except requests.RequestException as exc:
        raise SystemExit(
            f"FATAL: could not reach the live service at {url} to read "
            f"its current settings ({exc}) — is --spectra-url correct, "
            f"and is spectra.service actually running?")
    if resp.status_code != 200:
        raise SystemExit(
            f"FATAL: the live service refused to report its settings at "
            f"{url} (HTTP {resp.status_code}: {resp.text})")
    return resp.json()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write both halves (default: dry-run report)")
    ap.add_argument("--root", type=Path, default=REPO,
                    help="repo root holding storage/spectra/ "
                         "(default: this repo)")
    ap.add_argument("--spectra-url", default=None,
                    help="the running spectra.service's own base URL "
                         "(e.g. http://127.0.0.1:8010). REQUIRED with "
                         "--apply — hue_excluded_lights can only be "
                         "cleared through the live service's own PUT "
                         "/api/house/settings, never by editing "
                         "house_modes.json directly.")
    args = ap.parse_args(argv)

    if args.apply and not args.spectra_url:
        print("FATAL: --apply requires --spectra-url — "
             "HouseSettings.hue_excluded_lights can only be corrected "
             "through the running service's own PUT /api/house/settings; "
             "editing storage/spectra/house_modes.json directly would "
             "race its reconcilers and leave the house-mode tick stale.",
             file=sys.stderr)
        return 2

    scope_path = args.root / "storage" / "spectra" / "hue_scope.json"

    # ── half (a): hue_scope.json ────────────────────────────────────────
    if scope_path.exists():
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        to_move = plan_scope(scope)
    else:
        scope, to_move = {}, {}
        print(f"no {scope_path} found — nothing to move there "
             "(run scripts/seed_hue_scope.py first if this is unexpected)")

    if to_move:
        print(f"hue_scope.json: {len(to_move)} bulb(s) to move from "
             f"\"excluded\" to \"lights\":")
        for rid, name in sorted(to_move.items(), key=lambda kv: kv[1]):
            print(f"    {name}  ({rid})")
    else:
        print("hue_scope.json: already correct — none of his four bulbs "
             "sit in \"excluded\"")

    # ── half (b): HouseSettings.hue_excluded_lights ─────────────────────
    settings_excluded: list[str] = []
    new_excluded: list[str] = []
    if args.spectra_url:
        current = get_house_settings(args.spectra_url)
        settings_excluded = list(
            (current.get("settings") or {}).get("hue_excluded_lights") or [])
        new_excluded = plan_hue_excluded_lights(settings_excluded)
        removed = [n for n in settings_excluded if n not in new_excluded]
        if removed:
            print(f"HouseSettings.hue_excluded_lights: {len(removed)} "
                 f"name(s) to clear: {removed}")
        else:
            print("HouseSettings.hue_excluded_lights: already correct — "
                 "none of his four names are listed")
    else:
        print("HouseSettings.hue_excluded_lights: --spectra-url not "
             "given — skipped (pass it to check/clear this half)")

    if not args.apply:
        print("\ndry run — nothing written (pass --apply)")
        return 0

    if to_move:
        backups = args.root / "storage" / "spectra" / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        dest = backups / f"hue_scope-{time.strftime('%Y%m%d-%H%M%S')}.json"
        dest.write_text(json.dumps(scope, indent=2), encoding="utf-8")
        print(f"\nbacked up {scope_path} -> {dest}")
        _write_scope_atomic(scope_path, apply_scope(scope, to_move))
        print(f"wrote {scope_path}: {len(to_move)} bulb(s) moved to "
             "\"lights\"")
    else:
        print("\nhue_scope.json: nothing to write")

    if new_excluded != settings_excluded:
        apply_house_settings(args.spectra_url, new_excluded)
        print(f"PUT {args.spectra_url}/api/house/settings: "
             f"hue_excluded_lights now {new_excluded}")
    else:
        print("HouseSettings.hue_excluded_lights: nothing to write")

    return 0


if __name__ == "__main__":
    sys.exit(main())
