"""Dancer: procedural stick-figure dancer(s) that dance to the beat engine.

The figure is the same skeleton as the SpotFX gifsmith GIF dancers, but
rendered live: key poses land on beats (keybeat-style beat oscillator
tracking with a wall-clock fallback), moves chain fluidly and every state
change — dance type, partner, rotation, effect transitions — blends
through choreography instead of cutting.

Colors: each dancer is ONE solid color — the foreground gradient sampled
120° after its center (the partner 120° before it); `accent_color` (the
third color) shows in stunt flashes and impact bursts; `background_color`
stays a normal visible layer. Beat bursts grab one random third of the
gradient.

The dance library lives in dancer_moves.py — see its header for the
authoring pipeline (SpotFX tools/dancesmith previews it headless).
"""

import logging
import math

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.dancer_flames as dancer_flames
import fx.effects.dancer_moves as dm
import fx.effects.lattice as lattice
import fx.effects.particle_handoff as particle_handoff
from fx.color import parse_color, validate_color, validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

DT_MAX = 0.1
FORM_CAP = 220           # formation (transition-in) particle capacity
KERNEL_R = 6             # splat kernel table radius
BONE_STEP = 0.6          # px between samples along a bone
SNAP_MAX = 200           # max particles exported in a handoff snapshot
DEFAULT_PERIOD = 60.0 / 105.0  # free-run beat period until measured
GRAD_OFF = 1.0 / 3.0     # dancers sit ±120° from the gradient center
SUB = 2                  # burst path sub-samples per frame

# incoming siblings that adopt our particles (keep in sync with
# pacman.PARTICLE_SIBLINGS and SpotFX services/transition_phases.py)
PARTICLE_SIBLINGS = frozenset(
    {"Blackhole", "Orbits", "Fireworks", "Squiggles"}
)

_DANCES = dm.compile_dances()

_TUCK = dm.resolve_pose_vec("tuck_ball")
_FALL = dm.resolve_pose_vec("fall_straight")
_NEO = dm.resolve_pose_vec("neo_land")
_SUPER = dm.resolve_pose_vec("superman_up")
_SQUAT = dm.resolve_pose_vec("deep_squat")
_CATCH = dm.resolve_pose_vec("catch_ready")
_CRADLE = dm.resolve_pose_vec("cradle")
_CAUGHT = dm.resolve_pose_vec("caught")
_RUN = (dm.resolve_pose_vec("run_a"), dm.resolve_pose_vec("run_b"))
_TURN = dm.resolve_pose_vec("turn_lead")

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _cld_step — "cld" naming because self._phase is
# already the beat-clock phase). The drop stunt styles reuse library poses.
_CLD_LEAP = dm.resolve_pose_vec("star_jump")
_CLD_SPLIT = dm.resolve_pose_vec("jete_split")
_CLD_FREEZE = dm.resolve_pose_vec("freeze_pose")
CLD_LULL_S = 2.5       # crouch-settle fallback when no lull ramp arrives
CLD_DROP_SETTLE_S = 2.2  # phase auto-reset after the drop stunts land
# dance family → drop stunt style (anything else does the big jump)
_CLD_BREAKERS = frozenset({"hip_hop", "kpop", "robot", "floss"})
_CLD_SPLITTERS = frozenset({"ballet", "tango", "salsa", "tai_chi"})


def _smooth(u):
    return u * u * (3.0 - 2.0 * u)


class Dancer2d(Twod, GradientEffect):
    """Beat-locked procedural dancer(s) with dance styles, a partner,
    color bursts and full transition choreography."""

    NAME = "Dancer"
    CATEGORY = "Matrix"
    LATTICE_EXACT = True
    # colors update in place — recreation would reset the choreography.
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "jiggle",
        "phase",
        "phase_progress",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Body + flame colors; dancers sit 120° either side of the gradient center",
                default="linear-gradient(90deg, rgb(0,199,140) 0%, rgb(0,255,50) 48%, rgb(0,199,140) 100%)",
            ): validate_gradient,
            vol.Optional(
                "accent_color",
                description="Third color: stunt flashes (near-black = use gradient)",
                default="#000000",
            ): validate_color,
            vol.Optional(
                "dance_type",
                description="Dance style — changing it blends at the next beat, never cuts",
                default=dm.DEFAULT_DANCE,
            ): vol.In(list(dm.DANCE_NAMES)),
            vol.Optional(
                "reverse",
                description="Partner: adds the second dancer (drop-in entrance, flying exit)",
                default=False,
            ): bool,
            vol.Optional(
                "rotation",
                description="Stage angle in degrees; big changes make the dancers somersault into the new orientation",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-360.0, max=360.0)),
            vol.Optional(
                "x_offset",
                description="X offset for the stage center",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "y_offset",
                description="Vertical stage position; 0.5 = centered",
                default=0.32,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "radius_scale",
                description="Figure size as a fraction of the panel",
                default=0.7,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "blob_size",
                description="Limb thickness in pixels",
                default=1.9,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "trail_decay",
                description="Comet-trail length: 0 = crisp dots, 1 = long smear",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "burst_threshold",
                description="Music level a beat needs to fire a flame burst; 0 = every beat",
                default=0.63,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "burst_size",
                description="Flame particles per burst (louder music adds more)",
                default=30,
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
            vol.Optional(
                "burst_audio",
                description="How much loudness grows the flames",
                default=1.8,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "brightness_audio",
                description="How much the music pumps the dancers' brightness",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "base_speed",
                description="Steady dance rate; beats surge the dance forward on top of it",
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.5)),
            vol.Optional(
                "dance_intensity",
                description="How HARD they dance: scales the beat surges, the groove sway and the pose exaggeration together",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "half_beat",
                description="Dance at half tempo (keys land every 2nd beat)",
                default=False,
            ): bool,
            vol.Optional(
                "jiggle",
                description="Humanize: random variation added to the moves",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "frequency_range",
                description="Audio band driving bursts and brightness",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "impulse_decay",
                description="Decay filter applied to the audio impulse",
                default=0.06,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.3)),
            vol.Optional(
                "phase",
                description="Charge/lull/drop choreography phase (driven by SpotFX)",
                default="none",
            ): vol.In(["none", "charge", "lull", "drop"]),
            vol.Optional(
                "phase_progress",
                description="Progress through the current phase (ramped by SpotFX)",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        }
    )

    def __init__(self, ledfx, config):
        # Everything below survives config patches (morph ramps re-run
        # do_once constantly) — geometry-dependent caches live in do_once.
        self._rng = np.random.default_rng()

        # beat clock
        self.impulse = 0.0
        self._beat_latch = 0.0
        self._beat_seen = -1.0
        self._beat_moved_at = 0.0
        self._phase = 0.0
        self._last_kick_t = 0.0
        self._period = DEFAULT_PERIOD
        self.above_min_vol = True
        self._minvol_seen = True
        self._suppress = False
        self._quiet_q = 0.0  # 0 = dancing, 1 = fully in idle sway

        # sequencer (lead dancer; partner derives from it)
        self._dance_name = None
        self._pending_dance = None
        self._dance_wall_t = 0.0
        self._move = None
        self._ki = 0
        self._step_u = 0.0
        self._pose_from = _DANCES[dm.DEFAULT_DANCE]["idle"].copy()
        self._pose_to = self._pose_from.copy()
        self._ppose_from = dm.mirror_vec(self._pose_from)
        self._ppose_to = self._ppose_from.copy()
        self._tilt_from = 0.0
        self._tilt_to = 0.0
        self._spin_base = 0.0
        self._spin_from = 0.0
        self._spin_to = 0.0
        self._pspin_base = 0.0
        self._pspin_from = 0.0
        self._pspin_to = 0.0
        self._travel = 0.0
        self._last_move_name = None
        self._flourish_j = None  # accent joint queued by a finished move

        # dancers
        self._dancers = []
        self._partner_pending = None  # "add" | "remove"
        self._entry_done = False

        # rotation / somersault
        self._rot_target = None
        self._rot_shown = 0.0
        self._rot_anim = None

        # flame bursts (module keeps the whole particle system)
        self.flames = dancer_flames.FlameField(self._rng)
        self._ember_acc = 0.0  # continuous trickle accumulator
        self._sprays = []      # active limb sprays (multi-frame bursts)
        self._beat_no = 0       # beat counter
        self._burst_timer = -1.0  # mid-swing burst countdown after a kick
        self._step_u = 0.0      # continuous progress through the current step
        self._surge = 0.0       # decaying beat surge (dance speed boost)
        self._burst_window = 0.0  # s left where a beat wants a burst
        self._hold_t = 0.0        # flourish hold: freeze on a hit pose
        self._hit_arrival = False  # a hit (stretch) pose landed this frame

        # formation particles (transition in)
        self.f_x = np.zeros(FORM_CAP, np.float32)
        self.f_y = np.zeros(FORM_CAP, np.float32)
        self.f_sx = np.zeros(FORM_CAP, np.float32)
        self.f_sy = np.zeros(FORM_CAP, np.float32)
        self.f_tx = np.zeros(FORM_CAP, np.float32)
        self.f_ty = np.zeros(FORM_CAP, np.float32)
        self.f_age = np.zeros(FORM_CAP, np.float32)
        self.f_dur = np.full(FORM_CAP, 1.0, np.float32)
        self.f_grad = np.zeros(FORM_CAP, np.float32)
        self.n_f = 0
        self._form_alpha = None  # None = no formation running

        # transitions
        self._handoff_pending = True
        self._out_mode = None  # None | dissolve | collapse | flee
        self._out_center = (0.0, 0.0)
        self._out_t0 = 0.0
        self._erupt_hold = None
        self.trail = None
        self._last_pts = None  # (px, py, grad, bright) from last draw

        # splat kernel offset table
        span = np.arange(-KERNEL_R, KERNEL_R + 1)
        kdx, kdy = np.meshgrid(span, span)
        kdist = np.sqrt(kdx**2 + kdy**2).ravel()
        keep = kdist <= KERNEL_R
        self.k_dx = kdx.ravel()[keep].astype(np.int32)
        self.k_dy = kdy.ravel()[keep].astype(np.int32)
        self.k_dist = kdist[keep].astype(np.float32)
        self._kern_cache = {}

        super().__init__(ledfx, config)

    # ── config ──────────────────────────────────────────────────────────

    def config_updated(self, config):
        super().config_updated(config)
        self.accent_rgb = np.array(
            parse_color(self._config["accent_color"]), dtype=np.float32
        )
        self.x_offset = self._config["x_offset"]
        self.y_offset = self._config["y_offset"]
        self.radius_scale = self._config["radius_scale"]
        self.blob_size = max(float(self._config["blob_size"]), 1.5)
        self.trail_decay = self._config["trail_decay"]
        self.burst_threshold = self._config["burst_threshold"]
        self.burst_size = int(self._config["burst_size"])
        self.burst_audio = self._config["burst_audio"]
        self.base_speed = self._config["base_speed"]
        self.dance_intensity = self._config["dance_intensity"]
        self.brightness_audio = self._config["brightness_audio"]
        self.half_beat = self._config["half_beat"]
        self.jiggle = self._config["jiggle"]

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.impulse_filter = self.create_filter(
            alpha_decay=self._config["impulse_decay"], alpha_rise=0.99
        )

        # charge/lull/drop: edge-detect the phase key ("cld" naming —
        # self._phase is the beat clock). State is created here (not
        # __init__) because config_updated runs first, during
        # super().__init__; the pending flag is consumed in draw.
        new_cld = self._config.get("phase", "none")
        self.phase_progress = float(self._config.get("phase_progress", 0.0))
        if not hasattr(self, "_cld_phase"):
            # creation baseline: a stale persisted phase key must never
            # edge-fire choreography on a fresh instance
            self._cld_phase = "none"
            self._cld_t = 0.0
            self._cld_pending = None
            self._cld_done_t = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._cld_pending = new_cld if new_cld != self._cld_phase else None

        # dance switch: applied at the next beat so the motion never cuts
        want = self._config["dance_type"]
        if self._dance_name is None:
            self._dance_name = want
            self._seq_start(want, keep_pose=False)
        elif want != self._dance_name:
            self._pending_dance = want
            self._dance_wall_t = 0.0

        # partner (reverse) toggle → entry/exit choreography
        want_partner = bool(self._config["reverse"])
        have_partner = len(self._dancers) > 1 or any(
            d.get("role") == "partner" for d in self._dancers
        )
        if self._entry_done and want_partner != have_partner:
            self._partner_pending = "add" if want_partner else "remove"

        # rotation: small changes glide, big ones somersault
        rot = float(self._config["rotation"])
        if self._rot_target is None:
            self._rot_target = rot
            self._rot_shown = rot
        elif rot != self._rot_target:
            delta = rot - self._rot_target
            self._rot_target = rot
            if abs(delta) >= 20.0:
                self._start_somersault(rot, math.copysign(1.0, delta))

    def audio_data_updated(self, data):
        impulse = self.impulse_filter.update(
            getattr(data, self.power_func)()
        )
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        b = data.beat_oscillator()  # TRUE beat: surges/groove ride every hit
        self._beat_latch = float(b) if np.isfinite(b) else 0.0
        vol_now = max(0.0, min(1.0, self.audio.volume(filtered=False)))
        self.above_min_vol = vol_now >= self.audio._config["min_volume"]

    # ── geometry ────────────────────────────────────────────────────────

    def do_once(self):
        super().do_once()
        self.lat = lattice.get_view(self)
        lo, hi = self.lat.row_extents()
        rows = np.flatnonzero(lo <= hi)
        if rows.size:
            top, bottom = int(rows[0]), int(rows[-1])
        else:
            top, bottom = 0, self.r_height - 1
        stage_h = max(bottom - top + 1, 8)
        self.fig_h = max(stage_h * 0.82 * self.radius_scale, 8.0)
        self.stage_top = top
        self.stage_bottom = bottom
        # y_offset 0.5 = figure vertically CENTERED in the silhouette;
        # offsets shift the whole stage up/down from there
        mid = (top + bottom) / 2.0
        self.hip_y = (
            mid
            + 0.075 * self.fig_h
            + (self.y_offset - 0.5) * stage_h * 0.6
        )
        self.cx = (self.r_width - 1) * self.x_offset
        if self.trail is None or self.trail.shape[:2] != (
            self.r_height,
            self.r_width,
        ):
            self.trail = np.zeros(
                (self.r_height, self.r_width, 3), dtype=np.float32
            )
        if not self._dancers:
            self._spawn_initial()

    def _sep(self):
        # close pairing: the two dance as a unit, slight overlap is fine
        # (Javi) — travel sweeps carry them across the stage instead
        mode = _DANCES[self._dance_name]["partner"]
        k = 0.45 if mode == "together" else 0.55
        sep = max(self.fig_h * k, 6.0)
        return min(sep, self.r_width / 2.0 - self.fig_h * 0.3)

    def _slot_x(self, slot):
        return self.cx + slot * self._sep()

    # ── dancers / choreography ──────────────────────────────────────────

    def _new_dancer(self, role, slot):
        return {
            "role": role,  # "lead" | "partner"
            "mirror": role == "partner",  # which pose line it renders —
                                          # stable across role swaps
            "slot": float(slot),
            "slot_x": self._slot_x(slot),
            "grad_pos": (0.5 + GRAD_OFF) % 1.0
            if role == "lead"
            else (0.5 - GRAD_OFF) % 1.0,
            "alpha": 1.0,
            "scale": 1.0,
            "x_off": 0.0,
            "y_off": 0.0,
            "rot_add": 0.0,
            "override": None,  # pose vec
            "override_w": 0.0,
            "hidden": False,
            "stunt": None,
        }

    def _spawn_initial(self):
        """Fresh activation: everyone drops in (Neo style)."""
        partner = bool(self._config["reverse"])
        lead = self._new_dancer("lead", -1.0 if partner else 0.0)
        self._dancers = [lead]
        self._stunt(lead, "drop_in", dur=1.15)
        if partner:
            p = self._new_dancer("partner", 1.0)
            self._stunt(p, "drop_in", dur=1.15, delay=0.35)
            self._dancers.append(p)
        self._entry_done = True

    def _stunt(self, d, kind, dur, delay=0.0, **kw):
        d["stunt"] = {"kind": kind, "t": -delay, "dur": dur, **kw}

    def _start_somersault(self, to_deg, direction):
        if self._rot_anim is not None:
            # retarget mid-air: keep the flight, change the landing
            self._rot_anim["to"] = to_deg
            return
        self._rot_anim = {
            "t": 0.0,
            "dur": 0.9,
            "from": self._rot_shown,
            "to": to_deg,
            "extra": 360.0 * direction,
        }
        for i, d in enumerate(self._dancers):
            if d["stunt"] is None:
                self._stunt(d, "somersault", dur=0.9, delay=0.10 * i)

    def _process_partner_pending(self):
        if self._partner_pending is None or not self._entry_done:
            return
        busy = any(d["stunt"] is not None for d in self._dancers)
        if busy:
            return
        mode = _DANCES[self._dance_name]["partner"]
        if self._partner_pending == "add" and len(self._dancers) == 1:
            lead = self._dancers[0]
            lead["slot"] = -1.0
            p = self._new_dancer("partner", 1.0)
            hi = (0.5 + GRAD_OFF) % 1.0
            lo = (0.5 - GRAD_OFF) % 1.0
            p["grad_pos"] = lo if abs(lead["grad_pos"] - hi) < 0.02 else hi
            p["mirror"] = not lead.get("mirror", False)
            if mode == "together":
                # falls from the sky into the lead's arms
                self._stunt(p, "catch_drop", dur=1.5, delay=0.25)
                self._stunt(lead, "catch_lead", dur=1.5, delay=0.25)
            else:
                # lead steps aside, partner lands Neo-style in their place
                p["slot"] = 1.0
                self._stunt(p, "drop_in", dur=1.15, delay=0.45)
            self._dancers.append(p)
        elif self._partner_pending == "remove" and len(self._dancers) > 1:
            # EITHER dancer may be the one who leaves; the stayer takes
            # over the choreography chain and walks back to center
            li = int(self._rng.integers(0, 2))
            leaver = self._dancers[li]
            stayer = self._dancers[1 - li]
            stayer["role"] = "lead"
            leaver["role"] = "partner"
            # render parity (d["mirror"]) is NOT touched: the stayer keeps
            # dancing its own line — no pose snap at the handover
            self._dancers = [stayer, leaver]
            stayer["slot"] = 0.0
            self._stunt(leaver, "tumble_off", dur=1.4)
            if mode == "together":
                stayer["override"] = _TURN
                stayer["override_w"] = 1.0
                self._stunt(stayer, "fade_override", dur=0.9)
        self._partner_pending = None

    # ── sequencer ───────────────────────────────────────────────────────

    def _pick_move(self, dance):
        moves = dance["moves"]
        cur = self._move
        if cur is not None and cur.get("next"):
            pool = [moves[dance["by_name"][n]] for n in cur["next"]]
            w = np.array([m["weight"] for m in pool])
        else:
            pool = moves
            w = np.array(
                [
                    0.0
                    if (m["name"] == self._last_move_name and len(moves) > 1)
                    else m["weight"]
                    for m in moves
                ]
            )
        if w.sum() <= 0:
            w = np.ones(len(pool))
        return pool[int(self._rng.choice(len(pool), p=w / w.sum()))]

    def _jig(self, vec):
        if self.jiggle <= 0:
            return vec
        out = vec.copy()
        out[1:9] += self._rng.normal(0.0, 4.0 * self.jiggle, 8).astype(
            np.float32
        )
        out[9] += self._rng.normal(0.0, 0.012 * self.jiggle)
        return out

    def _seq_start(self, dance_name, keep_pose=True):
        """Enter a dance; keep_pose tweens from wherever the body is now."""
        self._dance_name = dance_name
        dance = _DANCES[dance_name]
        self._move = None
        self._move = self._pick_move(dance)
        self._ki = 0
        self._step_u = 0.0
        if not keep_pose:
            self._pose_from = dance["idle"].copy()
            self._ppose_from = dm.mirror_vec(dance["idle"])
        self._pose_to = self._jig(self._move["keys"][0])
        self._ppose_to = self._partner_key(self._move, 0)
        self._tilt_from = self._tilt_to
        self._tilt_to = float(self._move["tilt"][0])
        self._spin_base = (self._spin_base + self._spin_to) % 360.0
        self._spin_from = self._spin_to = 0.0
        self._pspin_base = (self._pspin_base + self._pspin_to) % 360.0
        self._pspin_from = self._pspin_to = 0.0

    def _partner_key(self, move, ki):
        if _DANCES[self._dance_name]["partner"] == "sync":
            return self._jig(move["keys"][ki])
        return self._jig(move["pkeys"][ki])

    def _seq_advance(self):
        """The step clock rolled over: commit the next key pose."""
        dance = _DANCES[self._dance_name]
        if self._move is not None and self._ki in self._move["hits"]:
            self._hit_arrival = True  # landed on a stretch/hit pose
        self._pose_from = self._pose_to
        self._ppose_from = self._ppose_to
        self._tilt_from = self._tilt_to
        self._spin_from = self._spin_to
        self._pspin_from = self._pspin_to
        move = self._move
        k = len(move["keys"])
        self._ki += 1
        if move["travel"]:
            self._travel += move["travel"] / k
            lim = getattr(self, "_travel_lim", 0.45)
            self._travel = float(np.clip(self._travel, -lim, lim))
        if self._ki >= k:
            # move complete
            self._last_move_name = move["name"]
            if move["flourish"]:
                self._flourish_j = move["accent"]
            if self._pending_dance:
                self._dance_name = self._pending_dance
                self._pending_dance = None
                self._seq_start(self._dance_name)
                return
            nxt = self._pick_move(dance)
            self._move = nxt
            self._ki = 0
            if nxt["swap"] and len(self._dancers) > 1:
                for d in self._dancers:
                    d["slot"] = -d["slot"]
            self._spin_base = (self._spin_base + self._spin_to) % 360.0
            self._spin_from = self._spin_to = 0.0
            self._pspin_base = (self._pspin_base + self._pspin_to) % 360.0
            self._pspin_from = self._pspin_to = 0.0
            move = nxt
            k = len(move["keys"])
        self._pose_to = self._jig(move["keys"][self._ki])
        self._ppose_to = self._partner_key(move, self._ki)
        self._tilt_to = float(move["tilt"][self._ki])
        frac = (self._ki + 1) / k
        self._spin_to = move["spin"] * frac
        self._pspin_to = (move["spin"] + move["partner_spin"]) * frac

    def _seq_pose(self, u):
        """Current tweened pose pair + tilt/spins at eased step progress."""
        move = self._move
        dance = _DANCES[self._dance_name]
        ease = dm.EASES[move["ease"] or dance["ease"]]
        w = ease(float(np.clip(u, 0.0, 1.0)))
        pose = self._pose_from * (1.0 - w) + self._pose_to * w
        ppose = self._ppose_from * (1.0 - w) + self._ppose_to * w
        # choreography exaggeration: push the pose away from the dance's
        # neutral stance — bigger arcs, deeper bends, wider steps (the
        # dance DOES more, not just faster). Facing (yaw) stays exact.
        ex = 1.0 + (dance["express"] - 1.0) * self.dance_intensity
        if abs(ex - 1.0) > 1e-3:
            neutral = dance["idle"]
            yaw_p, yaw_pp = pose[dm.I_YAW], ppose[dm.I_YAW]
            pose = neutral + (pose - neutral) * ex
            ppose = dm.mirror_vec(neutral) + (
                ppose - dm.mirror_vec(neutral)
            ) * ex
            pose[dm.I_YAW] = yaw_p
            ppose[dm.I_YAW] = yaw_pp
        tilt = self._tilt_from * (1.0 - w) + self._tilt_to * w
        spin = self._spin_base + self._spin_from * (1.0 - w) + self._spin_to * w
        pspin = (
            self._pspin_base
            + self._pspin_from * (1.0 - w)
            + self._pspin_to * w
        )
        # bounce: little hop that lands on each beat
        if dance["bounce"]:
            hop = math.sin(math.pi * min(self._phase, 1.0))
            pose = pose.copy()
            ppose = ppose.copy()
            pose[10] -= dance["bounce"] * hop
            ppose[10] -= dance["bounce"] * hop
        return pose, ppose, tilt, spin, pspin

    def _apply_groove(self, pose, ppose, dance):
        """Always-on beat-locked secondary motion: pendulum arm swing,
        shoulder/hip counter-sway, head bob, a lift into every beat.
        Scales with the dance's groove and the music; fades out when the
        room goes quiet. This is what keeps the body moving BETWEEN key
        poses instead of parking on them."""
        g = (
            dance["groove"]
            * self.dance_intensity
            * (1.0 - _smooth(self._quiet_q))
        )
        if g <= 0.02:
            return pose, ppose
        g *= 0.65 + 0.7 * min(self.impulse, 1.0)
        bp = 2.0 * math.pi * self._phase
        sway = math.sin(bp)
        nod = -math.cos(bp)                      # dips into the beat
        bob = 0.5 * (1.0 - math.cos(bp))         # lift lands ON the beat
        pose = pose.copy()
        ppose = ppose.copy()
        psign = 1.0 if dance["partner"] == "sync" else -1.0
        for vec, sgn in ((pose, 1.0), (ppose, psign)):
            s = sway * sgn
            vec[1] -= 4.5 * g * s                # arms pendulum together
            vec[2] += 4.5 * g * s
            vec[3] -= 6.0 * g * s                # forearms whip a bit more
            vec[4] += 6.0 * g * s
            vec[dm.I_SHO] += 3.0 * g * s
            vec[dm.I_SPINE] += 1.8 * g * s
            vec[dm.I_NECK] += 2.4 * g * nod * sgn
            vec[9] -= 0.011 * g * s              # hips counter the arms
            vec[10] -= 0.008 * g * bob           # rise into the beat
        return pose, ppose

    # ── beat clock ──────────────────────────────────────────────────────

    def _update_clock(self, dt):
        """Follow the beat oscillator; free-run at the last tempo when the
        tracker stalls. Returns True on a beat kick."""
        b = self._beat_latch
        if b != self._beat_seen:
            self._beat_seen = b
            self._beat_moved_at = self.now
        audio_live = (self.now - self._beat_moved_at) < 1.5
        if audio_live:
            phase = b
        else:
            phase = (self._phase + dt / max(self._period, 0.2)) % 1.0
        kick = False
        if phase < self._phase - 0.25:  # wrapped
            if self.now - self._last_kick_t >= 0.1:
                kick = True
                per = self.now - self._last_kick_t
                if 0.25 < per < 2.0:
                    self._period = 0.85 * self._period + 0.15 * per
                self._last_kick_t = self.now
        self._phase = phase
        if self.above_min_vol:
            self._minvol_seen = True
        if kick:
            self._suppress = not self._minvol_seen
            self._minvol_seen = False
        # quiet blend toward the idle sway
        target = 1.0 if self._suppress else 0.0
        if target > self._quiet_q:
            self._quiet_q = min(self._quiet_q + dt / 1.5, target)
        else:
            self._quiet_q = max(self._quiet_q - dt / 0.8, target)
        return kick and not self._suppress

    # ── stunts ──────────────────────────────────────────────────────────

    # ── charge/lull/drop choreography ──────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: the dance itself intensifies — surges,
    # groove and pose exaggeration all climb with the ramp; lull: the
    # dancers sink into a coiled deep-squat setup and hold it; drop: a
    # spectacular payoff stunt per dancer — a star jump, a leap landing in
    # the splits (graceful dances), or a low breakdance freeze-spin
    # (hip hop / kpop / robot / floss) — then back to the normal dance
    # (`phase` self-resets to "none").

    def _cld_drop_style(self):
        roll = float(self._rng.random())
        if roll < 0.25:
            return "jump"  # any dance may just leap huge
        if self._dance_name in _CLD_BREAKERS:
            return "breaker"
        if self._dance_name in _CLD_SPLITTERS:
            return "splits"
        return "jump"

    def _cld_step(self, dt):
        pend = self._cld_pending
        if pend is not None:
            self._cld_pending = None
            if pend != self._cld_phase:
                self._cld_phase = pend
                self._cld_t = 0.0
                self._cld_done_t = None
                if pend == "drop":
                    for i, d in enumerate(self._dancers):
                        d["hold_override"] = False
                        if d["stunt"] is None:
                            self._stunt(
                                d, "cld_drop", dur=1.8, delay=0.08 * i,
                                style=self._cld_drop_style(),
                            )
                elif pend != "lull":
                    for d in self._dancers:
                        d["hold_override"] = False
        if self._cld_phase == "none":
            return
        self._cld_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — the dancers rise out of the crouch and resume
        due, self._cld_done_t = particle_handoff.phase_release_due(
            self._cld_phase, self.phase_progress, self._cld_t,
            self._cld_done_t,
        )
        if due:
            _LOGGER.info(
                "dancer: %s watchdog release after %.1fs",
                self._cld_phase, self._cld_t,
            )
            for d in self._dancers:
                d["hold_override"] = False
            self._cld_phase = "none"
            self._apply_config(
                {"phase": "none", "phase_progress": 0.0},
                validate=False,
                fire_event=False,
            )
            return
        cfg_int = float(self._config["dance_intensity"])
        if self._cld_phase == "charge":
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            # the dance itself intensifies as the charge builds; a surge
            # floor keeps it visibly accelerating even in silence
            self.dance_intensity = min(2.4, cfg_int * (1.0 + 1.0 * p))
            self._surge = max(self._surge, 1.6 * p)
        elif self._cld_phase == "lull":
            # progress-driven once it moves (hand-scrubbable); wall-clock
            # fallback only while progress sits at 0
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            f = p if p > 0.0 else min(self._cld_t / CLD_LULL_S, 1.0)
            f = f * f * (3.0 - 2.0 * f)
            self.dance_intensity = cfg_int * (1.0 - 0.5 * f)
            for d in self._dancers:
                if d["stunt"] is None:
                    d["override"] = _SQUAT
                    d["override_w"] = f
                    d["hold_override"] = True
        else:  # drop
            if self._cld_t >= CLD_DROP_SETTLE_S:
                self._cld_phase = "none"
                # sanctioned in-render config path (under the effect lock);
                # self-reset so an identical later drop write edges again
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _update_stunts(self, dt):
        drop_h = self.hip_y - self.stage_top + self.fig_h
        removals = []
        for d in self._dancers:
            st = d["stunt"]
            if st is None:
                if d["override_w"] > 0.0 and not d.get("hold_override"):
                    d["override_w"] = max(d["override_w"] - dt * 3.0, 0.0)
                continue
            st["t"] += dt
            if st["t"] < 0.0:
                d["hidden"] = st["kind"] in ("drop_in", "catch_drop")
                continue
            u = min(st["t"] / st["dur"], 1.0)
            kind = st["kind"]
            done = st["t"] >= st["dur"]
            if kind == "somersault":
                d["hidden"] = False
                # apex ≈ neck height — any higher and the ball
                # tumbles off the top of the panel
                d["y_off"] = -math.sin(math.pi * u) * self.fig_h * 0.28
                w = min(u / 0.2, 1.0) * min((1.0 - u) / 0.2, 1.0)
                d["override"] = _TUCK
                d["override_w"] = float(np.clip(w * 1.4, 0.0, 1.0))
                d["yaw_add"] = 360.0 * _smooth(u)  # 3D corkscrew twist
            elif kind == "drop_in":
                d["hidden"] = False
                if u < 0.55:
                    fall = (u / 0.55) ** 2
                    d["y_off"] = -drop_h * (1.0 - fall)
                    d["override"] = _FALL
                    d["override_w"] = 1.0
                elif u < 0.8:
                    if not st.get("hit"):
                        st["hit"] = True
                        self._impact_flames(d, mag=0.8)
                    d["y_off"] = 0.0
                    d["override"] = _NEO
                    d["override_w"] = 1.0
                else:
                    d["override"] = _NEO
                    d["override_w"] = (1.0 - u) / 0.2
            elif kind == "catch_drop":
                d["hidden"] = False
                lead = self._dancers[0]
                if u < 0.5:
                    fall = (u / 0.5) ** 2
                    catch_y = -0.25 * self.fig_h
                    d["y_off"] = (-drop_h) * (1.0 - fall) + catch_y * fall
                    d["x_off"] = (lead["slot_x"] - d["slot_x"]) + self.fig_h * 0.25
                    d["override"] = _FALL if u < 0.35 else _CAUGHT
                    d["override_w"] = 1.0
                elif u < 0.7:
                    if not st.get("hit"):
                        st["hit"] = True
                        self._impact_flames(d, mag=0.5)
                    d["y_off"] = -0.25 * self.fig_h
                    d["x_off"] = (lead["slot_x"] - d["slot_x"]) + self.fig_h * 0.25
                    d["override"] = _CAUGHT
                    d["override_w"] = 1.0
                else:
                    s = (u - 0.7) / 0.3
                    e = _smooth(s)
                    d["y_off"] = -0.25 * self.fig_h * (1.0 - e)
                    d["x_off"] = (
                        (lead["slot_x"] - d["slot_x"]) + self.fig_h * 0.25
                    ) * (1.0 - e)
                    d["override"] = _CAUGHT
                    d["override_w"] = 1.0 - s
            elif kind == "catch_lead":
                if u < 0.5:
                    d["override"] = _CATCH
                    d["override_w"] = min(u / 0.15, 1.0)
                elif u < 0.7:
                    d["override"] = _CRADLE
                    d["override_w"] = 1.0
                else:
                    d["override"] = _CRADLE
                    d["override_w"] = 1.0 - (u - 0.7) / 0.3
            elif kind == "tumble_off":
                # 3D exit: crouch, launch burst, then a tight corkscrew
                # ball tumbling offscreen on a ballistic arc
                if u < 0.18:
                    d["override"] = _SQUAT
                    d["override_w"] = min(u / 0.08, 1.0)
                else:
                    v = (u - 0.18) / 0.82
                    if not st.get("hit"):
                        st["hit"] = True
                        self._impact_flames(d, mag=0.9)
                        st["dir"] = (
                            -1.0
                            if d["slot_x"] < self.r_width / 2.0
                            else 1.0
                        )
                    edge = (
                        -self.fig_h * 1.2
                        if st["dir"] < 0
                        else self.r_width + self.fig_h * 1.2
                    )
                    d["override"] = _TUCK
                    d["override_w"] = 1.0
                    d["x_off"] = _smooth(v) * (edge - d["slot_x"])
                    d["y_off"] = (
                        -math.sin(min(v * 1.15, 1.0) * math.pi)
                        * self.fig_h
                        * 0.5
                    )
                    d["rot_add"] += dt * 900.0 * st["dir"]
                    d["yaw_add"] = d.get("yaw_add", 0.0) + dt * 540.0
                if done:
                    removals.append(d)
            elif kind == "run_off":
                d["override"] = _RUN[int(self.now / 0.16) % 2]
                d["override_w"] = 1.0
                d["x_off"] += st["dir"] * self.fig_h * 2.2 * dt
                x = d["slot_x"] + d["x_off"]
                if x < -self.fig_h or x > self.r_width + self.fig_h:
                    d["hidden"] = True
            elif kind == "exit_tuck":
                d["override"] = _TUCK
                d["override_w"] = min(u / 0.25, 1.0)
                d["rot_add"] += dt * 460.0
                d["yaw_add"] = d.get("yaw_add", 0.0) + dt * 540.0
                d["y_off"] = -math.sin(math.pi * min(u, 1.0)) * self.fig_h * 0.3
            elif kind == "fade_override":
                d["override_w"] = max(1.0 - u * 1.5, 0.0)
            elif kind == "cld_drop":
                # drop payoff: coil, then the spectacular move
                style = st.get("style", "jump")
                if u < 0.15:
                    d["override"] = _SQUAT
                    d["override_w"] = max(
                        d["override_w"], min(u / 0.08, 1.0)
                    )
                elif style == "breaker":
                    # low breakdance freeze, whole figure spinning on the
                    # floor, then pop back up
                    v = (u - 0.15) / 0.85
                    if not st.get("hit"):
                        st["hit"] = True
                        self._impact_flames(d, mag=1.0)
                    d["override"] = _CLD_FREEZE
                    d["override_w"] = 1.0 if v < 0.78 else (1.0 - v) / 0.22
                    d["y_off"] = self.fig_h * 0.22 * min(v / 0.1, 1.0) * (
                        1.0 if v < 0.8 else max((1.0 - v) / 0.2, 0.0)
                    )
                    if v < 0.8:
                        d["rot_add"] += dt * 640.0 * (
                            1.0 if d.get("mirror") else -1.0
                        )
                    else:
                        # unwind to a clean upright landing
                        target = round(d["rot_add"] / 360.0) * 360.0
                        d["rot_add"] += (target - d["rot_add"]) * min(
                            dt * 8.0, 1.0
                        )
                elif style == "splits":
                    # grand jeté up, land ON THE FLOOR in the splits, hold
                    # the hit, then rise back into the dance
                    v = (u - 0.15) / 0.85
                    d["override"] = _CLD_SPLIT
                    if v < 0.6:
                        d["override_w"] = min(v / 0.12, 1.0)
                        d["y_off"] = (
                            -math.sin(math.pi * v / 0.6) * self.fig_h * 0.30
                        )
                    elif v < 0.72:
                        s = (v - 0.6) / 0.12
                        d["y_off"] = self.fig_h * 0.30 * s
                        d["override_w"] = 1.0
                        if not st.get("hit"):
                            st["hit"] = True
                            self._impact_flames(d, mag=1.1)
                    elif v < 0.88:
                        d["y_off"] = self.fig_h * 0.30
                        d["override_w"] = 1.0
                    else:
                        s = (v - 0.88) / 0.12
                        d["y_off"] = self.fig_h * 0.30 * (1.0 - s)
                        d["override_w"] = 1.0 - s
                else:  # jump
                    # huge star jump: full-bright apex, stuck landing
                    v = (u - 0.15) / 0.85
                    d["y_off"] = (
                        -math.sin(math.pi * min(v, 1.0))
                        * self.fig_h
                        * 0.36
                    )
                    if v < 0.55:
                        d["override"] = _CLD_LEAP
                        d["override_w"] = min(v / 0.10, 1.0)
                    else:
                        d["override"] = _NEO
                        d["override_w"] = (
                            1.0 if v < 0.85 else (1.0 - v) / 0.15
                        )
                    if v >= 0.9 and not st.get("hit"):
                        st["hit"] = True
                        self._impact_flames(d, mag=1.1)
                if done:
                    d["rot_add"] = 0.0
            if done and kind not in ("tumble_off", "run_off",
                                     "exit_tuck"):
                d["stunt"] = None
                d["y_off"] = 0.0
                d["yaw_add"] = 0.0
                d["x_off"] = 0.0 if kind != "run_off" else d["x_off"]
        for d in removals:
            if d in self._dancers:
                self._dancers.remove(d)
        # rotation animation (shared stage angle)
        ra = self._rot_anim
        if ra is not None:
            ra["t"] += dt
            v = min(ra["t"] / ra["dur"], 1.0)
            e = _smooth(v)
            self._rot_shown = ra["from"] + (
                ra["to"] + ra["extra"] - ra["from"]
            ) * e
            if v >= 1.0:
                self._rot_shown = ra["to"]
                self._rot_anim = None
        elif self._rot_target is not None and self._rot_shown != self._rot_target:
            step = 90.0 * dt
            diff = self._rot_target - self._rot_shown
            if abs(diff) <= step:
                self._rot_shown = self._rot_target
            else:
                self._rot_shown += math.copysign(step, diff)

    # ── flames ──────────────────────────────────────────────────────────

    def _accent_usable(self):
        """Near-black accent (Javi's default) means: color stunt flames
        from the gradient instead."""
        return float(self.accent_rgb.max()) > 24.0

    def _impact_flames(self, d, mag):
        x = d["slot_x"] + d["x_off"]
        y = self.hip_y + d["y_off"] + dm.LEG_REACH * self.fig_h * 0.8
        self.flames.emit(
            x, y, int(self.burst_size * 0.8), mag, self.fig_h,
            side=0 if d["role"] == "lead" else 1,
            accent=self._accent_usable(),
        )

    # extremities that can throw flames, with prominence weights
    _LIMBS = ((5, 1.0), (7, 1.0), (9, 0.85), (11, 0.85), (3, 0.7))

    def _prominent_limb(self, d):
        """The dancer's flourishing limb right now: the extremity moving
        fastest RELATIVE to the body. Returns (joint_idx, vel, speed) or
        None when nothing is really swinging."""
        j = d.get("joints")
        p = d.get("joints_prev")
        dt = self.passed
        if j is None or p is None or not np.isfinite(dt) or dt <= 1e-4:
            return None
        hip_v = (j[dm.J_HIP] - p[dm.J_HIP]) / dt
        best = None
        best_score = 0.0
        for idx, wgt in self._LIMBS:
            v = (j[idx] - p[idx]) / dt - hip_v
            sp = float(math.hypot(float(v[0]), float(v[1])))
            if sp * wgt > best_score:
                best_score = sp * wgt
                best = (idx, v, sp)
        if best is None or best[2] < self.fig_h * 0.45:
            return None
        return best

    def _flame_emission(self, worlds, kick, dt):
        """Flames are THROWN by the dance: once per beat, mid-swing (when
        limbs are actually moving), the most prominent limb fires a plume
        along its own motion, inheriting its momentum. No limb swinging →
        the burst radiates from the body. A hot ember trickle follows the
        flourishing limb between bursts."""
        if kick:
            self._beat_no += 1
        thr = self.burst_threshold
        mag = float(
            np.clip((self.impulse - thr) / max(1.0 - thr, 0.05), 0.0, 1.0)
        )
        over = self.impulse >= thr
        burst = False
        amplified = False
        if kick and over:
            self._burst_window = 0.45
            if self._burst_timer < 0.0:
                self._burst_timer = 0.12  # surge peak, mid-swing
        else:
            self._burst_window = max(self._burst_window - dt, 0.0)
        # hit-pose sync: a stretch pose landing inside the burst window
        # becomes a HELD flourish with an amplified burst
        if self._hit_arrival:
            self._hit_arrival = False
            if self._burst_window > 0.0 and over:
                self._hold_t = 0.22 + 0.3 * mag
                self._burst_window = 0.0
                self._burst_timer = -1.0  # the hold owns this beat's burst
                burst = True
                amplified = True
                mag = float(np.clip(mag * 1.4 + 0.15, 0.0, 1.0))
        if self._burst_timer >= 0.0:
            self._burst_timer -= dt
            if self._burst_timer < 0.0:
                burst = True
        if self._flourish_j is not None:
            # a finished move guarantees its payoff burst
            burst = True
            mag = max(mag, 0.35)
            self._flourish_j = None
        embers = 0
        if over and not burst:
            self._ember_acc += (6.0 + 18.0 * mag) * dt
            embers = int(self._ember_acc)
            self._ember_acc -= embers
        if not burst and not embers:
            return
        count = (
            int(round(
                self.burst_size
                * (0.35 + (0.35 + 0.5 * self.burst_audio) * mag)
                * (1.6 if amplified else 1.0)
            ))
            if burst
            else embers
        )
        third = int(self._rng.integers(0, 3)) if burst else None
        # drive active sprays: stream flames from the (moving) limb so
        # the burst reads as a spray following the swing
        for sp in self._sprays[:]:
            i = sp["i"]
            if i >= len(worlds):
                self._sprays.remove(sp)
                continue
            d, joints = worlds[i]
            if joints is None or d["hidden"]:
                self._sprays.remove(sp)
                continue
            sp["acc"] += sp["rate"] * dt
            k = int(sp["acc"])
            sp["acc"] -= k
            if k > 0:
                jj = sp["joint"]
                prev = d.get("joints_prev")
                if prev is not None and self.passed > 1e-4:
                    v = (joints[jj] - prev[jj]) / self.passed
                else:
                    v = np.zeros(2, np.float32)
                sp_v = float(math.hypot(float(v[0]), float(v[1])))
                if sp_v > self.fig_h * 0.25:
                    ang = math.atan2(float(v[1]), float(v[0]))
                else:
                    parent = joints[dm.PARENT_J.get(jj, dm.J_NECK)]
                    ax = joints[jj] - parent
                    ang = (
                        math.atan2(float(ax[1]), float(ax[0]))
                        if (ax[0] or ax[1])
                        else -math.pi / 2
                    )
                self.flames.emit(
                    float(joints[jj][0]), float(joints[jj][1]),
                    k, sp["mag"], self.fig_h,
                    side=i, dir_rad=ang, spread=0.32,
                    third=sp["third"],
                    extra_vx=float(v[0]) * 0.65,
                    extra_vy=float(v[1]) * 0.65,
                )
            sp["t"] -= dt
            if sp["t"] <= 0.0:
                self._sprays.remove(sp)

        for i, (d, joints) in enumerate(worlds):
            if d["hidden"] or d["alpha"] < 0.3 or joints is None:
                continue
            prom = self._prominent_limb(d)
            if prom is None and burst and self._move is not None:
                # limb fallback: the move's accent limb still throws the
                # burst (aimed along the limb) even when it's paused —
                # e.g. mid flourish-hold — carrying its residual velocity
                aj = self._move["accent"]
                if aj is not None and aj >= 0:
                    jj = dm.MIRROR_J.get(aj, aj) if d.get("mirror") else aj
                    prev = d.get("joints_prev")
                    if prev is not None and self.passed > 1e-4:
                        v = (joints[jj] - prev[jj]) / self.passed
                    else:
                        v = np.zeros(2, np.float32)
                    parent = joints[dm.PARENT_J.get(jj, dm.J_NECK)]
                    axis = joints[jj] - parent
                    prom = (jj, v, float(math.hypot(*axis)))
                    ang_override = math.atan2(
                        float(axis[1]), float(axis[0])
                    ) if (axis[0] or axis[1]) else -math.pi / 2
                else:
                    ang_override = None
            else:
                ang_override = None
            if prom is not None:
                idx = prom[0]
                if burst:
                    dur = 0.5 if amplified else 0.3
                    self._sprays.append({
                        "i": i, "joint": int(idx), "t": dur,
                        "rate": count / dur, "mag": mag,
                        "third": third, "acc": 1.0,  # first puff now
                    })
                else:
                    v = prom[1]
                    self.flames.emit(
                        float(joints[idx][0]), float(joints[idx][1]),
                        count, mag, self.fig_h,
                        side=i,
                        dir_rad=math.atan2(float(v[1]), float(v[0])),
                        spread=0.8, third=third,
                        extra_vx=float(v[0]) * 0.5,
                        extra_vy=float(v[1]) * 0.5,
                    )
            elif burst:
                # no limb at all (radiate moves): the WHOLE outline burns
                bx, by = self._bone_points(joints)
                cx = float(np.mean(joints[:, 0]))
                cy = float(np.mean(joints[:, 1]))
                self.flames.emit_points(
                    bx, by, cx, cy, count, mag, self.fig_h,
                    side=i, third=third,
                )

    # ── transitions ─────────────────────────────────────────────────────

    def _handoff_snapshot(self):
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        if self._last_pts is None:
            return None
        px, py, grad, bright = self._last_pts
        if len(px) > SNAP_MAX:
            idx = np.linspace(0, len(px) - 1, SNAP_MAX).astype(np.int64)
            px, py, grad, bright = px[idx], py[idx], grad[idx], bright[idx]
        centers = [
            (d["slot_x"] + d["x_off"], self.hip_y + d["y_off"])
            for d in self._dancers
            if not d["hidden"]
        ]
        cx = float(np.mean([c[0] for c in centers])) if centers else self.cx
        cy = float(np.mean([c[1] for c in centers])) if centers else self.hip_y
        return {
            "src": "dancer",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": px.astype(np.float32),
            "py": py.astype(np.float32),
            "grad": grad.astype(np.float32),
            "bright": bright.astype(np.float32),
            "gradient": self._config.get("gradient"),
            "spin_sign": 0.0,
            "blob_size": float(self.blob_size),
            "flow": "out",
            "center_px": (cx, cy),
            "trail": self.trail,
            "native": {
                "dance": self._dance_name,
                "partner": len(self._dancers) > 1,
                "travel": self._travel,
                "rotation_shown": self._rot_shown,
            },
        }

    def deactivate(self):
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:  # noqa: BLE001 — never break teardown
            pass
        super().deactivate()

    def _adopt_handoff(self):
        virtual = self._virtual
        snap = None
        sibling = (
            getattr(virtual, "_transition_effect", None) if virtual else None
        )
        live = False
        if sibling is not None and sibling is not self and hasattr(
            sibling, "_handoff_snapshot"
        ):
            try:
                snap = sibling._handoff_snapshot()
                live = snap is not None
            except Exception:  # noqa: BLE001
                snap = None
        if snap is None and virtual is not None:
            snap = particle_handoff.take(getattr(virtual, "id", "") or "")
        if not snap or tuple(snap["dims"]) != (self.r_width, self.r_height):
            return
        if (
            snap.get("trail") is not None
            and self.trail is not None
            and snap["trail"].shape == self.trail.shape
        ):
            np.maximum(self.trail, snap["trail"], out=self.trail)
        if snap["src"] == "dancer":
            native = snap.get("native") or {}
            try:
                # rotation continuity yes; stage drift NO — a restored
                # travel could re-spawn the pair half offscreen
                self._rot_shown = float(
                    native.get("rotation_shown", self._rot_shown)
                )
            except Exception:  # noqa: BLE001
                pass
            return
        if snap["src"] == "pacman" and live:
            # pacman's chomp wipe owns the crossfade — let the Neo drop-in
            # entrance play instead of double-drawing its entities
            return
        # cross-type: keep the predecessor's colors until SpotFX repaints
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            self._apply_config(
                {"gradient": g}, validate=False, fire_event=False
            )
        if snap["src"] in ("radial", "eye") and live:
            frac = particle_handoff.transition_progress(virtual)
            if frac is not None and frac < particle_handoff.BLOOM_START:
                # radial owns phase 1 (collapse); the eye owns it too — it
                # closes its lids and the reveal lands at the bloom. We
                # assemble there, from the pinch / the iris.
                self._erupt_hold = {
                    "center": snap.get("center_px") or (self.cx, self.hip_y),
                    "t0": particle_handoff.now(),
                }
                for d in self._dancers:
                    d["hidden"] = True
                return
        self._start_formation(snap)

    def _start_formation(self, snap):
        """Predecessor particles fly into the dancers' bodies."""
        for d in self._dancers:
            # clearing a mid-flight stunt (the boot drop-in!) must also
            # reset its kinematics — a drop_in cleared while hovering at
            # -drop_h otherwise leaves y_off pointing above the panel and
            # the dancer dances off-screen forever
            d["stunt"] = None
            d["hidden"] = False
            d["x_off"] = 0.0
            d["y_off"] = 0.0
            d["rot_add"] = 0.0
            d["scale"] = 1.0
            d["override_w"] = 0.0
        targets = self._sample_targets()
        if targets is None:
            return
        tx, ty, tg = targets
        px = snap.get("px")
        py = snap.get("py")
        if px is None or len(px) == 0:
            c = snap.get("center_px") or (self.cx, self.hip_y)
            k = min(len(tx), FORM_CAP)
            ang = self._rng.uniform(0, 2 * math.pi, k)
            px = c[0] + np.cos(ang) * 2.0
            py = c[1] + np.sin(ang) * 2.0
        k = int(min(len(px), len(tx), FORM_CAP))
        if k <= 0:
            return
        src_idx = np.linspace(0, len(px) - 1, k).astype(np.int64)
        tgt_idx = np.linspace(0, len(tx) - 1, k).astype(np.int64)
        self.f_sx[:k] = np.asarray(px)[src_idx]
        self.f_sy[:k] = np.asarray(py)[src_idx]
        self.f_x[:k] = self.f_sx[:k]
        self.f_y[:k] = self.f_sy[:k]
        self.f_tx[:k] = tx[tgt_idx]
        self.f_ty[:k] = ty[tgt_idx]
        self.f_age[:k] = 0.0
        self.f_dur[:k] = self._rng.uniform(0.5, 0.85, k)
        self.f_grad[:k] = tg[tgt_idx]
        self.n_f = k
        self._form_alpha = 0.0

    def _sample_targets(self):
        """Bone sample points of the current pose(s), for formations."""
        if not self._dancers or self._move is None:
            return None
        pose, ppose, tilt, spin, pspin = self._seq_pose(0.5)
        xs, ys, gs = [], [], []
        for d in self._dancers:
            p = pose if d["role"] == "lead" else ppose
            pts = self._dancer_points(d, p, tilt, spin, pspin)
            if pts is None:
                continue
            bx, by = pts[0], pts[1]
            xs.append(bx)
            ys.append(by)
            gs.append(np.full(len(bx), d["grad_pos"], np.float32))
        if not xs:
            return None
        return (
            np.concatenate(xs),
            np.concatenate(ys),
            np.concatenate(gs),
        )

    def _update_out_mode(self):
        """Outgoing choreography, chosen by who is coming in."""
        virtual = self._virtual
        inc = particle_handoff.incoming_sibling(virtual, self)
        if self._out_mode is None:
            if inc is None:
                return
            name = getattr(inc, "NAME", None)
            if name in PARTICLE_SIBLINGS:
                self._out_mode = "dissolve"
                self._out_t0 = particle_handoff.now()
                for i, d in enumerate(self._dancers):
                    self._stunt(d, "exit_tuck", dur=2.5, delay=0.08 * i)
            elif name == "Radial":
                self._out_mode = "collapse"
                self._out_t0 = particle_handoff.now()
                self._out_center = (
                    self.r_width * float(inc._config.get("x_offset", 0.5)),
                    self.r_height * float(inc._config.get("y_offset", 0.5)),
                )
            elif name == "Pacman":
                self._out_mode = "flee"
                self._out_t0 = particle_handoff.now()
                for d in self._dancers:
                    x = d["slot_x"]
                    self._stunt(
                        d,
                        "run_off",
                        dur=6.0,
                        dir=1.0 if x >= self.r_width / 2 else -1.0,
                    )
            return
        if inc is None and getattr(virtual, "_transition_effect", None) is not self:
            # crossfade over (or switched back to us) — reset choreography
            for d in self._dancers:
                if d["stunt"] and d["stunt"]["kind"] in (
                    "run_off",
                    "exit_tuck",
                ):
                    d["stunt"] = None
                d["scale"] = 1.0
                d["x_off"] = 0.0
                d["y_off"] = 0.0
                d["rot_add"] = 0.0
                d["hidden"] = False
            self._out_mode = None

    def _out_alpha(self, virtual):
        """Global body fade for the outgoing choreography."""
        if self._out_mode is None:
            return 1.0
        frac = particle_handoff.transition_progress(virtual)
        if frac is None:
            frac = min(
                (particle_handoff.now() - self._out_t0)
                / particle_handoff.COLLAPSE_FALLBACK_S,
                1.0,
            )
        if self._out_mode == "dissolve":
            m = particle_handoff.PACMAN_MORPH_START
            return float(np.clip(1.0 - frac / m, 0.0, 1.0))
        if self._out_mode == "collapse":
            g = float(
                np.clip(frac / particle_handoff.GATHER_FRAC, 0.0, 1.0)
            )
            e = _smooth(g)
            # shrink + spiral every dancer into the radial's center
            for d in self._dancers:
                d["scale"] = 1.0 - 0.9 * e
                d["x_off"] = (self._out_center[0] - d["slot_x"]) * e
                d["y_off"] = (self._out_center[1] - self.hip_y) * e
                d["rot_add"] = 720.0 * e
            return float(np.clip((1.0 - g) / 0.45, 0.0, 1.0))
        return 1.0  # flee: the run-off stunt handles visibility

    # ── rendering ───────────────────────────────────────────────────────

    def _dancer_points(self, d, pose, tilt, spin, pspin):
        """World-space sample points for one dancer: computes joints then
        samples bones. Kept for formation targets; the draw loop uses the
        split _dancer_joints/_bone_points so the hand-hold IK can run
        between the two."""
        joints = self._dancer_joints(d, pose, tilt, spin, pspin, track=False)
        if joints is None:
            return None
        bx, by = self._bone_points(joints)
        return bx, by, joints

    def _dancer_joints(self, d, pose, tilt, spin, pspin, track=True):
        """World-space joints for one dancer (stored on d), or None.
        `track` keeps the previous frame's joints for limb velocities."""
        if track:
            d["joints_prev"] = d.get("joints")
        if d["hidden"] or d["alpha"] <= 0.01:
            d["joints"] = None
            return None
        h = self.fig_h * d["scale"]
        if h < 3.0:
            d["joints"] = None
            return None
        p = pose
        if d["override"] is not None and d["override_w"] > 0.0:
            w = min(d["override_w"], 1.0)
            p = p * (1.0 - w) + d["override"] * w
        # ── locomotion: bodies WALK to where they're going, never slide.
        # Horizontal velocity of the stage anchor drives a side-step gait
        # (alternating reach, swing-foot lift, step bob, lean) blended in
        # proportionally to speed.
        dance_l = _DANCES[self._dance_name]
        tgt = self._slot_x(d["slot"])
        d["slot_x"] += (tgt - d["slot_x"]) * min(3.0 * self.passed, 1.0)
        travel = getattr(self, "_travel_render", self._travel) * h
        anchor = d["slot_x"] + d["x_off"] + travel
        prev_anchor = d.get("anchor_prev")
        d["anchor_prev"] = anchor
        dt_l = self.passed
        if (
            dance_l["locomotion"]
            and not (self._move is not None and self._move["leap"])
            and prev_anchor is not None
            and np.isfinite(dt_l)
            and dt_l > 1e-4
            and d["stunt"] is None
            and d["override_w"] < 0.3
            and abs(tilt) < 5.0
        ):
            vx = (anchor - prev_anchor) / dt_l
            walk = float(np.clip(abs(vx) / (0.55 * h), 0.0, 1.0))
            if walk > 0.04:
                cadence = float(np.clip(abs(vx) / (0.32 * h), 1.2, 4.5))
                d["walk_ph"] = (
                    d.get("walk_ph", 0.0) + dt_l * cadence * 2.0 * math.pi
                )
                ph = d["walk_ph"]
                sgn = 1.0 if vx >= 0 else -1.0
                sw = math.sin(ph)
                amp = 15.0 * walk
                lift = 20.0 * walk
                p = p.copy()
                p[6] += sgn * amp * (0.5 + 0.5 * sw)      # r_leg reach
                p[5] -= sgn * amp * (0.5 - 0.5 * sw)      # l_leg reach
                p[8] += lift * max(0.0, sw)               # r swing lift
                p[7] += lift * max(0.0, -sw)              # l swing lift
                p[0] += sgn * 3.5 * walk                  # lean into it
                p[10] -= 0.014 * walk * abs(sw)           # step bob
        # move spins are 3D yaw turns (foreshortened inside the FK);
        # mirrored/together partners spin opposite, synced ones the same
        if not d.get("mirror"):
            yaw = spin
        elif _DANCES[self._dance_name]["partner"] == "sync":
            yaw = pspin
        else:
            yaw = -pspin
        yaw += d.get("yaw_add", 0.0)
        joints = dm.joint_xy(p, h, yaw_extra=yaw)
        # floor tilt (worm) pivots at the ground under the hip
        t_deg = -tilt if d.get("mirror") else tilt
        if abs(t_deg) > 0.01:
            self._rotate(joints, 0.0, dm.LEG_REACH * h, t_deg)
        # stage rotation (config angle, somersaults) stays in the image
        # plane. A tucked flip spins about the BALL's centroid so it
        # reads as a tight tumbling ball, not a wobble about the hip.
        wx = anchor
        if d["stunt"] is None:
            # safety net: whatever state got us here, a dancing figure
            # is never stranded offscreen (exits/stunts may leave)
            margin = 0.3 * h
            wx = float(np.clip(wx, margin, self.r_width - margin))
        wy = self.hip_y + d["y_off"]
        joints[:, 0] += wx
        joints[:, 1] += wy
        # rotation in WORLD space: tucked flips spin about their own ball
        # centroid; everything else rotates the WHOLE STAGE about the
        # panel center — positions and orientations turn as one unit, so
        # a rotated pair stays centered and correctly arranged
        rot = self._rot_shown + d["rot_add"]
        if abs(rot) > 0.01:
            st = d.get("stunt")
            if st is not None and st["kind"] in (
                "somersault", "exit_tuck", "tumble_off",
            ):
                self._rotate(
                    joints,
                    float(np.mean(joints[:, 0])),
                    float(np.mean(joints[:, 1])),
                    rot,
                )
            else:
                mid_y = (self.stage_top + self.stage_bottom) / 2.0
                self._rotate(joints, float(self.cx), mid_y, rot)
        d["joints"] = joints
        return joints

    @staticmethod
    def _bone_points(joints):
        """Sample every bone at sub-pixel spacing → (xs, ys)."""
        xs, ys = [], []
        for a, b in dm.BONES:
            ax, ay = joints[a]
            bx, by = joints[b]
            dist = math.hypot(bx - ax, by - ay)
            npts = max(int(dist / BONE_STEP), 1) + 1
            t = np.linspace(0.0, 1.0, npts, dtype=np.float32)
            xs.append(ax + (bx - ax) * t)
            ys.append(ay + (by - ay) * t)
        return np.concatenate(xs), np.concatenate(ys)

    def _hold_hands(self, dance):
        """Together dances: the pair really holds hands — both held arms
        are re-solved with two-link IK to a shared clasp point."""
        pair = dance.get("hold")
        move = self._move
        if (
            not pair
            or move is None
            or not move.get("hold")
            or len(self._dancers) < 2
            or self._quiet_q > 0.6
        ):
            return
        lead, part = self._dancers[0], self._dancers[1]
        if lead["stunt"] is not None or part["stunt"] is not None:
            return
        lj, pj = lead.get("joints"), part.get("joints")
        if lj is None or pj is None:
            return
        li = dm._JI[pair[0]]
        pi = dm._JI[pair[1]]
        m = (lj[li] + pj[pi]) / 2.0
        # clamp the clasp point into both arms' reach (anchored at each
        # hand's actual shoulder joint)
        arms = (
            (lj, li, self.fig_h * lead["scale"]),
            (pj, pi, self.fig_h * part["scale"]),
        )

        def _shoulder(joints, hand_i):
            return joints[dm.PARENT_J[dm.PARENT_J[hand_i]]]

        for _ in range(2):
            for joints, hand_i, h in arms:
                sh = _shoulder(joints, hand_i)
                reach = (dm.ARM_LEN + dm.FORE_LEN) * 0.97 * h
                t = m - sh
                dist = math.hypot(float(t[0]), float(t[1]))
                if dist > reach:
                    m = sh + t * (reach / dist)
        for joints, hand_i, h in arms:
            sh = _shoulder(joints, hand_i)
            a = dm.ARM_LEN * h
            b = dm.FORE_LEN * h
            t = m - sh
            dist = max(math.hypot(float(t[0]), float(t[1])), 1e-4)
            ux, uy = float(t[0]) / dist, float(t[1]) / dist
            cos_e = (a * a + dist * dist - b * b) / (2.0 * a * dist)
            cos_e = max(-1.0, min(1.0, cos_e))
            sin_e = math.sqrt(max(1.0 - cos_e * cos_e, 0.0))
            # elbows hang down: pick the perpendicular with +y
            px_, py_ = -uy, ux
            if py_ < 0:
                px_, py_ = -px_, -py_
            elbow_i = dm.PARENT_J[hand_i]
            joints[elbow_i] = (
                sh[0] + ux * a * cos_e + px_ * a * sin_e,
                sh[1] + uy * a * cos_e + py_ * a * sin_e,
            )
            joints[hand_i] = m

    @staticmethod
    def _rotate(pts, cx, cy, deg):
        r = math.radians(deg)
        c, s = math.cos(r), math.sin(r)
        x = pts[:, 0] - cx
        y = pts[:, 1] - cy
        pts[:, 0] = cx + x * c - y * s
        pts[:, 1] = cy + x * s + y * c

    def _kernel(self, radius):
        """Kernel offsets + weights for a splat radius, cached (the radius
        set is tiny: body/tips/head/burst sizes)."""
        key = round(float(radius), 2)
        k = self._kern_cache.get(key)
        if k is None:
            keep = self.k_dist <= radius
            k = (
                self.k_dx[keep],
                self.k_dy[keep],
                (1.0 - self.k_dist[keep] / (radius + 0.5)).astype(
                    np.float32
                ),
            )
            if len(self._kern_cache) > 32:
                self._kern_cache.clear()
            self._kern_cache[key] = k
        return k

    def _splat(self, frame, xs, ys, rgb, radius, weights=None):
        """Scatter-add one color at many points (fireworks kernel idiom)."""
        if len(xs) == 0:
            return
        k_dx, k_dy, k_w = self._kernel(radius)
        xi = np.round(xs).astype(np.int32)
        yi = np.round(ys).astype(np.int32)
        px = (xi[:, None] + k_dx[None, :]).ravel()
        py = (yi[:, None] + k_dy[None, :]).ravel()
        valid = (
            (px >= 0)
            & (px < self.r_width)
            & (py >= 0)
            & (py < self.r_height)
        )
        idx = (py * self.r_width + px)[valid]
        kw = np.broadcast_to(
            k_w[None, :], (len(xi), len(k_dx))
        ).ravel()[valid]
        if weights is not None:
            kw = kw * np.repeat(
                weights.astype(np.float32), len(k_dx)
            )[valid]
        cells = self.r_width * self.r_height
        for ch in range(3):
            frame[..., ch] += np.bincount(
                idx, weights=kw * float(rgb[ch]), minlength=cells
            ).reshape(self.r_height, self.r_width).astype(np.float32)

    def _splat_multi(self, frame, x0, y0, x1, y1, rgbs, radius):
        """Per-particle colors with a 2-step motion smear (bursts)."""
        n = len(x1)
        if n == 0:
            return
        k_dx, k_dy, k_w = self._kernel(radius)
        fr = np.arange(1, SUB + 1, dtype=np.float32) / SUB
        xs = (x0[:, None] + (x1 - x0)[:, None] * fr).ravel()
        ys = (y0[:, None] + (y1 - y0)[:, None] * fr).ravel()
        xi = np.round(xs).astype(np.int32)
        yi = np.round(ys).astype(np.int32)
        pn = len(xi)
        kn = len(k_dx)
        px = (xi[:, None] + k_dx[None, :]).ravel()
        py = (yi[:, None] + k_dy[None, :]).ravel()
        valid = (
            (px >= 0)
            & (px < self.r_width)
            & (py >= 0)
            & (py < self.r_height)
        )
        idx = (py * self.r_width + px)[valid]
        kw = np.broadcast_to(k_w[None, :], (pn, kn)).ravel()[valid]
        rgb_sub = rgbs / SUB
        cells = self.r_width * self.r_height
        for ch in range(3):
            per_pt = np.repeat(rgb_sub[:, ch], SUB)
            vals = (
                np.broadcast_to(per_pt[:, None], (pn, kn)).ravel()[valid]
                * kw
            )
            frame[..., ch] += np.bincount(
                idx, weights=vals, minlength=cells
            ).reshape(self.r_height, self.r_width).astype(np.float32)

    # ── main loop ───────────────────────────────────────────────────────

    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        virtual = self._virtual

        if self._handoff_pending:
            self._handoff_pending = False
            try:
                self._adopt_handoff()
            except Exception:  # noqa: BLE001 — a bad snapshot must not kill us
                _LOGGER.exception("dancer handoff adoption failed")

        # held assembly while a radial predecessor collapses
        if self._erupt_hold is not None:
            hold = self._erupt_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._erupt_hold = None
            elif (
                frac is None
                or frac >= particle_handoff.BLOOM_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._erupt_hold = None
                for d in self._dancers:
                    d["hidden"] = False
                self._start_formation(
                    {"px": None, "py": None, "center_px": hold["center"]}
                )

        kick = self._update_clock(dt)
        self._cld_step(dt)

        # pending dance with no beats: apply on a wall timer so a quiet
        # room still honors the change (and still blends)
        if self._pending_dance is not None:
            self._dance_wall_t += dt
            if self._dance_wall_t > 2.5:
                self._dance_name = self._pending_dance
                self._pending_dance = None
                self._seq_start(self._dance_name)

        # ── surge clock: the dance progresses STEADILY at base_speed and
        # lunges forward on every beat — harder on loud hits, so big
        # flourishes accelerate INTO the flame bursts
        if kick and not self._suppress:
            self._surge = min(
                self._surge
                + (1.1 + 2.8 * min(self.impulse, 1.0))
                * self.dance_intensity,
                5.5,
            )
        self._surge *= 0.5 ** (dt / 0.14)
        dance_now = _DANCES[self._dance_name]
        tempo_mult = dance_now["tempo"] * (2 if self.half_beat else 1)
        steps_per_s = 1.0 / max(self._period * tempo_mult, 0.15)
        # steady rate rides the music's sustained energy: a hot,
        # fast-paced track accelerates the whole dance (the clock is
        # already BPM-proportional; surges add the per-beat lunges)
        heat = 0.75 + 0.85 * min(self.impulse, 1.0)
        adv = (
            steps_per_s
            * (0.55 * self.base_speed * heat + self._surge)
            * (1.0 - _smooth(self._quiet_q))
            * dt
        )
        if self._hold_t > 0.0:
            # flourish hold: freeze on the hit pose (groove keeps the
            # body alive) while the amplified burst blooms
            self._hold_t -= dt
            adv *= 0.05
        self._step_u += adv
        guard = 0
        while self._step_u >= 1.0 and guard < 4:
            self._step_u -= 1.0
            self._seq_advance()
            guard += 1

        self._update_out_mode()
        self._process_partner_pending()
        self._update_stunts(dt)

        # decay stage drift back to the slot when the move isn't traveling
        if self._move is not None and not self._move["travel"]:
            self._travel *= math.exp(-0.4 * dt)
        # travel renders CONTINUOUSLY: the committed base plus this
        # step's share scaled by step progress — no per-beat teleports
        mv = self._move
        share = (
            mv["travel"] / len(mv["keys"])
            if (mv is not None and mv["travel"])
            else 0.0
        )
        self._travel_render = self._travel + share * float(
            np.clip(self._step_u, 0.0, 1.0)
        )
        # travel range: a solo dancer may sweep (walk/leap) across the
        # whole panel; a pair keeps its formation inside the edges
        sep = self._sep() if len(self._dancers) > 1 else 0.0
        self._travel_lim = max(
            0.25,
            (self.r_width / 2.0 - sep - 0.4 * self.fig_h)
            / max(self.fig_h, 1.0),
        )
        self._travel_render = float(
            np.clip(self._travel_render, -self._travel_lim,
                    self._travel_lim)
        )

        # pose
        dance = _DANCES[self._dance_name]
        pose, ppose, tilt, spin, pspin = self._seq_pose(self._step_u)
        if self._quiet_q > 0.001:
            q = _smooth(self._quiet_q)
            idle = dance["idle"].copy()
            sway = math.sin(self.now * 0.8) * 3.0
            idle[1] += sway
            idle[2] -= sway
            idle[10] += math.sin(self.now * 1.6) * 0.008
            pose = pose * (1.0 - q) + idle * q
            ppose = ppose * (1.0 - q) + dm.mirror_vec(idle) * q
            tilt *= 1.0 - q

        pose, ppose = self._apply_groove(pose, ppose, dance)

        out_alpha = self._out_alpha(virtual)

        # render bodies
        frame = np.zeros((self.r_height, self.r_width, 3), np.float32)
        flash = max(0.0, 0.25 - (self.now - self._last_kick_t)) / 0.25
        body_gain = (
            0.72
            + min(self.brightness_audio * self.impulse, 0.45)
            + 0.18 * flash
        )
        worlds = []
        pts_export = []
        for d in self._dancers:
            p = ppose if d.get("mirror") else pose
            self._dancer_joints(d, p, tilt, spin, pspin)
        if dance["partner"] == "together":
            self._hold_hands(dance)
        for d in self._dancers:
            joints = d.get("joints")
            if joints is None:
                worlds.append((d, None))
                continue
            bx, by = self._bone_points(joints)
            worlds.append((d, joints))
            a = d["alpha"] * out_alpha
            if self._form_alpha is not None:
                a *= self._form_alpha
            if a <= 0.01:
                continue
            # the whole figure is ONE solid color (head included) — the
            # accent third color only shows in stunt flashes and bursts.
            # Dark palette tails can't make a dancer invisible: walk the
            # sample point toward the gradient center until it's bright.
            gp = d["grad_pos"]
            base = self.get_gradient_color(gp).astype(np.float32)
            steps = 0
            while float(base.max()) < 30.0 and steps < 5:
                gp = gp + (0.5 - gp) * 0.35
                base = self.get_gradient_color(gp).astype(np.float32)
                steps += 1
            body_rgb = base * (body_gain * a)
            self._splat(frame, bx, by, body_rgb, self.blob_size * 0.75)
            h = self.fig_h * d["scale"]
            head_r = dm.HEAD_RADIUS * h + self.blob_size * 0.4
            self._splat(
                frame,
                joints[[dm.J_HEAD], 0],
                joints[[dm.J_HEAD], 1],
                body_rgb,
                min(head_r, KERNEL_R),
            )
            if a > 0.25:
                pts_export.append(
                    (
                        bx,
                        by,
                        np.full(len(bx), d["grad_pos"], np.float32),
                        np.full(len(bx), body_gain * a, np.float32),
                    )
                )

        if pts_export:
            self._last_pts = tuple(
                np.concatenate([p[i] for p in pts_export])
                for i in range(4)
            )

        # flames
        if not self._suppress and self._out_mode is None:
            self._flame_emission(worlds, kick, dt)
        mid_x = None
        if (
            len(self._dancers) > 1
            and _DANCES[self._dance_name]["partner"] in dm.MIRROR_MODES
        ):
            d0, d1 = self._dancers[0], self._dancers[1]
            mid_x = (
                d0["slot_x"] + d0["x_off"] + d1["slot_x"] + d1["x_off"]
            ) / 2.0
        self.flames.step(
            dt, self.now, self.fig_h, self.r_width, self.r_height,
            mid_x=mid_x,
        )
        self.flames.render(
            frame,
            self.get_gradient_color_vectorized1d,
            self.accent_rgb,
            self._kernel,
            self.now,
            self.impulse,
        )

        # formation particles fly home; body fades in as they arrive
        if self._form_alpha is not None and self.n_f:
            k = self.n_f
            self.f_age[:k] += dt
            prog = np.clip(self.f_age[:k] / self.f_dur[:k], 0.0, 1.0)
            e = prog * prog * (3.0 - 2.0 * prog)
            self.f_x[:k] = self.f_sx[:k] + (self.f_tx[:k] - self.f_sx[:k]) * e
            self.f_y[:k] = self.f_sy[:k] + (self.f_ty[:k] - self.f_sy[:k]) * e
            rgbs = self.get_gradient_color_vectorized1d(
                self.f_grad[:k]
            ).astype(np.float32) * (1.0 - 0.5 * e)[:, None]
            self._splat_multi(
                frame, self.f_x[:k], self.f_y[:k], self.f_x[:k],
                self.f_y[:k], rgbs, max(self.blob_size * 0.6, 1.0),
            )
            self._form_alpha = float(np.mean(e))
            if np.all(prog >= 1.0):
                self._form_alpha = None
                self.n_f = 0
        elif self._form_alpha is not None:
            self._form_alpha = None

        # trails
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))
        np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
