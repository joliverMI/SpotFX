"""
Seed / re-seed the "Dancers" scene pair for the native LedFX `dancer`
effect (NOT the old keybeat2d GIF "Dancer" scene — that one stays).

Structure mirrors the Pacman/Squiggles seeders (node-level scopes, empty
target scopes, instant param writes coalescing with the switch):

  - "Dancers Scene Setter" (composite): Matrix→dancer / Strips→orbits1d /
    Singles→power + the two starter Color Sets. The dance style is picked
    by an intensity_chooser (trigger-intensity bands 0-4 / 4-7 / 7-10 →
    thresholds 0.0 / 0.4 / 0.7 on the internal 0..1 scale), then randomly
    within the band:
        low  : tai chi, ballet
        mid  : cowboy, salsa, moonwalk, worm
        high : hip hop, robot, tango, floss, worm
    Reactivity rides intensity too: burst_threshold drops (more bursts)
    and burst count (shape `edges` sub-field → burst_size) grows.
  - "Dancers" (scene_update) lanes:
      First : the Setter
      Rest  : scene_morph advance 1 + Color Flare
      Shape : random pick — re-roll the dance (same intensity chooser,
              weight 3) | Partner toggle (drop-in / flying exit) |
              stage-angle somersaults (±25° / level)
      Color : cycle "Orbits" color group (weight 4, preserve effect) |
              Ambient Flip and Back - Fast

Also inserts the scene into the "Mid Group" and "Drop Group" scene groups
(weight 1.0, idempotent).

Deterministic UUIDs (uuid5) so re-running upserts the same two events.

USAGE
  .venv/bin/python scripts/seed_dancers_scene.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
SETTER_ID = str(uuid.uuid5(NS, "spotfx-dancers-scene-setter"))
SCENE_ID = str(uuid.uuid5(NS, "spotfx-dancers-scene"))

# Shared refs (same ones the live Fireworks / Pacman scenes use)
GROUP_ORBITS = "e935c277-f62a-54ea-ae61-618d77140025"
EVENT_COLOR_FLARE = "fixed-color-flare"
EVENT_AMBIENT_FLIP_FAST = "1c2226d5-94c8-4dd1-b4c8-ccfb0cfd37a3"

# groups the scene joins
TARGET_GROUPS = ("Mid Group", "Drop Group")

# intensity bands (0-10 user scale → 0..1 internal) → weighted dances
DANCE_BANDS = [
    ("low", 0.0, [("tai_chi", 2.0), ("ballet", 1.0)]),
    ("mid", 0.4, [("cowboy", 1.5), ("salsa", 1.5), ("moonwalk", 1.0),
                  ("worm", 0.5)]),
    ("high", 0.7, [("hip_hop", 2.0), ("kpop", 2.0), ("robot", 1.5),
                   ("tango", 1.5), ("floss", 1.0), ("worm", 1.0)]),
]


def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS, f"spotfx-dancers-{tag}"))


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


def label_params(params, ramp_ms=0):
    return {
        "type": "ledfx_effect_param",
        "labels": [],
        "weight": 1.0,
        "virtual_id": None,
        "category": None,
        "params": params,
        "ramp_ms": ramp_ms,
        "fallback_s": None,
    }


def dance_write(style):
    return label_params([{"param_label": "Dance Type",
                          "string_value": style}])


def dance_chooser(tag):
    """intensity_chooser: band by trigger intensity, then random within
    the band. Lane 0 doubles as the no-intensity fallback."""
    lanes = []
    for band, threshold, styles in DANCE_BANDS:
        lanes.append({
            "id": _uid(f"{tag}-lane-{band}"),
            "name": {"low": "0-4", "mid": "4-7", "high": "7-10"}[band],
            "labels": [],
            "threshold": threshold,
            "scope": None,
            "actions": [{
                "type": "random_group",
                "id": _uid(f"{tag}-rand-{band}"),
                "labels": [],
                "weight": 1.0,
                "dedupe": True,
                "scope": None,
                "options": [
                    option(f"{tag}-{band}-{style}", [dance_write(style)],
                           weight=w, name=style)
                    for style, w in styles
                ],
            }],
        })
    return {
        "type": "intensity_chooser",
        "id": _uid(f"{tag}-chooser"),
        "labels": [],
        "weight": 3.0,
        "source": "trigger_intensity",
        "scope": MATRIX,
        "lanes": lanes,
    }


MATRIX = scope(categories=["Matrix"])
STRIPS = scope(categories=["Strips"])
SINGLES = scope(categories=["Singles"])

# reactivity preset (mirrors config/effect_params.json defaults; the two
# accents ride trigger intensity)
DANCER_REACTIVITY = {
    "burst_audio": 1.8,
    "brightness_audio": 0.6,
    "impulse_decay": 0.06,
    "jiggle": 0.25,
    # louder songs burst easier (centered on Javi's tuned 0.63)
    "burst_threshold": intensity_map(0.78, 0.45, 0.63),
    # pace + punch ride TRIGGER INTENSITY (0-10 per-song-scaled, same
    # signal the dance-type bands use): quiet songs dance measured,
    # big drops dance fast and hit hard
    "base_speed": intensity_map(1.4, 2.4, 2.0),
    "dance_intensity": intensity_map(0.7, 1.7, 1.0),
}
DANCER_LABEL_PARAMS = [
    {"param_label": "Trail Length", "target_value": 0.25},
]


def rand_toggle():
    """50/50 random boolean binding (matches the Orbits setter)."""
    return {
        "bind": "signal", "signal": "random", "window_beats": 0,
        "window_dir": "past", "mode": "steps", "in_min": 0.0,
        "in_max": 1.0, "out_min": 0.0, "out_max": 1.0,
        "steps": [{"threshold": 0.5, "value": True}],
        "fallback": False, "random_sign": False,
    }


# non-Matrix settings copied from the Orbits Scene Setter (Javi)
ORBITS1D_REACTIVITY = {
    "spin": 0.37, "base_speed": 0.3, "jiggle": 0.15,
    "tether_scatter": 0.0, "reactivity_scale": 1.0, "speed_jump": 1.0,
    "speed_jog": 1.0, "brightness_audio": 0.5, "size_audio": 0.5,
    "color_shift": 1.0, "impulse_decay": 0.06,
}
SINGLE_VID = scope(virtual_ids=["single-color-effect"])


SETTER = {
    "id": SETTER_ID,
    "name": "Dancers Scene Setter",
    "event_type": "composite",
    "color": "#ff2080",
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
                        target("effect", value={"effect_type": "dancer"}),
                        target("shape", ramp_ms=0, value={
                            # `edges` sub-field → burst_size on dancer
                            "edges": intensity_map(7.0, 16.0, 10.0),
                            "blob_size": 1.9,
                            "radius_scale": 0.7,
                            "reverse": False,
                        }),
                        target("reactivity", ramp_ms=0,
                               value={"reactivity_values":
                                      DANCER_REACTIVITY}),
                    ]), label_params(DANCER_LABEL_PARAMS),
                        dance_chooser("setter")],
                        name="Matrix", nscope=MATRIX),
                    # Strips + Singles + color: mirrored from the
                    # Orbits Scene Setter (Javi wants them identical)
                    node("setter-strips", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "orbits1d"}),
                        target("shape", value={
                            "edges": intensity_map(1.0, 8.0, 3.0),
                            "horizon_scale": 0.19,
                            "radius_scale": 1.8,
                            "blob_size": intensity_map(4.0, 1.0, None),
                            "reverse": rand_toggle(),
                            "x_offset": 0.0,
                            "y_offset": 0.0,
                        }),
                        target("reactivity",
                               value={"reactivity_values":
                                      ORBITS1D_REACTIVITY}),
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


def partner_toggle_step():
    """Tri-state Partner (reverse) on the Matrix: adds the second dancer
    with a drop-in / catch entrance, removes it superman / spin-off."""
    return morph_step(
        [target("shape", value={"reverse": "toggle"}, tscope=MATRIX)],
        ramp_ms=0, name="Partner toggle",
    )


def stage_angle_step(deg, name):
    """20°+ Stage Angle deltas make the dancers somersault into the new
    orientation. Rotation has no AspectValue slot → label-addressed."""
    return label_params([{"param_label": "Stage Angle",
                          "target_value": float(deg)}])


SCENE = {
    "id": SCENE_ID,
    "name": "Dancers",
    "event_type": "scene_update",
    "color": "#ff2080",
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
                        # re-roll the dance for the current intensity band
                        option("shape-dance", [dance_chooser("shape")],
                               weight=3.0, name="New dance"),
                        option("shape-partner", [partner_toggle_step()],
                               weight=1.0, name="Partner"),
                        option("shape-tilt-r",
                               [stage_angle_step(25, "Tilt right")],
                               weight=0.5, name="Somersault right"),
                        option("shape-tilt-l",
                               [stage_angle_step(-25, "Tilt left")],
                               weight=0.5, name="Somersault left"),
                        option("shape-level",
                               [stage_angle_step(0, "Level")],
                               weight=0.5, name="Somersault level"),
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
    """Add the Dancers scene (weight 1.0) to the target scene groups.
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
    print("done — scene 'Dancers' + 'Dancers Scene Setter' seeded")
