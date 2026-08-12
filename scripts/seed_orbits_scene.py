"""
Seed / re-seed the "Orbits" scene pair, mirroring the "Black Hole" scene:

  - "Orbits Scene Setter" (composite, scene_override): switches the Matrix to
    the orbits effect with Javi's tuned look (pulled from the LedFX-stored
    crystal-mapper orbits config), Strips→melt / Singles→power exactly like the
    Black Hole Setter, and fires the same two starter Color Sets
    (Black Hole Rainbow + Bass Drop Brightness).
  - "Orbits" (scene_update) lanes:
      First : the Setter
      Rest  : cycle the "Orbits" color group by 3 + reverse spin
      Shape : random pick — reverse spin | add a particle | remove a particle
              (particle count bounded 3..10 so the look stays dense-but-clean)
      Color : random pick — color_shift +1 (colors jump A,B,C → C,A,B, wrap
              bounces at the range ends) | cycle the "Orbits" group

Deterministic UUIDs (uuid5) so re-running upserts the same two events.

USAGE
  .venv/bin/python scripts/seed_orbits_scene.py           # POST to running SpotFX
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
SETTER_ID = str(uuid.uuid5(NS, "spotfx-orbits-scene-setter"))
SCENE_ID = str(uuid.uuid5(NS, "spotfx-orbits-scene"))

# Color refs shared with the Black Hole scene
SET_BLACK_HOLE_RAINBOW = "c7bc2bdd-9145-46cd-bcad-6f3c240c3bfc"
SET_BASS_DROP_BRIGHTNESS = "25aa6203-0836-4f6e-8375-8532761bfc96"
# "Orbits" color group — seeded by scripts/seed_orbits_colorsets.py
GROUP_ORBITS = "e935c277-f62a-54ea-ae61-618d77140025"

# Tuned orbits look (LedFX-space), pulled from the stored crystal-mapper config
ORBITS_PARTICLES = 6  # shape aspect: the `edges` sub-field ("Edge / Particle Count")
ORBITS_REACTIVITY = {
    "spin": 0.37,
    "base_speed": 0.3,
    "jiggle": 0.15,
    "tether_scatter": 0.0,
    "reactivity_scale": 1.0,
    "speed_jump": 1.0,
    "speed_jog": 1.0,
    "brightness_audio": 0.5,
    "size_audio": 0.5,
    "color_shift": 1,
    "impulse_decay": 0.06,
}
ORBITS_HORIZON = 0.19       # tether ring radius
ORBITS_FIELD_RADIUS = 1.8   # radius_scale — field size vs panel edge


def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS, f"spotfx-orbits-{tag}"))


def scope(categories=None, virtual_ids=None):
    return {
        "virtual_ids": virtual_ids or [],
        "categories": categories or [],
        "roles": [],
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


MATRIX = scope(categories=["Matrix"])
STRIPS = scope(categories=["Strips"])
SINGLE = scope(virtual_ids=["single-color-effect"])


def reverse_spin_step(ramp_ms=500):
    """Tri-state toggle of the orbits spin direction (Matrix only)."""
    return morph_step(
        [target("shape", value={"reverse": "toggle"}, tscope=MATRIX)],
        ramp_ms=ramp_ms, name="Reverse spin",
    )


def particle_nudge_step(amount, name):
    """Add/remove one particle; bounded 3..10 so the look stays clean.
    Particle count lives on the Shape aspect's `edges` sub-field."""
    return morph_step(
        [target(
            "shape", mode="nudge",
            value={"edges_nudge": {"amount": amount, "scale": 0.0,
                                   "lo": 3, "hi": 10, "wrap": False}},
            tscope=MATRIX,
        )],
        ramp_ms=0, name=name,
    )


SETTER = {
    "id": SETTER_ID,
    "name": "Orbits Scene Setter",
    "event_type": "composite",
    "color": "#FFD700",
    "labels": [],
    "energy_level": None,
    "ai_exposed": False,
    "fixed": False,
    "scene_override": True,
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
                    node("setter-matrix", [morph_step(ramp_ms=1500, targets=[
                        target("effect", value={"effect_type": "orbits"}),
                        target("shape", value={
                            "edges": ORBITS_PARTICLES,  # → particle_count on orbits
                            "horizon_scale": ORBITS_HORIZON,
                            "radius_scale": ORBITS_FIELD_RADIUS,
                            "reverse": False,
                            "x_offset": 0.0,   # frontend −1..1 → centered
                            "y_offset": 0.0,
                        }),
                        target("reactivity",
                               value={"reactivity_values": ORBITS_REACTIVITY}),
                    ])], name="Matrix", nscope=scope(categories=["Matrix"])),
                    node("setter-strips", [morph_step([
                        target("effect", value={"effect_type": "melt"}, tscope=STRIPS),
                        target("reactivity", value={"number": 0.74}, tscope=STRIPS),
                        target("blur", value={"number": 0.16},
                               tscope=scope(virtual_ids=["radial-dummy"])),
                        target("shape", value={"flip": False}, tscope=STRIPS),
                    ])], name="Strips", nscope=scope(categories=["Strips"])),
                    node("setter-singles", [morph_step([
                        target("effect", value={"effect_type": "power"}, tscope=SINGLE),
                        target("reactivity", value={"number": 0.29}, tscope=SINGLE),
                        target("blur", value={"number": 1.0}, tscope=SINGLE),
                        target("shape", value={"flip": False}, tscope=SINGLE),
                    ])], name="Singles", nscope=scope(categories=["Singles"])),
                    node("setter-color-a",
                         [set_color(SET_BLACK_HOLE_RAINBOW, advance=1, ramp_ms=150)]),
                    node("setter-color-b",
                         [set_color(SET_BASS_DROP_BRIGHTNESS, advance=1, ramp_ms=0)]),
                ],
            }]),
        ],
    },
}

SCENE = {
    "id": SCENE_ID,
    "name": "Orbits",
    "event_type": "scene_update",
    "color": "#3050FF",
    "labels": ["mid", "star"],
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
            "alternatives": [
                {"type": "event_ref", "event_id": SETTER_ID,
                 "labels": [], "weight": 1.0},
            ],
        },
        {
            # scene updates: cycle the Orbits group by 3 + reverse spin
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
                        node("rest-color",
                             [set_color(GROUP_ORBITS, advance=3,
                                        ramp_ms=5000)]),
                        node("rest-reverse", [reverse_spin_step(ramp_ms=500)]),
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
                        option("shape-reverse", [reverse_spin_step()]),
                        option("shape-add",
                               [particle_nudge_step(1.0, "Add particle")]),
                        option("shape-remove",
                               [particle_nudge_step(-1.0, "Remove particle")]),
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
                        option("color-jump", [morph_step(
                            [target(
                                "reactivity", mode="nudge",
                                value={"reactivity_nudges": {
                                    "color_shift": {"amount": 1.0, "scale": 0.0,
                                                    "wrap": True},
                                }},
                                tscope=MATRIX,
                            )],
                            ramp_ms=0, name="Color jump",
                        )]),
                        option("color-cycle",
                               [set_color(GROUP_ORBITS, advance=1,
                                          ramp_ms=2000, preserve_effect=True)]),
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


if __name__ == "__main__":
    try:
        post(SETTER)
        post(SCENE)
    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code, e.read().decode()[:2000])
        sys.exit(1)
    print("done — scene 'Orbits' + 'Orbits Scene Setter' seeded")
