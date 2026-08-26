import logging

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
from fx.effects.audio import AudioReactiveEffect
from fx.effects.twod import Twod
from fx.utils import nonlinear_log
from fx.virtuals import virtual_id_validator

_LOGGER = logging.getLogger(__name__)

# div zero protection
epsilon = 1e-6

# fallback source when none is configured or the configured one is missing
DEFAULT_SOURCE_VIRTUAL = "radial-dummy"

# narrowest band the implode warp compresses the pattern into (norm radius)
IMPLODE_MIN_W = 0.10

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
CHARGE_SPIN_REV_S = 0.9  # extra rev/s at full charge
LULL_IMPLODE_S = 1.2     # implode fallback when no lull ramp arrives
DROP_BLOOM_S = 0.5       # bloom fallback when no drop ramp arrives


class Radial2d(Twod):
    NAME = "Radial"
    CATEGORY = "Matrix"
    # add keys you want hidden or in advanced here
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + [
        "test",
        "background_color",
        "background_brightness",
        "background_mode",
    ]
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + ["phase", "phase_progress"]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "source_virtual",
                description="The virtual from which to source the 1d pixels",
                default=DEFAULT_SOURCE_VIRTUAL,
            ): virtual_id_validator,
            vol.Optional(
                "edges",
                description="Edges count of mapping",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=8)),
            vol.Optional(
                "x_offset",
                description="X offset for center point",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "y_offset",
                description="Y offset for center point",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "twist",
                description="twist that thing",
                default=0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-4, max=4)),
            vol.Optional(
                "polygon",
                description="Use polygonal or radial lobes",
                default=True,
            ): bool,
            vol.Optional(
                "rotation",
                description="static rotation",
                default=0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=0.5)),
            vol.Optional(
                "spin",
                description="Spin the radial effect to the audio impulse",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "base_rotation",
                description=(
                    "Quiet base rotation FLOOR, in revolutions per second "
                    "(linear and absolute — unlike Spin, which is a squared "
                    "gain on live audio). The pattern never turns slower "
                    "than this; whenever the audio's own drive is faster, "
                    "the reactive spin takes over unchanged. 0 disables it "
                    "(the vendored behaviour)."
                ),
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "frequency_range",
                description="Frequency range for the spin impulse",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "star",
                description="pull polygon points to star shape",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
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
        self.bar = 0
        self.virtual = None
        self.spin_total = 0.0
        # revolutions the AUDIO callback has added since the last rendered
        # frame — read (and zeroed) only by _base_rotation_step
        self._reactive_advance = 0.0
        self.max_radius = None
        # particle ⇄ radial handoff state (here, NOT do_once, so it survives
        # config-patch grid rebuilds)
        self._handoff_pending = True
        self._reveal = None    # incoming bloom: {"mode": "transition"|"timed", ...}
        self._mask_out = None  # outgoing collapse: {"frac0": float}
        super().__init__(ledfx, config)

    def config_updated(self, config):
        super().config_updated(config)
        self.source_virtual = None
        self.edges = self._config.get("edges")
        self.x_offset = self._config.get("x_offset")
        self.y_offset = self._config.get("y_offset")
        self.twist = self._config.get("twist")
        self.polygon = self._config.get("polygon")
        self.rotation = self._config.get("rotation")
        # bring impulse spin injection into a reasonable range of control
        self.spin = nonlinear_log(self._config.get("spin"), 2) / 10.0
        # LINEAR rev/s, deliberately NOT put through nonlinear_log: this is an
        # absolute floor a human sets in a plain unit, not a gain to shape.
        self.base_rotation = float(self._config.get("base_rotation", 0.0) or 0.0)
        self.power_func = AudioReactiveEffect.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.star = self._config.get("star")

        # charge/lull/drop: edge-detect the phase key. State is created here
        # (not __init__) because config_updated runs first, during
        # super().__init__; the pending flag is consumed in draw.
        new_phase = self._config.get("phase", "none")
        self.phase_progress = float(self._config.get("phase_progress", 0.0))
        if not hasattr(self, "_phase"):
            # creation baseline: a stale persisted phase key must never
            # edge-fire choreography on a fresh instance
            self._phase = "none"
            self._phase_t = 0.0
            self._phase_pending = None
            self._phase_done_t = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

    def audio_data_updated(self, data):
        self.impulse = getattr(data, self.power_func)()
        delta = self.impulse * self.spin
        self._reactive_advance += delta
        self.spin_total += delta
        self.spin_total %= 1.0  # keep it in [0, 1)

    def do_once(self):
        super().do_once()

        # Compute center based on normalized offsets
        self.cx = self.r_width * self.x_offset
        self.cy = self.r_height * self.y_offset

        # Create fixed coordinate grid
        y, x = np.indices((self.r_height, self.r_width))
        self.dx = x - self.cx
        self.dy = y - self.cy

        # Precompute base radius from center
        self.radius_base = np.sqrt(self.dx**2 + self.dy**2)

        # Compute maximum radius (used for normalization)
        # Add a small epsilon to avoid division by zero or crossing zero artifacts
        radius_stretch = 1.0 + epsilon
        self.max_radius = np.max(self.radius_base) * radius_stretch

    def _ensure_source(self):
        if not self.source_virtual:
            # Try to fetch source_virtual (e.g. on startup race)
            virtuals = self._ledfx.virtuals._virtuals
            self.source_virtual = virtuals.get(
                self._config["source_virtual"]
            )
            if self.source_virtual is None:
                # Configured source missing or "unknown" (stale saved
                # configs) — fall back so we never render black forever.
                self.source_virtual = virtuals.get(DEFAULT_SOURCE_VIRTUAL)

    def _source_scroll_sign(self):
        """+1 if the source strip's content drifts toward higher index
        (radial rings expand outward), -1 if inward. Only Melt is
        direction-aware; everything else assumes outward."""
        try:
            self._ensure_source()
            eff = getattr(self.source_virtual, "active_effect", None)
            if eff is not None and getattr(eff, "NAME", "") == "Melt":
                return -1.0 if eff._config.get("flip") else 1.0
        except Exception:
            pass
        return 1.0

    def _handoff_snapshot(self):
        """Neutral handoff snapshot (see particle_handoff module): radial has
        no particles to hand over, but exports its center, flow direction and
        apparent-rotation sign so a particle successor can erupt from the
        center continuing the spin. None before the first render."""
        if self.max_radius is None:
            return None
        tw = self._config.get("twist") or 0.0
        spin = 0.0
        if tw:
            spin = float(
                np.sign(tw)
                * self._source_scroll_sign()
                * particle_handoff.RADIAL_SPIN_PARITY
            )
        empty = np.empty(0, dtype=np.float32)
        return {
            "src": "radial",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": empty,
            "py": empty.copy(),
            "grad": empty.copy(),
            "bright": empty.copy(),
            "gradient": None,
            "spin_sign": spin,
            "blob_size": None,
            "flow": "out",
            "center_px": (float(self.cx), float(self.cy)),
            "trail": None,
        }

    def deactivate(self):
        # Leave state behind for a particle successor (effect switch)
        # before the base clears _virtual.
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        super().deactivate()

    def _adopt_handoff(self):
        """First-draw adoption from a particle predecessor: continue its
        rotation (patch our twist sign) and arm the center-out bloom."""
        snap = None
        virtual = self._virtual
        sibling = (
            getattr(virtual, "_transition_effect", None) if virtual else None
        )
        live = False
        if sibling is not None and sibling is not self and hasattr(
            sibling, "_handoff_snapshot"
        ):
            try:
                snap = sibling._handoff_snapshot()
            except Exception:
                snap = None
            live = snap is not None
        if snap is None and virtual is not None:
            snap = particle_handoff.take(getattr(virtual, "id", "") or "")
        # src gate keeps radial→radial recreations (and anything else)
        # from replaying the bloom
        if not snap or snap.get("src") not in (
            "orbits",
            "fish",
            "blackhole",
            "fireworks",
            "squiggles",
            "dancer",
            "eye",
        ):
            return
        if tuple(snap["dims"]) != (self.r_width, self.r_height):
            return
        # apparent rotation = sign(twist) × source scroll; pick the twist
        # sign that continues the particles' spin (magnitude stays ours)
        spin_sign = float(snap.get("spin_sign") or 0.0)
        tw = self._config.get("twist") or 0.0
        if spin_sign and tw:
            want = np.sign(
                spin_sign
                * self._source_scroll_sign()
                * particle_handoff.RADIAL_SPIN_PARITY
            )
            if np.sign(tw) != want:
                # sanctioned in-render config path (we hold the effect lock);
                # one-time — never patch config per frame here
                self._apply_config(
                    {"twist": abs(tw) * want},
                    validate=False,
                    fire_event=False,
                )
        if live and particle_handoff.transition_progress(virtual) is not None:
            # two-phase choreography driven by the crossfade counters
            self._reveal = {"mode": "transition"}
        else:
            # no-transition path: short standalone bloom
            self._reveal = {"mode": "timed", "t": 0.0}

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: the rotation accelerates in the direction
    # already set; lull: the pattern implodes to a held center point (same
    # warp as the transition implode, standalone timing); drop: it blooms
    # back out of the center, then `phase` self-resets to "none".

    def _phase_step(self, dt):
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._phase = pend
                self._phase_t = 0.0
                self._phase_done_t = None
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — the pattern quietly blooms back out
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "radial: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            return
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        if self._phase == "charge":
            # apparent-direction sign: the audio spin's sign if it has one,
            # else the twist's (rotation-by-twist), else clockwise
            sign = (
                float(np.sign(self._config.get("spin") or 0.0))
                or float(np.sign(self._config.get("twist") or 0.0))
                or 1.0
            )
            # ease-in: spin-up maxes AT the ramp end
            self.spin_total = (
                self.spin_total + sign * CHARGE_SPIN_REV_S * p * p * dt
            ) % 1.0
        elif self._phase == "drop":
            done = max(p, min(self._phase_t / DROP_BLOOM_S, 1.0))
            if done >= 1.0:
                self._phase = "none"
                # sanctioned in-render config path (under the effect lock);
                # self-reset so an identical later drop write edges again
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _base_rotation_step(self, dt):
        """DEVIATION (fx/VENDOR.md #22): a quiet BASE ROTATION floor.

        Semantics are a FLOOR, not a sum:

            effective rev/s = max(base_rotation, reactive rev/s)

        so in silence the pattern turns steadily at ``base_rotation``, and
        the instant the audio's own drive is faster the reactive spin owns
        the motion COMPLETELY UNCHANGED — which is what preserves the
        existing reactivity exactly at every peak. (A summed design would
        speed every peak up slightly; it is a one-line change here if that
        is ever preferred.)

        WHERE it advances is load-bearing: the vendored effect's only motion
        source is ``audio_data_updated``, and audio callbacks stop entirely
        when the capture pipeline stalls or the effect is left unsubscribed
        — a base term living there would stall with them, which is exactly
        the "quiet" case this exists for. So it rides the RENDER clock
        (``self.passed``) in ``draw`` instead, and holds with zero audio
        frames.

        DIRECTION follows the current one and never fights it: the sign
        ladder is the same one the charge phase already uses — the audio
        spin's sign (which is what the spin_sign/Flip machinery writes),
        else the twist's, else clockwise.
        """
        # drain unconditionally: the accumulator must never carry a stale
        # frame's advance across a base_rotation=0 stretch
        reactive = self._reactive_advance
        self._reactive_advance = 0.0
        if self.base_rotation <= 0.0 or dt <= 0.0:
            return
        sign = (
            float(np.sign(self._config.get("spin") or 0.0))
            or float(np.sign(self._config.get("twist") or 0.0))
            or 1.0
        )
        want = self.base_rotation * dt          # revolutions owed this frame
        got = reactive * sign                   # revolutions the audio made,
        #                                         measured along `sign`
        if want > got:
            self.spin_total = (
                self.spin_total + sign * (want - got)
            ) % 1.0

    def _phase_warp(self):
        """Standalone lull implode / drop bloom warp, when no crossfade
        choreography owns the screen. Returns (warp, bg_alpha) or None."""
        if self._phase == "lull":
            # progress-driven once it moves (hand-scrubbable in the LedFX
            # UI); the wall-clock fallback only runs while progress sits at 0
            # so a lost ramp still implodes
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            s = p if p > 0.0 else min(self._phase_t / LULL_IMPLODE_S, 1.0)
            e = s * s * (3.0 - 2.0 * s)
            return (0.0, 1.0 - e * (1.0 - IMPLODE_MIN_W)), 1.0 - e
        if self._phase == "drop":
            s = max(
                float(np.clip(self.phase_progress, 0.0, 1.0)),
                min(self._phase_t / DROP_BLOOM_S, 1.0),
            )
            e = s * s * (3.0 - 2.0 * s)
            return (0.0, max(e, 1e-3)), e
        return None

    def draw(self):
        self._ensure_source()

        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        dt = float(self.passed) if np.isfinite(self.passed) else 1.0 / 60.0
        dt = min(max(dt, 0.0), 0.1)
        self._phase_step(dt)
        self._base_rotation_step(dt)

        virtual = self._virtual
        feather = particle_handoff.REVEAL_FEATHER
        gather = particle_handoff.GATHER_FRAC

        # ── outgoing "suck in": we are the crossfade sibling and a particle
        # effect is coming in — collapse the pattern into the center
        if self._mask_out is None:
            inc = particle_handoff.incoming_sibling(virtual, self)
            if inc is not None and getattr(inc, "NAME", None) in (
                "Orbits",
                "Blackhole",
                "Fireworks",
                "Squiggles",
                "Dancer",
            ):
                # incoming infall blackhole with an event horizon: implode
                # down to the horizon RING (the pattern compresses into that
                # disc and hands over), not all the way to a point
                floor = 0.0
                if getattr(inc, "NAME", None) == "Blackhole":
                    try:
                        if (
                            inc.horizon_scale > 0
                            and not inc._config.get("reverse")
                        ):
                            sx = getattr(inc, "sx", None)
                            sy = getattr(inc, "sy", None)
                            if sx is not None and sy is not None:
                                rh_px = (
                                    inc.horizon_scale * (sx + sy) / 2.0
                                )
                                floor = min(
                                    rh_px / self.max_radius, 0.9
                                )
                    except Exception:
                        floor = 0.0
                self._mask_out = {
                    "frac0": particle_handoff.transition_progress(virtual)
                    or 0.0,
                    "floor": floor,
                }
                self._reveal = None

        # warp = (origin, scale): the pattern is sampled at
        # u = origin + (norm_radius - origin) / scale. Bloom: origin 0,
        # scale grows 0→1 — the pattern stretches out of the center.
        # Implode: origin = the incoming horizon ring (0 = a point) and
        # scale shrinks 1→IMPLODE_MIN_W — everything INSIDE the ring
        # expands out to it while everything OUTSIDE collapses onto it,
        # the whole pattern converging into a narrow band at the ring.
        # bg_alpha fades the background color in/out as its own transition.
        warp = None
        bg_alpha = 0.0
        pat_alpha = 1.0
        bloom_start = particle_handoff.BLOOM_START
        if self._mask_out is not None:
            frac = particle_handoff.transition_progress(virtual)
            if (
                frac is None
                or getattr(virtual, "_transition_effect", None) is not self
            ):
                self._mask_out = None
            else:
                f0 = self._mask_out["frac0"]
                floor = self._mask_out.get("floor", 0.0)
                # implode lands exactly when the successor erupts — no dead
                # air between touchdown and the burst
                s = np.clip(
                    (frac - f0) / max(bloom_start - f0, 1e-3), 0.0, 1.0
                )
                e = s * s * (3.0 - 2.0 * s)
                if s >= 1.0:
                    if floor <= 0.0:
                        # fully imploded — the erupting particles own the rest
                        return
                    # compressed into the horizon band: dissolve as the
                    # blackhole's burst takes over (a static hold reads as
                    # a hang)
                    diss = np.clip(
                        (frac - bloom_start) / 0.25, 0.0, 1.0
                    )
                    if diss >= 1.0:
                        return
                    warp = (floor, IMPLODE_MIN_W)
                    bg_alpha = 0.0
                    pat_alpha = 1.0 - float(diss)
                else:
                    warp = (floor, 1.0 - e * (1.0 - IMPLODE_MIN_W))
                    bg_alpha = 1.0 - e       # background fades away with it
        elif self._reveal is not None:
            if self._reveal["mode"] == "transition":
                if getattr(virtual, "_transition_effect", None) is self:
                    # interrupted mid-bloom: we're the outgoing side now
                    self._reveal = None
                else:
                    frac = particle_handoff.transition_progress(virtual)
                    if frac is None:
                        # crossfade over. The counter almost never reads a
                        # full 1.0 before the sibling clears, so a bloom
                        # that visibly started is simply DONE — replaying
                        # it on the timer would explode twice. Only fall
                        # back to the timer if it never started (sibling
                        # died during phase 1).
                        if self._reveal.get("p", 0.0) > 0.0:
                            self._reveal = None
                        else:
                            self._reveal = {"mode": "timed", "t": 0.0}
                    elif frac < bloom_start:
                        # the collapsing particles own the early phase
                        return
                    else:
                        p2 = (frac - bloom_start) / (1.0 - bloom_start)
                        e = p2 * p2 * (3.0 - 2.0 * p2)
                        self._reveal["p"] = e
                        warp = (0.0, max(e, 1e-3))  # pattern stretches out
                        bg_alpha = e                # background fades in
                        if frac >= 1.0:
                            self._reveal = None
            if self._reveal is not None and self._reveal["mode"] == "timed":
                self._reveal["t"] += self.passed
                p = min(
                    self._reveal["t"] / particle_handoff.REVEAL_FALLBACK_S,
                    1.0,
                )
                e = p * p * (3.0 - 2.0 * p)
                warp = (0.0, max(e, 1e-3))
                bg_alpha = e
                if p >= 1.0:
                    self._reveal = None

        # charge/lull/drop: the standalone lull implode / drop bloom, only
        # when no crossfade choreography is already warping the pattern
        if warp is None:
            phase_warp = self._phase_warp()
            if phase_warp is not None:
                warp, bg_alpha = phase_warp

        if self.source_virtual and hasattr(
            self.source_virtual, "assembled_frame"
        ):
            pixels_in = self.source_virtual.assembled_frame

            # Use precomputed geometry
            dx = self.dx
            dy = self.dy
            radius = self.radius_base.copy()

            # Compute rotation + spin as one angle in radians
            rotate_and_spin = (self.spin_total + self.rotation) % 1.0
            theta = rotate_and_spin * 2 * np.pi

            # Angle and rotation
            angle = np.arctan2(dy, dx)
            angle -= theta
            angle_norm = (angle + np.pi) / (2 * np.pi)  # [0, 1)

            # Radius modulation based on edges
            if self.edges == 1:
                ux = np.cos(theta)
                uy = np.sin(theta)
                radius = np.abs(dx * ux + dy * uy)
            elif self.edges == 2:
                cos_angle = np.cos(angle)
                sin_angle = np.sin(angle)
                modulation = np.sqrt(cos_angle**2 + 0.25 * sin_angle**2)
                radius *= modulation
            elif self.edges >= 3:
                if not self.polygon:
                    modulation = np.cos((self.edges * angle) / 2)
                    radius *= np.abs(modulation)
                else:
                    a = np.pi * 2 / self.edges
                    half_a = a / 2
                    angle_mod = (angle + half_a) % a - half_a
                    polygon_radius = np.cos(np.pi / self.edges) / np.clip(
                        np.cos(angle_mod), epsilon, None
                    )

                    # Optional starburst shaping
                    if self.star != 0:
                        ripple = 1 + self.star * np.cos(self.edges * angle)
                        polygon_radius *= ripple
                    radius /= polygon_radius

            # Normalize and apply twist
            norm_radius = radius / self.max_radius
            if warp is not None:
                # explosion / implosion warp: sample the pattern at
                # u = origin + (norm - origin)/scale. Origin 0 = zoom from
                # the center (bloom); origin = horizon ring = two-sided
                # convergence onto the ring (implode).
                origin, wscale = warp
                u = origin + (norm_radius - origin) / max(wscale, 1e-3)
                twist_index = (u + self.twist * angle_norm) % 1.0
            else:
                twist_index = (norm_radius + self.twist * angle_norm) % 1.0

            # Map to strip
            strip = pixels_in.clip(0, 255).astype(np.uint8)
            N = len(strip)
            indices = np.clip((twist_index * N).astype(np.int32), 0, N - 1)

            # Fill image
            rgb_array = strip[indices]
            if warp is not None:
                # the pattern only exists for u in [0, 1] (feathered both
                # ends); elsewhere show the background color, itself fading
                # with bg_alpha — the bg is a plain fade, not part of the
                # explosion
                edge = (
                    np.clip((1.0 + feather - u) / feather, 0.0, 1.0)
                    * np.clip((u + feather) / feather, 0.0, 1.0)
                ).astype(np.float32)[..., None]
                bg = np.asarray(
                    getattr(self, "_bg_color", np.zeros(3)),
                    dtype=np.float32,
                )
                rgb_array = (
                    rgb_array.astype(np.float32) * (edge * pat_alpha)
                    + bg[None, None, :] * (1.0 - edge) * bg_alpha
                ).astype(np.uint8)
            image = Image.fromarray(rgb_array, mode="RGB")
            self.matrix.paste(image)
