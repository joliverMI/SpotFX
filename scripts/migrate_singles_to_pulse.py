#!/usr/bin/env python3
"""Move every scene's Singles from Power to Pulse, carrying his tuning from
the Pulse test scene (single-led-power plan, phase 4).

The Admiral, 2026-10-07, verbatim: "also the pulse effect looks good enough
to push to the rest of the scenes. note that I changed the trigger timing on
the flares make sure that that gets pushed to the other scenes also"

WHAT IS CARRIED IS READ, NEVER TYPED HERE. Everything comes from the live
tuning scene ("Pulse Test (Orbits V2)", `--source` for another) at the
moment the script runs, so a retune he makes before deploy travels too:

  * the Singles entry's params, verbatim (today `{}` — his tuning landed as
    Pulse's own schema defaults, PR 359, so the scene stores nothing)
  * every Pulse flare kind (type pulse_flash / pulse_flip) declared on it,
    verbatim — trigger_offset_ms (his trigger timing: Flash -92 ms, Colour
    Flip -355 ms when this was written; both were seeded at 0 by
    scripts/add_pulse_flares.py), min_intensity, gain, enabled — together
    with WHERE it is attached: every band of each response class it sits on,
    at its scale. A kind attached to only SOME bands of a class, at mixed
    scales, or inside a lane is refused rather than guessed.
  * any OTHER flare kind on the tuning scene whose trigger_offset_ms is not 0
    (none today): retimed by name+type on the scenes that have one, never
    declared where missing (an Orbits param patch means nothing on Fish).

WHICH SCENES. Exactly those whose Singles category entry runs "power" — and
only those. A Singles entry with intensity steps or drift is SKIPPED and
named (refusing to guess what Power's steps/drift should drive on Pulse).
Disabled scenes are included (they are still his scenes; re-enabling one
should not bring Power back). The House scenes (Singles is a `gradient`
virtual entry) and the tuning scene itself never match.

PER SCENE, ONLY THESE CHANGE:
  1. the Singles entry's effect_type power -> pulse and its params replaced
     by the tuning scene's. Its colour, brightness (STAR's ⚡ binding
     included) and background brightness are the scene's own and untouched.
  2. each Pulse flare kind NOT already present on the scene (by type) is
     declared (appended to flare_kinds) and attached to every band of the
     same response class(es) as on the tuning scene, at the same scale,
     directly (no lane), so it fires alongside the band's own kinds.
  3. a Pulse kind (or retimed other kind) ALREADY on the scene keeps its
     attachments; its trigger_offset_ms is moved to his value only if it
     still holds the seed default 0. ANY OTHER VALUE IS HIS OWN PER-SCENE
     TIMING: it is kept and reported, never overwritten.

RAW-DICT EDIT, never scene_store.save() (AGENTS.md: a SceneV2 round-trip
re-serialises every field and runs the legacy flare migration shim). SceneV2
is used only to READ: every scene must parse before and after. Proof before
any write: applying this run's own --revert to the result must give back
the original store EXACTLY (every scene, every field), so nothing outside
the manifest can have changed. After the write the file is re-read and
compared again.

UNDO, two ways:
  * restore the backup this run writes:
    storage/spectra/backups/scenes-pre-pulse-p4-<stamp>.json
  * `--revert` (dry run unless --apply): reads the manifest written beside
    that backup (pulse-p4-<stamp>.manifest.json; the newest one by default,
    `--manifest PATH` for another) and puts Power + each scene's old params
    back, removes the kinds this run declared, detaches them, and restores
    retimed offsets. Each item is reverted only while it still holds exactly
    what this run wrote; anything he has changed since is LEFT ALONE and
    named. A kind he has edited since keeps its band attachments too, and a
    scene whose Singles entry he has retuned since is left whole (its Pulse
    flares act only on Pulse).

Idempotent: after --apply no scene's Singles runs Power, so a second run
finds nothing to do. Dry run by default; --apply backs up first and writes
atomically (tmp + replace, indent=2 — the store's own format). Never run by
the build: a deploy step, after which SPECTRA re-reads scenes on its own.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402

DEFAULT_SOURCE = "Pulse Test (Orbits V2)"
SINGLES = "Singles"
OLD_EFFECT = "power"
NEW_EFFECT = "pulse"
PULSE_KIND_TYPES = ("pulse_flash", "pulse_flip")
SEED_OFFSET_MS = 0          # what add_pulse_flares.py and the model default write
BACKUP_TAG = "pre-pulse-p4"
MANIFEST_PREFIX = "pulse-p4-"
MANIFEST_SUFFIX = ".manifest.json"


# ── reading his tuning ─────────────────────────────────────────────────────

@dataclass
class CarriedKind:
    spec: dict                      # the tuning scene's own declaration
    attach: dict[str, float]        # response class -> scale on every band


@dataclass
class Tuning:
    source_id: str
    source_name: str
    singles_params: dict
    declare: list[CarriedKind]
    retime: list[dict]              # other kinds with a nonzero offset


def _offset(kind: dict) -> int:
    return int(kind.get("trigger_offset_ms") or 0)


def _find_one(store: dict, name: str) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene {name!r} not found — refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"scene {name!r} matches {len(matches)} scenes — "
                         "refusing to guess which one")
    return matches[0]


def singles_entries(raw: dict) -> list[dict]:
    return [d for d in raw.get("devices") or []
            if d.get("target") == SINGLES
            and d.get("target_kind", "category") == "category"]


def _attachment_plan(raw: dict, name: str) -> dict[str, float]:
    """Where the tuning scene attaches `name`: {class: scale}. Refuses any
    shape this script would have to guess how to copy onto other bands."""
    plan: dict[str, float] = {}
    for cls, resp in (raw.get("responses") or {}).items():
        bands = resp.get("bands") or []
        holding = [b for b in bands if name in (b.get("kinds") or {})]
        if not holding:
            continue
        if len(holding) != len(bands):
            raise SystemExit(
                f"{name!r} is attached to {len(holding)} of {len(bands)} "
                f"{cls!r} bands on the tuning scene — refusing to guess "
                "which bands of other scenes should carry it")
        scales = {b["kinds"][name] for b in holding}
        if len(scales) != 1:
            raise SystemExit(f"{name!r} is attached at mixed scales "
                             f"{sorted(scales)} — refusing to guess")
        if any(name in (b.get("kind_lanes") or {}) for b in holding):
            raise SystemExit(f"{name!r} sits in a lane on the tuning scene — "
                             "refusing to guess which lane it joins elsewhere")
        plan[cls] = scales.pop()
    return plan


def extract_tuning(store: dict, source: str = DEFAULT_SOURCE) -> Tuning:
    sid = _find_one(store, source)
    raw = store[sid]
    SceneV2(**raw)                 # must parse under the current code
    entries = singles_entries(raw)
    if len(entries) != 1 or entries[0].get("effect_type") != NEW_EFFECT:
        raise SystemExit(f"{source!r} has no single Singles entry running "
                         f"{NEW_EFFECT!r} — it is not the tuning scene")
    if entries[0].get("effect_steps") or entries[0].get("drift"):
        raise SystemExit(f"{source!r}'s Singles entry has intensity steps or "
                         "drift — refusing to guess how to carry them")
    declare, retime = [], []
    for kind in raw.get("flare_kinds") or []:
        if kind.get("type") in PULSE_KIND_TYPES:
            declare.append(CarriedKind(copy.deepcopy(kind),
                                       _attachment_plan(raw, kind["name"])))
        elif _offset(kind) != SEED_OFFSET_MS:
            retime.append({"name": kind["name"], "type": kind.get("type"),
                           "to": _offset(kind)})
    if not declare:
        raise SystemExit(f"{source!r} declares no Pulse flare kinds — "
                         "nothing of his flare tuning to carry")
    return Tuning(sid, source, copy.deepcopy(entries[0].get("params") or {}),
                  declare, retime)


# ── one scene, forward ─────────────────────────────────────────────────────

@dataclass
class ScenePlan:
    scene_id: str
    name: str
    disabled: bool
    singles: dict | None = None     # {entry_id, before, after}
    declared: list[dict] = field(default_factory=list)
    attached: list[list] = field(default_factory=list)   # [cls, idx, name, scale]
    retimed: list[dict] = field(default_factory=list)    # {name, type, from, to}
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def manifest(self) -> dict:
        return {"scene_id": self.scene_id, "name": self.name,
                "singles": self.singles, "declared": self.declared,
                "attached": self.attached, "retimed": self.retimed}


def _retime(raw: dict, kind: dict, to: int, plan: ScenePlan) -> None:
    have = _offset(kind)
    if have == to:
        return
    if have != SEED_OFFSET_MS:
        plan.notes.append(f"{kind['name']!r} kept at its own {have} ms "
                          f"(his timing on this scene; tuning scene has {to})")
        return
    kind["trigger_offset_ms"] = to
    plan.retimed.append({"name": kind["name"], "type": kind.get("type"),
                         "from": have, "to": to})


def migrate_scene(sid: str, raw: dict, tuning: Tuning) -> ScenePlan | None:
    """Mutate `raw` in place. None = not a Power scene (left untouched)."""
    if sid == tuning.source_id:
        return None
    power = [d for d in singles_entries(raw)
             if d.get("effect_type") == OLD_EFFECT]
    if not power:
        return None
    plan = ScenePlan(sid, raw.get("name", sid), bool(raw.get("disabled")))
    if len(singles_entries(raw)) != 1:
        plan.skipped = (f"{len(singles_entries(raw))} Singles entries — "
                        "refusing to guess which one to switch")
        return plan
    dev = power[0]
    if dev.get("effect_steps") or dev.get("drift"):
        plan.skipped = ("Singles entry has intensity steps or drift on "
                        "Power's params — refusing to guess what they drive "
                        "on Pulse")
        return plan
    kinds = raw.get("flare_kinds")
    if kinds is None:
        kinds = raw["flare_kinds"] = []
    by_name = {k.get("name"): k for k in kinds}
    for carried in tuning.declare:
        name, ktype = carried.spec["name"], carried.spec["type"]
        clash = by_name.get(name)
        if clash is not None and clash.get("type") != ktype:
            plan.skipped = (f"a flare kind named {name!r} already exists as "
                            f"type {clash.get('type')!r} — refusing to "
                            "overwrite it")
            return plan

    before = {"effect_type": dev.get("effect_type"),
              "params": copy.deepcopy(dev.get("params"))}
    dev["effect_type"] = NEW_EFFECT
    dev["params"] = copy.deepcopy(tuning.singles_params)
    plan.singles = {"entry_id": dev.get("id"), "before": before,
                    "after": {"effect_type": NEW_EFFECT,
                              "params": copy.deepcopy(tuning.singles_params)}}

    for carried in tuning.declare:
        name, ktype = carried.spec["name"], carried.spec["type"]
        existing = [k for k in kinds if k.get("type") == ktype]
        if existing:
            for k in existing:
                _retime(raw, k, _offset(carried.spec), plan)
            continue
        kinds.append(copy.deepcopy(carried.spec))
        plan.declared.append(copy.deepcopy(carried.spec))
        responses = raw.get("responses") or {}
        for cls, scale in carried.attach.items():
            bands = (responses.get(cls) or {}).get("bands") or []
            if not bands:
                plan.notes.append(f"{name!r} declared but this scene has no "
                                  f"{cls!r} bands to attach it to")
            for i, band in enumerate(bands):
                band_kinds = band.get("kinds")
                if band_kinds is None:
                    band_kinds = band["kinds"] = {}
                if name in band_kinds:
                    continue
                band_kinds[name] = scale
                plan.attached.append([cls, i, name, scale])

    for want in tuning.retime:
        matches = [k for k in kinds if k.get("name") == want["name"]
                   and k.get("type") == want["type"]]
        if not matches:
            plan.notes.append(f"{want['name']!r} ({want['type']}) has no "
                              f"match here — his {want['to']} ms not applied")
        for k in matches:
            _retime(raw, k, want["to"], plan)
    return plan


def migrate(store: dict, tuning: Tuning) -> list[ScenePlan]:
    """Mutate `store` in place; one plan per Power scene, store order."""
    plans = []
    for sid, raw in store.items():
        work = copy.deepcopy(raw)
        plan = migrate_scene(sid, work, tuning)
        if plan is None:
            continue
        if plan.skipped is None:
            store[sid] = work
        plans.append(plan)
    return plans


# ── revert ─────────────────────────────────────────────────────────────────

def revert(store: dict, manifest: dict) -> list[str]:
    """Mutate `store` in place, undoing `manifest`; returns one line per
    item LEFT ALONE because it no longer holds what the forward run wrote."""
    kept: list[str] = []
    for entry in manifest.get("scenes", []):
        sid, name = entry["scene_id"], entry["name"]
        raw = store.get(sid)
        if raw is None:
            kept.append(f"{name}: scene no longer exists — nothing to revert")
            continue
        singles = entry.get("singles")
        if singles:
            dev = next((d for d in raw.get("devices") or []
                        if d.get("id") == singles["entry_id"]), None)
            now = None if dev is None else {
                "effect_type": dev.get("effect_type"),
                "params": dev.get("params")}
            if now != singles["after"]:
                # He has worked on this scene's Pulse since: the Pulse flares
                # act only on Pulse, so the whole scene stays as it is.
                kept.append(f"{name}: Singles entry changed since — the "
                            "whole scene left as it is")
                continue
            dev["effect_type"] = singles["before"]["effect_type"]
            dev["params"] = copy.deepcopy(singles["before"]["params"])
        kinds = raw.get("flare_kinds") or []
        removing: set[str] = set()
        for spec in entry.get("declared", []):
            have = [k for k in kinds if k.get("name") == spec["name"]]
            if have == [spec]:
                removing.add(spec["name"])
            elif have:
                kept.append(f"{name}: {spec['name']!r} edited since — kept, "
                            "with its band attachments")
        raw["flare_kinds"] = [k for k in kinds
                              if k.get("name") not in removing]
        responses = raw.get("responses") or {}
        for cls, idx, kname, scale in entry.get("attached", []):
            if kname not in removing:
                continue
            bands = (responses.get(cls) or {}).get("bands") or []
            band_kinds = bands[idx].get("kinds") if idx < len(bands) else None
            if band_kinds is not None and band_kinds.get(kname) == scale:
                del band_kinds[kname]
            else:
                kept.append(f"{name}: {cls} band {idx} no longer holds "
                            f"{kname!r} at x{scale} — left as it is")
        for r in entry.get("retimed", []):
            matches = [k for k in raw.get("flare_kinds") or []
                       if k.get("name") == r["name"]
                       and k.get("type") == r["type"]]
            if matches and all(_offset(k) == r["to"] for k in matches):
                for k in matches:
                    k["trigger_offset_ms"] = r["from"]
            else:
                kept.append(f"{name}: {r['name']!r} timing changed since — "
                            "left as it is")
    return kept


# ── checks, report, I/O ────────────────────────────────────────────────────

def verify(before: dict, after: dict, manifest: dict) -> None:
    """The forward run's whole effect must be exactly what its manifest
    says: reverting a copy must reproduce `before` byte for byte."""
    for sid, raw in after.items():
        SceneV2(**raw)
    if set(before) != set(after):
        raise SystemExit("UNEXPECTED: the scene id set changed")
    probe = copy.deepcopy(after)
    kept = revert(probe, manifest)
    if kept:
        raise SystemExit(f"UNEXPECTED: own revert left items alone: {kept}")
    for sid in before:
        if json.dumps(before[sid], sort_keys=True) != \
                json.dumps(probe[sid], sort_keys=True):
            raise SystemExit(f"UNEXPECTED: scene {before[sid].get('name')!r} "
                             "differs beyond what the manifest records")


def _fmt_ms(ms: int) -> str:
    return f"{ms:+d} ms" if ms else "0 ms"


def _fmt_params(params: dict | None) -> str:
    """Param names, ⚡ marking a bound value; `{}` = the effect's defaults."""
    if not params:
        return "{}"
    return "{" + ", ".join(k + ("⚡" if isinstance(v, dict) and "bind" in v
                                 else "") for k, v in params.items()) + "}"


def table(plans: list[ScenePlan]) -> str:
    rows = ["| Scene | Singles | Flares added (trigger timing) | "
            "Flares retimed (old → new) | Notes |",
            "|---|---|---|---|---|"]
    for p in plans:
        scene = p.name + (" *(disabled)*" if p.disabled else "")
        if p.skipped:
            rows.append(f"| {scene} | power (unchanged) | — | — | "
                        f"SKIPPED: {p.skipped} |")
            continue
        old = p.singles["before"]
        added = "<br>".join(
            f"{k['name']} ({_fmt_ms(_offset(k))}"
            + (f", above {k['min_intensity']}" if k.get("min_intensity")
               is not None else "") + ")" for k in p.declared) or "—"
        retimed = "<br>".join(f"{r['name']}: {_fmt_ms(r['from'])} → "
                              f"{_fmt_ms(r['to'])}" for r in p.retimed) or "—"
        notes = "<br>".join(p.notes) or ""
        rows.append(f"| {scene} | {old['effect_type']} → {NEW_EFFECT}<br>"
                    f"params {_fmt_params(old['params'])} → "
                    f"{_fmt_params(p.singles['after']['params'])} | "
                    f"{added} | {retimed} | {notes} |")
    return "\n".join(rows)


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _stamp(backup_dir: Path) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base, n = stamp, 1
    while (backup_dir / f"scenes-{BACKUP_TAG}-{stamp}.json").exists() or \
            (backup_dir / f"{MANIFEST_PREFIX}{stamp}{MANIFEST_SUFFIX}").exists():
        n += 1
        stamp = f"{base}-{n}"
    return stamp


def _write_and_check(path: Path, store: dict) -> None:
    _atomic_write(path, store)
    if json.loads(path.read_text(encoding="utf-8")) != store:
        raise SystemExit(f"POST-WRITE CHECK FAILED: {path} does not hold what "
                         "was written — restore from the backup")


def latest_manifest(backup_dir: Path) -> Path:
    found = sorted(backup_dir.glob(f"{MANIFEST_PREFIX}*{MANIFEST_SUFFIX}"),
                   key=lambda p: p.stat().st_mtime)
    if not found:
        raise SystemExit(f"no {MANIFEST_PREFIX}*{MANIFEST_SUFFIX} in "
                         f"{backup_dir} — nothing to revert")
    return found[-1]


def run_forward(scenes_file: Path, source: str, *, apply: bool,
                out=print) -> dict:
    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)
    for raw in store.values():
        SceneV2(**raw)
    tuning = extract_tuning(store, source)
    out(f"his tuning, read from {tuning.source_name!r}:")
    out(f"  Singles params: {json.dumps(tuning.singles_params)}"
        + ("  (Pulse's own defaults)" if not tuning.singles_params else ""))
    for c in tuning.declare:
        attach = ", ".join(f"every {cls} band x{s}" for cls, s in
                           c.attach.items()) or "not attached"
        out(f"  {c.spec['name']} [{c.spec['type']}]: trigger "
            f"{_fmt_ms(_offset(c.spec))}, min_intensity "
            f"{c.spec.get('min_intensity')}, {attach}")
    for r in tuning.retime:
        out(f"  {r['name']} [{r['type']}]: trigger {_fmt_ms(r['to'])}")
    plans = migrate(store, tuning)
    applied = [p for p in plans if p.skipped is None]
    manifest = {"source": tuning.source_name,
                "scenes": [p.manifest() for p in applied]}
    out("")
    if not plans:
        out("no scene's Singles runs Power — nothing to do")
        return {"applied": False, "plans": plans, "manifest": manifest}
    out(table(plans))
    verify(before, store, manifest)
    out(f"\nverified: reverting this plan reproduces all {len(before)} "
        "scenes exactly")
    if not apply:
        out(f"\nDRY RUN — would switch {len(applied)} scene(s). "
            "Use --apply to write.")
        return {"applied": False, "plans": plans, "manifest": manifest}
    if not applied:
        out("\nnothing to write")
        return {"applied": False, "plans": plans, "manifest": manifest}
    backup_dir = scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(backup_dir)
    backup = backup_dir / f"scenes-{BACKUP_TAG}-{stamp}.json"
    shutil.copy2(scenes_file, backup)
    if json.loads(backup.read_text(encoding="utf-8")) != before:
        raise SystemExit("backup does not match the store read — aborting, "
                         "nothing written")
    manifest["backup"] = str(backup)
    mpath = backup_dir / f"{MANIFEST_PREFIX}{stamp}{MANIFEST_SUFFIX}"
    _atomic_write(mpath, manifest)
    out(f"backed up {scenes_file} -> {backup}")
    out(f"manifest (for --revert) -> {mpath}")
    _write_and_check(scenes_file, store)
    out(f"written and verified: {len(applied)} scene(s) switched to Pulse")
    return {"applied": True, "plans": plans, "manifest": manifest,
            "backup": backup, "manifest_path": mpath}


def run_revert(scenes_file: Path, manifest_path: Path | None, *, apply: bool,
               out=print) -> dict:
    backup_dir = scenes_file.parent / "backups"
    mpath = manifest_path or latest_manifest(backup_dir)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    kept = revert(store, manifest)
    for raw in store.values():
        SceneV2(**raw)
    out(f"revert from {mpath}:")
    for entry in manifest.get("scenes", []):
        out(f"  {entry['name']}: Singles {NEW_EFFECT} → "
            f"{entry['singles']['before']['effect_type']}; removing "
            f"{[k['name'] for k in entry['declared']] or 'no kinds'}; "
            f"{len(entry['retimed'])} retime(s) undone")
    for line in kept:
        out(f"  LEFT ALONE — {line}")
    if not apply:
        out("\nDRY RUN — use --apply to write.")
        return {"applied": False, "kept": kept}
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(backup_dir)
    backup = backup_dir / f"scenes-{BACKUP_TAG}-revert-{stamp}.json"
    shutil.copy2(scenes_file, backup)
    out(f"backed up {scenes_file} -> {backup}")
    _write_and_check(scenes_file, store)
    out("reverted and verified")
    return {"applied": True, "kept": kept, "backup": backup}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the store (default: dry-run print)")
    ap.add_argument("--revert", action="store_true",
                    help="undo a previous --apply from its manifest")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="manifest to revert (default: the newest one)")
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help=f"the tuning scene (default {DEFAULT_SOURCE!r})")
    ap.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    args = ap.parse_args(argv)
    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to do")
    if args.revert:
        run_revert(args.scenes_file, args.manifest, apply=args.apply)
    else:
        run_forward(args.scenes_file, args.source, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
