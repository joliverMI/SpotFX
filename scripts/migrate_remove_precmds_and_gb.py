"""
One-shot migration: retire pre-commands and the global-brightness action.

Task 1 — convert every `ledfx_global_brightness` action (anywhere in an event:
         composite root tree, legacy actions/steps/lanes) into an equivalent
         `morph_step` — brightness aspect, absolute mode, empty scope = ALL
         imported virtuals. Preserves weight / labels / ramp_ms (null ramp
         still means settings.smooth_ramp_ms on the morph path).
Task 2 — strip the five legacy pre-command keys (pre_brightness_enabled/value/
         ramp_ms, pre_transition_enabled/value) from every stored event.
Task 3 — strip pre-command override label tokens (-brightness, -transition,
         =brightness:*, =transition:*, =ramp:*) from profile triggers and
         setlist_triggers.
Task 4 — drop pre_brightness_lead_ms / pre_transition_lead_ms from settings.

Dry run by default (prints a report, writes nothing). Pass --apply to write.
On --apply, events.json is backed up to storage/backups/ first, and every
transformed event is validated through models.music_event.MusicEvent before
anything is written — any validation failure aborts with no changes.

USAGE
  .venv/bin/python scripts/migrate_remove_precmds_and_gb.py           # dry run
  .venv/bin/python scripts/migrate_remove_precmds_and_gb.py --apply
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVENTS_PATH = ROOT / "storage" / "events.json"
SETTINGS_PATH = ROOT / "storage" / "settings.json"
PROFILES_DIR = ROOT / "storage" / "profiles"
BACKUP_DIR = ROOT / "storage" / "backups"

PRE_KEYS = (
    "pre_brightness_enabled", "pre_brightness_value", "pre_brightness_ramp_ms",
    "pre_transition_enabled", "pre_transition_value",
)
LEAD_KEYS = ("pre_brightness_lead_ms", "pre_transition_lead_ms")
BARE_TOKENS = {"-brightness", "-transition"}
PREFIX_TOKENS = ("=brightness:", "=transition:", "=ramp:")


def gb_to_morph_step(a: dict) -> dict:
    """Exact shape the old UI convert chip (msConvertGlobalBrightness) produced."""
    return {
        "type": "morph_step",
        "weight": a.get("weight", 1.0),
        "labels": a.get("labels", []),
        "ramp_ms": a.get("ramp_ms"),
        "intensity_source": "rms_total",
        "targets": [{
            "scope": {"virtual_ids": [], "categories": [], "roles": []},  # empty = all imported
            "aspect": "brightness",
            "mode": "absolute",
            "absolute_value": {"number": a.get("brightness", 1.0)},
            "nudge_amount": 0,
            "intensity_scale": 0,
            "intensity_source": "rms_total",
            "ramp_ms": None,
        }],
    }


def convert_tree(node, path: str, hits: list[str]):
    """Recursively replace ledfx_global_brightness dicts anywhere in the value."""
    if isinstance(node, dict):
        if node.get("type") == "ledfx_global_brightness":
            hits.append(f"{path} (brightness={node.get('brightness')}, ramp={node.get('ramp_ms')})")
            return gb_to_morph_step(node)
        return {k: convert_tree(v, f"{path}.{k}", hits) for k, v in node.items()}
    if isinstance(node, list):
        return [convert_tree(v, f"{path}[{i}]", hits) for i, v in enumerate(node)]
    return node


def strip_labels(labels: list) -> tuple[list, list]:
    kept, dropped = [], []
    for l in labels or []:
        s = str(l).strip()
        if s in BARE_TOKENS or any(s.startswith(p) for p in PREFIX_TOKENS):
            dropped.append(s)
        else:
            kept.append(l)
    return kept, dropped


def main() -> None:
    apply = "--apply" in sys.argv

    # ── Task 1 + 2: events ───────────────────────────────────────────────
    raw = json.loads(EVENTS_PATH.read_text())
    converted: list[str] = []
    stripped_events = 0
    out: dict = {}
    for eid, ev in raw.items():
        hits: list[str] = []
        ev = convert_tree(ev, ev.get("name", eid), hits)
        if hits:
            converted.extend(hits)
        before = len(ev)
        for k in PRE_KEYS:
            ev.pop(k, None)
        if len(ev) != before:
            stripped_events += 1
        out[eid] = ev

    print(f"Events: {len(out)} total")
    print(f"Task 1 — ledfx_global_brightness → morph_step: {len(converted)} action(s)")
    for h in converted:
        print(f"  • {h}")
    print(f"Task 2 — pre_* keys stripped from {stripped_events} event(s)")

    # ── Validate every transformed event through the current model ───────
    from models.music_event import MusicEvent
    errors = 0
    for eid, ev in out.items():
        try:
            MusicEvent(**ev)
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"  ✗ VALIDATION FAILED {eid} ({ev.get('name')}): {e}")
    if errors:
        print(f"\nABORT: {errors} event(s) failed validation — nothing written.")
        sys.exit(1)
    print("Validation: all events parse through MusicEvent ✓")

    # ── Task 3: profile trigger labels ────────────────────────────────────
    profile_changes: list[tuple[Path, dict, list[str]]] = []
    for pf in sorted(PROFILES_DIR.glob("*.json")):
        pdata = json.loads(pf.read_text())
        dropped_here: list[str] = []
        for key in ("triggers", "setlist_triggers"):
            container = pdata.get(key)
            if isinstance(container, dict):  # setlist_triggers: {setlist_id: [trigs]}
                groups = container.values()
            elif isinstance(container, list):
                groups = [container]
            else:
                continue
            for trigs in groups:
                for t in trigs or []:
                    kept, dropped = strip_labels(t.get("labels", []))
                    if dropped:
                        t["labels"] = kept
                        dropped_here.extend(dropped)
        if dropped_here:
            profile_changes.append((pf, pdata, dropped_here))
    print(f"Task 3 — override label tokens: {sum(len(d) for _, _, d in profile_changes)} "
          f"token(s) across {len(profile_changes)} profile(s)")
    for pf, _, dropped in profile_changes:
        print(f"  • {pf.name}: {dropped}")

    # ── Task 4: settings lead-ms keys ─────────────────────────────────────
    sdata = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
    lead_present = [k for k in LEAD_KEYS if k in sdata]
    print(f"Task 4 — settings keys to remove: {lead_present or 'none'}")

    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return

    # ── Write ─────────────────────────────────────────────────────────────
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"events-pre-gb-precmd-removal-{stamp}.json"
    shutil.copy2(EVENTS_PATH, backup)
    print(f"\nBackup: {backup}")

    EVENTS_PATH.write_text(json.dumps(out, indent=2))
    print(f"Wrote {EVENTS_PATH}")
    for pf, pdata, _ in profile_changes:
        pf.write_text(json.dumps(pdata, indent=2))
        print(f"Wrote {pf}")
    if lead_present:
        for k in lead_present:
            sdata.pop(k, None)
        SETTINGS_PATH.write_text(json.dumps(sdata, indent=2))
        print(f"Wrote {SETTINGS_PATH}")
    print("DONE")


if __name__ == "__main__":
    main()
