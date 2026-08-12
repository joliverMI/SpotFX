"""
Seed / re-seed the "Pacman" scene pair, mirroring the "Fireworks" scene
structure (node-level scopes with empty target scopes — parent scope set
once per lane node, children inherit):

  - "Pacman Scene Setter" (composite): Matrix→pacman / Strips→orbits1d /
    Singles→power. EVERY settable pacman parameter from Javi's LedFX
    "default" preset is asserted explicitly: shape sub-fields (reverse,
    edges→ghost_count, blob_size→entity_size — the pacman aliases added in
    morph_compiler), reactivity per-param values, and the label-addressed
    leftovers (Trail Length / Wall Brightness / Dot Brightness / Wall Color
    Roll / Fright Time) via one ledfx_effect_param. The same values are the
    catalog defaults (the switch starter). Two accents ride trigger
    intensity instead of being fixed:
      * ghost_count (shape `edges` sub-field) bound 2..4, fallback 4
      * beat_jump (reactivity) bound 0.8..3.0, fallback 1.5
    plus the same two starter Color Sets the Fireworks Setter fires
    ("Orbits" group pick + Bass Drop Brightness). Colors / background /
    brightness are deliberately NOT asserted — the Color Sets own those.
  - "Pacman" (scene_update) lanes:
      First : the Setter
      Rest  : scene_morph advance 1 + Color Flare (same as Fireworks)
      Shape : random pick — Fright! (Matrix reverse toggle: ghosts turn
              blue and she hunts them) | More ghosts (+1) | Fewer (−1)
      Color : random pick — cycle the "Orbits" color group (weight 4,
              preserve effect) | Ambient Flip and Back - Fast

Deterministic UUIDs (uuid5) so re-running upserts the same two events.

USAGE
  .venv/bin/python scripts/seed_pacman_scene.py    # POST to running SpotFX
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"

NS = uuid.NAMESPACE_DNS
SETTER_ID = str(uuid.uuid5(NS, "spotfx-pacman-scene-setter"))
SCENE_ID = str(uuid.uuid5(NS, "spotfx-pacman-scene"))

# Shared refs (same ones the live Fireworks / Black Hole scenes use)
GROUP_ORBITS = "e935c277-f62a-54ea-ae61-618d77140025"
SET_BASS_DROP_BRIGHTNESS = "25aa6203-0836-4f6e-8375-8532761bfc96"
EVENT_COLOR_FLARE = "fixed-color-flare"
EVENT_AMBIENT_FLIP_FAST = "1c2226d5-94c8-4dd1-b4c8-ccfb0cfd37a3"


def _uid(tag: str) -> str:
    return str(uuid.uuid5(NS, f"spotfx-pacman-{tag}"))


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

# ── Javi's LedFX "default" preset, asserted explicitly ──────────────────────
# (values mirror config/effect_params.json defaults, captured from the
# preset; update BOTH if the preset is re-saved)
PAC_REACTIVITY = {
    "wall_audio": 1.3,
    "base_speed": 2.0,
    "speed_audio": 3.3,
    "ghost_speed": 0.73,
    "impulse_decay": 0.09,
    # beat_jump rides trigger intensity (added in the target below)
}
# label-addressed params without an AspectValue slot
PAC_LABEL_PARAMS = [
    {"param_label": "Trail Length", "target_value": 0.35},
    {"param_label": "Wall Brightness", "target_value": 0.34},
    {"param_label": "Dot Brightness", "target_value": 0.78},
    {"param_label": "Wall Color Roll", "target_value": 0.41},
    {"param_label": "Fright Time", "target_value": 6.0},
]


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


SETTER = {
    "id": SETTER_ID,
    "name": "Pacman Scene Setter",
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
                    # Matrix — effect switch + the FULL preset asserted.
                    # Param targets use ramp_ms=0 ON PURPOSE: instant writes
                    # coalesce with the switch into one atomic PUT; ramped
                    # params would race the switch crossfade (see the
                    # Fireworks Setter for the long-form rationale).
                    node("setter-matrix", [morph_step(ramp_ms=1500, targets=[
                        target("effect", value={"effect_type": "pacman"}),
                        target("shape", ramp_ms=0, value={
                            # `edges` sub-field → ghost_count on pacman
                            "edges": intensity_map(2.0, 4.0, 4.0),
                            # `blob_size` sub-field → entity_size
                            "blob_size": 3.0,
                            "reverse": False,
                        }),
                        target("reactivity", ramp_ms=0,
                               value={"reactivity_values": {
                                   **PAC_REACTIVITY,
                                   "beat_jump": intensity_map(0.8, 3.0, 1.5),
                               }}),
                    ]), label_params(PAC_LABEL_PARAMS)],
                        name="Matrix", nscope=MATRIX),
                    # Strips — pacman has no 1D sibling; Orbits Strip keeps
                    # the "little runners on a track" vibe (catalog-default
                    # tuning applies on switch).
                    node("setter-strips", [morph_step(ramp_ms=500, targets=[
                        target("effect", value={"effect_type": "orbits1d"}),
                    ])], name="Strips", nscope=STRIPS),
                    # Singles — same power look as the Fireworks Setter.
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


def fright_step(ramp_ms=0):
    """Tri-state Reverse on the Matrix — pacman's fright mode: ghosts turn
    blue and she hunts them (and back)."""
    return morph_step(
        [target("shape", value={"reverse": "toggle"}, tscope=MATRIX)],
        ramp_ms=ramp_ms, name="Fright! (reverse)",
    )


def ghost_nudge_step(amount, name):
    """More/fewer ghosts; ghost count lives on the Shape aspect's
    `edges` sub-field (bounded 1..4)."""
    return morph_step(
        [target(
            "shape", mode="nudge",
            value={"edges_nudge": {"amount": amount, "scale": 0.0,
                                   "lo": 1, "hi": 4, "wrap": False}},
            tscope=MATRIX,
        )],
        ramp_ms=0, name=name,
    )


SCENE = {
    "id": SCENE_ID,
    "name": "Pacman",
    "event_type": "scene_update",
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
            # scene updates: palette morph + a color flare, like Fireworks
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
                        option("shape-fright", [fright_step()]),
                        option("shape-more-ghosts",
                               [ghost_nudge_step(1.0, "More ghosts")]),
                        option("shape-fewer-ghosts",
                               [ghost_nudge_step(-1.0, "Fewer ghosts")]),
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
    print("done — scene 'Pacman' + 'Pacman Scene Setter' seeded")
