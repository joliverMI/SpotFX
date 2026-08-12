"""
Seed / re-seed the "Fireworks" scene pair, mirroring the LIVE "Black Hole"
scene structure (node-level scopes with empty target scopes — parent scope
set once per lane node, children inherit):

  - "Fireworks Scene Setter" (composite): Matrix→fireworks / Strips→
    fireworks1d / Singles→power. EVERY settable parameter from Javi's LedFX
    "default" presets is asserted explicitly (shape sub-fields + reactivity
    per-param values + a Trail Length ledfx_effect_param, since trail_decay
    has no AspectValue slot) — so the tuned look survives stale
    morph_effect_state snapshots, not just fresh switches. The same values
    are ALSO captured in the catalog defaults (the switch starter). Two
    accents ride trigger intensity instead of being fixed:
      * Matrix burst size (shape `edges` sub-field → burst_size) bound
        5..14, fallback 8 (the preset value)
      * Matrix beat_burst bound 1..6, fallback 4 (the preset value)
    plus the same two starter Color Sets the Black Hole Setter fires
    ("Orbits" group pick + Bass Drop Brightness). Colors / background /
    brightness are deliberately NOT asserted — the Color Sets own those.
  - "Fireworks" (scene_update) lanes:
      First : the Setter
      Rest  : scene_morph advance 1 + Color Flare (same as Black Hole)
      Shape : random pick — reverse (Matrix+Strips together, implosion
              fireworks) | bigger bursts (+2) | smaller bursts (−2)
      Color : random pick — cycle the "Orbits" color group (weight 4,
              preserve effect) | Ambient Flip and Back - Fast

Deterministic UUIDs (uuid5) so re-running upserts the same two events.

USAGE
  .venv/bin/python scripts/seed_fireworks_scene.py    # POST to running SpotFX
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
SETTER_ID = str(uuid.uuid5(NS, "spotfx-fireworks-scene-setter"))
SCENE_ID = str(uuid.uuid5(NS, "spotfx-fireworks-scene"))

# Shared refs (same ones the live Black Hole scene uses)
GROUP_ORBITS = "e935c277-f62a-54ea-ae61-618d77140025"
SET_BASS_DROP_BRIGHTNESS = "25aa6203-0836-4f6e-8375-8532761bfc96"
EVENT_COLOR_FLARE = "fixed-color-flare"
EVENT_AMBIENT_FLIP_FAST = "1c2226d5-94c8-4dd1-b4c8-ccfb0cfd37a3"


def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS, f"spotfx-fireworks-{tag}"))


def scope(categories=None, virtual_ids=None):
    return {
        "virtual_ids": virtual_ids or [],
        "categories": categories or [],
        "roles": [],
    }


def intensity_map(out_min, out_max, fallback):
    """Bind a value to the fired trigger's intensity score."""
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
    # target scopes stay EMPTY by default — the lane node's scope is the
    # parent and children inherit it (clean parent/override layering)
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


MATRIX = scope(categories=["Matrix"])
STRIPS = scope(categories=["Strips"])
SINGLES = scope(categories=["Singles"])
MATRIX_STRIPS = scope(categories=["Matrix", "Strips"])

# ── Javi's LedFX "default" presets, asserted explicitly ─────────────────────
# (values mirror config/effect_params.json defaults, captured from the
# presets; update BOTH if the preset is re-saved)
FW2D_REACTIVITY = {
    "spawn_rate": 0.0,        # beat-bursts only
    "spawn_audio": 2.0,
    "burst_speed": 1.8,
    "burst_life": 1.9,
    "speed_audio": 3.2,
    "brightness_audio": 2.0,
    "burst_audio": 1.0,
    "max_blobs": 100,
    "drag": 0.69,
    "impulse_decay": 0.06,
    # beat_burst rides trigger intensity (added in the target below)
}
FW2D_TRAIL = 0.27
FW1D_REACTIVITY = {
    "spawn_rate": 0.0,
    "beat_burst": 2,
    "spawn_audio": 0.0,
    "burst_speed": 0.5,
    "burst_life": 1.2,
    "speed_audio": 2.5,
    "brightness_audio": 2.0,
    "max_blobs": 6,
    "drag": 0.5,
    "impulse_decay": 0.06,
}
FW1D_TRAIL = 0.24


def trail_param(value):
    """trail_decay has no Shape AspectValue slot — set it via the unified
    param label (scope inherited from the lane node)."""
    return {
        "type": "ledfx_effect_param",
        "labels": [],
        "weight": 1.0,
        "virtual_id": None,
        "category": None,
        "params": [{"param_label": "Trail Length", "target_value": value}],
        "ramp_ms": 0,
        "fallback_s": None,
    }


SETTER = {
    "id": SETTER_ID,
    "name": "Fireworks Scene Setter",
    "event_type": "composite",
    "color": "#FFD700",
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
                    # Matrix — effect switch + the FULL preset asserted:
                    # shape sub-fields, reactivity per-param values, and
                    # Trail Length. Burst size + beat_burst ride trigger
                    # intensity with the preset values as fallbacks.
                    # Param targets use ramp_ms=0 ON PURPOSE: instant writes
                    # coalesce with the switch into one atomic PUT (bus keys
                    # by (virtual, effect)) — ramped params would tween in
                    # parallel with the switch crossfade and can be lost to
                    # write races; the glide would be invisible under the
                    # crossfade anyway.
                    node("setter-matrix", [morph_step(ramp_ms=1500, targets=[
                        target("effect", value={"effect_type": "fireworks"}),
                        target("shape", ramp_ms=0, value={
                            # `edges` sub-field → burst_size on fireworks
                            "edges": intensity_map(5.0, 14.0, 8.0),
                            "blob_size": 2.0,
                            "radius_scale": 1.0,
                            "reverse": False,
                            "x_offset": 0.0,   # frontend −1..1 → centered
                            "y_offset": 0.0,
                        }),
                        target("reactivity", ramp_ms=0,
                               value={"reactivity_values": {
                                   **FW2D_REACTIVITY,
                                   "beat_burst": intensity_map(1.0, 6.0, 4.0),
                               }}),
                    ]), trail_param(FW2D_TRAIL)],
                        name="Matrix", nscope=MATRIX),
                    # Strips — effect switch + the full 1D preset asserted.
                    node("setter-strips", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "fireworks1d"}),
                        target("shape", ramp_ms=0, value={
                            "blob_size": 1.7,
                            "reverse": False,
                        }),
                        target("reactivity", ramp_ms=0,
                               value={"reactivity_values": FW1D_REACTIVITY}),
                    ]), trail_param(FW1D_TRAIL)],
                        name="Strips", nscope=STRIPS),
                    # Singles — same power look as the Black Hole Setter.
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


def reverse_step(ramp_ms=500):
    """Tri-state Reverse on Matrix + Strips together — flips both
    fireworks into implosion mode (and back)."""
    return morph_step(
        [target("shape", value={"reverse": "toggle"}, tscope=MATRIX_STRIPS)],
        ramp_ms=ramp_ms, name="Reverse (implode)",
    )


def burst_nudge_step(amount, name):
    """Bigger/smaller fireworks; burst size lives on the Shape aspect's
    `edges` sub-field (bounded 4..16)."""
    return morph_step(
        [target(
            "shape", mode="nudge",
            value={"edges_nudge": {"amount": amount, "scale": 0.0,
                                   "lo": 4, "hi": 16, "wrap": False}},
            tscope=MATRIX,
        )],
        ramp_ms=0, name=name,
    )


SCENE = {
    "id": SCENE_ID,
    "name": "Fireworks",
    "event_type": "scene_update",
    "color": "#FF6A00",
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
            # scene updates: palette morph + a color flare, like Black Hole
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
                        option("shape-bigger",
                               [burst_nudge_step(2.0, "Bigger bursts")]),
                        option("shape-smaller",
                               [burst_nudge_step(-2.0, "Smaller bursts")]),
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


if __name__ == "__main__":
    try:
        post(SETTER)
        post(SCENE)
    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code, e.read().decode()[:2000])
        sys.exit(1)
    print("done — scene 'Fireworks' + 'Fireworks Scene Setter' seeded")
