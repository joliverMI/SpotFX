"""
Seed / re-seed the "Eye" scene pair for the native LedFX `eye` effect.

RUN ONLY AFTER THE TUNING GATE (docs/ADDING_EFFECTS.md): Javi tunes the
eye's defaults in the LedFX UI first; sync the tuned values into
EYE_SHAPE / EYE_REACTIVITY / EYE_LABEL_PARAMS below (and into
config/effect_params.json defaults) before running.

Structure mirrors the Dancers/Pacman seeders (node-level scopes, empty
target scopes, instant param writes coalescing with the switch):

  - "Eye Scene Setter" (composite): Matrix→eye / Strips→blackhole1d
    (presets mirrored from the live "Black Hole Setter") / Singles→power
    + the scene-group color. Flames ride trigger intensity; snap
    threshold drops (snaps easier) and snap hold grows with intensity.
  - "Eye" (scene_update) lanes:
      First : the Setter
      Rest  : scene_morph advance 1 + Color Flare
      Shape : random pick — Flame flare (temporary Flames burst that
              burns back down via fallback_s, weight 3) | Pupil dilate |
              Gaze widen | Spin flip
      Color : cycle "Orbits" color group (weight 4, preserve effect) |
              Ambient Flip and Back - Fast
      (Charge/Lull/Drop lanes stay EMPTY — the canonical phase events
      drive the eye's native charge/lull/drop choreography.)

Also inserts the scene into the "Mid Group", "Drop Group" and "Dark Hype"
scene groups (weight 1.0, idempotent).

Deterministic UUIDs (uuid5) so re-running upserts the same two events.

USAGE
  .venv/bin/python scripts/seed_eye_scene.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
SETTER_ID = str(uuid.uuid5(NS, "spotfx-eye-scene-setter"))
SCENE_ID = str(uuid.uuid5(NS, "spotfx-eye-scene"))

# Shared refs (same ones the live Fireworks / Pacman / Dancers scenes use)
GROUP_ORBITS = "e935c277-f62a-54ea-ae61-618d77140025"
EVENT_COLOR_FLARE = "fixed-color-flare"
EVENT_AMBIENT_FLIP_FAST = "1c2226d5-94c8-4dd1-b4c8-ccfb0cfd37a3"

# groups the scene joins (EXACT live names — check GET /api/events)
TARGET_GROUPS = ("Mid Group", "Drop Group", "Dark Hype")


def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS, f"spotfx-eye-{tag}"))


def scope(categories=None, virtual_ids=None):
    return {
        "virtual_ids": virtual_ids or [],
        "categories": categories or [],
        "roles": [],
    }


def intensity_map(out_min, out_max, fallback):
    return {
        "bind": "signal",
        "signal": "trigger_intensity",
        "window_beats": 0,
        "window_dir": "past",
        "mode": "map",
        "in_min": 0.0,
        "in_max": 1.0,
        "out_min": out_min,
        "out_max": out_max,
        "steps": [],
        "fallback": fallback,
    }


def target(aspect, mode="absolute", value=None, tscope=None, **kw):
    return {
        "scope": tscope or scope(),
        "aspect": aspect,
        "mode": mode,
        "absolute_value": value or {},
        "nudge_amount": kw.get("nudge_amount", 0.0),
        "intensity_scale": 0.0,
        "intensity_source": "rms_total",
        "ramp_ms": kw.get("ramp_ms"),
    }


def morph_step(targets, ramp_ms=500, name=""):
    return {
        "type": "morph_step",
        "name": name,
        "labels": [],
        "weight": 1.0,
        "ramp_ms": ramp_ms,
        "intensity_source": "rms_total",
        "targets": targets,
    }


def set_color(ref_id, advance=1, ramp_ms=0, preserve_effect=False, weight=1.0):
    return {
        "type": "set_color",
        "labels": [],
        "weight": weight,
        "ref_id": ref_id,
        "pick_mode": "default",
        "advance": advance,
        "direction": "forward",
        "ramp_ms": ramp_ms,
        "ramp_scale": 1.0,
        "preserve_effect": preserve_effect,
    }


def event_ref(event_id, weight=1.0):
    return {"type": "event_ref", "event_id": event_id,
            "labels": [], "weight": weight}


def node(tag, actions, name="", nscope=None):
    return {
        "id": _uid(tag),
        "name": name,
        "labels": [],
        "offset_ms": 0,
        "scope": nscope,
        "actions": actions,
    }


def option(tag, actions, weight=1.0, name=""):
    return {
        "id": _uid(tag),
        "name": name,
        "labels": [],
        "weight": weight,
        "energy_floor": None,
        "energy_ceiling": None,
        "energy_scale": 0.0,
        "scope": None,
        "actions": actions,
    }


def label_params(params, ramp_ms=0, fallback_s=None):
    return {
        "type": "ledfx_effect_param",
        "labels": [],
        "weight": 1.0,
        "virtual_id": None,
        "category": None,
        "params": params,
        "ramp_ms": ramp_ms,
        "fallback_s": fallback_s,
    }


MATRIX = scope(categories=["Matrix"])
STRIPS = scope(categories=["Strips"])
SINGLES = scope(categories=["Singles"])
SINGLE_VID = scope(virtual_ids=["single-color-effect"])

# ── eye presets ─────────────────────────────────────────────────────────
# SYNC WITH JAVI'S TUNED DEFAULTS BEFORE RUNNING (and mirror them into
# config/effect_params.json "eye" defaults). Shape sub-fields:
# radius_scale → iris_size, blob_size → pupil_size (compiler aliases).
EYE_SHAPE = {
    "radius_scale": 0.54,   # → iris_size (Javi's tuned defaults)
    "blob_size": 0.36,      # → pupil_size
    "x_offset": 0.0,
    "y_offset": 0.0,
}
EYE_REACTIVITY = {
    "flame_audio": 2.0,
    "speed_audio": 2.9,
    "spin_audio": 0.0,
    "impulse_decay": 0.06,
    # louder songs search faster, snap easier, and hold the stare longer
    "drift_speed": intensity_map(0.35, 0.8, 0.5),
    "snap_threshold": intensity_map(0.75, 0.45, 0.6),
    "snap_hold": intensity_map(0.15, 0.5, 0.2),
}
SPIN_DEFAULT = 0.08
EYE_LABEL_PARAMS = [
    # eye-specific params without a shared sub-field slot — label-addressed.
    # Javi's tuned default has flames 0; the SCENE runs them lit, riding
    # trigger intensity (the Shape lane flares them higher temporarily).
    {"param_label": "Flames", "target_value": intensity_map(0.2, 0.6, 0.35)},
    {"param_label": "Gaze Radius", "target_value": 0.5},
    {"param_label": "Spin", "target_value": SPIN_DEFAULT},
]

# Strips: blackhole1d, mirrored from the live "Black Hole Setter"
BH1D_SHAPE = {
    "swirl": 3.1,
    "radius_scale": 1.0,
    "blob_size": 0.5,
    "reverse": True,
    "x_offset": 0.0,
    "y_offset": 0.0,
}
BH1D_REACTIVITY = {
    "base_speed": 1.0, "accel": 5.0, "spawn_rate": 1.0, "beat_burst": 2.0,
    "spawn_audio": 1.0, "speed_audio": 2.3, "impulse_decay": 0.06,
    "max_blobs": 50.0, "edge_speed": 1.0, "approach_width": 0.16,
}


SETTER = {
    "id": SETTER_ID,
    "name": "Eye Scene Setter",
    "event_type": "composite",
    "color": "#ff8800",
    "labels": [],
    "energy_level": None,
    "ai_exposed": False,
    "fixed": False,
    "scene_override": False,
    "actions": [],
    "sequence_steps": [],
    "revert": None,
    "beat_sequence_steps": [],
    "beat_revert": None,
    "beat_sequence_fallback": "fallback",
    "beat_sequence_start_offset_beats": 0,
    "morph_lanes": [],
    "device_targets": [],
    "event_offset_ms": 0,
    "root": {
        "type": "parallel_group",
        "id": _uid("setter-root"),
        "labels": [],
        "weight": 1.0,
        "children": [
            node("setter-main", [{
                "type": "parallel_group",
                "id": _uid("setter-inner"),
                "labels": [],
                "weight": 1.0,
                "children": [
                    # Matrix — switch + preset. Instant param writes
                    # coalesce with the switch into one atomic PUT.
                    node("setter-matrix", [morph_step(ramp_ms=1500, targets=[
                        target("effect", value={"effect_type": "eye"}),
                        target("shape", ramp_ms=0, value=dict(EYE_SHAPE)),
                        target("reactivity", ramp_ms=0,
                               value={"reactivity_values": EYE_REACTIVITY}),
                    ]), label_params(EYE_LABEL_PARAMS)],
                        name="Matrix", nscope=MATRIX),
                    # Strips: blackhole is the eye's designated 1D effect
                    node("setter-strips", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "blackhole1d"}),
                        target("shape", value=dict(BH1D_SHAPE)),
                        target("reactivity",
                               value={"reactivity_values": BH1D_REACTIVITY}),
                    ])], name="Strips", nscope=STRIPS),
                    node("setter-singles", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "power"},
                               tscope=SINGLE_VID),
                        target("reactivity", value={"number": 0.29},
                               tscope=SINGLE_VID),
                        target("blur", value={"number": 1.0},
                               tscope=SINGLE_VID),
                    ])], name="Singles", nscope=SINGLES),
                    node("setter-color-a",
                         [set_color("__scene_group__", advance=1,
                                    ramp_ms=150)]),
                ],
            }]),
        ],
    },
}


def flame_flare():
    """The eye's shape morph: a temporary Flames surge that burns back
    down — fallback_s restores the prior config server-side."""
    return label_params(
        [{"param_label": "Flames", "target_value": 1.0}],
        ramp_ms=120, fallback_s=2.5,
    )


SCENE = {
    "id": SCENE_ID,
    "name": "Eye",
    "event_type": "scene_update",
    "color": "#ff8800",
    "labels": [],
    "energy_level": None,
    "ai_exposed": False,
    "fixed": False,
    "scene_override": False,
    "actions": [],
    "sequence_steps": [],
    "revert": None,
    "beat_sequence_steps": [],
    "beat_revert": None,
    "beat_sequence_fallback": "fallback",
    "beat_sequence_start_offset_beats": 0,
    "device_targets": [],
    "root": None,
    "event_offset_ms": 0,
    "morph_lanes": [
        {
            "name": "First",
            "labels": [],
            "offset_ms": 0,
            "alternatives": [event_ref(SETTER_ID)],
        },
        {
            "name": "Rest",
            "labels": [],
            "offset_ms": 0,
            "alternatives": [
                {
                    "type": "parallel_group",
                    "id": _uid("rest-par"),
                    "labels": [],
                    "weight": 1.0,
                    "children": [
                        node("rest-main", [
                            {"type": "scene_morph", "labels": [],
                             "weight": 1.0, "advance": 1,
                             "direction": "forward"},
                            event_ref(EVENT_COLOR_FLARE),
                        ]),
                    ],
                },
            ],
        },
        {
            "name": "Shape",
            "labels": [],
            "offset_ms": 0,
            "alternatives": [
                {
                    "type": "random_group",
                    "id": _uid("shape-random"),
                    "labels": [],
                    "weight": 1.0,
                    "dedupe": True,
                    "scope": None,
                    "options": [
                        option("shape-flames", [flame_flare()],
                               weight=3.0, name="Flame flare"),
                        option("shape-pupil", [label_params(
                            [{"param_label": "Pupil Size",
                              "target_value": 0.5}],
                            ramp_ms=150, fallback_s=2.0)],
                            weight=1.0, name="Pupil dilate"),
                        option("shape-gaze", [label_params(
                            [{"param_label": "Gaze Radius",
                              "target_value": 0.6}],
                            fallback_s=3.0)],
                            weight=1.0, name="Gaze widen"),
                        option("shape-spinflip", [label_params(
                            [{"param_label": "Spin",
                              "target_value": SPIN_DEFAULT,
                              "flip_sign": True}])],
                            weight=0.5, name="Spin flip"),
                    ],
                },
            ],
        },
        {
            "name": "Color",
            "labels": [],
            "offset_ms": 0,
            "alternatives": [
                {
                    "type": "random_group",
                    "id": _uid("color-random"),
                    "labels": [],
                    "weight": 1.0,
                    "dedupe": True,
                    "scope": None,
                    "options": [
                        option("color-cycle",
                               [set_color(GROUP_ORBITS, advance=1,
                                          ramp_ms=2000,
                                          preserve_effect=True,
                                          weight=4.0)],
                               weight=4.0),
                        option("color-ambient",
                               [event_ref(EVENT_AMBIENT_FLIP_FAST)]),
                    ],
                },
            ],
        },
    ],
}


def post(event: dict) -> None:
    req = urllib.request.Request(
        f"{BASE}/api/events",
        data=json.dumps(event).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        out = json.load(resp)
    eid = out.get("id") or (out.get("event") or {}).get("id")
    print(f"upserted: {event['name']}  ({eid or 'ok'})")


def insert_into_groups() -> None:
    """Add the Eye scene (weight 1.0) to the target scene groups.
    Idempotent; warns on a missing group name instead of silently
    no-opping."""
    with urllib.request.urlopen(f"{BASE}/api/events") as resp:
        evs = json.load(resp)
    evs = evs.get("events", evs) if isinstance(evs, dict) else evs
    groups = {e["name"]: e for e in evs
              if e.get("event_type") == "scene_group"}
    for name in TARGET_GROUPS:
        e = groups.get(name)
        if e is None:
            print(f"  !! scene group '{name}' NOT FOUND — live names: "
                  f"{sorted(groups)}")
            continue
        members = e.get("scene_group_members") or []
        if SCENE_ID in [m["event_id"] for m in members]:
            print(f"  already in group '{name}'")
            continue
        members.append({"event_id": SCENE_ID, "weight": 1.0})
        e["scene_group_members"] = members
        post(e)
        print(f"  -> added to group '{name}'")


if __name__ == "__main__":
    try:
        post(SETTER)
        post(SCENE)
        insert_into_groups()
    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code, e.read().decode()[:2000])
        sys.exit(1)
    print("done — scene 'Eye' + 'Eye Scene Setter' seeded")
