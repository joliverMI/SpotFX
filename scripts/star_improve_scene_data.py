"""STAR's scene data for the star improve plan (2026-11-12,
data/star-improve-plan/plan.md) — four surgical changes to ONE scene, with a
timestamped backup, a structural diff, --revert, and a dry run by default.

His words, verbatim: "I want to improve the star scene ... the amount of
star should dynamically change with the music ... constantly be flowing and
bouncing between the top and bottom values for that setting. Flares should
change the number of edges, but do it visually smoothly like we have. The
melt (which is used as the effect for radial) should have more "dark
blobs" ..."; round 1 Q5: "now it should change until there is a new scene
update or flare"; after the star grid: "let's do -.2 to +.4 as the standard
range they sway between. I want it to go through 0. go on the build".

WHAT CHANGES, and nothing else (every other field on STAR and every other
scene byte-identical, asserted after the write):

  1. Matrix entry (radial): the entry ease-in `spin_ease_in_s: 1.0` (his
     "spin from the beginning"; the effect's own default stays 0 so every
     other Radial scene is byte-identical), the star wave on, across his
     standard range — `star_wave: true`, `star_wave_lo: -0.2`,
     `star_wave_hi: 0.4` — and the
     `star` binding's own picks brought INSIDE that range so the value a
     fire lands (where the sway starts) is a standard one: steps
     {0.0 -> 0.0, 0.5 -> 0.3}, fallback 0.0, random_sign off (today: ±0.3 /
     ±0.5, half of which sit outside -0.2..0.4).
  2. The two 0.7–1 PERMANENT patch kinds ("Flare patch 0.7–1", "Drop patch
     0.7–1") drop their `star: 0.0` write — it flattened the star for the
     rest of the run on any loud flare; their `spin: 0.55` write stays.
  3. A new PERMANENT flare kind "Edge Morph" (`edges` mode random_other,
     3..6 — never the same count twice in a row; the existing 0.6 s shape
     morph glides it) attached at weight 1.0 to the two upper flare bands
     (0.35–0.7 and 0.7–1) — his Q12 default. A kind of that name already
     present is refused, not duplicated.
  4. Strips entry (melt): `dark_floor: 0.5` — his Q7 default (B2 on the
     explainer: 61% of the strip lit -> 33%, still the brightest strip).

NOT here: the fire-time sign-flip fix, the ease-in, the speed cap (engine
code); the TV ring lookup (scripts/tv_ring_pixel_map.py, a device config).

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — the discipline of
scripts/switch_star_reverse_flares_to_flip.py and star_strips_always_melt.py
(a model round-trip has silently rewritten other scenes). SceneV2 is used to
READ (validation before and after) only. The patched store is re-read from
disk and diffed against the pre-write snapshot: the run fails unless the
only differing paths are the ones listed above.

--revert performs the exact inverse (the pre-change values are pinned here
and verified against the store before reverting). Idempotent: a field
already at its target is reported and skipped; a field at neither the
expected old nor the target shape is REFUSED rather than overwritten.

Dry-run by default; --apply writes (atomic tmp+replace, indent=2) after
copying the store to storage/spectra/backups/scenes-star-improve-<stamp>.json.
Not run against live storage by the build — DJ applies it at deploy.
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
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config                                   # noqa: E402
from spectra.models.scene import SceneV2                     # noqa: E402

SCENE_NAME = "STAR"
STAR_ID = "d3aab04c-7e23-4693-bd26-16bad45792a6"
MATRIX_ENTRY = "93385d09-a352-4f16-9678-ce3760d93eac"
STRIPS_ENTRY = "039e4e68-0337-4401-8ef1-10610abbfc1a"
PATCH_KINDS = ("Flare patch 0.7–1", "Drop patch 0.7–1")
EDGE_KIND = "Edge Morph"
EDGE_BANDS = ((0.35, 0.7), (0.7, 1.0))

WAVE_LO, WAVE_HI = -0.2, 0.4
SPIN_EASE_IN_S = 1.0
DARK_FLOOR = 0.5

OLD_STAR_BINDING = {
    "bind": "signal", "signal": "random", "window_beats": 0, "window_dir": "past",
    "mode": "steps", "in_min": 0.0, "in_max": 1.0, "out_min": 0.0, "out_max": 1.0,
    "steps": [{"threshold": 0.0, "value": 0.3}, {"threshold": 0.5, "value": 0.5}],
    "fallback": 0.3, "random_sign": True, "dice": "a", "sticky": False,
}
NEW_STAR_BINDING = {
    **OLD_STAR_BINDING,
    "steps": [{"threshold": 0.0, "value": 0.0}, {"threshold": 0.5, "value": 0.3}],
    "fallback": 0.0, "random_sign": False,
}
STAR_PARAM_TARGET = {"mode": "absolute", "value": 0.0, "offset": None, "lo": None, "hi": None}
EDGE_KIND_RAW = {
    "name": EDGE_KIND, "type": "permanent", "jump": None,
    "params": {"edges": {"mode": "random_other", "value": None, "offset": None,
                         "lo": 3.0, "hi": 6.0}},
    "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0, "min_intensity": None,
    "enabled": True,
}


class Refuse(SystemExit):
    pass


def _find_scene(store: dict) -> str:
    if STAR_ID in store and store[STAR_ID].get("name") == SCENE_NAME:
        return STAR_ID
    matches = [sid for sid, raw in store.items() if raw.get("name") == SCENE_NAME]
    if len(matches) != 1:
        raise Refuse(f"scene '{SCENE_NAME}' matches {len(matches)} scenes — refusing to guess")
    return matches[0]


def _entry(raw: dict, entry_id: str, target: str, effect: str) -> dict:
    for dev in raw.get("devices", []):
        if dev.get("id") == entry_id:
            if dev.get("target") != target or dev.get("effect_type") != effect:
                raise Refuse(f"entry {entry_id} is {dev.get('target')}/{dev.get('effect_type')}, "
                             f"expected {target}/{effect} — refusing")
            return dev
    for dev in raw.get("devices", []):
        if dev.get("target") == target and dev.get("effect_type") == effect:
            return dev
    raise Refuse(f"no {target}/{effect} entry on {SCENE_NAME}")


def plan(raw: dict, revert: bool) -> list[tuple[str, Any]]:
    """The list of (path, action) this run would perform — printed on a dry
    run, applied on --apply. Each action is a closure over `raw`."""
    actions: list[tuple[str, Any]] = []
    matrix = _entry(raw, MATRIX_ENTRY, "Matrix", "radial")
    strips = _entry(raw, STRIPS_ENTRY, "Strips", "melt")
    mp = matrix.setdefault("params", {})
    sp = strips.setdefault("params", {})

    # 1. the wave + the star binding
    want_wave = {} if revert else {"spin_ease_in_s": SPIN_EASE_IN_S, "star_wave": True,
                                   "star_wave_lo": WAVE_LO, "star_wave_hi": WAVE_HI}
    for key in ("spin_ease_in_s", "star_wave", "star_wave_lo", "star_wave_hi"):
        cur = mp.get(key)
        if revert:
            if key in mp:
                actions.append((f"Matrix.params.{key}", ("del", mp, key)))
        elif cur != want_wave[key]:
            if key in mp and cur is not None:
                raise Refuse(f"Matrix.params.{key} is {cur!r}, neither absent nor the target — refusing")
            actions.append((f"Matrix.params.{key}", ("set", mp, key, want_wave[key])))
    src, dst = (NEW_STAR_BINDING, OLD_STAR_BINDING) if revert else (OLD_STAR_BINDING, NEW_STAR_BINDING)
    cur = mp.get("star")
    if cur == dst:
        pass
    elif cur == src:
        actions.append(("Matrix.params.star", ("set", mp, "star", copy.deepcopy(dst))))
    else:
        raise Refuse(f"Matrix.params.star is not the expected binding — refusing. Found: {cur}")

    # 2. the two patch kinds' star write
    kinds = raw.setdefault("flare_kinds", [])
    for name in PATCH_KINDS:
        hits = [k for k in kinds if k.get("name") == name]
        if len(hits) != 1:
            raise Refuse(f"flare kind {name!r}: {len(hits)} found — refusing")
        params = hits[0].setdefault("params", {})
        if revert:
            if "star" not in params:
                actions.append((f"flare_kinds[{name}].params.star", ("set", params, "star", dict(STAR_PARAM_TARGET))))
            elif params["star"] != STAR_PARAM_TARGET:
                raise Refuse(f"{name}: star target is {params['star']}, not the known shape — refusing")
        else:
            if "star" in params:
                if params["star"] != STAR_PARAM_TARGET:
                    raise Refuse(f"{name}: star target is {params['star']}, not the known shape — refusing")
                actions.append((f"flare_kinds[{name}].params.star", ("del", params, "star")))

    # 3. Edge Morph
    bands = raw.get("responses", {}).get("flare", {}).get("bands", [])
    existing = [i for i, k in enumerate(kinds) if k.get("name") == EDGE_KIND]
    if revert:
        if existing:
            actions.append((f"flare_kinds[{EDGE_KIND}]", ("pop_kind", kinds, existing[0])))
        for b in bands:
            if (b.get("intensity_min"), b.get("intensity_max")) in EDGE_BANDS and EDGE_KIND in b.get("kinds", {}):
                actions.append((f"responses.flare.bands[{b['intensity_min']}-{b['intensity_max']}].kinds.{EDGE_KIND}",
                                ("del", b["kinds"], EDGE_KIND)))
    else:
        if len(existing) > 1:
            raise Refuse(f"{EDGE_KIND}: {len(existing)} kinds of that name — refusing")
        if not existing:
            actions.append((f"flare_kinds[{EDGE_KIND}]", ("append_kind", kinds, copy.deepcopy(EDGE_KIND_RAW))))
        elif kinds[existing[0]] != EDGE_KIND_RAW:
            raise Refuse(f"{EDGE_KIND} exists with a different shape — refusing")
        found = set()
        for b in bands:
            key = (b.get("intensity_min"), b.get("intensity_max"))
            if key in EDGE_BANDS:
                found.add(key)
                if b.setdefault("kinds", {}).get(EDGE_KIND) != 1.0:
                    actions.append((f"responses.flare.bands[{key[0]}-{key[1]}].kinds.{EDGE_KIND}",
                                    ("set", b["kinds"], EDGE_KIND, 1.0)))
        if found != set(EDGE_BANDS):
            raise Refuse(f"flare bands {sorted(set(EDGE_BANDS) - found)} not found on {SCENE_NAME} — refusing")

    # 4. dark floor
    cur = sp.get("dark_floor")
    if revert:
        if "dark_floor" in sp:
            if cur != DARK_FLOOR:
                raise Refuse(f"Strips.params.dark_floor is {cur!r}, not {DARK_FLOOR} — refusing")
            actions.append(("Strips.params.dark_floor", ("del", sp, "dark_floor")))
    elif cur != DARK_FLOOR:
        if cur is not None:
            raise Refuse(f"Strips.params.dark_floor is {cur!r}, neither absent nor {DARK_FLOOR} — refusing")
        actions.append(("Strips.params.dark_floor", ("set", sp, "dark_floor", DARK_FLOOR)))
    return actions


def apply_actions(actions) -> None:
    for _path, act in actions:
        op = act[0]
        if op == "set":
            _, d, k, v = act
            d[k] = v
        elif op == "del":
            _, d, k = act
            del d[k]
        elif op == "append_kind":
            _, lst, v = act
            lst.append(v)
        elif op == "pop_kind":
            _, lst, i = act
            lst.pop(i)


def diff_paths(a: Any, b: Any, path: str = "") -> list[str]:
    """Every JSON path at which a and b differ (leaf granularity)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}")
            else:
                out.extend(diff_paths(a[k], b[k], f"{path}.{k}"))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}[len {len(a)}->{len(b)}]"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff_paths(x, y, f"{path}[{i}]"))
        return out
    return [] if a == b else [path]


def allowed_paths(sid: str) -> tuple[str, ...]:
    return (f".{sid}.devices[", f".{sid}.flare_kinds", f".{sid}.responses.flare.bands[")


def run(scenes_file: Path, *, apply: bool, revert: bool) -> list[str]:
    if not scenes_file.exists():
        raise Refuse(f"no {scenes_file} — nothing to migrate")
    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)
    sid = _find_scene(store)
    SceneV2(**store[sid])          # read-only: the store validates before
    actions = plan(store[sid], revert)
    label = "revert" if revert else "forward"
    print(f"— {SCENE_NAME} ({sid}), {label}: {len(actions)} change(s)")
    for path, act in actions:
        print(f"  {path}: {act[0]}" + (f" -> {act[3]!r}" if act[0] == 'set' else ""))
    if not actions:
        print("nothing to do")
        return []
    apply_actions(actions)
    SceneV2(**store[sid])          # ... and after
    changed = diff_paths(before, store)
    bad = [c for c in changed if not c.startswith(allowed_paths(sid))]
    if bad:
        raise Refuse(f"the patch touched paths outside STAR's own entries/kinds/bands: {bad}")
    if not apply:
        print(f"\nDRY RUN — would write {len(changed)} leaf path(s) on {SCENE_NAME} in {scenes_file} "
              "(use --apply); every other scene byte-identical.")
        return changed
    backup_dir = scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-star-improve-{stamp}.json"
    shutil.copy2(scenes_file, backup)
    print(f"backed up {scenes_file} -> {backup}")
    fd, tmp = tempfile.mkstemp(dir=str(scenes_file.parent), prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, scenes_file)
    after = json.loads(scenes_file.read_text(encoding="utf-8"))
    reread = diff_paths(before, after)
    if sorted(reread) != sorted(changed):
        raise Refuse(f"post-write diff differs from the plan: {reread} vs {changed}")
    print(f"patched {len(changed)} leaf path(s) on {SCENE_NAME}; every other scene byte-identical")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the store (default: dry run)")
    ap.add_argument("--revert", action="store_true", help="the exact inverse")
    ap.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    a = ap.parse_args()
    run(a.scenes_file, apply=a.apply, revert=a.revert)


if __name__ == "__main__":
    main()
