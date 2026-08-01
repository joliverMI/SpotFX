"""
Seed / re-seed the "Squiggles" scene pair, mirroring the Black Hole /
Fireworks scene structure, then insert the scene into every scene group
that contains the Black Hole scene (weight 1.0, idempotent).

  - "Squiggles Scene Setter" (composite): Matrix→squiggles / Strips→
    orbits1d / Singles→power. Every settable squiggles parameter is
    asserted: shape sub-fields (reverse, blob_size, x/y offset),
    reactivity per-param values, and the label-addressed leftovers
    (Step Size / Step Count / Horizontal Gap) via one ledfx_effect_param.
    beat_burst rides trigger intensity 1..5 (fallback 2).
    Plus the same two starter Color Sets as Black Hole/Fireworks.
  - "Squiggles" (scene_update) lanes:
      First : the Setter
      Rest  : scene_morph advance 1 + Color Flare
      Shape : random pick — Reverse (turn around) | Long chains
              (Step Count 8) | Short chains (Step Count 3)
      Color : random pick — cycle the "Orbits" color group (weight 4,
              preserve effect) | Ambient Flip and Back - Fast

Deterministic UUIDs (uuid5) so re-running upserts the same two events.

USAGE
  .venv/bin/python scripts/seed_squiggles_scene.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
SETTER_ID = str(uuid.uuid5(NS, "spotfx-squiggles-scene-setter"))
SCENE_ID = str(uuid.uuid5(NS, "spotfx-squiggles-scene"))

BLACK_HOLE_SCENE = "ce69ee8d-5548-42db-85df-48d0149a0087"
GROUP_ORBITS = "e935c277-f62a-54ea-ae61-618d77140025"
SET_BASS_DROP_BRIGHTNESS = "25aa6203-0836-4f6e-8375-8532761bfc96"
EVENT_COLOR_FLARE = "fixed-color-flare"
EVENT_AMBIENT_FLIP_FAST = "1c2226d5-94c8-4dd1-b4c8-ccfb0cfd37a3"


def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS, f"spotfx-squiggles-{tag}"))


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


def label_params(params):
    return {
        "type": "ledfx_effect_param",
        "labels": [],
        "weight": 1.0,
        "virtual_id": None,
        "category": None,
        "params": params,
        "ramp_ms": 0,
        "fallback_s": None,
    }


MATRIX = scope(categories=["Matrix"])
STRIPS = scope(categories=["Strips"])
SINGLES = scope(categories=["Singles"])

SQ_REACTIVITY = {
    "spawn_rate": 0.0,
    "spawn_audio": 0.5,
    "base_speed": 38.0,
    "speed_audio": 2.7,
    "length_audio": 1.0,
    "brightness_audio": 1.0,
    "jiggle": 0.24,
    "max_blobs": 14,
    "impulse_decay": 0.06,
    # beat_burst rides trigger intensity (added in the target below)
}
SQ_LABEL_PARAMS = [
    {"param_label": "Step Size", "target_value": 3},
    {"param_label": "Step Count", "target_value": 4},
    {"param_label": "Horizontal Gap", "target_value": 25.0},
]

SETTER = {
    "id": SETTER_ID,
    "name": "Squiggles Scene Setter",
    "event_type": "composite",
    "color": "#00E5B0",
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
                    # Matrix — switch + full look. Param targets ramp_ms=0
                    # so they coalesce with the switch (see Fireworks
                    # Setter for the rationale).
                    node("setter-matrix", [morph_step(ramp_ms=1500, targets=[
                        target("effect", value={"effect_type": "squiggles"}),
                        target("shape", ramp_ms=0, value={
                            "blob_size": 1.0,
                            "reverse": False,
                            "x_offset": 0.0,
                            "y_offset": 0.0,
                        }),
                        target("reactivity", ramp_ms=0,
                               value={"reactivity_values": {
                                   **SQ_REACTIVITY,
                                   "beat_burst": intensity_map(1.0, 5.0, 2.0),
                               }}),
                    ]), label_params(SQ_LABEL_PARAMS)],
                        name="Matrix", nscope=MATRIX),
                    node("setter-strips", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "orbits1d"}),
                    ])], name="Strips", nscope=STRIPS),
                    node("setter-singles", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "power"}),
                        target("reactivity", value={"number": 0.29}),
                        target("blur", value={"number": 1.0}),
                        target("shape", value={"flip": False}),
                    ])], name="Singles", nscope=SINGLES),
                    node("setter-color-a",
                         [set_color(GROUP_ORBITS, advance=1, ramp_ms=150)]),
                    node("setter-color-b",
                         [set_color(SET_BASS_DROP_BRIGHTNESS,
                                    advance=1, ramp_ms=0)]),
                ],
            }]),
        ],
    },
}


def reverse_step():
    return morph_step(
        [target("shape", value={"reverse": "toggle"}, tscope=MATRIX)],
        ramp_ms=0, name="Reverse (turn around)",
    )


SCENE = {
    "id": SCENE_ID,
    "name": "Squiggles",
    "event_type": "scene_update",
    "color": "#00E5B0",
    "labels": ["particle"],
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
                        option("shape-reverse", [reverse_step()]),
                        option("shape-long", [label_params([
                            {"param_label": "Step Count",
                             "target_value": 8},
                        ])], name="Long chains"),
                        option("shape-short", [label_params([
                            {"param_label": "Step Count",
                             "target_value": 3},
                        ])], name="Short chains"),
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
    """Add the Squiggles scene (weight 1.0) to every scene group that
    contains the Black Hole scene. Idempotent."""
    with urllib.request.urlopen(f"{BASE}/api/events") as resp:
        evs = json.load(resp)
    evs = evs.get("events", evs) if isinstance(evs, dict) else evs
    for e in evs:
        if e.get("event_type") != "scene_group":
            continue
        members = e.get("scene_group_members") or []
        ids = [m["event_id"] for m in members]
        if BLACK_HOLE_SCENE not in ids or SCENE_ID in ids:
            continue
        members.append({"event_id": SCENE_ID, "weight": 1.0})
        e["scene_group_members"] = members
        post(e)
        print(f"  -> added to group '{e['name']}'")


if __name__ == "__main__":
    try:
        post(SETTER)
        post(SCENE)
        insert_into_groups()
    except urllib.error.HTTPError as err:
        print("HTTP error:", err.code, err.read().decode()[:2000])
        sys.exit(1)
    print("done — scene 'Squiggles' seeded + inserted into groups")
