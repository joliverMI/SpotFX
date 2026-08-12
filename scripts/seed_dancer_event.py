"""
Seed the "Dancer" scene_update event: a dancing stick figure on the Matrix.

- First lane (scene entry): morph_step switches the Matrix to keybeat2d
  (starter config = effect_params defaults on first use; thereafter
  morph_effect_state resumes the last style/color).
- Rest lane (scene updates): random style swap (image_location + beat_frames
  ALWAYS in one patch), position shuffle, half-beat groove, flip.
- Shape lane (shape/combo flares): big-move GIF burst or a stretch burst,
  both with LedFX server-side fallback so the normal dance auto-restores.
- Color lane (color/combo flares): Dancer Color (keybeat2d tint) changes.

Idempotent by event name. Reads storage/gif_assets.json and refuses to seed
styles whose assets are missing from the live LedFX asset store.

Run: .venv/bin/python scripts/seed_dancer_event.py [--force-offline]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.music_event import (  # noqa: E402
    AspectValue,
    EffectParamChange,
    LedFxEffectParamAction,
    MorphLane,
    MorphScope,
    MorphStepAction,
    MorphTarget,
    MusicEvent,
    RandomGroupAction,
    RandomOption,
)

EVENT_NAME = "Dancer"
MATRIX_SCOPE = MorphScope(categories=["Matrix"])

# Rest-lane color variety fires only sometimes; flare Color lane always recolors.
DANCER_COLORS = ["#ffffff", "#ff2080", "#20c0ff", "#ffd020", "#30ff70", "#b040ff", "#ff5010"]


def _load_manifest() -> dict:
    path = Path(__file__).parent.parent / "storage" / "gif_assets.json"
    return json.loads(path.read_text())["assets"]


def _check_live_assets(assets: dict) -> None:
    import requests
    try:
        resp = requests.get("http://localhost:8888/api/assets", timeout=5)
        live = {a["path"] for a in resp.json().get("assets", [])}
    except Exception as exc:
        raise SystemExit(f"LedFX unreachable ({exc}); use --force-offline to skip the check")
    missing = [aid for aid, e in assets.items() if e["path"] not in live]
    if missing:
        raise SystemExit(f"assets missing from LedFX (publish them first): {missing}")


def _style_params(entry: dict) -> LedFxEffectParamAction:
    """image_location + beat_frames in ONE action → one PUT patch, never split."""
    return LedFxEffectParamAction(
        category="Matrix",
        ramp_ms=0,
        params=[
            EffectParamChange(param_label="Dance GIF", string_value=entry["path"]),
            EffectParamChange(param_label="Beat Frames", string_value=entry["beat_frames"]),
        ],
    )


def _big_burst(entry: dict, fallback_s: float) -> LedFxEffectParamAction:
    action = _style_params(entry)
    action.fallback_s = fallback_s
    return action


def _position(x: int, y: int) -> LedFxEffectParamAction:
    return LedFxEffectParamAction(
        category="Matrix",
        ramp_ms=400,
        params=[
            EffectParamChange(param_label="Dancer X", target_value=x),
            EffectParamChange(param_label="Dancer Y", target_value=y),
        ],
    )


def _toggle(label: str, action_word: str = "toggle") -> LedFxEffectParamAction:
    return LedFxEffectParamAction(
        category="Matrix",
        params=[EffectParamChange(param_label=label, toggle_action=action_word)],
    )


def _color(hex_color: str, ramp_ms: int = 400) -> LedFxEffectParamAction:
    return LedFxEffectParamAction(
        category="Matrix",
        ramp_ms=ramp_ms,
        params=[EffectParamChange(param_label="Dancer Color", string_value=hex_color)],
    )


def build_event(assets: dict, existing_id: str | None) -> MusicEvent:
    normal = {aid: e for aid, e in assets.items() if e.get("energy") == "normal"}
    big = {aid: e for aid, e in assets.items() if e.get("energy") == "big"}

    first_lane = MorphLane(
        name="First",
        alternatives=[
            MorphStepAction(
                name="Enter dancer",
                targets=[
                    MorphTarget(
                        scope=MATRIX_SCOPE,
                        aspect="effect",
                        absolute_value=AspectValue(effect_type="keybeat2d"),
                    )
                ],
            )
        ],
    )

    style_options = []
    for aid, entry in sorted(normal.items()):
        style_options.append(
            RandomOption(
                name=f"style: {entry.get('style', aid)}",
                weight=1.0,
                # Disco reads as high-energy; gate it off mellow sections.
                energy_floor=0.45 if entry.get("style") == "disco" else None,
                actions=[_style_params(entry)],
            )
        )
    rest_lane = MorphLane(
        name="Rest",
        alternatives=[
            RandomGroupAction(
                options=style_options
                + [
                    RandomOption(name="move left", actions=[_position(-30, 0)]),
                    RandomOption(name="move right", actions=[_position(30, 0)]),
                    RandomOption(name="center", actions=[_position(0, 0)]),
                    RandomOption(
                        name="half-beat groove",
                        energy_ceiling=0.45,
                        actions=[_toggle("Half Beat")],
                    ),
                    RandomOption(name="face flip", actions=[_toggle("Flip")]),
                    RandomOption(
                        name="recolor",
                        actions=[_color(DANCER_COLORS[1])],
                        weight=0.5,
                    ),
                ]
            )
        ],
    )

    big_options = []
    for aid, entry in sorted(big.items()):
        weight = 2.0 if entry.get("style") == "basic" else 1.0
        big_options.append(
            RandomOption(
                name=f"big move: {entry.get('style', aid)}",
                weight=weight,
                actions=[_big_burst(entry, fallback_s=7.0)],
            )
        )
    stretch_burst = LedFxEffectParamAction(
        category="Matrix",
        fallback_s=4.0,
        params=[
            EffectParamChange(param_label="Dancer Width", target_value=140),
            EffectParamChange(param_label="Dancer Height", target_value=130),
            EffectParamChange(param_label="Effect Brightness", target_value=1.8),
        ],
    )
    shape_lane = MorphLane(
        name="Shape",
        alternatives=[
            RandomGroupAction(
                options=big_options
                + [RandomOption(name="stretch burst", weight=1.0, actions=[stretch_burst])]
            )
        ],
    )

    color_lane = MorphLane(
        name="Color",
        alternatives=[
            RandomGroupAction(
                options=[
                    RandomOption(name=f"tint {c}", actions=[_color(c, ramp_ms=250)])
                    for c in DANCER_COLORS
                ]
            )
        ],
    )

    kwargs = {"id": existing_id} if existing_id else {}
    return MusicEvent(
        name=EVENT_NAME,
        event_type="scene_update",
        color="#ff2080",
        morph_lanes=[first_lane, rest_lane, shape_lane, color_lane],
        **kwargs,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-offline", action="store_true",
                        help="skip the live LedFX asset existence check")
    args = parser.parse_args()

    assets = _load_manifest()
    if not args.force_offline:
        _check_live_assets(assets)

    from services import profile_manager
    existing = next(
        (e for e in profile_manager.list_events() if e.name == EVENT_NAME), None
    )
    event = build_event(assets, existing.id if existing else None)
    profile_manager.save_event(event)
    verb = "updated" if existing else "created"
    print(f"{verb} scene_update event '{EVENT_NAME}' ({event.id})")
    print(f"  styles: {[e.get('style') for e in assets.values() if e.get('energy') == 'normal']}")
    print(f"  big moves: {[e.get('style') for e in assets.values() if e.get('energy') == 'big']}")


if __name__ == "__main__":
    main()
