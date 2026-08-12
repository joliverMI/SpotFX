"""Seed the "Update Intensity" event + wire it into every scene-group member.

Pass 1 (Shape lanes): every member scene's Shape-lane alternatives are
wrapped in a parallel group that also fires "Update Intensity" by reference.

Pass 2 (scene-specific params): the two intensity bindings excluded from the
shared event as cross-effect leak hazards live INLINE in their own scene —
Black Hole gets spawn_rate, Dancers gets base_speed — as a "Scene Intensity"
morph step added wherever the Update Intensity ref goes for that scene.

Pass 3 (Rest lanes): the Update Intensity ref (+ that scene's inline params)
is copied into each member's Rest lane, EXCEPT where the Rest fire is a
scene morph (it switches members — intensity writes there would hit the
outgoing scene). Random alternatives/options: only the branches WITHOUT a
scene_morph get the additions.

Deterministic event id (uuid5); every pass is idempotent (skips subtrees
already containing the ref / the "Scene Intensity" step).

Run: .venv/bin/python scripts/seed_update_intensity.py [--apply]
Dry-run by default. Uses the live API so the running engine sees changes.
"""

import argparse
import json
import sys
import urllib.request
import uuid

BASE = "http://localhost:8000/api"
NS = uuid.uuid5(uuid.NAMESPACE_DNS, "spotfx.update-intensity")
UI_EVENT_ID = str(uuid.uuid5(NS, "event"))
MEMBERS = ["Black Hole", "Orbits", "Lines", "Squiggles", "Mid Star",
           "Fireworks", "Dancers", "Hype Star", "Pacman"]
REST_LANE, SHAPE_LANE = 1, 2
SCENE_STEP_NAME = "Scene Intensity"


def bind(out_min, out_max, fallback):
    return {
        "bind": "signal", "signal": "trigger_intensity",
        "window_beats": 0, "window_dir": "past", "mode": "map",
        "in_min": 0.0, "in_max": 1.0,
        "out_min": out_min, "out_max": out_max,
        "steps": [], "fallback": fallback, "random_sign": False,
    }


# Shared event: reconciled/portable params (see project memory for sources).
REACTIVITY_VALUES = {
    "beat_burst": bind(1.0, 6.0, 3.0),
    "burst_threshold": bind(0.78, 0.45, 0.63),
    "dance_intensity": bind(0.7, 1.7, 1.0),
    "beat_jump": bind(0.8, 3.0, 1.5),
}

# Scene-local params (cross-effect leak hazards, so they live only in the
# scene whose setter originally bound them).
INLINE_PARAMS = {
    "Black Hole": {"spawn_rate": bind(0.5, 2.0, 1.0)},
    "Dancers": {"base_speed": bind(0.6, 1.8, 1.0)},
}


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.load(r)


def _post(path, body):
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def build_event():
    return {
        "id": UI_EVENT_ID,
        "name": "Update Intensity",
        "event_type": "single",
        "actions": [{
            "type": "morph_step",
            "name": "Update Intensity",
            "ramp_ms": 0,
            "targets": [{
                "scope": {"virtual_ids": [], "categories": [], "roles": []},
                "aspect": "reactivity",
                "mode": "absolute",
                "absolute_value": {"reactivity_values": REACTIVITY_VALUES},
            }],
        }],
    }


def ui_ref():
    return {"type": "event_ref", "event_id": UI_EVENT_ID,
            "labels": [], "weight": 1.0}


def scene_step(params):
    return {
        "type": "morph_step", "name": SCENE_STEP_NAME, "ramp_ms": 0,
        "targets": [{
            "scope": {"virtual_ids": [], "categories": [], "roles": []},
            "aspect": "reactivity", "mode": "absolute",
            "absolute_value": {"reactivity_values": params},
        }],
    }


def _walk(action):
    yield action
    if not isinstance(action, dict):
        return
    for key in ("children", "options", "lanes"):
        for c in action.get(key) or []:
            for a in c.get("actions") or []:
                yield from _walk(a)


def _refs_ui(action) -> bool:
    return any(a.get("type") == "event_ref" and a.get("event_id") == UI_EVENT_ID
               for a in _walk(action) if isinstance(a, dict))


def _has_scene_step(action) -> bool:
    return any(a.get("type") == "morph_step" and a.get("name") == SCENE_STEP_NAME
               for a in _walk(action) if isinstance(a, dict))


def _has_scene_morph(action) -> bool:
    return any(a.get("type") == "scene_morph"
               for a in _walk(action) if isinstance(a, dict))


def _child(name, actions):
    return {"id": str(uuid.uuid4()), "name": name, "labels": [],
            "offset_ms": 0, "actions": actions}


def wrap(alt, extra_actions):
    """parallel(original, extras) preserving the alternative's pick weight."""
    return {
        "type": "parallel_group", "id": str(uuid.uuid4()), "labels": [],
        "weight": alt.get("weight", 1.0),
        "children": [_child("", [alt])]
        + [_child(a.get("name") or "Update Intensity", [a])
           for a in extra_actions],
    }


def ensure_additions(alt, additions, log, where):
    """Return (new_alt, changed): make sure `additions` (list of builders →
    dicts) fire alongside this alternative. parallel_group → append children;
    anything else → wrap."""
    todo = []
    for build, present in additions:
        if not present(alt):
            todo.append(build())
    if not todo:
        return alt, False
    if alt.get("type") == "parallel_group":
        for a in todo:
            alt["children"].append(_child(a.get("name") or "Update Intensity", [a]))
        log.append(f"{where}: appended {[a.get('name') or a['type'] for a in todo]}")
        return alt, True
    log.append(f"{where}: wrapped with {[a.get('name') or a['type'] for a in todo]}")
    return wrap(alt, todo), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    events = _get("/events")
    by_name = {e["name"]: e for e in events if e.get("event_type") == "scene_update"}
    print(f"Update Intensity event id: {UI_EVENT_ID}")
    if args.apply:
        _post("/events", build_event())
        print("event: SAVED")

    for name in MEMBERS:
        ev = by_name.get(name)
        if ev is None:
            print(f"{name}: NOT FOUND — skipped")
            continue
        log: list[str] = []
        changed = False
        lanes = ev.get("morph_lanes") or []
        while len(lanes) <= SHAPE_LANE:
            lanes.append({"name": ["First", "Rest", "Shape", "Color"][len(lanes)],
                          "alternatives": []})
        inline = INLINE_PARAMS.get(name)
        additions = [(ui_ref, _refs_ui)]
        if inline:
            additions.append((lambda p=inline: scene_step(p), _has_scene_step))

        # ── Shape lane: every alternative fires ref (+ inline step) ──
        shape = lanes[SHAPE_LANE]
        alts = shape.get("alternatives") or []
        if not alts:
            new = [ui_ref()] + ([scene_step(inline)] if inline else [])
            shape["alternatives"] = [wrap(new[0], new[1:]) if len(new) > 1 else new[0]]
            log.append("Shape: empty lane → plain additions")
            changed = True
        else:
            out = []
            for i, alt in enumerate(alts):
                alt2, ch = ensure_additions(alt, additions, log, f"Shape[{i}]")
                out.append(alt2)
                changed = changed or ch
            shape["alternatives"] = out

        # ── Rest lane: additions except where the fire is a scene morph ──
        rest = lanes[REST_LANE]
        out = []
        for i, alt in enumerate(rest.get("alternatives") or []):
            if not _has_scene_morph(alt):
                alt2, ch = ensure_additions(alt, additions, log, f"Rest[{i}]")
                out.append(alt2)
                changed = changed or ch
                continue
            # scene-morphing alternative: add only into random options that
            # DON'T morph away; skip entirely when there's no such branch.
            touched = False
            for node in _walk(alt):
                if not isinstance(node, dict) or node.get("type") != "random_group":
                    continue
                for o in node.get("options") or []:
                    opt_tree = {"type": "parallel_group",
                                "children": [{"actions": o.get("actions") or []}]}
                    if _has_scene_morph(opt_tree):
                        continue
                    for build, present in additions:
                        if not present(opt_tree):
                            o.setdefault("actions", []).append(build())
                            touched = True
                    if touched:
                        log.append(f"Rest[{i}]: added into non-morph random option "
                                   f"{o.get('name') or '(unnamed)'!r}")
            if touched:
                changed = True
            elif not _refs_ui(alt):
                log.append(f"Rest[{i}]: scene morph, no non-morph branch — skipped")
            out.append(alt)
        rest["alternatives"] = out

        status = " | ".join(log) if log else "no changes needed"
        print(f"{name}: {status}")
        if changed and args.apply:
            ev["morph_lanes"] = lanes
            _post("/events", ev)
            print(f"{name}: SAVED")
    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
