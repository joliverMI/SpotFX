"""Dance library for the Dancer effect — pure data + pure math, no LedFX
imports (also consumed headless by SpotFX tools/dancesmith preview tooling).

ADDING A NEW DANCE (the 5-minute version — full guide in SpotFX
tools/dancesmith/README.md):
  1. Add named poses to POSES below (angle convention next paragraph).
  2. Add a DANCES entry: partner mode, tempo, ease, energy tier, moves.
  3. Run  python3 -m tools.dancesmith preview --dance <name>  from the
     SpotFX repo to eyeball every move through the crystal mask, then
     python3 -m tools.dancesmith validate  (also runs at effect init).
  4. Register the new name in SpotFX config/effect_params.json
     ("Dance Type" options) so morphs/scenes can select it.

POSE FORMAT (same skeleton + conventions as SpotFX tools/gifsmith): a pose
is a flat dict of ABSOLUTE segment angles in degrees plus a hip offset.
Limb angles are measured from straight-down (0°), rotating toward that
side's OUTWARD direction — 90° = horizontal out, 180° = straight up,
negative = inward across the body. Forearm/shin angles are absolute too
(chained from the elbow/knee position, not relative to the parent bone).
The torso angle is from straight-up (positive leans right). dx/dy offset
the hip in units of figure height (positive dy = down). Missing keys = 0.

MOVE FORMAT — a move is one continuous phrase; each key pose lands on a
beat (or every `tempo` beats):
  keys          list of pose names; "<name>!m" mirrors a pose
  accent        joint name bursts fly from (default: chest — radiates)
  weight        selection weight (default 1.0)
  flourish      True = always burst on the move's last key
  spin          degrees the whole figure rotates over the move (pirouette)
  partner_spin  extra spin applied only to the partner (underarm turn)
  tilt          per-key figure tilt degrees (floor moves like the worm);
                scalar = same tilt on every key
  travel        net horizontal drift over the move, in figure heights
                (mirrored partner drifts the opposite way)
  swap          True = the two dancers exchange slots over this move
  partner_keys  explicit pose list for the partner in "together" dances
                (default: mirrored keys)
  next          allowed follow-up move names (staged moves, e.g. the worm
                must get down before it wiggles); omit = any move
  ease          per-move easing override

DANCE FORMAT:
  partner  "mirror"   partner dances the mirror image (tai chi, robot…)
           "sync"     partner dances the same steps side by side (cowboy)
           "together" partner uses partner_keys/mirror + close spacing
  tempo    beats per key pose (tai chi = 2, everything else = 1)
  ease     default easing: cosine (fluid) | sharp (late snap) | linear
  energy   "calm" | "mid" | "high" — SpotFX intensity bands key off this
  idle     pose held (with a slow sway) when the music goes quiet
  bounce   per-beat vertical bob in figure heights (musicality)
"""

from __future__ import annotations

import math

import numpy as np

# ── skeleton (identical proportions to tools/gifsmith/skeleton.py) ──────

POSE_KEYS = (
    "torso",
    "l_arm", "r_arm", "l_fore", "r_fore",
    "l_leg", "r_leg", "l_shin", "r_shin",
    "dx", "dy",
    # skeleton v2 articulation (older poses simply omit these = 0):
    "spine",  # upper-spine bend ADDED to torso (S-curves, chest pops)
    "neck",   # head tilt added to torso+spine (nods, head snaps)
    "yaw",    # facing, degrees about the vertical axis: 0 = to the
              # viewer, 90 = profile — rendered as fake-3D foreshortening
    "shoulders",  # shoulder-line tilt, degrees (+ = right shoulder up):
                  # shrugs, sass, shoulder isolations
)
_KI = {k: i for i, k in enumerate(POSE_KEYS)}
I_SPINE, I_NECK, I_YAW = _KI["spine"], _KI["neck"], _KI["yaw"]
I_SHO = _KI["shoulders"]

LOWER_TORSO = 0.17
UPPER_TORSO = 0.13   # lower+upper = the old 0.30 torso
SHOULDER_W = 0.055   # half shoulder width — arms hang from real shoulders
HIP_W = 0.04         # half hip width — legs from real hip corners
NECK_LEN = 0.055
HEAD_RADIUS = 0.085
ARM_LEN = 0.16
FORE_LEN = 0.15
THIGH_LEN = 0.20
SHIN_LEN = 0.20
LEG_REACH = THIGH_LEN + SHIN_LEN  # neutral hip height above the feet

# FK output joint order ("neck" = the shoulder line where arms attach)
JOINTS = (
    "hip", "chest", "neck", "head",
    "l_elbow", "l_hand", "r_elbow", "r_hand",
    "l_knee", "l_foot", "r_knee", "r_foot",
    "l_sho", "r_sho", "l_hip", "r_hip",
)
_JI = {name: i for i, name in enumerate(JOINTS)}
J_HIP, J_CHEST, J_NECK, J_HEAD = 0, 1, 2, 3

# bone segments as (joint_a, joint_b) indices — arms hang from a real
# shoulder bar, legs from hip corners (wider, more human silhouette that
# collapses correctly when the figure yaws)
BONES = (
    (0, 1), (1, 2),     # hip → chest → neck base (two-segment spine)
    (2, 3),             # neck line up to the head
    (12, 13),           # shoulder bar
    (12, 4), (4, 5),    # l_sho → l_elbow → l_hand
    (13, 6), (6, 7),    # r_sho → r_elbow → r_hand
    (14, 8), (8, 9),    # l_hip → l_knee → l_foot
    (15, 10), (10, 11),  # r_hip → r_knee → r_foot
)

# joint mirror pairs (partner accents) and parents (burst directions)
MIRROR_J = {
    4: 6, 6: 4, 5: 7, 7: 5, 8: 10, 10: 8, 9: 11, 11: 9,
    12: 13, 13: 12, 14: 15, 15: 14,
}
PARENT_J = {
    1: 0, 2: 1, 3: 2,
    4: 12, 5: 4, 6: 13, 7: 6,
    8: 14, 9: 8, 10: 15, 11: 10,
    12: 2, 13: 2, 14: 0, 15: 0,
}


def pose_vec(pose: dict) -> np.ndarray:
    """Pose dict → float32 vector in POSE_KEYS order."""
    v = np.zeros(len(POSE_KEYS), dtype=np.float32)
    for k, val in pose.items():
        i = _KI.get(k)
        if i is not None:
            v[i] = val
    return v


def mirror_vec(v: np.ndarray) -> np.ndarray:
    """Swap left/right limbs, flip the lean, offset, spine, neck, yaw."""
    out = v.copy()
    for a, b in ((1, 2), (3, 4), (5, 6), (7, 8)):
        out[a], out[b] = v[b], v[a]
    out[0] = -v[0]
    out[9] = -v[9]
    out[I_SPINE] = -v[I_SPINE]
    out[I_NECK] = -v[I_NECK]
    out[I_YAW] = -v[I_YAW]
    out[I_SHO] = -v[I_SHO]
    return out


def joint_xy(v: np.ndarray, h: float, yaw_extra: float = 0.0) -> np.ndarray:
    """Forward kinematics: pose vector → (12, 2) joint positions in a local
    frame whose origin is the NEUTRAL hip (y down, units = pixels for a
    figure `h` pixels tall). Two-segment spine + neck; `yaw` (pose key +
    yaw_extra, degrees) foreshortens x about the hip's vertical axis for
    fake-3D turns and spins."""
    out = np.empty((len(JOINTS), 2), dtype=np.float32)
    hip_x = float(v[9]) * h
    hip_y = float(v[10]) * h
    out[0] = (hip_x, hip_y)

    a1 = math.radians(float(v[0]))
    d1 = (math.sin(a1), -math.cos(a1))
    chest = (
        hip_x + d1[0] * LOWER_TORSO * h,
        hip_y + d1[1] * LOWER_TORSO * h,
    )
    out[1] = chest
    a2 = math.radians(float(v[0]) + float(v[I_SPINE]))
    d2 = (math.sin(a2), -math.cos(a2))
    neck = (
        chest[0] + d2[0] * UPPER_TORSO * h,
        chest[1] + d2[1] * UPPER_TORSO * h,
    )
    out[2] = neck
    a3 = math.radians(
        float(v[0]) + float(v[I_SPINE]) + float(v[I_NECK])
    )
    d3 = (math.sin(a3), -math.cos(a3))
    head_off = (NECK_LEN + HEAD_RADIUS * 0.9) * h
    out[3] = (neck[0] + d3[0] * head_off, neck[1] + d3[1] * head_off)

    # shoulder bar: perpendicular to the upper spine, tilted by the
    # `shoulders` key (+ = right shoulder up)
    sho = math.radians(float(v[0]) + float(v[I_SPINE]) + float(v[I_SHO]))
    sperp = (math.cos(sho), math.sin(sho))
    out[12] = (
        neck[0] - sperp[0] * SHOULDER_W * h,
        neck[1] - sperp[1] * SHOULDER_W * h,
    )
    out[13] = (
        neck[0] + sperp[0] * SHOULDER_W * h,
        neck[1] + sperp[1] * SHOULDER_W * h,
    )
    # hip corners: perpendicular to the lower spine
    hperp = (math.cos(a1), math.sin(a1))
    out[14] = (hip_x - hperp[0] * HIP_W * h, hip_y - hperp[1] * HIP_W * h)
    out[15] = (hip_x + hperp[0] * HIP_W * h, hip_y + hperp[1] * HIP_W * h)

    for side, sgn, ai in (("l", -1.0, 1), ("r", 1.0, 2)):
        arm = math.radians(float(v[ai]))
        fore = math.radians(float(v[ai + 2]))
        leg = math.radians(float(v[ai + 4]))
        shin = math.radians(float(v[ai + 6]))
        sho_pt = out[12] if side == "l" else out[13]
        hip_pt = out[14] if side == "l" else out[15]
        ex = sho_pt[0] + sgn * math.sin(arm) * ARM_LEN * h
        ey = sho_pt[1] + math.cos(arm) * ARM_LEN * h
        hx = ex + sgn * math.sin(fore) * FORE_LEN * h
        hy = ey + math.cos(fore) * FORE_LEN * h
        kx = hip_pt[0] + sgn * math.sin(leg) * THIGH_LEN * h
        ky = hip_pt[1] + math.cos(leg) * THIGH_LEN * h
        fx = kx + sgn * math.sin(shin) * SHIN_LEN * h
        fy = ky + math.cos(shin) * SHIN_LEN * h
        base = 4 if side == "l" else 6
        out[base] = (ex, ey)
        out[base + 1] = (hx, hy)
        out[base + 4] = (kx, ky)
        out[base + 5] = (fx, fy)

    yaw = float(v[I_YAW]) + yaw_extra
    if abs(yaw) > 0.01:
        # fake 3D: foreshorten x about the hip's vertical axis; cos sweeps
        # 1 → 0 (profile) → -1 (seen from behind = mirrored)
        c = math.cos(math.radians(yaw))
        out[:, 0] = hip_x + (out[:, 0] - hip_x) * c
    return out


# ── easing ───────────────────────────────────────────────────────────────

def _ease_cosine(t: float) -> float:
    return (1.0 - math.cos(math.pi * t)) / 2.0


def _ease_sharp(t: float) -> float:
    """Hold, then snap late in the beat — staccato (robot, tango)."""
    if t < 0.55:
        return 0.0
    return _ease_cosine((t - 0.55) / 0.45)


def _ease_linear(t: float) -> float:
    return t


def _ease_flow(t: float) -> float:
    """Cosine attack with a little follow-through: the limb overshoots
    the pose (~7%) and settles — motion reads alive instead of stopping
    dead on every beat."""
    if t <= 0.5:
        return (1.0 - math.cos(math.pi * t)) / 2.0
    u = (t - 0.5) * 2.0
    k = 1.4
    b = 1.0 + (k + 1.0) * (u - 1.0) ** 3 + k * (u - 1.0) ** 2
    return 0.5 + 0.5 * b


def _ease_snap(t: float) -> float:
    """Fast attack with a little overshoot, then settle — the limb POPS
    to the pose right on the beat (moonwalk knee lifts)."""
    k = 1.6
    u = t - 1.0
    return 1.0 + (k + 1.0) * u * u * u + k * u * u


EASES = {
    "cosine": _ease_cosine,
    "sharp": _ease_sharp,
    "linear": _ease_linear,
    "flow": _ease_flow,
    "snap": _ease_snap,
}

# always-on groove amplitude per energy tier (beat-locked secondary
# motion layered over the key poses — see dancer.py _apply_groove)
GROOVE_BY_ENERGY = {"calm": 0.7, "mid": 1.0, "high": 1.35}

# choreography exaggeration per energy tier: rendered poses are pushed
# AWAY from the dance's neutral stance by this factor (bigger arcs,
# deeper bends, wider steps) — yaw is exempt (facing must stay exact)
EXPRESS_BY_ENERGY = {"calm": 1.12, "mid": 1.24, "high": 1.34}


# ── pose library ─────────────────────────────────────────────────────────
# Gifsmith originals first (same numbers → same silhouette), then per-dance
# vocabulary, then choreography poses used by the stunt layer.

POSES: dict[str, dict] = {
    # — shared / gifsmith heritage —
    "idle": {"l_arm": 12, "r_arm": 12, "l_fore": 8, "r_fore": 8,
             "l_leg": 10, "r_leg": 10, "l_shin": 5, "r_shin": 5},
    "stand_tall": {"l_arm": 8, "r_arm": 8, "l_fore": 5, "r_fore": 5,
                   "l_leg": 6, "r_leg": 6, "l_shin": 3, "r_shin": 3},
    "sway_r": {"torso": 12, "dx": 0.05, "r_arm": 40, "r_fore": 30,
               "l_arm": 15, "l_fore": 10, "r_leg": 18, "l_leg": 4,
               "r_shin": 8, "l_shin": 2},
    "arms_up": {"l_arm": 165, "r_arm": 165, "l_fore": 175, "r_fore": 175,
                "l_leg": 12, "r_leg": 12, "l_shin": 6, "r_shin": 6},
    "clap": {"l_arm": 60, "r_arm": 60, "l_fore": -35, "r_fore": -35,
             "l_leg": 10, "r_leg": 10, "l_shin": 5, "r_shin": 5},
    "star_jump": {"dy": -0.12, "l_arm": 135, "r_arm": 135, "l_fore": 140,
                  "r_fore": 140, "l_leg": 40, "r_leg": 40, "l_shin": 42,
                  "r_shin": 42},
    "jump_tuck": {"dy": -0.18, "l_arm": 168, "r_arm": 168, "l_fore": 178,
                  "r_fore": 178, "l_leg": 55, "r_leg": 55, "l_shin": 100,
                  "r_shin": 100},
    "deep_squat": {"dy": 0.16, "l_leg": 70, "r_leg": 70, "l_shin": 0,
                   "r_shin": 0, "l_arm": 88, "r_arm": 88, "l_fore": 92,
                   "r_fore": 92},

    # — tai chi —
    "tai_idle": {"l_arm": 20, "r_arm": 20, "l_fore": -12, "r_fore": -12,
                 "l_leg": 16, "r_leg": 16, "l_shin": 4, "r_shin": 4,
                 "dy": 0.04},
    "cloud_a": {"torso": 6, "spine": 4, "neck": -4, "dx": 0.05,
                "dy": 0.05,
                "r_arm": 95, "r_fore": 120, "l_arm": 35, "l_fore": -25,
                "r_leg": 24, "l_leg": 8, "r_shin": 10, "l_shin": 2},
    "cloud_b": {"torso": -4, "spine": -3, "shoulders": -4,
                "dx": -0.02, "dy": 0.06,
                "r_arm": 60, "r_fore": 20, "l_arm": 70, "l_fore": 95,
                "r_leg": 12, "l_leg": 18, "r_shin": 4, "l_shin": 8},
    "gather_ball": {"dy": 0.07, "l_arm": 45, "r_arm": 55, "l_fore": -40,
                    "r_fore": -55, "l_leg": 20, "r_leg": 20, "l_shin": 2,
                    "r_shin": 2},
    "push_a": {"torso": -6, "dx": -0.04, "dy": 0.06,
               "l_arm": 55, "r_arm": 55, "l_fore": 35, "r_fore": 35,
               "l_leg": 24, "r_leg": 10, "l_shin": 10, "r_shin": 2},
    "push_b": {"torso": 8, "dx": 0.06, "dy": 0.04,
               "l_arm": 75, "r_arm": 75, "l_fore": 70, "r_fore": 70,
               "l_leg": 8, "r_leg": 26, "l_shin": 2, "r_shin": 12},
    "whip": {"torso": 5, "dx": 0.04, "dy": 0.08,
             "r_arm": 92, "r_fore": 95, "l_arm": 65, "l_fore": 25,
             "r_leg": 30, "l_leg": 14, "r_shin": 12, "l_shin": 4},
    "rooster": {"dy": 0.01, "r_arm": 120, "r_fore": 150, "l_arm": 22,
                "l_fore": -15, "r_leg": 62, "r_shin": -55, "l_leg": 6,
                "l_shin": 3},
    "crane_open": {"torso": -3, "dy": 0.03,
                   "l_arm": 110, "r_arm": 110, "l_fore": 125, "r_fore": 125,
                   "l_leg": 14, "r_leg": 14, "l_shin": 5, "r_shin": 5},
    "snake_low": {"torso": 16, "spine": 10, "neck": -8,
                  "dx": 0.10, "dy": 0.14,
                  "r_arm": 80, "r_fore": 60, "l_arm": 30, "l_fore": -20,
                  "r_leg": 72, "r_shin": 25, "l_leg": 16, "l_shin": -30},

    # — ballet —
    "ballet_first": {"l_arm": 25, "r_arm": 25, "l_fore": -28, "r_fore": -28,
                     "l_leg": 5, "r_leg": 5, "l_shin": 8, "r_shin": 8},
    "plie": {"dy": 0.09, "l_arm": 32, "r_arm": 32, "l_fore": -32,
             "r_fore": -32, "l_leg": 42, "r_leg": 42, "l_shin": -18,
             "r_shin": -18},
    "releve": {"dy": -0.03, "l_arm": 138, "r_arm": 138, "l_fore": 158,
               "r_fore": 158, "l_leg": 5, "r_leg": 5, "l_shin": 2,
               "r_shin": 2},
    "arabesque": {"torso": -14, "spine": -9, "neck": -6,
                  "dx": -0.04, "dy": 0.02,
                  "l_arm": 95, "l_fore": 92, "r_arm": 45, "r_fore": 60,
                  "l_leg": 8, "l_shin": 4, "r_leg": 88, "r_shin": 96},
    "passe": {"l_arm": 100, "r_arm": 100, "l_fore": 130, "r_fore": 130,
              "l_leg": 6, "l_shin": 3, "r_leg": 55, "r_shin": -62},
    "grand_jete": {"dy": -0.16, "l_arm": 92, "r_arm": 92, "l_fore": 96,
                   "r_fore": 96, "l_leg": 72, "r_leg": 72, "l_shin": 76,
                   "r_shin": 76},
    "pirouette_pose": {"l_arm": 55, "r_arm": 55, "l_fore": -48,
                       "r_fore": -48, "l_leg": 5, "l_shin": 2,
                       "r_leg": 52, "r_shin": -58},
    "bow": {"torso": 32, "dx": 0.03, "l_arm": 40, "r_arm": 15,
            "l_fore": 65, "r_fore": -25, "l_leg": 8, "r_leg": 16,
            "l_shin": 4, "r_shin": 8},
    "lift_hold": {"l_arm": 155, "r_arm": 155, "l_fore": 170, "r_fore": 170,
                  "l_leg": 22, "r_leg": 22, "l_shin": 6, "r_shin": 6,
                  "dy": 0.02},
    "lift_fly": {"dy": -0.30, "l_arm": 130, "r_arm": 130, "l_fore": 140,
                 "r_fore": 140, "l_leg": 30, "r_leg": 30, "l_shin": 34,
                 "r_shin": 34},

    # — cowboy line dance —
    "cow_idle": {"l_arm": 28, "r_arm": 28, "l_fore": -38, "r_fore": -38,
                 "l_leg": 12, "r_leg": 12, "l_shin": 5, "r_shin": 5},
    "grapevine_a": {"dx": 0.08, "torso": 5, "yaw": 22,
                    "l_leg": -30, "r_leg": 42,
                    "l_shin": -20, "r_shin": 20, "l_arm": 35, "r_arm": 45,
                    "l_fore": -30, "r_fore": 15},
    "grapevine_b": {"dx": 0.16, "l_leg": 22, "r_leg": 22, "l_shin": 10,
                    "r_shin": 10, "l_arm": 30, "r_arm": 50, "l_fore": -40,
                    "r_fore": 25},
    "heel_dig": {"r_leg": 44, "r_shin": -30, "l_leg": 8, "l_shin": 4,
                 "l_arm": 30, "r_arm": 78, "l_fore": -38, "r_fore": 48,
                 "torso": -6, "shoulders": 6},
    "stomp_up": {"r_leg": 38, "r_shin": 20, "l_leg": 8, "l_shin": 4,
                 "l_arm": 35, "r_arm": 50, "l_fore": -30, "r_fore": 20,
                 "dy": -0.02},
    "stomp_down": {"dy": 0.05, "l_leg": 14, "r_leg": 14, "l_shin": 6,
                   "r_shin": 6, "l_arm": 30, "r_arm": 30, "l_fore": -35,
                   "r_fore": -35, "torso": 2},
    "lasso_a": {"l_arm": 32, "l_fore": -35, "r_arm": 130, "r_fore": 95,
                "l_leg": 12, "r_leg": 20, "l_shin": 5, "r_shin": 9,
                "torso": 4, "dx": 0.03},
    "lasso_b": {"l_arm": 32, "l_fore": -35, "r_arm": 135, "r_fore": 172,
                "l_leg": 12, "r_leg": 20, "l_shin": 5, "r_shin": 9,
                "torso": -2},
    "lasso_c": {"l_arm": 32, "l_fore": -35, "r_arm": 130, "r_fore": -125,
                "l_leg": 12, "r_leg": 20, "l_shin": 5, "r_shin": 9,
                "torso": 4, "dx": -0.03},
    "lasso_d": {"l_arm": 32, "l_fore": -35, "r_arm": 125, "r_fore": -35,
                "l_leg": 12, "r_leg": 20, "l_shin": 5, "r_shin": 9,
                "torso": 2},
    "kick_bc": {"torso": -8, "r_leg": 48, "r_shin": 44, "l_leg": 6,
                "l_shin": 3, "l_arm": 45, "r_arm": 25, "l_fore": 20,
                "r_fore": -30},
    "scoot": {"dy": -0.07, "l_leg": 26, "r_leg": 26, "l_shin": 30,
              "r_shin": 30, "l_arm": 40, "r_arm": 40, "l_fore": -20,
              "r_fore": -20, "torso": 6},

    # — robot —
    "robot_idle": {"l_arm": 18, "r_arm": 18, "l_fore": 90, "r_fore": 90,
                   "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4},
    "robo_r_up": {"l_arm": 18, "l_fore": 90, "r_arm": 90, "r_fore": 180,
                  "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4},
    "robo_flat": {"l_arm": 90, "r_arm": 90, "l_fore": 90, "r_fore": 90,
                  "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4},
    "robo_lean": {"torso": 15, "dx": 0.05, "l_arm": 18, "r_arm": 18,
                  "l_fore": 90, "r_fore": 90, "l_leg": 4, "r_leg": 24,
                  "l_shin": 2, "r_shin": 10},
    "robo_march": {"r_leg": 44, "r_shin": 42, "l_leg": 6, "l_shin": 3,
                   "l_arm": 45, "l_fore": 130, "r_arm": 18, "r_fore": 90},
    "robo_low": {"dy": 0.09, "l_leg": 48, "r_leg": 48, "l_shin": -12,
                 "r_shin": -12, "l_arm": 90, "r_arm": 90, "l_fore": 92,
                 "r_fore": 92},
    "robo_salute": {"l_arm": 18, "l_fore": 90, "r_arm": 110, "r_fore": -160,
                    "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4,
                    "torso": -3},
    "robo_wave_l": {"l_arm": 90, "l_fore": 90, "r_arm": 14, "r_fore": 20,
                    "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4},

    # — moonwalk —
    "mj_idle": {"torso": 4, "l_arm": 16, "r_arm": 24, "l_fore": 6,
                "r_fore": 18, "l_leg": 9, "r_leg": 13, "l_shin": 4,
                "r_shin": 6},
    "mj_glide_a": {"torso": 9, "spine": 4, "yaw": 40, "dx": 0.05,
                   "neck": -10, "shoulders": 7, "dy": 0.045,
                   "l_arm": -30, "l_fore": -38, "r_arm": -22,
                   "r_fore": -28,
                   "r_leg": 82, "r_shin": -20,
                   "l_leg": 4, "l_shin": 8},
    "mj_glide_b": {"torso": 9, "spine": -4, "yaw": 40, "dx": -0.05,
                   "neck": 8, "shoulders": -7, "dy": 0.045,
                   "r_arm": 30, "r_fore": 38, "l_arm": 22, "l_fore": 28,
                   "l_leg": -82, "l_shin": 16,
                   "r_leg": -2, "r_shin": -8},
    "mj_lean": {"torso": -27, "spine": -8, "neck": -14,
                "shoulders": -6,
                "dx": -0.06, "l_arm": 14, "r_arm": 14,
                "l_fore": 4, "r_fore": 4, "l_leg": 8, "r_leg": 30,
                "l_shin": 4, "r_shin": 14},
    "mj_toe": {"dy": -0.08, "l_leg": 10, "r_leg": 10, "l_shin": -22,
               "r_shin": -22, "l_arm": 65, "r_arm": 25, "l_fore": -45,
               "r_fore": 60, "torso": -4, "neck": -5},
    "mj_spin": {"l_arm": -22, "r_arm": -22, "l_fore": -62, "r_fore": -62,
                "l_leg": 6, "r_leg": 6, "l_shin": 3, "r_shin": 3},
    "mj_kick": {"torso": -6, "yaw": 15, "dy": -0.02, "neck": -8,
                "l_leg": 6, "l_shin": 3, "r_leg": 56, "r_shin": 62,
                "l_arm": 72, "l_fore": 82, "r_arm": -24, "r_fore": -36},
    "mj_crotch": {"dy": 0.03, "l_leg": 18, "r_leg": 18, "l_shin": -22,
                  "r_shin": -22, "r_arm": 8, "r_fore": -32,
                  "l_arm": 132, "l_fore": 156, "torso": -6, "neck": 10,
                  "shoulders": -8},
    "mj_smooth_l": {"dx": -0.11, "torso": -13, "yaw": -18, "neck": -10,
                    "l_leg": 44, "l_shin": 22, "r_leg": 8, "r_shin": 4,
                    "l_arm": 42, "l_fore": -46, "r_arm": 20,
                    "r_fore": 8, "shoulders": -7},
    "mj_thriller_a": {"l_arm": 78, "r_arm": 96, "l_fore": 62,
                      "r_fore": 88, "torso": 8, "spine": -9,
                      "shoulders": 13, "neck": 12, "yaw": 10,
                      "l_leg": 22, "r_leg": 10, "l_shin": 9,
                      "r_shin": 4, "dy": 0.03},
    "mj_point_up": {"r_arm": 146, "r_fore": 158, "l_arm": 20,
                    "l_fore": -28, "torso": -6, "spine": -4, "dx": 0.05,
                    "l_leg": 24, "r_leg": 8, "l_shin": 10,
                    "r_shin": -18, "neck": 6, "shoulders": -8},

    # — floss —  (both arms swing to one side; the crossing hand pokes out
    # PAST the torso at a steeper angle so it never hides behind the body)
    "floss_l": {"dx": 0.06, "torso": -6, "shoulders": -10, "neck": 4,
                "l_arm": 55, "l_fore": 68, "r_arm": -30, "r_fore": -78,
                "l_leg": 12, "r_leg": 12, "l_shin": 5, "r_shin": 5},
    "floss_l_wide": {"dx": 0.10, "torso": -9,
                     "l_arm": 72, "l_fore": 84, "r_arm": -38, "r_fore": -88,
                     "l_leg": 14, "r_leg": 10, "l_shin": 6, "r_shin": 4},
    "floss_low_l": {"dx": 0.06, "dy": 0.06, "torso": -6,
                    "l_arm": 55, "l_fore": 68, "r_arm": -30, "r_fore": -78,
                    "l_leg": 28, "r_leg": 28, "l_shin": -8, "r_shin": -8},

    # — the worm —
    "crouch_prep": {"dy": 0.14, "torso": 22, "l_leg": 55, "r_leg": 55,
                    "l_shin": -15, "r_shin": -15, "l_arm": 55, "r_arm": 55,
                    "l_fore": 45, "r_fore": 45},
    "worm_flat": {"torso": 8, "l_arm": 100, "r_arm": 100, "l_fore": 110,
                  "r_fore": 110, "l_leg": 10, "r_leg": 10, "l_shin": 5,
                  "r_shin": 5, "dy": 0.10},
    "worm_a": {"torso": 26, "spine": -30, "neck": 14, "dy": 0.12,
               "l_arm": 110, "r_arm": 110,
               "l_fore": 95, "r_fore": 95, "l_leg": 6, "r_leg": 6,
               "l_shin": 20, "r_shin": 20},
    "worm_b": {"torso": -10, "spine": 26, "neck": -10, "dy": 0.07,
               "l_arm": 95, "r_arm": 95,
               "l_fore": 120, "r_fore": 120, "l_leg": 24, "r_leg": 24,
               "l_shin": -6, "r_shin": -6},
    "worm_c": {"torso": -24, "spine": 30, "neck": -12, "dy": 0.11,
               "l_arm": 85, "r_arm": 85,
               "l_fore": 100, "r_fore": 100, "l_leg": 12, "r_leg": 12,
               "l_shin": 26, "r_shin": 26},

    # — hip hop —
    "hh_idle": {"torso": 2, "l_arm": 20, "r_arm": 20, "l_fore": 12,
                "r_fore": 12, "l_leg": 14, "r_leg": 14, "l_shin": 6,
                "r_shin": 6},
    "hh_low": {"dy": 0.07, "l_leg": 30, "r_leg": 30, "l_shin": -4,
               "r_shin": -4, "l_arm": 26, "r_arm": 26, "l_fore": 18,
               "r_fore": 18, "torso": 4, "shoulders": 7, "neck": 5},
    "top_rock_r": {"torso": 9, "spine": -5, "shoulders": -9,
                   "dx": 0.04, "r_leg": -16, "r_shin": -10,
                   "l_leg": 22, "l_shin": 10, "l_arm": 72, "l_fore": 45,
                   "r_arm": 22, "r_fore": 10},
    "arm_cross": {"l_arm": -28, "r_arm": -28, "l_fore": -58, "r_fore": -58,
                  "l_leg": 16, "r_leg": 16, "l_shin": 7, "r_shin": 7,
                  "torso": -3},
    "chest_pop": {"torso": -4, "spine": -20, "neck": 10, "dx": -0.02,
                  "l_arm": 38, "r_arm": 38,
                  "l_fore": 12, "r_fore": 12, "l_leg": 12, "r_leg": 18,
                  "l_shin": 5, "r_shin": 8},
    "raise_roof": {"l_arm": 118, "r_arm": 118, "l_fore": 162, "r_fore": 162,
                   "l_leg": 16, "r_leg": 16, "l_shin": 7, "r_shin": 7,
                   "dy": 0.02},
    "raise_roof_b": {"l_arm": 112, "r_arm": 112, "l_fore": 128, "r_fore": 128,
                     "l_leg": 20, "r_leg": 20, "l_shin": 9, "r_shin": 9,
                     "dy": 0.05},
    "skate_r": {"torso": 10, "dx": 0.06, "r_leg": 30, "r_shin": 22,
                "l_leg": 6, "l_shin": 3, "l_arm": 48, "l_fore": 25,
                "r_arm": -15, "r_fore": -32},
    "freeze_pose": {"torso": -10, "spine": -6, "neck": 12,
                    "dx": -0.03, "r_arm": 138, "r_fore": 155,
                    "l_arm": 42, "l_fore": -35, "l_leg": 32, "r_leg": 32,
                    "l_shin": -10, "r_shin": -10, "dy": 0.06},

    # — salsa —
    "salsa_idle": {"dx": 0.02, "torso": 2, "l_arm": 48, "r_arm": 48,
                   "l_fore": 28, "r_fore": 28, "l_leg": 10, "r_leg": 10,
                   "l_shin": 5, "r_shin": 5},
    "salsa_step": {"dx": -0.09, "dy": 0.03, "torso": -5, "spine": 5,
                   "r_leg": 28, "r_shin": 14,
                   "l_leg": 8, "l_shin": -12, "l_arm": 52, "r_arm": 42,
                   "l_fore": 34, "r_fore": 18},
    "hip_roll_r": {"dx": 0.14, "dy": 0.04, "torso": -10, "spine": 14,
                   "neck": -4, "l_arm": 52, "r_arm": 38,
                   "l_fore": 32, "r_fore": 12, "l_leg": 18, "r_leg": 8,
                   "l_shin": -20, "r_shin": 4},
    "cross_mid": {"torso": 4, "l_arm": 60, "r_arm": 60, "l_fore": 45,
                  "r_fore": 45, "l_leg": 24, "r_leg": 24, "l_shin": 12,
                  "r_shin": 12, "dy": 0.02},
    "dip_lead": {"torso": 14, "dx": 0.05, "dy": 0.05, "l_leg": 12,
                 "r_leg": 44, "l_shin": 5, "r_shin": 20, "l_arm": 70,
                 "r_arm": 55, "l_fore": 55, "r_fore": 30},
    "dip_follow": {"torso": -48, "dx": -0.08, "dy": 0.10, "l_leg": 24,
                   "r_leg": 58, "l_shin": 10, "r_shin": 66, "l_arm": 130,
                   "l_fore": 150, "r_arm": 55, "r_fore": 35},
    "shimmy_a": {"l_arm": 82, "r_arm": 82, "l_fore": 74, "r_fore": 74,
                 "l_leg": 14, "r_leg": 14, "l_shin": 6, "r_shin": 6,
                 "torso": -3, "shoulders": 12},
    "shimmy_b": {"l_arm": 78, "r_arm": 86, "l_fore": 62, "r_fore": 86,
                 "l_leg": 14, "r_leg": 14, "l_shin": 6, "r_shin": 6,
                 "torso": 3, "shoulders": -12},
    "turn_lead": {"r_arm": 148, "r_fore": 168, "l_arm": 40, "l_fore": 20,
                  "l_leg": 12, "r_leg": 12, "l_shin": 5, "r_shin": 5},

    # — tango —
    "tango_frame": {"torso": 2, "l_arm": 86, "l_fore": 72, "r_arm": 30,
                    "r_fore": -42, "l_leg": 8, "r_leg": 8, "l_shin": 4,
                    "r_shin": 4},
    "tango_walk": {"torso": 5, "yaw": 28, "dx": 0.03,
                   "l_arm": 86, "l_fore": 72,
                   "r_arm": 30, "r_fore": -42, "r_leg": 30, "r_shin": 16,
                   "l_leg": 6, "l_shin": 3},
    "corte": {"torso": 18, "spine": 8, "dx": 0.07, "dy": 0.12,
              "l_arm": 82,
              "l_fore": 66, "r_arm": 35, "r_fore": -35, "l_leg": 8,
              "r_leg": 60, "l_shin": 5, "r_shin": 30},
    "gancho": {"torso": 6, "spine": 6, "shoulders": -5,
               "l_arm": 86, "l_fore": 72, "r_arm": 30,
               "r_fore": -42, "l_leg": 8, "l_shin": 4, "r_leg": 52,
               "r_shin": -118},
    "flick": {"torso": -4, "l_arm": 86, "l_fore": 72, "r_arm": 30,
              "r_fore": -42, "l_leg": 6, "l_shin": 3, "r_leg": 22,
              "r_shin": 62},
    "head_snap": {"torso": -3, "spine": -5, "neck": -22,
                  "l_arm": 88, "l_fore": 75, "r_arm": 32,
                  "r_fore": -40, "l_leg": 10, "r_leg": 10, "l_shin": 5,
                  "r_shin": 5},
    "tango_dip_f": {"torso": -52, "dx": -0.07, "dy": 0.09, "l_leg": 20,
                    "r_leg": 62, "l_shin": 8, "r_shin": 72, "l_arm": 120,
                    "l_fore": 145, "r_arm": 60, "r_fore": 40},

    # — ballet (realism pass): port de bras positions, pointed-line
    #   legs (shin continues the leg angle), épaulement via shoulders +
    #   neck, profile yaw on arabesques/leaps —
    "bras_bas": {"l_arm": 24, "r_arm": 24, "l_fore": -38, "r_fore": -38,
                 "l_leg": 7, "r_leg": 7, "l_shin": 7, "r_shin": 7,
                 "neck": 2},
    "first_arms": {"l_arm": 48, "r_arm": 48, "l_fore": -52, "r_fore": -52,
                   "l_leg": 7, "r_leg": 7, "l_shin": 7, "r_shin": 7},
    "second_arms": {"l_arm": 84, "r_arm": 84, "l_fore": 68, "r_fore": 68,
                    "l_leg": 7, "r_leg": 7, "l_shin": 7, "r_shin": 7,
                    "shoulders": 0, "neck": 3},
    "fifth_sus_sous": {"dy": -0.045, "l_arm": 132, "r_arm": 132,
                       "l_fore": -166, "r_fore": -166, "l_leg": 4,
                       "r_leg": 4, "l_shin": -6, "r_shin": -6},
    "plie_second": {"dy": 0.075, "l_leg": 38, "r_leg": 38, "l_shin": -22,
                    "r_shin": -22, "l_arm": 84, "r_arm": 84, "l_fore": 66,
                    "r_fore": 66},
    "tendu_r": {"r_leg": 40, "r_shin": 41, "l_leg": 5, "l_shin": 3,
                "l_arm": 84, "r_arm": 84, "l_fore": 68, "r_fore": 68,
                "shoulders": -4, "neck": 5, "yaw": 8},
    "balance_r": {"torso": 8, "dx": 0.06, "dy": 0.02, "r_arm": 86,
                  "r_fore": 74, "l_arm": 34, "l_fore": -42, "l_leg": -8,
                  "r_leg": 16, "l_shin": -4, "r_shin": 8,
                  "shoulders": 6, "neck": -5},
    "arabesque_1st": {"torso": -11, "spine": -7, "neck": -6, "yaw": 30,
                      "dx": -0.03, "l_arm": 97, "l_fore": 94,
                      "r_arm": 56, "r_fore": 64, "l_leg": 7, "l_shin": 5,
                      "r_leg": 84, "r_shin": 89, "shoulders": -5},
    "penchee": {"torso": -32, "spine": -11, "neck": -8, "yaw": 30,
                "dx": -0.05, "dy": 0.03, "l_arm": 108, "l_fore": 104,
                "r_arm": 60, "r_fore": 68, "l_leg": 10, "l_shin": 7,
                "r_leg": 116, "r_shin": 121, "shoulders": -6},
    "attitude_back": {"yaw": 25, "torso": -6, "spine": -4, "neck": -4,
                      "l_arm": 134, "l_fore": -168, "r_arm": 80,
                      "r_fore": 70, "l_leg": 6, "l_shin": 4,
                      "r_leg": 76, "r_shin": 24, "shoulders": 5},
    "retire_spin": {"l_leg": 5, "l_shin": 3, "r_leg": 52, "r_shin": -56,
                    "l_arm": 50, "r_arm": 50, "l_fore": -54,
                    "r_fore": -54, "dy": -0.02},
    "chasse_prep": {"dy": 0.05, "l_leg": 9, "l_shin": 5, "r_leg": 32,
                    "r_shin": 16, "l_arm": 48, "r_arm": 48,
                    "l_fore": -52, "r_fore": -52, "torso": 3},
    "jete_split": {"dy": -0.17, "yaw": 25, "torso": 3, "spine": -4,
                   "l_leg": 86, "l_shin": 90, "r_leg": 84, "r_shin": 88,
                   "l_arm": 100, "l_fore": 97, "r_arm": 68, "r_fore": 76,
                   "neck": -4},
    "jete_peak": {"dy": -0.24, "yaw": 28, "torso": 2, "spine": -6,
                  "l_leg": 90, "l_shin": 94, "r_leg": 88, "r_shin": 92,
                  "l_arm": 108, "l_fore": 104, "r_arm": 62, "r_fore": 70,
                  "neck": -7, "shoulders": -4},
    "land_fourth": {"dy": 0.06, "l_leg": 27, "l_shin": -14, "r_leg": 12,
                    "r_shin": 6, "l_arm": 82, "r_arm": 82, "l_fore": 64,
                    "r_fore": 64, "torso": 2},
    "bourree_a": {"dy": -0.035, "l_leg": 5, "r_leg": 3, "l_shin": -9,
                  "r_shin": -3, "l_arm": 130, "r_arm": 130,
                  "l_fore": -164, "r_fore": -164},
    "bourree_b": {"dy": -0.03, "l_leg": 3, "r_leg": 5, "l_shin": -3,
                  "r_shin": -9, "l_arm": 128, "r_arm": 128,
                  "l_fore": -160, "r_fore": -160},
    "support_raise": {"r_arm": 148, "r_fore": 176, "l_arm": 40,
                      "l_fore": -45, "l_leg": 12, "r_leg": 12,
                      "l_shin": 6, "r_shin": 6},
    "support_reach": {"l_arm": 78, "l_fore": 60, "r_arm": 30,
                      "r_fore": -35, "l_leg": 14, "r_leg": 14,
                      "l_shin": 6, "r_shin": 6, "torso": 3},

    # — bender forms (tai chi: air/fire/water — big sweeps, swirls,
    #   low horizontal stretches) —
    "horse_stance": {"dy": 0.14, "l_leg": 48, "r_leg": 48, "l_shin": -20,
                     "r_shin": -20, "l_arm": 58, "r_arm": 58,
                     "l_fore": 38, "r_fore": 38, "spine": -3},
    "fire_punch": {"dy": 0.11, "l_leg": 44, "r_leg": 44, "l_shin": -10,
                   "r_shin": -10, "r_arm": 90, "r_fore": 90,
                   "l_arm": 16, "l_fore": -55, "torso": -4, "spine": -4,
                   "shoulders": -8, "yaw": 18},
    "water_whip_r": {"torso": 15, "spine": 11, "neck": -6, "dx": 0.11,
                     "dy": 0.08, "r_arm": 100, "r_fore": 96,
                     "l_arm": -18, "l_fore": -62, "r_leg": 56,
                     "r_shin": 26, "l_leg": 10, "l_shin": 4,
                     "shoulders": 8},
    "air_sweep": {"torso": -9, "spine": -7, "neck": 4, "dx": -0.04,
                  "r_arm": 152, "r_fore": 148, "l_arm": 48, "l_fore": 84,
                  "r_leg": 22, "l_leg": 8, "r_shin": 9, "l_shin": 3,
                  "shoulders": 7, "yaw": -14},
    "low_stretch": {"dy": 0.18, "torso": 18, "spine": 12, "neck": -10,
                    "l_leg": 72, "l_shin": 30, "r_leg": 12, "r_shin": -28,
                    "l_arm": 96, "r_arm": 88, "l_fore": 93, "r_fore": 86,
                    "dx": 0.06},
    "swirl_a": {"l_arm": 118, "l_fore": 150, "r_arm": 32, "r_fore": -22,
                "torso": 5, "spine": 5, "l_leg": 20, "r_leg": 20,
                "l_shin": 6, "r_shin": 6, "dy": 0.05, "yaw": 16},
    "swirl_b": {"l_arm": 158, "l_fore": 176, "r_arm": 62, "r_fore": 36,
                "torso": -4, "spine": -6, "l_leg": 14, "r_leg": 26,
                "l_shin": 5, "r_shin": 10, "dy": 0.03, "yaw": -12},
    "swirl_c": {"l_arm": -28, "l_fore": -72, "r_arm": 118, "r_fore": 150,
                "torso": -6, "spine": 6, "l_leg": 26, "r_leg": 14,
                "l_shin": 10, "r_shin": 5, "dy": 0.06, "yaw": 14},
    "swirl_d": {"r_arm": 158, "r_fore": 176, "l_arm": 62, "l_fore": 36,
                "torso": 4, "spine": -5, "l_leg": 26, "r_leg": 14,
                "l_shin": 10, "r_shin": 5, "dy": 0.03, "yaw": -16},

    # — wide flares / spins (skeleton v2) —
    "wide_lunge": {"dx": 0.14, "dy": 0.06, "torso": 8, "spine": -6,
                   "l_leg": 12, "l_shin": 5, "r_leg": 58, "r_shin": 30,
                   "l_arm": 105, "r_arm": 100, "l_fore": 112,
                   "r_fore": 108},
    "arms_wide": {"l_arm": 95, "r_arm": 95, "l_fore": 100, "r_fore": 100,
                  "l_leg": 26, "r_leg": 26, "l_shin": 12, "r_shin": 12},
    "robo_head_l": {"l_arm": 18, "r_arm": 18, "l_fore": 90, "r_fore": 90,
                    "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4,
                    "neck": -16},
    "robo_shrug": {"l_arm": 18, "r_arm": 45, "l_fore": 90, "r_fore": 110,
                   "l_leg": 8, "r_leg": 8, "l_shin": 4, "r_shin": 4,
                   "shoulders": 16, "neck": -6},
    "chaine_prep": {"l_arm": 62, "r_arm": 62, "l_fore": -52, "r_fore": -52,
                    "l_leg": 6, "r_leg": 20, "l_shin": 3, "r_shin": 9,
                    "dy": -0.02},

    # — hip/knee dynamics pass (weight shifts, knee lifts, deep rides) —
    "cow_strut": {"dy": 0.02, "dx": -0.05, "r_leg": 58, "r_shin": -52,
                  "l_leg": 8, "l_shin": 4, "torso": -5, "shoulders": -7,
                  "l_arm": 30, "l_fore": -40, "r_arm": 48, "r_fore": 22},
    "cow_squat_ride": {"dy": 0.13, "l_leg": 42, "r_leg": 42,
                       "l_shin": -26, "r_shin": -26, "l_arm": 32,
                       "r_arm": 32, "l_fore": -42, "r_fore": -42,
                       "torso": 6, "neck": -4},
    "robo_hip_l": {"dx": -0.09, "shoulders": -11, "l_arm": 18,
                   "r_arm": 18, "l_fore": 90, "r_fore": 90, "l_leg": 8,
                   "r_leg": 24, "l_shin": 4, "r_shin": 12, "neck": 7},
    "robo_knee": {"r_leg": 64, "r_shin": -64, "l_leg": 6, "l_shin": 3,
                  "l_arm": 18, "l_fore": 90, "r_arm": 45, "r_fore": 130},
    "mj_kneepop": {"dy": 0.05, "l_leg": 15, "r_leg": 15, "l_shin": -34,
                   "r_shin": -34, "torso": -8, "l_arm": 22, "r_arm": 22,
                   "l_fore": -14, "r_fore": -14, "neck": -6},
    "mj_hip": {"dy": -0.02, "torso": -16, "spine": 7, "l_leg": 8,
               "r_leg": 22, "l_shin": 4, "r_shin": -26, "l_arm": 26,
               "r_arm": 26, "l_fore": -20, "r_fore": -20,
               "shoulders": 5},
    "cuban_a": {"dx": 0.11, "dy": 0.04, "torso": -7, "spine": 9,
                "shoulders": 9, "neck": -4, "l_leg": 24, "l_shin": -26,
                "r_leg": 8, "r_shin": 4, "l_arm": 56, "r_arm": 36,
                "l_fore": 32, "r_fore": 8},
    "ocho_l": {"yaw": -35, "dx": -0.07, "dy": 0.04, "l_leg": 28,
               "l_shin": -32, "r_leg": 6, "r_shin": 3, "l_arm": 86,
               "l_fore": 72, "r_arm": 30, "r_fore": -42,
               "shoulders": -6, "neck": -8},
    "kp_knee_drop": {"dy": 0.20, "l_leg": 30, "l_shin": 6, "r_leg": 76,
                     "r_shin": -56, "r_arm": 128, "r_fore": 140,
                     "l_arm": 30, "l_fore": -40, "torso": 4, "neck": 6},

    # — kpop (high pop-and-lock, synchronized formation) —
    "kp_stance": {"l_leg": 18, "r_leg": 18, "l_shin": 8, "r_shin": 8,
                  "l_arm": 16, "r_arm": 16, "l_fore": 8, "r_fore": 8,
                  "neck": 3},
    "kp_point_r": {"r_arm": 128, "r_fore": 140, "l_arm": 34,
                   "l_fore": -46, "torso": -5, "spine": -5,
                   "shoulders": -9, "neck": 8, "yaw": 14,
                   "l_leg": 10, "r_leg": 26, "l_shin": 5, "r_shin": 12},
    "kp_point_low": {"dy": 0.12, "l_leg": 48, "r_leg": 48, "l_shin": -14,
                     "r_shin": -14, "r_arm": 96, "r_fore": 104,
                     "l_arm": 28, "l_fore": -40, "torso": 5, "spine": 6,
                     "neck": -5, "shoulders": -6},
    "kp_lock_x": {"l_arm": -32, "r_arm": -32, "l_fore": -80,
                  "r_fore": -80, "l_leg": 22, "r_leg": 22, "l_shin": 10,
                  "r_shin": 10, "spine": -6, "neck": 6},
    "kp_chest_lock": {"spine": -22, "neck": 14, "torso": -3,
                      "l_arm": 30, "r_arm": 30, "l_fore": 92,
                      "r_fore": 92, "shoulders": 0,
                      "l_leg": 16, "r_leg": 22, "l_shin": 7, "r_shin": 10},
    "kp_hip_r": {"dx": 0.13, "torso": -8, "spine": 10, "shoulders": 14,
                 "neck": -8, "l_arm": 58, "l_fore": 30, "r_arm": 20,
                 "r_fore": -30, "l_leg": 20, "r_leg": 6, "l_shin": 9,
                 "r_shin": 3},
    "kp_hair_a": {"neck": 22, "spine": 9, "torso": 6, "l_arm": 42,
                  "r_arm": 68, "l_fore": -35, "r_fore": 95,
                  "l_leg": 14, "r_leg": 20, "l_shin": 6, "r_shin": 9},
    "kp_hair_b": {"neck": -26, "spine": -8, "torso": -5, "l_arm": 70,
                  "r_arm": 36, "l_fore": 110, "r_fore": -20,
                  "l_leg": 20, "r_leg": 14, "l_shin": 9, "r_shin": 6,
                  "shoulders": 8},
    "kp_wave_flat": {"l_arm": 90, "r_arm": 90, "l_fore": 90, "r_fore": 90,
                     "l_leg": 16, "r_leg": 16, "l_shin": 7, "r_shin": 7,
                     "neck": -4},

    # — choreography / stunt poses —
    "tuck_ball": {"torso": 28, "spine": 52, "neck": 46, "dy": -0.04,
                  "l_arm": 62, "r_arm": 62, "l_fore": -75, "r_fore": -75,
                  "l_leg": 102, "r_leg": 102, "l_shin": 10, "r_shin": 10},
    "fall_straight": {"l_arm": 150, "r_arm": 150, "l_fore": 165,
                      "r_fore": 165, "l_leg": 8, "r_leg": 8, "l_shin": 4,
                      "r_shin": 4},
    "neo_land": {"dy": 0.22, "torso": 10, "l_leg": 28, "l_shin": 6,
                 "r_leg": 72, "r_shin": -48, "r_arm": 28, "r_fore": -18,
                 "l_arm": 95, "l_fore": 60},
    "superman_up": {"l_arm": 172, "l_fore": 178, "r_arm": 15, "r_fore": 8,
                    "l_leg": 5, "r_leg": 5, "l_shin": 2, "r_shin": 2},
    "run_a": {"torso": 10, "r_leg": 46, "r_shin": 22, "l_leg": 12,
              "l_shin": 58, "l_arm": 42, "l_fore": -28, "r_arm": -18,
              "r_fore": -46, "dy": 0.01},
    "run_b": {"torso": 10, "l_leg": 46, "l_shin": 22, "r_leg": 12,
              "r_shin": 58, "r_arm": 42, "r_fore": -28, "l_arm": -18,
              "l_fore": -46, "dy": -0.02},
    "catch_ready": {"l_arm": 118, "r_arm": 118, "l_fore": 95, "r_fore": 95,
                    "l_leg": 26, "r_leg": 26, "l_shin": -6, "r_shin": -6,
                    "dy": 0.06, "torso": -4},
    "cradle": {"l_arm": 70, "r_arm": 70, "l_fore": -48, "r_fore": -48,
               "l_leg": 24, "r_leg": 24, "l_shin": -4, "r_shin": -4,
               "dy": 0.05},
    "caught": {"l_arm": 140, "r_arm": 60, "l_fore": 160, "r_fore": 30,
               "l_leg": 20, "r_leg": 26, "l_shin": 30, "r_shin": 40},
    "spin_star": {"l_arm": 95, "r_arm": 95, "l_fore": 100, "r_fore": 100,
                  "l_leg": 20, "r_leg": 20, "l_shin": 10, "r_shin": 10},
}


# ── dance library ────────────────────────────────────────────────────────

DANCES: dict[str, dict] = {
    "tai_chi": {
        "label": "Tai Chi",
        "partner": "mirror",
        "tempo": 2,
        "ease": "flow",
        "energy": "calm",
        "express": 1.22,
        "idle": "tai_idle",
        "bounce": 0.0,
        "moves": [
            # water: continuous both-arm circles, weight carried side
            # to side — the swirl progression IS the bending
            {"name": "water_swirl", "weight": 2.5, "accent": "l_hand",
             "hits": [1, 3],
             "keys": ["swirl_a", "swirl_b", "swirl_c", "swirl_d"]},
            {"name": "water_whip", "weight": 1.5, "accent": "r_hand",
             "hits": [1, 3],
             "keys": ["gather_ball", "water_whip_r", "swirl_b",
                      "water_whip_r!m"]},
            # fire: rooted horse stance, driving straight strikes
            {"name": "fire_strikes", "weight": 1.5, "accent": "r_hand",
             "hits": [1, 3],
             "keys": ["horse_stance", "fire_punch", "horse_stance",
                      "fire_punch!m"]},
            # air: rising diagonal sweeps + a full spiraling turn
            {"name": "air_spiral", "accent": "r_hand", "spin": 360.0,
             "hits": [1], "flourish": True,
             "keys": ["swirl_a", "air_sweep", "swirl_c", "crane_open"]},
            # earth low: sink deep and stretch out flat
            {"name": "low_stretch", "weight": 1.5, "accent": "l_hand",
             "hits": [1, 2],
             "keys": ["horse_stance", "low_stretch", "low_stretch!m",
                      "horse_stance"]},
            {"name": "cloud_hands", "accent": "r_hand",
             "keys": ["cloud_a", "cloud_b", "cloud_a!m", "cloud_b!m"]},
            {"name": "single_whip", "accent": "r_hand", "hits": [1],
             "keys": ["gather_ball", "whip", "whip!m"]},
            {"name": "snake_creeps", "accent": "r_hand", "hits": [1, 3],
             "keys": ["crane_open", "snake_low", "crane_open",
                      "snake_low!m"]},
            {"name": "slow_turn", "accent": "r_hand", "spin": 360.0,
             "keys": ["gather_ball", "crane_open", "gather_ball!m",
                      "tai_idle"]},
        ],
    },
    "ballet": {
        "label": "Ballet",
        "partner": "together",
        "tempo": 1,
        "ease": "flow",
        "energy": "calm",
        "express": 1.2,    # flashy: big lines, still real vocabulary
        "groove": 0.85,
        "idle": "bras_bas",
        "bounce": 0.006,
        "moves": [
            # adage: breathing port de bras through the positions
            {"name": "port_de_bras", "weight": 2.0, "accent": "r_hand",
             "hits": [3],
             "keys": ["bras_bas", "first_arms", "second_arms",
                      "fifth_sus_sous"]},
            {"name": "plie_releve", "weight": 1.5, "accent": "r_hand",
             "hits": [2],
             "keys": ["second_arms", "plie_second", "fifth_sus_sous",
                      "plie_second"]},
            {"name": "tendu_seq", "accent": "r_foot",
             "keys": ["first_arms", "tendu_r", "second_arms",
                      "tendu_r!m"]},
            {"name": "balance_waltz", "weight": 1.5, "accent": "r_hand",
             "keys": ["balance_r", "first_arms", "balance_r!m",
                      "first_arms"]},
            {"name": "pirouette", "hits": [2], "accent": "l_hand",
             "flourish": True, "spin": 360.0,
             "keys": ["chasse_prep", "retire_spin", "retire_spin",
                      "land_fourth"]},
            {"name": "arabesque_line", "hits": [1, 2], "accent": "r_foot",
             "flourish": True,
             "keys": ["tendu_r", "arabesque_1st", "penchee",
                      "arabesque_1st"]},
            {"name": "grand_jete", "hits": [1], "accent": "r_foot",
             "travel": 0.45, "leap": True,
             "keys": ["chasse_prep", "jete_split", "land_fourth",
                      "first_arms"]},
            {"name": "grand_jete_l", "hits": [1], "accent": "l_foot",
             "travel": -0.45, "leap": True,
             "keys": ["chasse_prep!m", "jete_split!m", "land_fourth!m",
                      "first_arms"]},
            # the big one: a leap that sails ACROSS the stage — run-up,
            # split rising into a floating peak, landing in fourth
            {"name": "jete_across", "weight": 1.2, "accent": "r_foot",
             "hits": [1, 2], "flourish": True, "travel": 0.85,
             "leap": True,
             "keys": ["chasse_prep", "jete_split", "jete_peak",
                      "land_fourth"]},
            {"name": "jete_across_l", "weight": 1.2, "accent": "l_foot",
             "hits": [1, 2], "flourish": True, "travel": -0.85,
             "leap": True,
             "keys": ["chasse_prep!m", "jete_split!m", "jete_peak!m",
                      "land_fourth!m"]},
            {"name": "attitude_turn", "hits": [1, 2], "accent": "l_hand",
             "spin": 180.0,
             "keys": ["first_arms", "attitude_back", "attitude_back",
                      "fifth_sus_sous"]},
            {"name": "bourree", "accent": "r_foot", "travel": 0.4,
             "keys": ["bourree_a", "bourree_b", "bourree_a",
                      "bourree_b"]},
            {"name": "bourree_l", "accent": "l_foot", "travel": -0.4,
             "keys": ["bourree_b", "bourree_a", "bourree_b",
                      "bourree_a"]},
            {"name": "chaine_turns", "accent": "l_hand",
             "spin": 720.0, "travel": 0.5, "flourish": True,
             "keys": ["chaine_prep", "chaine_prep", "chaine_prep",
                      "first_arms"]},
            {"name": "chaine_turns_l", "accent": "r_hand",
             "spin": -720.0, "travel": -0.5, "flourish": True,
             "keys": ["chaine_prep", "chaine_prep", "chaine_prep",
                      "first_arms"]},
            # pas de deux: she spins under his raised hand (held)
            {"name": "supported_pirouette", "hits": [1], "accent": "r_hand",
             "flourish": True, "partner_spin": 360.0,
             "keys": ["support_raise", "support_raise", "support_raise",
                      "first_arms"],
             "partner_keys": ["retire_spin", "retire_spin", "retire_spin",
                              "first_arms"]},
            # promenade: she holds the arabesque, he walks her around
            {"name": "promenade_arabesque", "hits": [1, 2],
             "accent": "r_foot", "partner_spin": 150.0,
             "keys": ["support_reach", "support_reach", "support_reach",
                      "first_arms"],
             "partner_keys": ["arabesque_1st", "arabesque_1st",
                              "arabesque_1st", "first_arms"]},
            {"name": "lift", "hits": [2], "accent": "l_hand",
             "flourish": True,
             "keys": ["plie", "catch_ready", "lift_hold", "plie"],
             "partner_keys": ["plie", "releve", "lift_fly", "plie"]},
        ],
    },
    "kpop": {
        "label": "K-Pop",
        "partner": "sync",     # groups hit the choreo in unison
        "tempo": 1,
        "ease": "sharp",       # pop AND lock
        "energy": "high",
        "express": 1.3,
        "groove": 1.15,
        "idle": "kp_stance",
        "bounce": 0.018,
        "moves": [
            {"name": "point_hits", "weight": 2.0, "accent": "r_hand",
             "hits": [0, 2],
             "keys": ["kp_point_r", "kp_stance", "kp_point_r!m",
                      "kp_stance"]},
            {"name": "chest_locks", "weight": 1.5, "accent": "head",
             "hits": [0, 2],
             "keys": ["kp_chest_lock", "kp_stance", "kp_chest_lock",
                      "kp_lock_x"]},
            {"name": "hip_hits", "accent": "l_hand", "hits": [0, 2],
             "keys": ["kp_hip_r", "kp_stance", "kp_hip_r!m",
                      "kp_stance"]},
            {"name": "wave_lock", "weight": 1.5, "accent": "r_hand",
             "hits": [2],
             "keys": ["robo_wave_l", "robo_wave_l!m", "kp_wave_flat",
                      "kp_stance"]},
            {"name": "hair_flip", "accent": "head", "hits": [1],
             "flourish": True,
             "keys": ["kp_hair_a", "kp_hair_b", "kp_stance",
                      "kp_stance"]},
            {"name": "low_point", "accent": "r_hand", "hits": [1, 2],
             "keys": ["kp_stance", "kp_point_low", "kp_point_low!m",
                      "kp_stance"]},
            {"name": "x_lock_drop", "accent": "l_hand", "hits": [0, 1],
             "flourish": True,
             "keys": ["kp_lock_x", "kp_point_low", "kp_stance",
                      "kp_stance"]},
            {"name": "spin_point", "accent": "r_hand", "hits": [2],
             "flourish": True, "spin": 360.0,
             "keys": ["kp_stance", "spin_star", "kp_point_r",
                      "kp_point_r"]},
            {"name": "slide_formation", "accent": "r_foot",
             "travel": 0.24,
             "keys": ["kp_hip_r", "kp_stance", "kp_hip_r", "kp_stance"]},
            {"name": "knee_drop", "accent": "r_hand", "hits": [1, 2],
             "flourish": True,
             "keys": ["kp_stance", "kp_knee_drop", "kp_knee_drop",
                      "kp_stance"]},
        ],
    },
    "cowboy": {
        "label": "Cowboy Line Dance",
        "partner": "sync",
        "tempo": 1,
        "ease": "flow",
        "energy": "mid",
        "idle": "cow_idle",
        "bounce": 0.015,
        "moves": [
            {"name": "grapevine", "weight": 1.5, "accent": "r_foot",
             "travel": 0.30,
             "keys": ["grapevine_a", "grapevine_b", "grapevine_a",
                      "cow_idle"]},
            {"name": "grapevine_back", "accent": "l_foot", "travel": -0.30,
             "keys": ["grapevine_a!m", "grapevine_b!m", "grapevine_a!m",
                      "cow_idle"]},
            {"name": "heel_digs", "hits": [0, 2], "accent": "r_foot",
             "keys": ["heel_dig", "cow_idle", "heel_dig!m", "cow_idle"]},
            {"name": "lasso_swing", "hits": [1, 3], "weight": 1.5, "accent": "r_hand",
             "flourish": True,
             "keys": ["lasso_a", "lasso_b", "lasso_c", "lasso_d"]},
            {"name": "stomp_clap", "accent": "l_hand",
             "keys": ["stomp_up", "stomp_down", "clap", "cow_idle"]},
            {"name": "boot_scoot", "accent": "r_foot", "travel": -0.18,
             "keys": ["scoot", "cow_idle", "scoot", "cow_idle"]},
            {"name": "line_kick", "hits": [0, 2], "accent": "r_foot",
             "keys": ["kick_bc", "cow_idle", "kick_bc!m", "cow_idle"]},
            {"name": "knee_struts", "weight": 1.5, "accent": "r_foot",
             "hits": [0, 2],
             "keys": ["cow_strut", "cow_idle", "cow_strut!m",
                      "cow_idle"]},
            {"name": "squat_ride", "accent": "l_hand", "hits": [0, 2],
             "keys": ["cow_squat_ride", "stomp_down", "cow_squat_ride",
                      "stomp_down"]},
        ],
    },
    "robot": {
        "label": "Robot",
        "partner": "mirror",
        "tempo": 1,
        "ease": "sharp",
        "energy": "high",
        "groove": 0.3,
        "idle": "robot_idle",
        "bounce": 0.0,
        "moves": [
            {"name": "iso_arms", "hits": [2], "weight": 1.5, "accent": "r_hand",
             "keys": ["robot_idle", "robo_r_up", "robo_flat", "robo_r_up!m"]},
            {"name": "march", "hits": [0, 2], "accent": "r_foot",
             "keys": ["robo_march", "robot_idle", "robo_march!m",
                      "robot_idle"]},
            {"name": "lean_pop", "accent": "head",
             "keys": ["robo_lean", "robo_lean!m", "robo_low", "robot_idle"]},
            {"name": "salute", "accent": "r_hand",
             "keys": ["robo_salute", "robot_idle", "robo_salute!m",
                      "robot_idle"]},
            {"name": "wave_pass", "weight": 1.5, "accent": "l_hand",
             "keys": ["robo_wave_l", "robo_flat", "robo_wave_l!m",
                      "robo_flat"]},
            {"name": "squat_pop", "hits": [3], "accent": "head", "flourish": True,
             "keys": ["robo_low", "robot_idle", "robo_low", "robo_flat"]},
            {"name": "head_iso", "accent": "head",
             "keys": ["robo_head_l", "robot_idle", "robo_head_l!m",
                      "robot_idle"]},
            {"name": "shrug_iso", "accent": "r_hand",
             "keys": ["robo_shrug", "robot_idle", "robo_shrug!m",
                      "robot_idle"]},
            {"name": "hip_pops", "weight": 1.5, "accent": "l_hand",
             "hits": [0, 2],
             "keys": ["robo_hip_l", "robot_idle", "robo_hip_l!m",
                      "robot_idle"]},
            {"name": "knee_piston", "accent": "r_foot", "hits": [1, 3],
             "keys": ["robo_knee", "robo_low", "robo_knee!m",
                      "robo_low"]},
        ],
    },
    "moonwalk": {
        "label": "Michael Jackson",
        "partner": "mirror",
        "tempo": 1,
        "ease": "linear",
        "energy": "mid",
        "locomotion": False,
        "idle": "mj_idle",
        "bounce": 0.0,
        "moves": [
            # THE moonwalk — backslide glides both directions
            # profile backslide ACROSS the stage; the mirrored
            # right-hand version flips the facing with the direction
            {"name": "moonwalk_l", "weight": 2.0, "accent": "l_foot",
             "travel": -0.7, "ease": "snap",
             "keys": ["mj_glide_a", "mj_glide_b", "mj_glide_a",
                      "mj_glide_b"]},
            {"name": "moonwalk_r", "weight": 2.0, "accent": "r_foot",
             "travel": 0.7, "ease": "snap",
             "keys": ["mj_glide_a!m", "mj_glide_b!m", "mj_glide_a!m",
                      "mj_glide_b!m"]},
            # Smooth Criminal anti-gravity lean
            {"name": "lean_hold", "hits": [1, 2], "accent": "head",
             "flourish": True, "ease": "cosine",
             "keys": ["mj_idle", "mj_lean", "mj_lean", "mj_idle"]},
            # Billie Jean toe stand
            {"name": "toe_stand", "hits": [1, 2], "accent": "r_foot",
             "flourish": True, "ease": "cosine",
             "keys": ["mj_idle", "mj_toe", "mj_toe", "mj_idle"]},
            # spin ending ON the toes
            {"name": "spin_toe", "weight": 1.5, "accent": "r_hand",
             "flourish": True, "spin": 360.0, "ease": "cosine",
             "hits": [2],
             "keys": ["mj_spin", "mj_spin", "mj_toe", "mj_toe"]},
            # Billie Jean kicks snapping into the point-up freeze
            {"name": "kick_freeze", "weight": 1.5, "accent": "r_foot",
             "hits": [0, 2, 3], "flourish": True, "ease": "sharp",
             "keys": ["mj_kick", "mj_idle", "mj_kick!m",
                      "mj_point_up"]},
            # crotch-grab pop into the point
            {"name": "crotch_pop", "accent": "l_hand", "hits": [0, 2],
             "ease": "sharp",
             "keys": ["mj_crotch", "mj_idle", "mj_crotch",
                      "mj_point_up"]},
            # Smooth Criminal side snaps (hat-brim arm)
            {"name": "smooth_lean", "accent": "l_hand", "hits": [0, 2],
             "ease": "sharp",
             "keys": ["mj_smooth_l", "mj_idle", "mj_smooth_l!m",
                      "mj_idle"]},
            # Thriller claw sway
            {"name": "thriller", "accent": "r_hand",
             "keys": ["mj_thriller_a", "mj_thriller_a!m",
                      "mj_thriller_a", "mj_thriller_a!m"]},
            {"name": "knee_pops", "accent": "r_foot",
             "hits": [0, 2], "ease": "sharp",
             "keys": ["mj_kneepop", "mj_idle", "mj_kneepop", "mj_toe"]},
            {"name": "hip_snap", "accent": "head", "hits": [0, 2],
             "ease": "sharp",
             "keys": ["mj_hip", "mj_idle", "mj_hip", "mj_idle"]},
        ],
    },
    "floss": {
        "label": "Flossing",
        "partner": "mirror",
        "tempo": 1,
        "ease": "linear",
        "energy": "high",
        "idle": "hh_idle",
        "bounce": 0.012,
        "moves": [
            {"name": "floss_basic", "weight": 2.0, "accent": "r_hand",
             "keys": ["floss_l", "floss_l!m", "floss_l", "floss_l!m"]},
            {"name": "floss_wide", "hits": [1, 3], "accent": "r_hand", "flourish": True,
             "keys": ["floss_l_wide", "floss_l_wide!m", "floss_l_wide",
                      "floss_l_wide!m"]},
            {"name": "floss_low", "accent": "l_hand",
             "keys": ["floss_low_l", "floss_low_l!m", "floss_low_l",
                      "floss_low_l!m"]},
        ],
    },
    "worm": {
        "label": "The Worm",
        "partner": "mirror",
        "tempo": 1,
        "ease": "flow",
        "energy": "high",
        "locomotion": False,
        "idle": "hh_idle",
        "bounce": 0.0,
        "moves": [
            {"name": "worm_drop", "accent": "head",
             "tilt": [0.0, 30.0, 80.0],
             "keys": ["hh_idle", "crouch_prep", "worm_flat"],
             "next": ["worm_wave", "worm_wave_back"]},
            {"name": "worm_wave", "hits": [0, 2], "weight": 2.0, "accent": "head",
             "tilt": 84.0, "travel": 0.16,
             "keys": ["worm_a", "worm_b", "worm_c", "worm_b"],
             "next": ["worm_wave", "worm_wave_back", "worm_up"]},
            {"name": "worm_wave_back", "accent": "l_foot",
             "tilt": 84.0, "travel": -0.16,
             "keys": ["worm_c", "worm_b", "worm_a", "worm_b"],
             "next": ["worm_wave", "worm_up"]},
            {"name": "worm_up", "hits": [2], "accent": "head", "flourish": True,
             "tilt": [80.0, 25.0, 0.0, 0.0],
             "keys": ["worm_flat", "crouch_prep", "star_jump", "hh_idle"],
             "next": ["worm_drop", "worm_drop"]},
        ],
    },
    "hip_hop": {
        "label": "Hip Hop",
        "partner": "mirror",
        "tempo": 1,
        "ease": "flow",
        "energy": "high",
        "idle": "hh_idle",
        "bounce": 0.02,
        "moves": [
            {"name": "bounce_rock", "weight": 1.5, "accent": "r_hand",
             "keys": ["hh_idle", "hh_low", "top_rock_r", "hh_low"]},
            {"name": "top_rock", "accent": "r_foot",
             "keys": ["top_rock_r", "hh_idle", "top_rock_r!m", "hh_idle"]},
            {"name": "chest_pops", "accent": "head",
             "keys": ["chest_pop", "hh_idle", "chest_pop", "hh_low"]},
            {"name": "raise_roof", "hits": [0, 2], "weight": 1.5, "accent": "r_hand",
             "flourish": True,
             "keys": ["raise_roof", "raise_roof_b", "raise_roof",
                      "raise_roof_b"]},
            {"name": "skate", "accent": "l_foot", "travel": 0.12,
             "keys": ["skate_r", "hh_low", "skate_r!m", "hh_low"]},
            {"name": "cross_throw", "hits": [1], "accent": "r_hand",
             "keys": ["arm_cross", "raise_roof", "arm_cross", "hh_idle"]},
            {"name": "freeze", "hits": [1, 2], "accent": "r_hand", "flourish": True,
             "keys": ["hh_low", "freeze_pose", "freeze_pose", "hh_idle"]},
            {"name": "spin_freeze", "hits": [2], "accent": "r_hand", "flourish": True,
             "spin": 360.0,
             "keys": ["hh_low", "spin_star", "freeze_pose",
                      "freeze_pose"]},
            {"name": "wide_flare", "hits": [1, 2], "weight": 1.5, "accent": "r_hand",
             "flourish": True,
             "keys": ["hh_low", "wide_lunge", "wide_lunge!m",
                      "arms_wide"]},
        ],
    },
    "salsa": {
        "label": "Salsa",
        "partner": "together",
        "tempo": 1,
        "ease": "flow",
        "energy": "mid",
        "idle": "salsa_idle",
        "bounce": 0.012,
        "hold": ("r_hand", "l_hand"),
        "moves": [
            {"name": "basic_step", "weight": 2.0, "accent": "r_foot",
             "keys": ["salsa_step", "salsa_idle", "salsa_step!m",
                      "salsa_idle"]},
            {"name": "hip_rolls", "accent": "l_hand",
             "keys": ["hip_roll_r", "salsa_idle", "hip_roll_r!m",
                      "salsa_idle"]},
            {"name": "cross_body", "hits": [1], "accent": "r_hand", "swap": True,
             "hold": False, "flourish": True,
             "keys": ["salsa_step", "cross_mid", "salsa_idle"]},
            {"name": "underarm_turn", "hits": [0], "accent": "r_hand", "flourish": True,
             "partner_spin": 360.0,
             "keys": ["turn_lead", "turn_lead", "salsa_idle", "salsa_idle"],
             "partner_keys": ["spin_star", "spin_star", "salsa_idle!m",
                              "salsa_idle!m"]},
            {"name": "dip", "hits": [1, 2], "accent": "r_hand", "flourish": True,
             "keys": ["salsa_idle", "dip_lead", "dip_lead", "salsa_idle"],
             "partner_keys": ["salsa_idle", "dip_follow", "dip_follow",
                              "salsa_idle"]},
            {"name": "shimmy", "accent": "l_hand", "hold": False,
             "keys": ["shimmy_a", "shimmy_b", "shimmy_a", "shimmy_b"]},
            {"name": "cuban_walk", "weight": 1.5, "accent": "l_foot",
             "travel": 0.3,
             "keys": ["cuban_a", "cuban_a!m", "cuban_a", "cuban_a!m"]},
        ],
    },
    "tango": {
        "label": "Tango",
        "partner": "together",
        "tempo": 1,
        "ease": "sharp",
        "energy": "high",
        "groove": 0.8,
        "idle": "tango_frame",
        "bounce": 0.0,
        "hold": ("r_hand", "l_hand"),
        "moves": [
            {"name": "tango_walks", "weight": 1.5, "accent": "r_foot",
             "travel": 0.12,
             "keys": ["tango_walk", "tango_frame", "tango_walk!m",
                      "tango_frame"]},
            {"name": "corte_lunge", "hits": [1, 2], "accent": "head", "flourish": True,
             "keys": ["tango_frame", "corte", "corte", "tango_frame"]},
            {"name": "gancho", "hits": [1], "accent": "r_foot",
             "keys": ["tango_frame", "gancho", "tango_frame", "head_snap"]},
            {"name": "promenade", "accent": "l_hand", "travel": 0.24,
             "keys": ["tango_walk", "tango_walk!m", "tango_walk",
                      "tango_frame"]},
            {"name": "flicks", "hits": [0, 2], "accent": "r_foot",
             "keys": ["flick", "tango_frame", "flick!m", "tango_frame"]},
            {"name": "tango_dip", "hits": [1, 2], "accent": "head", "flourish": True,
             "keys": ["tango_frame", "corte", "corte", "tango_frame"],
             "partner_keys": ["tango_frame", "tango_dip_f", "tango_dip_f",
                              "tango_frame"]},
            {"name": "ochos", "weight": 1.5, "accent": "l_foot",
             "hits": [0, 2],
             "keys": ["ocho_l", "tango_frame", "ocho_l!m",
                      "tango_frame"]},
        ],
    },
}

DANCE_NAMES = tuple(DANCES.keys())
DEFAULT_DANCE = "tai_chi"

# partner modes where the second dancer is a reflection/copy (entry/exit:
# Neo drop-in / superman out) vs a true partner (drop-catch / spin-off)
MIRROR_MODES = ("mirror", "sync")


# ── compilation ──────────────────────────────────────────────────────────

def resolve_pose_vec(name: str) -> np.ndarray:
    """Pose name → vector; '!m' suffix mirrors."""
    mirrored = name.endswith("!m")
    base = name[:-2] if mirrored else name
    if base not in POSES:
        raise KeyError(f"unknown pose '{base}'")
    v = pose_vec(POSES[base])
    return mirror_vec(v) if mirrored else v


def compile_dances() -> dict[str, dict]:
    """POSES/DANCES → numeric tables the effect consumes.

    Each compiled move:
      keys      (K, 11) float32
      pkeys     (K, 11) float32 partner poses (mirrored keys by default)
      tilt      (K,) float32 figure tilt per key, degrees
      accent    joint index (JOINTS order), -1 = radiate from the chest
      spin/partner_spin/travel/weight  floats
      flourish/swap  bools
      next      tuple of move names or None
      ease      easing fn name or None (dance default)
    """
    out = {}
    for dname, d in DANCES.items():
        moves = []
        for m in d["moves"]:
            keys = np.stack([resolve_pose_vec(k) for k in m["keys"]])
            if m.get("partner_keys"):
                pk = m["partner_keys"]
                if len(pk) != len(m["keys"]):
                    raise ValueError(
                        f"{dname}/{m['name']}: partner_keys length mismatch"
                    )
                pkeys = np.stack([resolve_pose_vec(k) for k in pk])
            else:
                pkeys = np.stack([mirror_vec(k) for k in keys])
            tilt = m.get("tilt", 0.0)
            if np.isscalar(tilt):
                tilt_arr = np.full(len(keys), float(tilt), dtype=np.float32)
            else:
                if len(tilt) != len(keys):
                    raise ValueError(
                        f"{dname}/{m['name']}: tilt length mismatch"
                    )
                tilt_arr = np.asarray(tilt, dtype=np.float32)
            accent = m.get("accent")
            if accent is not None and accent not in _JI:
                raise KeyError(f"{dname}/{m['name']}: bad accent '{accent}'")
            for nxt in m.get("next") or ():
                if nxt not in {mm["name"] for mm in d["moves"]}:
                    raise KeyError(f"{dname}/{m['name']}: bad next '{nxt}'")
            if m.get("ease") is not None and m["ease"] not in EASES:
                raise KeyError(f"{dname}/{m['name']}: bad ease '{m['ease']}'")
            hits = tuple(int(i) for i in m.get("hits", ()))
            for hi in hits:
                if not 0 <= hi < len(m["keys"]):
                    raise IndexError(f"{dname}/{m['name']}: hit {hi} range")
            hold = m.get("hold")
            if hold is None:
                hold = bool(d.get("hold"))  # dance default: hold if a pair exists
            moves.append({
                "name": m["name"],
                "keys": keys,
                "pkeys": pkeys,
                "tilt": tilt_arr,
                "accent": _JI[accent] if accent else -1,
                "spin": float(m.get("spin", 0.0)),
                "partner_spin": float(m.get("partner_spin", 0.0)),
                "travel": float(m.get("travel", 0.0)) * 1.25,
                "weight": float(m.get("weight", 1.0)),
                "flourish": bool(m.get("flourish", False)),
                "swap": bool(m.get("swap", False)),
                "hold": bool(hold),
                "leap": bool(m.get("leap", False)),
                "hits": hits,
                "next": tuple(m.get("next") or ()) or None,
                "ease": m.get("ease"),
            })
        if d["ease"] not in EASES:
            raise KeyError(f"{dname}: bad ease '{d['ease']}'")
        hold_pair = d.get("hold")
        if hold_pair is not None:
            for jn in hold_pair:
                if jn not in _JI:
                    raise KeyError(f"{dname}: bad hold joint '{jn}'")
        out[dname] = {
            "label": d["label"],
            "partner": d["partner"],
            "tempo": int(d.get("tempo", 1)),
            "ease": d["ease"],
            "energy": d["energy"],
            "groove": float(
                d.get("groove", GROOVE_BY_ENERGY[d["energy"]])
            ),
            "express": float(
                d.get("express", EXPRESS_BY_ENERGY[d["energy"]])
            ),
            # stepping overlay when the body relocates (walk, don't
            # slide); moonwalk/worm opt out — gliding IS their move
            "locomotion": bool(d.get("locomotion", True)),
            "idle": resolve_pose_vec(d["idle"]),
            "bounce": float(d.get("bounce", 0.0)),
            # (lead_joint, partner_joint) hand-hold for "together" dances
            "hold": tuple(hold_pair) if hold_pair else None,
            "moves": moves,
            "by_name": {m["name"]: i for i, m in enumerate(moves)},
        }
    return out


def validate() -> list[str]:
    """Sanity-check the whole library; returns a list of problems (empty =
    good). compile_dances() raising is also a validation failure."""
    problems = []
    for name, p in POSES.items():
        for k in p:
            if k not in _KI:
                problems.append(f"pose {name}: unknown key '{k}'")
        for k in ("l_leg", "r_leg"):
            # 125 allows a penchée (leg past vertical) but still catches
            # sign errors / typos
            if abs(p.get(k, 0)) > 125:
                problems.append(f"pose {name}: {k}={p[k]} looks dislocated")
    try:
        compile_dances()
    except Exception as e:  # noqa: BLE001 — surface everything
        problems.append(f"compile failed: {e}")
    return problems
