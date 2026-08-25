"""RECONCILE the two trigger worlds — land his editor-copy edits in the copy
SPECTRA actually fires from, once, for the whole library.

His report (2026-08-24): "I have updated several song profiles/triggers and
I want those updates reflected in Spectra. The system still fires on the old
triggers, despite me being in My Triggers Only mode." The mechanism, the four
standing decisions, and why provenance needs a sidecar ledger are all in
spectra/services/profile_trigger_sync.py's own docstring — this script is
only the batch driver around that planner, plus the safety it deserves at
this size.

  DRY RUN BY DEFAULT. --apply is a separate, deliberate act, sequenced by
  firstmate at deploy, never by this script on its own initiative.

  BACKUPS FIRST. --apply copies storage/spectra/triggers.json, the
  provenance ledger, AND the whole storage/profiles/ directory into
  storage/backups/trigger-reconcile-<stamp>/ before touching anything —
  both worlds, even though the forward pass only reads one of them.

  A BEFORE/AFTER DIFF IS THE PROOF, not the summary counts. Every changed
  song's fired-copy rows are diffed line by line; --apply additionally
  re-reads the file afterwards and asserts the REAL diff equals the PLANNED
  one. A same-shaped write once backfilled seven unwanted flare kinds into a
  scene and only the diff caught it.

  REVERSE (--reverse) is opt-in and separately gated: it patches only
  timestamp/enabled/intensity, only on triggers the ledger ties to a known
  legacy event, only in place on the raw profile dict. Everything lossy is
  named and skipped. See plan_reverse.

Usage:
  .venv/bin/python scripts/reconcile_profile_triggers.py            # dry run
  .venv/bin/python scripts/reconcile_profile_triggers.py --apply
  .venv/bin/python scripts/reconcile_profile_triggers.py --reverse  # dry run
  Point it at a snapshot instead of live storage:
    --profiles-dir <dir> --spectra-storage <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write (default: dry run, nothing is touched)")
    ap.add_argument("--reverse", action="store_true",
                    help="also plan the SPECTRA -> profile direction "
                         "(faithful fields only; see plan_reverse)")
    ap.add_argument("--profiles-dir", default=None,
                    help="legacy profile store (default: this repo's storage/profiles)")
    ap.add_argument("--spectra-storage", default=None,
                    help="SPECTRA storage dir (default: SPECTRA_STORAGE_DIR / repo)")
    ap.add_argument("--uri", default=None, help="reconcile ONE song only")
    ap.add_argument("--diff-limit", type=int, default=8,
                    help="songs whose full row diff is printed (0 = none)")
    args = ap.parse_args()

    if args.spectra_storage:
        os.environ["SPECTRA_STORAGE_DIR"] = str(Path(args.spectra_storage).resolve())

    from spectra import config as scfg
    from spectra.services import (profile_sync_ledger, profile_trigger_sync,
                                  trigger_store)

    profiles_dir = Path(args.profiles_dir) if args.profiles_dir else REPO / "storage" / "profiles"
    print(f"profiles : {profiles_dir}")
    print(f"fired    : {scfg.TRIGGERS_FILE}")
    print(f"ledger   : {scfg.PROFILE_SYNC_LEDGER_FILE}")
    print(f"mode     : {'APPLY' if args.apply else 'dry run'}"
          f"{' + reverse' if args.reverse else ''}\n")

    if not profiles_dir.is_dir():
        print(f"FAIL: no profiles directory at {profiles_dir}")
        return 2

    fired_before = trigger_store._load_raw()
    ledger = profile_sync_ledger.load()

    # ── plan every song ──────────────────────────────────────────────────────
    plans: list[profile_trigger_sync.SyncPlan] = []
    raw_profiles: dict[str, tuple[Path, dict]] = {}
    seen_uris: set[str] = set()
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  skipped unreadable profile {path.name}: {exc}")
            continue
        uri = data.get("spotify_uri") or ""
        if not uri or (args.uri and uri != args.uri):
            continue
        if uri in seen_uris:
            # Two profile files claiming one URI: profile_manager's own index
            # keeps whichever it indexed last, so this script refuses to guess
            # and reports instead of silently picking one.
            print(f"  ! duplicate spotify_uri in {path.name} — SKIPPED "
                  f"(already handled by {raw_profiles[uri][0].name})")
            continue
        seen_uris.add(uri)
        raw_profiles[uri] = (path, data)
        plans.append(profile_trigger_sync.plan_song(
            uri, data.get("triggers", []), fired_before.get(uri, []),
            profile_sync_ledger.for_song(ledger, uri)))

    changed = [p for p in plans if p.changes]
    totals = {"songs": len(plans), "songs_changed": len(changed),
              "written": sum(len(p.upserts) for p in changed),
              "deleted": sum(len(p.deletes) for p in changed),
              "unchanged": sum(p.unchanged for p in plans),
              "protected_spectra_authored": sum(len(p.protected) for p in plans),
              "generated_untouched": sum(p.generated_untouched for p in plans)}
    by_reason: dict[str, int] = {}
    skipped_rows: list[tuple[str, profile_trigger_sync.SkippedTrigger]] = []
    for p in plans:
        for s in p.skipped:
            by_reason[s.reason] = by_reason.get(s.reason, 0) + 1
            skipped_rows.append((p.uri, s))

    print("── PLAN ────────────────────────────────────────────────")
    for k, v in totals.items():
        print(f"  {k:28s} {v}")
    print(f"  {'skipped (never written)':28s} {by_reason or 0}")
    print()

    if skipped_rows:
        print("── SKIPPED, by reason (preserved in his profiles, never clamped) ──")
        for uri, s in skipped_rows[:40]:
            name = raw_profiles.get(uri, (Path(uri), None))[0].name
            print(f"  {s.reason:20s} {s.timestamp_ms:>9d}ms  {s.event_id[:36]:36s}  {name}")
        if len(skipped_rows) > 40:
            print(f"  ... {len(skipped_rows) - 40} more")
        print()

    # ── the proof: what actually moves ───────────────────────────────────────
    planned_after = json.loads(json.dumps(fired_before))
    for p in changed:
        dead = set(p.deletes)
        replacing = {t.id for t in p.upserts}
        rows = [r for r in planned_after.get(p.uri, [])
                if r.get("id") not in dead and r.get("id") not in replacing]
        rows.extend(json.loads(t.model_dump_json()) for t in p.upserts)
        if rows:
            planned_after[p.uri] = rows
        else:
            planned_after.pop(p.uri, None)

    if args.diff_limit and changed:
        print("── DIFF (fired copy, per song) ─────────────────────────")
        for p in changed[:args.diff_limit]:
            name = raw_profiles[p.uri][0].name
            print(f"\n  {name}   +{len(p.upserts)} / -{len(p.deletes)} "
                  f"({p.unchanged} unchanged, {len(p.protected)} SPECTRA-authored protected)")
            lines = profile_trigger_sync.diff_json(
                sorted(fired_before.get(p.uri, []), key=lambda r: (r.get("timestamp_ms", 0), r.get("id", ""))),
                sorted(planned_after.get(p.uri, []), key=lambda r: (r.get("timestamp_ms", 0), r.get("id", ""))))
            for line in lines[:60]:
                print("    " + line)
            if len(lines) > 60:
                print(f"    ... {len(lines) - 60} more diff lines")
        if len(changed) > args.diff_limit:
            print(f"\n  ... {len(changed) - args.diff_limit} more changed songs "
                  f"(raise --diff-limit to see them)")
        print()

    # ── reverse direction (opt-in) ───────────────────────────────────────────
    rev_plans = []
    if args.reverse:
        for uri, (path, data) in raw_profiles.items():
            rp = profile_trigger_sync.plan_reverse(
                uri, data.get("triggers", []), fired_before.get(uri, []),
                profile_sync_ledger.for_song(ledger, uri))
            if rp.edits:
                rev_plans.append((path, data, rp))
        print("── REVERSE PLAN (SPECTRA -> profile, faithful fields only) ──")
        print(f"  songs with faithful edits   {len(rev_plans)}")
        print(f"  triggers edited             {sum(len(r.edits) for _, _, r in rev_plans)}")
        for path, _d, rp in rev_plans[:10]:
            for e in rp.edits[:6]:
                print(f"    {path.name[:44]:44s} {e.trigger_id[:8]} {e.changes}")
        print()

    if not args.apply:
        print("dry run — nothing written. Re-run with --apply to land it.")
        return 0

    # ── APPLY ────────────────────────────────────────────────────────────────
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # Beside the storage actually being modified, not the repo — so a run
    # against a snapshot backs the SNAPSHOT up, never the live tree.
    backup = scfg.SPECTRA_STORAGE.parent / "backups" / f"trigger-reconcile-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    if scfg.TRIGGERS_FILE.exists():
        shutil.copy2(scfg.TRIGGERS_FILE, backup / "triggers.json")
    if scfg.PROFILE_SYNC_LEDGER_FILE.exists():
        shutil.copy2(scfg.PROFILE_SYNC_LEDGER_FILE, backup / "profile_sync_ledger.json")
    shutil.copytree(profiles_dir, backup / "profiles")
    print(f"backed up both worlds -> {backup}")

    for p in plans:
        profile_trigger_sync.apply_plan(p)

    fired_after = trigger_store._load_raw()
    real = profile_trigger_sync.diff_json(fired_before, fired_after)
    planned = profile_trigger_sync.diff_json(fired_before, planned_after)
    if real != planned:
        print("FAIL: the written file does not match the planned change.\n"
              f"      restore from {backup} and investigate before re-running.")
        return 3
    print(f"applied: {totals['written']} written, {totals['deleted']} deleted "
          f"across {totals['songs_changed']} songs — "
          f"the written diff matches the planned diff exactly")

    if args.reverse:
        for path, data, rp in rev_plans:
            touched = profile_trigger_sync.apply_reverse(rp, data)
            if touched:
                path.write_text(json.dumps(data, indent=2, ensure_ascii=True),
                                encoding="utf-8")
        print(f"reverse applied: {sum(len(r.edits) for _, _, r in rev_plans)} "
              f"triggers across {len(rev_plans)} profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
