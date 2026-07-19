"""Stick-figure skeleton renderer for LED-matrix GIF assets.

A Pose is a flat dict of segment angles (degrees) plus a hip offset, so poses
tween, compose (``{**a, **b}``) and mirror trivially. All limb angles are
ABSOLUTE, measured from straight-down (0°) rotating toward that side's
outward direction — 90° is horizontal out, 180° is straight up. The torso
angle is measured from straight-up (positive leans right). ``dx``/``dy``
offset the hip in units of figure height (positive dy = down).

Pose keys: torso, l_arm, r_arm, l_fore, r_fore, l_leg, r_leg, l_shin,
r_shin, dx, dy. Missing keys default to 0.

The named pose library lives in poses.json next to this module.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

POSES_FILE = Path(__file__).with_name("poses.json")

POSE_KEYS = [
    "torso",
    "l_arm", "r_arm", "l_fore", "r_fore",
    "l_leg", "r_leg", "l_shin", "r_shin",
    "dx", "dy",
]

# Segment lengths in units of figure height.
TORSO_LEN = 0.30
HEAD_RADIUS = 0.085
ARM_LEN = 0.16
FORE_LEN = 0.15
THIGH_LEN = 0.20
SHIN_LEN = 0.20


def load_poses() -> dict[str, dict]:
    return json.loads(POSES_FILE.read_text())


def mirror(pose: dict) -> dict:
    """Swap left/right limbs and flip the lean/offset."""
    out = dict(pose)
    for l_key, r_key in (
        ("l_arm", "r_arm"), ("l_fore", "r_fore"),
        ("l_leg", "r_leg"), ("l_shin", "r_shin"),
    ):
        out[l_key], out[r_key] = pose.get(r_key, 0), pose.get(l_key, 0)
    out["torso"] = -pose.get("torso", 0)
    out["dx"] = -pose.get("dx", 0)
    return out


def tween(pose_a: dict, pose_b: dict, t: float, ease: str = "cosine") -> dict:
    if ease == "cosine":
        t = (1 - math.cos(math.pi * t)) / 2
    return {
        key: pose_a.get(key, 0) * (1 - t) + pose_b.get(key, 0) * t
        for key in POSE_KEYS
    }


def _limb_dir(angle_deg: float, side: str) -> tuple[float, float]:
    """Unit vector for a limb angle: 0° = down, rotating outward per side."""
    rad = math.radians(angle_deg)
    x = math.sin(rad)
    if side == "l":
        x = -x
    return x, math.cos(rad)


def _joint_positions(pose: dict, height_px: float, cx: float, cy: float) -> dict:
    """Compute joint pixel positions. (cx, cy) is the neutral hip position."""
    h = height_px
    get = lambda key: pose.get(key, 0)

    hip = (cx + get("dx") * h, cy + get("dy") * h)

    torso_rad = math.radians(get("torso"))
    torso_dir = (math.sin(torso_rad), -math.cos(torso_rad))
    neck = (hip[0] + torso_dir[0] * TORSO_LEN * h, hip[1] + torso_dir[1] * TORSO_LEN * h)
    head_center = (
        neck[0] + torso_dir[0] * HEAD_RADIUS * h * 1.35,
        neck[1] + torso_dir[1] * HEAD_RADIUS * h * 1.35,
    )

    joints = {"hip": hip, "neck": neck, "head": head_center}
    for side in ("l", "r"):
        arm_dir = _limb_dir(get(f"{side}_arm"), side)
        elbow = (neck[0] + arm_dir[0] * ARM_LEN * h, neck[1] + arm_dir[1] * ARM_LEN * h)
        fore_dir = _limb_dir(get(f"{side}_fore"), side)
        hand = (elbow[0] + fore_dir[0] * FORE_LEN * h, elbow[1] + fore_dir[1] * FORE_LEN * h)
        leg_dir = _limb_dir(get(f"{side}_leg"), side)
        knee = (hip[0] + leg_dir[0] * THIGH_LEN * h, hip[1] + leg_dir[1] * THIGH_LEN * h)
        shin_dir = _limb_dir(get(f"{side}_shin"), side)
        foot = (knee[0] + shin_dir[0] * SHIN_LEN * h, knee[1] + shin_dir[1] * SHIN_LEN * h)
        joints[f"{side}_elbow"] = elbow
        joints[f"{side}_hand"] = hand
        joints[f"{side}_knee"] = knee
        joints[f"{side}_foot"] = foot
    return joints


def render_pose(
    pose: dict,
    width: int,
    height: int,
    stroke_px: float = 2.0,
    figure_height_px: float | None = None,
    color: tuple[int, int, int] = (255, 255, 255),
    supersample: int = 8,
) -> Image.Image:
    """Render one pose, white-on-black by default, anti-aliased via supersampling."""
    if figure_height_px is None:
        figure_height_px = height * 0.82

    ss = supersample
    h = figure_height_px * ss
    canvas = Image.new("RGB", (width * ss, height * ss), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Neutral hip: horizontally centered; legs (0.4h) reach ~2px above bottom.
    cx = width * ss / 2
    cy = height * ss - 2 * ss - (THIGH_LEN + SHIN_LEN) * h

    joints = _joint_positions(pose, h, cx, cy)
    stroke = max(1, round(stroke_px * ss))

    bones = [
        ("hip", "neck"),
        ("neck", "l_elbow"), ("l_elbow", "l_hand"),
        ("neck", "r_elbow"), ("r_elbow", "r_hand"),
        ("hip", "l_knee"), ("l_knee", "l_foot"),
        ("hip", "r_knee"), ("r_knee", "r_foot"),
    ]
    for start, end in bones:
        draw.line([joints[start], joints[end]], fill=color, width=stroke)
        for point in (joints[start], joints[end]):
            radius = stroke / 2
            draw.ellipse(
                [point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius],
                fill=color,
            )

    head_r = HEAD_RADIUS * h
    hx, hy = joints["head"]
    draw.ellipse([hx - head_r, hy - head_r, hx + head_r, hy + head_r], fill=color)

    return canvas.resize((width, height), Image.LANCZOS)


def resolve_pose(name: str, library: dict[str, dict] | None = None) -> dict:
    """Resolve a pose name from the library; a trailing ``!mirror`` mirrors it."""
    if library is None:
        library = load_poses()
    mirrored = name.endswith("!mirror")
    base = name[: -len("!mirror")] if mirrored else name
    if base not in library:
        raise KeyError(f"unknown pose '{base}'; have: {sorted(k for k in library if not k.startswith('_'))}")
    pose = {k: v for k, v in library[base].items() if k in POSE_KEYS}
    return mirror(pose) if mirrored else pose


def build_dance(
    key_pose_names: list[str],
    tweens_per_beat: int = 2,
    width: int = 72,
    height: int = 37,
    stroke_px: float = 2.0,
    color: tuple[int, int, int] = (255, 255, 255),
    library: dict[str, dict] | None = None,
) -> tuple[list[Image.Image], str]:
    """Render a looping dance: key poses land on beats, tween frames between.

    Returns (frames, beat_frames) where beat_frames is the keybeat2d-ready
    string of the frame indices the key poses landed on — computed, so it can
    never drift from the frames.
    """
    if library is None:
        library = load_poses()
    keys = [resolve_pose(name, library) for name in key_pose_names]
    frames: list[Image.Image] = []
    beat_indices: list[int] = []
    step = 1 + tweens_per_beat
    for i, pose in enumerate(keys):
        next_pose = keys[(i + 1) % len(keys)]
        beat_indices.append(i * step)
        frames.append(render_pose(pose, width, height, stroke_px, color=color))
        for j in range(1, step):
            frames.append(
                render_pose(
                    tween(pose, next_pose, j / step),
                    width, height, stroke_px, color=color,
                )
            )
    return frames, " ".join(str(i) for i in beat_indices)
