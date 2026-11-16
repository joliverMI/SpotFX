#!/usr/bin/env python3
"""Declare a "Word Shape" flare kind on the six shape scenes and give each a
full-range Words band holding it (Word Shapes plan W2.5, 2026-11-15).

THE BAND IS THE SWITCH. The Admiral's Q6 A, verbatim: a shape is "on for
every song once a scene's Words band has a Word Shape kind attached (the
build attaches one to all six scenes)". A scene with no `responses["word"]`
section is `no_class` and writes nothing (.claude/skills/word-shapes/
SKILL.md, "THE BAND IS THE SWITCH"), so THIS SCRIPT is what turns Word
Shapes on in his room — nothing else in the whole feature does. The six
scenes are the plan's six, BY NAME:

    Black Hole V2, STAR, Orbits V2, Fish, Sauron, Fireworks V2

Ids are resolved by name; an ambiguous name is refused rather than guessed,
and a MISSING scene is reported and skipped, never invented — Sauron's seed
(scripts/seed_sauron_scene.py) is still gated on his own live tuning
session, so on a store where it has not run yet five scenes are patched and
Sauron is named as absent.

WHAT IT WRITES, per scene, and nothing else:

  * `flare_kinds` gains ONE entry — `{"name": "Word Shape", "type":
    "word_shape", ...}`. The type carries no jump/params/gain/hold_ms of its
    own (models/scene.py FlareKind._shape refuses them): the five timings
    are ROOM settings (word_shape_form_slow_s / _form_fast_s / _hold_min_s /
    _hold_max_s / _release_ratio, Sonic-tellable), Energy-paced per word,
    and the shape itself is the sung label's. Offset 0, no minimum
    intensity, enabled.
  * `responses["word"]` is CREATED as one full-range band
    ([0.0, 1.0)) attaching that kind at x1.0, in its own implicit lane
    (`kind_lanes` empty), with every other ResponseSpec/FlareBand field at
    the model's default. Full range because his answer is "every song" —
    `scene_response.words_band_draws` asks, at PLAN time, whether the
    showing scene's Words section has a band covering this Energy with an
    enabled `word_shape` kind, and a word it cannot draw is planned as the
    ordinary colour word it is. A band that stopped short of 1.0 would
    silently return the loudest words to colour.

NO COLOUR KIND IS POOLED BESIDE IT. His Q5 A allows one (a Words band is an
ordinary ResponseSpec, so a colour kind beside the shape fires exactly as
it would anywhere), but he did not ask for one and it is his to add from
the Scenes page. This script writes the shape and only the shape.

UNDO (plan §7), all three paths intact after this runs:
  * the kind's POWER BUTTON switches it off on that scene (`enabled` false)
    — `words_band_draws` then says no and the word is a colour word again;
  * DETACHING it from the Words band does the same;
  * `--revert` removes the kind and the Words section from all six —
    and, on a legacy scene, the now-empty `flare_kinds` key as well, so the
    legacy flag goes back the way it came. The one thing it does NOT take
    back is the explicit `reroll_dice: true` above: removing a flag this
    script cannot prove it wrote would be its own silent edit, and leaving
    it is LOAD-NEUTRAL (under the restored legacy flag a missing flag means
    True anyway). So a revert restores the LOADED scene exactly and the raw
    bytes nearly; THE BACKUP IS THE BYTE-EXACT RESTORE.
Because each of the first two leaves data this script did not write, a
re-run after either one REFUSES rather than quietly undoing his undo: a
`Word Shape` kind that already exists is left exactly as authored (a
switched-off one is never re-enabled), and a Words section that differs
from what this script writes aborts with the difference named. That is the
AGENTS.md rule — his data is not yours to silently change — applied to the
one script that could.

HIS STORED SCENES ARE IN THE LEGACY FORMAT, and that makes a THIRD,
LOAD-PRESERVING write necessary (found by the W2.5 review, 2026-11-16,
running this script end to end on a scratch copy of a real-shaped store).
A legacy scene has NO `flare_kinds` key at all — its kinds are auto-named
on load (models/scene.py `_migrate_flare_kinds`) — and the ABSENCE OF THAT
KEY IS THE LEGACY FLAG: with it absent, a response class carrying no
explicit `reroll_dice` loads with the historical default TRUE and gains a
"Dice Re-roll" drift-jump kind on every band; with it present, the same
class loads FALSE and that kind silently DETACHES. Declaring the Word Shape
kind introduces `flare_kinds`, so on his real store it would flip exactly
that flag. Therefore, before introducing the key on a scene that lacks it,
this script writes the explicit legacy default (`reroll_dice: true`) into
every response spec that has none — the loaded scene is then byte-for-byte
what it was. The guard against the next version of this mistake is in
`verify_diff`: it compares the LOADED models (`SceneV2(**raw).model_dump()`,
the Word Shape kind and the Words section stripped) as well as the raw
dicts, so a change in load semantics can no longer be invisible to it.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() (the
add_pulse_flares.py / add_fireworks_burst_flare.py rule: a model round-trip
re-serializes EVERY field in current canonical form, and the legacy
flare-band migration shim has previously rewritten unrelated scene data as
a side effect of such a round-trip). This script loads the RAW JSON, uses
SceneV2 only to READ (validation + diagnostics), and mutates exactly
`flare_kinds` (+1) and `responses.word` (new) on each named scene. After
--apply it RE-READS the written file and structurally verifies the diff
against the backup — raw AND loaded — failing loudly on any difference
beyond those two keys and the legacy default above.
It also compares scene_store.scene_warnings before and after: a warning
this change introduced is a bug, not a notice.

DEPLOY ORDER — and WHO RUNS THIS. Run it only AFTER the W1 code is
deployed and `spectra.service` restarted: an older process cannot load a
`word` response class (models/scene.py's RESPONSE_CLASSES) and fails model
validation on load. And it is DJ who runs it, at W3, not any build: the
tuning gate (docs/ADDING_EFFECTS.md) puts the Admiral's eye before a shape
is live in a song, and his first look is the Words preview (W2.1) — which
needs the kind DECLARED to show anything, and this script is what declares
it. Dry-run by default; --apply backs the store up to
storage/spectra/backups/scenes-word-shapes-<stamp>.json first (atomic
tmp+replace, indent=2, scene_store's own on-disk format) — never over an
existing backup file: a run that would reuse a taken name takes the next
free one, so the backup of the ORIGINAL store can never be clobbered by a
backup of a patched one. A run with nothing to do writes nothing and backs
nothing up. Not run against
live storage by this build — tested against a fixture store only.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402
from spectra.services.scene_store import scene_warnings  # noqa: E402

# The plan's six, in the plan's order.
SCENE_NAMES = ["Black Hole V2", "STAR", "Orbits V2", "Fish", "Sauron",
               "Fireworks V2"]
KIND_NAME = "Word Shape"
# The kind and the section are written as LITERALS, in exactly the shape the
# models serialize — tests/test_add_word_shapes.py pins both against
# FlareKind/ResponseSpec.model_dump(mode="json"), so a model field added
# later fails that test here rather than writing a half-canonical scene into
# his store.
KIND = {"name": KIND_NAME, "type": "word_shape", "jump": None, "params": {},
        "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0,
        "min_intensity": None, "enabled": True}
WORD_SECTION = {
    "bands": [{"intensity_min": 0.0, "intensity_max": 1.0,
               "curve": "linear", "gain": 1.0, "param_patch": {},
               "kinds": {KIND_NAME: 1.0}, "kind_lanes": {}}],
    "reroll_dice": False,
    "color_set_jump": False,
}


def find_scene_id(store: dict, name: str) -> str | None:
    """The one scene called `name`, or None when there is none (reported and
    skipped by the caller). An ambiguous name is refused, never guessed."""
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        return None
    if len(matches) > 1:
        raise SystemExit(f"scene {name!r} matches {len(matches)} scenes — "
                         "refusing to guess which one")
    return matches[0]


def _declared(raw: dict) -> list[dict]:
    return [k for k in (raw.get("flare_kinds") or [])
            if k.get("name") == KIND_NAME]


def _legacy_defaults(raw: dict) -> list[str]:
    """Write the explicit legacy `reroll_dice` default into every response
    spec that has none, and say which — called ONLY on a scene that has no
    `flare_kinds` key yet, i.e. immediately before this script introduces
    one. See the module docstring: the key's absence IS the legacy flag, and
    introducing it would otherwise detach a "Dice Re-roll" kind from every
    band of any class that left the flag implicit."""
    out: list[str] = []
    for cls, spec in (raw.get("responses") or {}).items():
        if isinstance(spec, dict) and "reroll_dice" not in spec:
            spec["reroll_dice"] = True
            out.append(cls)
    return out


def patch(raw: dict, label: str, *, revert: bool = False
          ) -> tuple[list[str], bool]:
    """Mutate `raw` (one scene) in place, forward or revert. Returns the
    lines to print and whether anything was actually WRITTEN — a scene that
    is already as this script wants it returns lines (saying so) and False,
    so a no-op run neither writes the store nor takes a backup."""
    legacy = "flare_kinds" not in raw
    kinds = raw.setdefault("flare_kinds", [])
    responses = raw.setdefault("responses", {})
    have = _declared(raw)
    word = responses.get("word")
    lines: list[str] = []
    wrote = False

    if revert:
        # Check EVERYTHING before mutating anything: a refusal must leave the
        # scene exactly as it was.
        if have and have != [KIND]:
            raise SystemExit(
                f"{label}: {KIND_NAME!r} no longer matches what this script "
                f"wrote ({have}) — refusing to remove it; switch it off with "
                f"its power button instead, or detach it from the Words band")
        if word is not None and word != WORD_SECTION:
            raise SystemExit(
                f"{label}: the Words section differs from what this script "
                f"wrote — refusing to remove it.\n"
                f"  stored:  {json.dumps(word, sort_keys=True)}\n"
                f"  written: {json.dumps(WORD_SECTION, sort_keys=True)}")
        if word is not None:
            del responses["word"]
            if not responses:
                del raw["responses"]
            lines.append("Words section removed")
            wrote = True
        if have:
            kinds[:] = [k for k in kinds if k.get("name") != KIND_NAME]
            lines.append(f"{KIND_NAME!r}: declaration removed")
            wrote = True
        # The mirror of the responses handling above, and the legacy flag's
        # own inverse: a `flare_kinds` key left behind EMPTY would keep the
        # scene in the canonical format this script put it in, so the key
        # goes too — but ONLY where that is load-neutral, which is exactly
        # when no response spec is relying on the implicit default (every
        # one of them carries an explicit reroll_dice, as the forward
        # direction made sure of). Where one still relies on it, the key
        # stays rather than silently flipping a class's Dice Re-roll back
        # on; verify_diff's loaded-model comparison is the backstop either
        # way.
        implicit = [cls for cls, spec in (raw.get("responses") or {}).items()
                    if isinstance(spec, dict) and "reroll_dice" not in spec]
        if not kinds and not implicit:
            del raw["flare_kinds"]
            if wrote:
                lines.append("empty 'flare_kinds' key dropped — back to the "
                             "legacy format it was stored in")
        elif not kinds and wrote:
            lines.append(f"empty 'flare_kinds' key KEPT: responses."
                         f"{implicit[0]} has no explicit 'reroll_dice', so "
                         f"dropping the key would turn its Dice Re-roll back "
                         f"on — restore from the backup for a byte-exact "
                         f"revert")
        return lines, wrote

    if have and have[0].get("type") != "word_shape":
        raise SystemExit(
            f"{label}: {KIND_NAME!r} already exists as type "
            f"{have[0].get('type')!r} — refusing to overwrite it")
    if word is not None and word != WORD_SECTION:
        raise SystemExit(
            f"{label}: it already has a Words section, and it is not the one "
            f"this script writes — refusing to overwrite it (his own edit, or "
            f"an undo: detaching the kind from the band is one of plan §7's "
            f"three undo paths).\n"
            f"  stored:  {json.dumps(word, sort_keys=True)}\n"
            f"  written: {json.dumps(WORD_SECTION, sort_keys=True)}")

    if not have:
        if legacy:
            for cls in _legacy_defaults(raw):
                lines.append(f"responses.{cls}: 'reroll_dice: true' written "
                             f"explicitly — the legacy default this scene "
                             f"was relying on, which declaring a flare kind "
                             f"would otherwise turn off")
                wrote = True
        kinds.append(copy.deepcopy(KIND))
        lines.append(f"{KIND_NAME!r}: declared (type=word_shape, offset 0, no "
                     "minimum intensity, enabled)")
        wrote = True
    else:
        enabled = have[0].get("enabled", True)
        lines.append(f"{KIND_NAME!r}: already declared, left exactly as "
                     f"authored (enabled={enabled})")
    if word is None:
        responses["word"] = copy.deepcopy(WORD_SECTION)
        lines.append(f"Words section created: one band [0.0-1.0) attaching "
                     f"{KIND_NAME!r} at x1.0, its own lane")
        wrote = True
    return lines, wrote


def _strip_ours(raw_scene: dict) -> dict:
    """A copy of one scene with this script's own two keys taken out, so the
    rest can be compared for equality. An empty `flare_kinds` list and an
    empty `responses` map are dropped, so the legacy and canonical spellings
    of "nothing here" compare equal."""
    side = copy.deepcopy(raw_scene)
    side["flare_kinds"] = [k for k in side.get("flare_kinds", [])
                           if k.get("name") != KIND_NAME]
    if not side["flare_kinds"]:
        del side["flare_kinds"]
    responses = side.get("responses")
    if isinstance(responses, dict):
        responses.pop("word", None)
        if not responses:
            del side["responses"]
    return side


def _normalize(before_scene: dict, after_scene: dict) -> tuple[dict, dict]:
    """The pair of `before`/`after` copies that must be EQUAL: this script's
    own two keys removed from both, plus the one load-preserving write it
    makes on a legacy scene (an explicit `reroll_dice: true` where that spec
    had no flag at all — see the module docstring) removed from the after
    side, since it is a write whose whole purpose is to leave the LOADED
    scene unchanged."""
    b, a = _strip_ours(before_scene), _strip_ours(after_scene)
    for cls, spec in ((a.get("responses") or {})).items():
        was = (b.get("responses") or {}).get(cls)
        if (isinstance(was, dict) and "reroll_dice" not in was
                and isinstance(spec, dict)
                and spec.get("reroll_dice") is True):
            del spec["reroll_dice"]
    return b, a


def _loaded(raw_scene: dict) -> dict:
    """The scene AS THE ENGINE SEES IT — every migration applied — with this
    script's own kind and section taken out again. The raw comparison above
    cannot see a change in LOAD SEMANTICS (the W2.5 review's finding: merely
    introducing a `flare_kinds` key detaches a legacy class's Dice Re-roll),
    so this is compared too."""
    dumped = SceneV2(**copy.deepcopy(raw_scene)).model_dump(mode="json")
    dumped["flare_kinds"] = [k for k in dumped.get("flare_kinds") or []
                             if k.get("name") != KIND_NAME]
    (dumped.get("responses") or {}).pop("word", None)
    # The two ids SceneV2 INVENTS when the stored dict omits one (a fresh
    # uuid4 per load, scene and device alike) would make this comparison
    # non-deterministic rather than meaningful — drop exactly those.
    if "id" not in raw_scene:
        dumped.pop("id", None)
    for stored, loaded in zip(raw_scene.get("devices") or [],
                              dumped.get("devices") or []):
        if isinstance(stored, dict) and "id" not in stored:
            loaded.pop("id", None)
    return dumped


def verify_diff(before: dict, after: dict, sids: list[str]) -> None:
    """Every difference between `before` and `after` must be this script's
    own change on one of `sids` — in the RAW dicts and in the LOADED models
    alike; raises SystemExit otherwise."""
    if set(before) != set(after):
        raise SystemExit("UNEXPECTED: the scene id set changed")
    for sid in before:
        name = before[sid].get("name")
        if sid not in sids:
            if before[sid] != after[sid]:
                raise SystemExit(f"UNEXPECTED: scene {name!r} ({sid}) changed")
            continue
        b, a = _normalize(before[sid], after[sid])
        if b != a:
            raise SystemExit(
                f"UNEXPECTED: {name!r} ({sid}) differs beyond the "
                f"{KIND_NAME!r} declaration and its Words section")
        if _loaded(before[sid]) != _loaded(after[sid]):
            raise SystemExit(
                f"UNEXPECTED: {name!r} ({sid}) LOADS differently beyond the "
                f"{KIND_NAME!r} declaration and its Words section — the raw "
                f"keys are as intended but a migration now reads them "
                f"differently (see this script's docstring on the legacy "
                f"`flare_kinds` flag)")


def new_warnings(before: dict, after: dict, sid: str) -> list[str]:
    """Warnings scene_store.scene_warnings reports on the patched scene that
    it did not report on the original (a warning this change introduced is a
    bug, not a notice)."""
    was = set(scene_warnings(SceneV2(**before[sid]))) if sid in before else set()
    now = scene_warnings(SceneV2(**after[sid]))
    return [w for w in now if w not in was]


def _free_backup_path(backup_dir: Path) -> Path:
    """A backup path that does not exist yet. The stamp is seconds-
    resolution, so two applies inside one second would otherwise have
    `shutil.copy2` clobber the backup of the ORIGINAL store with a backup of
    the already-patched one (the W2.5 review observed exactly that) — the
    one file anyone would reach for to undo this."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for n in range(1, 100):
        suffix = "" if n == 1 else f"-{n}"
        candidate = backup_dir / f"scenes-word-shapes-{stamp}{suffix}.json"
        if not candidate.exists():
            return candidate
    raise SystemExit(f"{backup_dir} already holds 99 backups stamped "
                     f"{stamp} — refusing to overwrite any of them")


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--revert", action="store_true",
                        help="exact inverse: remove the declaration and the "
                             "Words section from every named scene")
    parser.add_argument("--scene", dest="scenes", action="append",
                        help=f"scene name; repeatable (default: the plan's "
                             f"six — {', '.join(SCENE_NAMES)})")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    args = parser.parse_args(argv)

    names = args.scenes or SCENE_NAMES
    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to do")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)

    touched: list[str] = []
    missing: list[str] = []
    changed_any = False
    print(f"— {'revert' if args.revert else 'forward'}, "
          f"{len(names)} scene(s) named:")
    for name in names:
        sid = find_scene_id(store, name)
        if sid is None:
            missing.append(name)
            print(f"  {name}: NOT IN THIS STORE — skipped (not invented)")
            continue
        touched.append(sid)
        SceneV2(**store[sid])          # must parse under the current code
        lines, wrote = patch(store[sid], f"{name} ({sid})",
                             revert=args.revert)
        print(f"  {name} ({sid}):")
        for line in lines:
            print("    " + line)
        if not lines:
            print("    nothing to do")
        changed_any = changed_any or wrote
        SceneV2(**store[sid])          # the result must parse too
        added = new_warnings(before, store, sid)
        if added:
            raise SystemExit(
                f"UNEXPECTED: {name!r} gained scene warning(s) from this "
                f"change — refusing:\n  " + "\n  ".join(added))
    if missing:
        print(f"  absent: {', '.join(missing)} — nothing written for "
              f"{'it' if len(missing) == 1 else 'them'}")
    verify_diff(before, store, touched)
    if not changed_any:
        print("nothing to do")
        return 0
    if not args.apply:
        print("\nDRY RUN — use --apply to write.")
        return 0

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = _free_backup_path(backup_dir)
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")
    _atomic_write(args.scenes_file, store)
    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    verify_diff(json.loads(backup.read_text(encoding="utf-8")), written,
                touched)
    print(f"written and verified: only the {KIND_NAME!r} declarations and "
          f"their Words sections changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
