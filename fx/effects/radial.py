import logging

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
from fx.effects import lull_dark, lull_handoff, phase_grammar
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

# Admiral order, 2026-10-06 ("reduce the maximum speed of rotation of Star
# by 20 percent"): ONE scale applied to every source that contributes to
# Star's rotation speed, so the *ceiling* — not just a default — drops by
# a uniform 20% everywhere it can be reached. Before this change the
# reactive ceiling (spin config at its own max 1.0, full audio impulse)
# was 6 rev/s (see radial-effect skill / AGENTS.md: rev/s = 6 × impulse ×
# spin²); after, 4.8 rev/s. A binding/config already set to spin's own
# max (1.0) reaches the new, lower ceiling automatically — the scale is
# applied to the OUTPUT, never to spin's own [-1, 1] input range, so
# nothing about how a binding reaches "max" needs to change.
ROTATION_SPEED_SCALE = 0.8

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
# extra rev/s at full charge — scaled by ROTATION_SPEED_SCALE (was 0.9)
CHARGE_SPIN_REV_S = 0.9 * ROTATION_SPEED_SCALE
LULL_IMPLODE_S = 1.2     # implode fallback when no lull ramp arrives
DROP_BLOOM_S = 0.5       # bloom fallback when no drop ramp arrives

# ── THE STAR PLAN (2026-10-13, data/star-plan/report.md; the Admiral: "Use
# lull b, drop d 3"). Read the "STAR'S OWN LULL AND DROP" block above
# `_lull_bands` before touching any of these.
#
# LULL B — the bands fall in as particles. `lull_mode` "bands" (the
# default) / "implode" (today's warp, kept selectable).
LULL_MODES = ("bands", "implode")
DEFAULT_LULL_MODE = "bands"
DEFAULT_LULL_CORE_U = 0.14   # a falling piece is swallowed by the core here
DEFAULT_LULL_PIECE_TAU_S = 0.7   # a piece's radius decays on this (s)
LULL_CUT_END = 0.95          # the rim cut reaches the core at this share of
#                              the approach — the last pieces still fall in
LULL_END_FADE = 0.06         # ... and everything left eases to black over the
#                              last this-share, black ON the dark point
LULL_CUT_SOFT = 0.04         # the cut's feather, in shaped-radius units
LULL_PIECE_CAP = 220         # pieces falling at once (the program cap)
LULL_SHED_PIECES = 180       # roughly how many pieces a whole lull sheds
LULL_SWIRL_REV_S = 0.25      # a piece's own small swirl (± this, rev/s)
LULL_DRIFT_U_S = 0.04        # ... plus a steady inward drift (u / s)
LULL_HELD_CAP = 260          # swallowed pieces kept for the drop
LULL_HOLD_MAX = 8.0          # how far Star lifts the strip's own lull fade
# the visible region a piece may be shed from: the panel's inscribed
# ellipse, a little grown (the crystal's real light is a hexagon inside the
# rectangle — crystal-hex-grid skill; a piece shed from a dead corner would
# fly in out of nothing)
SHED_REGION = 1.15
LIT_MIN = 20.0               # a cell counts as lit above this (0..255)
#
# DROP D3 — the bands snap back. The pieces the lull swallowed are thrown
# back out of the core along their own angles and snap onto their bands as
# the bloom reveals them; the bands wear a hue-kept colour gain.
SNAP_T0_S = 0.55             # a piece's flight out ...
SNAP_PER_U_S = 0.3           # ... plus this per shaped-radius unit
SNAP_OVERSHOOT = 0.16        # the snap's overshoot past its band
SNAP_FADE_S = 0.5            # a landed piece melts into its band over this
SNAP_SWIRL_REV_S = 0.06      # their small swirl on the way out
DEFAULT_DROP_SNAP_GAIN = 1.6     # the bands' colour gain at the mark ...
DEFAULT_DROP_SNAP_DECAY_S = 1.0  # ... decaying to 1 over this
#
# THE SHAPE MORPH: an `edges` change (STAR's dice re-roll) glides from the
# old polygon to the new one instead of cutting in one frame.
DEFAULT_SHAPE_MORPH_S = 0.6
#
# THE BANDS RELEASE (a transition program OUT of Star): how many pieces
# Star's lit cells hand over by default (ProgramSettings.bands_pieces wins
# when a program asks).
RELEASE_PIECES = 180
RELEASE_LIT_MIN = 0.12       # a cell's brightest channel / 255 to be a piece

_LUM = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_SPLAT_R = 2
_sp = np.arange(-_SPLAT_R, _SPLAT_R + 1)
_SDX, _SDY = (a.ravel() for a in np.meshgrid(_sp, _sp))


def _smooth(s):
    s = np.clip(s, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def splat_brighter(layer, x, y, rgb, size=1.1):
    """Soft dots composed BRIGHTER-WINS into `layer` (H, W, 3) float: where
    a dot is brighter (perceived luminance) than the cell, the cell takes the
    dot's colour outright. Never a per-channel max — two set colours of
    different hues maxed together pale toward white (the plan's named risk);
    this way every lit cell still wears exactly one set colour."""
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return
    y = np.asarray(y, dtype=np.float32)
    h, w = layer.shape[:2]
    ix = np.floor(x).astype(np.int32)
    iy = np.floor(y).astype(np.int32)
    cx = ix[:, None] + _SDX[None, :]
    cy = iy[:, None] + _SDY[None, :]
    d2 = (cx + 0.5 - x[:, None]) ** 2 + (cy + 0.5 - y[:, None]) ** 2
    wgt = np.exp(-d2 / (2.0 * size * size)).astype(np.float32)
    ok = (cx >= 0) & (cx < w) & (cy >= 0) & (cy < h) & (wgt > 0.05)
    if not ok.any():
        return
    flat = (cy * w + cx)[ok]
    vals = (wgt[..., None] * np.asarray(rgb, np.float32)[:, None, :])[ok]
    lum = vals @ _LUM
    order = np.lexsort((lum, flat))
    flat, vals, lum = flat[order], vals[order], lum[order]
    last = np.ones(flat.size, dtype=bool)
    last[:-1] = flat[1:] != flat[:-1]
    flat, vals, lum = flat[last], vals[last], lum[last]
    out = layer.reshape(-1, 3)
    win = lum > out[flat] @ _LUM
    out[flat[win]] = vals[win]


def hue_gain(frame, g):
    """`frame` scaled by `g`, hue-kept: a pixel scales whole and stops at
    full, so a colour gain never pushes one channel to 255 while the others
    catch up (which is what whitens an over-full colour)."""
    if g <= 1.0:
        return frame
    mx = frame.max(axis=-1, keepdims=True)
    k = np.where(mx > 0.0, np.minimum(g, 255.0 / np.maximum(mx, 1.0)), 1.0)
    return frame * k


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
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "phase", "phase_progress", *lull_dark.KEYS, *phase_grammar.BREATH_KEYS,
        lull_handoff.DROP_KEY, phase_grammar.SHOCK_ON_KEY,
    ]
    # Star takes the BREATH-HOLD itself (in its own draw, like Pulse) and
    # never the shared Shockwave overlay — its drop is D3, the bands
    # snapping back (fx.device_model.BREATH_HOLD_EFFECTS / DROP_SHOCK_TOLD_
    # EFFECTS name it; DROP_SHOCK stays False).
    BREATH_HOLD = True

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
                    "(the vendored behaviour). Max reduced 2026-10-06 (see "
                    "ROTATION_SPEED_SCALE above) from 2.0 to 1.6 rev/s — "
                    "config/effect_params.json's own declared max must "
                    "stay in sync with this literal."
                ),
                default=0.0,
            ): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=2.0 * ROTATION_SPEED_SCALE)
            ),
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
            vol.Optional(
                "lull_mode",
                description=(
                    "How the lull empties the star: bands = the outermost "
                    "band breaks into pieces that spiral into the core, then "
                    "the next, until the last is gone at the dark point "
                    "(the pieces are kept for the drop, which throws them "
                    "back out); implode = the pattern squeezes into a "
                    "narrow band at the core (the original lull)"
                ),
                default=DEFAULT_LULL_MODE,
            ): vol.In(list(LULL_MODES)),
            vol.Optional(
                "lull_core_u",
                description="Lull (bands): how close to the centre a "
                            "falling piece gets before the core swallows it "
                            "(shaped-radius units, 1 = the panel's corner)",
                default=DEFAULT_LULL_CORE_U,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.4)),
            vol.Optional(
                "lull_piece_tau",
                description="Lull (bands): how fast a piece falls — its "
                            "radius decays on this many seconds",
                default=DEFAULT_LULL_PIECE_TAU_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.3, max=2.0)),
            vol.Optional(
                "drop_snap_gain",
                description="Drop (the bands snap back): the bands' "
                            "hue-kept colour gain at the mark (more colour, "
                            "never white); 1 = none",
                default=DEFAULT_DROP_SNAP_GAIN,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=2.5)),
            vol.Optional(
                "drop_snap_decay_s",
                description="Drop (the bands snap back): seconds the "
                            "colour gain takes to settle back to 1",
                default=DEFAULT_DROP_SNAP_DECAY_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=3.0)),
            vol.Optional(
                "shape_morph_s",
                description="Seconds a change of Edges glides from the old "
                            "shape to the new one (0 = the old instant cut)",
                default=DEFAULT_SHAPE_MORPH_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            **lull_dark.schema_fields(),
            **phase_grammar.breath_schema_fields(),
            **lull_handoff.drop_schema_fields(),
            **phase_grammar.shock_on_schema_fields(),
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
        # THE STAR PLAN state (`_lull_bands` / `_drop_snap` / the morph)
        self._rng = np.random.default_rng()
        self._bands = None     # lull B: the rim cut and its falling pieces
        self._held = None      # pieces the core swallowed, kept for the drop
        self._snap = None      # drop D3: the pieces flying back out
        self._silent_drop = False   # the orphan watchdog's quiet release
        self._morph = None     # {"from": edges, "t": s} while edges glides
        self._palette = None   # the set's colours, read off the strip (64x3)
        self._omega = 0.0      # live rotation rate, rad/s (the release)
        self._spin_prev = None
        self._last_u = None    # last frame's shaped radius / angle fields
        self._last_angle = None
        super().__init__(ledfx, config)

    def config_updated(self, config):
        super().config_updated(config)
        self.source_virtual = None
        # THE SHAPE MORPH: a CHANGE of edges on a live instance (STAR's dice
        # re-roll lands as a jump) glides from the old shape to the new one.
        # Creation (no `edges` yet) and an unchanged value never start one.
        new_edges = self._config.get("edges")
        old_edges = getattr(self, "edges", None)
        morph_s = float(self._config.get("shape_morph_s",
                                         DEFAULT_SHAPE_MORPH_S) or 0.0)
        if (old_edges is not None and new_edges != old_edges
                and morph_s > 0.0):
            self._morph = {"from": int(old_edges), "t": 0.0}
        elif morph_s <= 0.0:
            self._morph = None
        self.edges = new_edges
        self.x_offset = self._config.get("x_offset")
        self.y_offset = self._config.get("y_offset")
        self.twist = self._config.get("twist")
        self.polygon = self._config.get("polygon")
        self.rotation = self._config.get("rotation")
        # bring impulse spin injection into a reasonable range of control
        # — scaled by ROTATION_SPEED_SCALE so the reactive ceiling (spin at
        # its own max 1.0, full audio impulse) drops by the same 20% as
        # every other rotation-speed source, without narrowing spin's own
        # [-1, 1] input range.
        self.spin = (
            nonlinear_log(self._config.get("spin"), 2) / 10.0 * ROTATION_SPEED_SCALE
        )
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

    # ── the set's colours (the palette Star's pieces wear) ───────────────
    # Star draws nothing of its own: its colours are the strip's (the
    # `radial-dummy` virtual running the scene's Strips effect — Melt on
    # STAR). The set's own gradient lives on that strip effect, so it is read
    # from there once a frame and cached: a piece is drawn in the SET colour
    # nearest its cell (transition_cloud.nearest_set_grad — the Flame Lick's
    # rule), and a transition program reads the cached palette through
    # `get_gradient_color_vectorized1d` even after the strip has switched to
    # the next scene's effect.

    def _refresh_palette(self, pixels_in=None):
        from fx.effects import transition_program as tp
        pal = None
        eff = getattr(self.source_virtual, "active_effect", None) \
            if self.source_virtual is not None else None
        fn = getattr(eff, "get_gradient_color_vectorized1d", None)
        if fn is not None:
            try:
                p = np.asarray(fn(tp.PALETTE_GRID), dtype=np.float32)
                if p.shape == (tp.PALETTE_GRID.size, 3) and np.isfinite(p).all():
                    pal = p
            except Exception:                              # noqa: BLE001
                pal = None
        if pal is None and pixels_in is not None:
            # a strip effect with no gradient: its own frame is the palette
            try:
                strip = np.asarray(pixels_in, dtype=np.float32)
                if strip.ndim == 2 and strip.shape[0] > 1 and strip.max() > 0:
                    idx = np.clip((tp.PALETTE_GRID * (strip.shape[0] - 1))
                                  .astype(np.int32), 0, strip.shape[0] - 1)
                    pal = strip[idx, :3].copy()
            except Exception:                              # noqa: BLE001
                pal = None
        if pal is not None:
            self._palette = pal

    def get_gradient_color_vectorized1d(self, points):
        """The colour set at `points` (n,) 0..1, as the cached strip palette
        holds it — what a transition program samples for the pieces Star
        releases (transition_program._sample_rgb). Raises when no palette
        has been seen yet (the program then falls back)."""
        from fx.effects import transition_program as tp
        rgb = tp.palette_rgb(self._palette, np.asarray(points, np.float32))
        if rgb is None:
            raise RuntimeError("radial: no colour set seen yet")
        return rgb

    def _set_colours(self, cell_rgb):
        """For each cell colour (n, 3): its nearest SET colour at full and
        that colour's gradient position (never a pale mix — the set's own)."""
        from fx.effects import transition_cloud
        cell_rgb = np.asarray(cell_rgb, dtype=np.float32)
        if self._palette is None:
            full = cell_rgb * (255.0 / np.maximum(
                cell_rgb.max(axis=1, keepdims=True), 1.0))
            return np.zeros(len(cell_rgb), np.float32), full.astype(np.float32)
        grad, full = transition_cloud.nearest_set_grad(self._palette, cell_rgb)
        return grad.astype(np.float32), full.astype(np.float32)

    # ── THE BANDS RELEASE (a transition program OUT of Star) ─────────────
    def _program_snapshot(self, settings=None):
        """What a TRANSITION PROGRAM captures when Star is the outgoing form
        (transition_program.TransitionProgram.capture asks for this before
        the ordinary `_handoff_snapshot`): the neutral snapshot plus Star's
        bands RELEASED as pieces — sampled from the last frame's lit cells,
        brightness-weighted, each in the set colour nearest its cell and
        moving with the ring it sat on (v = ω × r about the centre, from the
        live rotation rate), so the cloud leaves still turning.

        Deliberately NOT in `_handoff_snapshot`: that one also feeds the
        ordinary crossfade's adoptions (every particle effect's `src ==
        "radial"` branch reads it), whose behaviour this change leaves
        exactly as it was. No lit cells -> no pieces -> no program (the
        switch rides its ordinary path)."""
        snap = self._handoff_snapshot()
        if snap is None:
            return None
        cap = int(getattr(settings, "bands_pieces", RELEASE_PIECES)
                  or RELEASE_PIECES)
        try:
            m = np.asarray(self.matrix, dtype=np.float32)
        except Exception:                                  # noqa: BLE001
            return snap
        if m.ndim != 3 or m.shape[:2] != (self.r_height, self.r_width):
            return snap
        b = m.max(axis=2) / 255.0
        ys, xs = np.nonzero(b > RELEASE_LIT_MIN)
        if xs.size == 0:
            return snap
        if xs.size > cap:
            wgt = b[ys, xs].astype(np.float64)
            wgt = wgt / wgt.sum()
            pick = self._rng.choice(xs.size, cap, replace=False, p=wgt)
            ys, xs = ys[pick], xs[pick]
        px = xs.astype(np.float32) + 0.5
        py = ys.astype(np.float32) + 0.5
        w = float(self._omega)
        vx = (-w * (py - float(self.cy))).astype(np.float32)
        vy = (w * (px - float(self.cx))).astype(np.float32)
        grad, full = self._set_colours(m[ys, xs])
        snap.update({
            "px": px, "py": py, "vx": vx, "vy": vy,
            "grad": grad,
            "bright": np.clip(b[ys, xs], 0.0, 1.0).astype(np.float32),
            "rgb": full,
            "om": np.full(px.size, w, dtype=np.float32),
            "gesture": "bands",
        })
        return snap

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
            "sauron",
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
                prev = self._phase
                self._phase = pend
                self._phase_t = 0.0
                self._phase_done_t = None
                self._phase_edge(prev, pend)
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
            # a quiet release, never a payoff: nothing is thrown back out
            self._silent_drop = True
            self._held = None
            self._bands = None
            self._snap = None
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
        choreography owns the screen. Returns (warp, bg_alpha) or None.
        A lull in "bands" mode has no warp: its picture is cut from the rim
        inward instead (`_lull_bands`)."""
        if self._phase == "lull" and self._lull_mode() == "bands":
            return None
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

    # ── STAR'S OWN LULL AND DROP (the star plan, the Admiral 2026-10-13:
    # "Use lull b, drop d 3") ────────────────────────────────────────────
    #
    # LULL B — THE BANDS FALL IN AS PARTICLES. A rim CUT sweeps from the
    # outermost band inward (in Star's own shaped radius, so it is the
    # shape's outline shrinking): every lit cell the cut passes breaks off
    # as a piece (about LULL_SHED_PIECES over the whole lull, brightness
    # weighted), which keeps the ring's rotation (a piece lives in Star's
    # ROTATING frame, so it turns with the star) and spirals into the core —
    # its radius decays on `lull_piece_tau` with a small swirl — until the
    # core swallows it. Band by band the star empties; the cut reaches the
    # centre at LULL_CUT_END of the approach and the last pieces are in by
    # the DARK POINT (lull_dark's shared rule — Star reads it itself, so a
    # long lull keeps shedding until 3 s before its drop), where the panel is
    # black. Pieces wear the SET colour nearest their cell at full and are
    # composed brighter-wins, never by a channel max (`splat_brighter`) — so
    # pieces of two hues at the core never pale toward white. Every piece
    # the core swallows is KEPT (`_held`) for the drop.
    #
    # DROP D3 — THE BANDS SNAP BACK. On the drop's edge the kept pieces are
    # thrown back out of the core along their own angles and snap onto the
    # band each came from (a small overshoot, SNAP_OVERSHOOT) as the bloom
    # reveals the pattern, then melt into it; the bands wear a hue-kept
    # colour gain (`drop_snap_gain`, x1.6 at the mark, settling over
    # `drop_snap_decay_s`) — more colour, never white. It is Star's drop and
    # replaces the shared Shockwave overlay on this effect (Star is not a
    # DROP_SHOCK member), but it OBEYS THE SAME THREE SWITCHES: SpotFX tells
    # Star the verdict (`drop_shock_on` — the room's switch, the scene's,
    # and the top-bar Energy floor); told False, the drop is the plain bloom
    # (no pieces thrown, no colour gain). The told drop intensity scales the
    # gain and how long it lasts (lull_handoff.drop_scale; untold = 1). A
    # drop with nothing kept (a charge straight into a drop, an "implode"
    # lull) is the plain bloom too, and so is the orphan watchdog's quiet
    # release. A new charge or lull discards anything still in flight.
    #
    # THE BREATH-HOLD: Star takes the lull's short true black before the
    # mark itself (phase_grammar.breath_gain, once a frame — the base
    # Twod's shared painter only runs for Shockwave members). In "bands"
    # mode the panel is already black there; in "implode" mode it is the
    # one moment the implode goes dark.

    def _lull_mode(self):
        mode = self._config.get("lull_mode", DEFAULT_LULL_MODE)
        return mode if mode in LULL_MODES else DEFAULT_LULL_MODE

    def _phase_edge(self, prev, new):
        if new in ("charge", "lull"):
            self._snap = None
            self._silent_drop = False
            self._held = None
        if new == "lull":
            self._bands = None
        if new == "drop":
            self._begin_snap()
        if prev == "lull" and new != "lull":
            self._bands = None

    # the shape a piece rides: a piece at shaped radius u and angle phi
    # (Star's rotating frame) sits at u * max_radius * _shape_div(phi) px

    def _shape_div_for(self, phi, edges):
        phi = np.asarray(phi, dtype=np.float32)
        if edges == 2:
            return 1.0 / np.sqrt(np.cos(phi) ** 2 + 0.25 * np.sin(phi) ** 2)
        if edges is not None and edges >= 3:
            if not self.polygon:
                return 1.0 / np.maximum(np.abs(np.cos((edges * phi) / 2)), 0.05)
            a = np.pi * 2 / edges
            half_a = a / 2
            am = (phi + half_a) % a - half_a
            pr = np.cos(np.pi / edges) / np.clip(np.cos(am), epsilon, None)
            if self.star != 0:
                pr = pr * (1 + self.star * np.cos(edges * phi))
            return np.maximum(pr, 1e-3)
        return np.ones_like(phi)

    def _shape_div(self, phi):
        f = self._shape_div_for(phi, self.edges)
        m = self._morph_mix()
        if m is not None:
            fb = self._shape_div_for(phi, self._morph["from"])
            # the shaped radius blends linearly (r/f), so the divisor blends
            # harmonically
            f = 1.0 / ((1.0 - m) / fb + m / f)
        return f

    def _piece_xy(self, u, phi, theta):
        r = np.asarray(u, np.float32) * self.max_radius * self._shape_div(phi)
        ang = np.asarray(phi, np.float32) + theta
        return (self.cx + r * np.cos(ang)).astype(np.float32), \
            (self.cy + r * np.sin(ang)).astype(np.float32)

    def _morph_mix(self):
        if self._morph is None:
            return None
        s = float(self._config.get("shape_morph_s", DEFAULT_SHAPE_MORPH_S) or 0.0)
        if s <= 0.0:
            return None
        return float(_smooth(self._morph["t"] / s))

    def _shed_region(self):
        w2 = max(self.r_width / 2.0, 1.0)
        h2 = max(self.r_height / 2.0, 1.0)
        return ((self.dx / w2) ** 2 + (self.dy / h2) ** 2) <= SHED_REGION

    def _lull_bands(self, rgb, u, angle, dt):
        """LULL B, one frame (block comment above): cut the picture `rgb`
        (float, H x W x 3) from the rim inward, shed the cells the cut passed
        as pieces, let the falling pieces spiral in, keep what the core
        swallows. Returns the pieces' layer to compose (or None)."""
        cfg = self._config
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        tim = lull_dark.lull_timing(cfg, p, self._phase_t, legacy_dark_at=1.0)
        core = float(cfg.get("lull_core_u", DEFAULT_LULL_CORE_U))
        tau = float(cfg.get("lull_piece_tau", DEFAULT_LULL_PIECE_TAU_S))
        st = self._bands
        lum = rgb.max(axis=2)
        if st is None:
            region = self._shed_region()
            lit = region & (lum > LIT_MIN)
            ref = lum[lit]
            top = float(u[region].max()) if region.any() else 1.0
            st = self._bands = {
                "top": max(top, core),
                "cut": max(top, core) + LULL_CUT_SOFT,
                "prob": float(np.clip(LULL_SHED_PIECES / max(int(lit.sum()), 1),
                                      0.02, 1.0)),
                "region": region,
                "peak0": float(np.percentile(ref, 95)) if ref.size else 0.0,
                "u": np.zeros(0, np.float32), "u0": np.zeros(0, np.float32),
                "phi": np.zeros(0, np.float32), "sw": np.zeros(0, np.float32),
                "rgb": np.zeros((0, 3), np.float32),
                "b": np.zeros(0, np.float32),
            }
            if self._held is None:
                self._held = {"u0": np.zeros(0, np.float32),
                              "phi": np.zeros(0, np.float32),
                              "rgb": np.zeros((0, 3), np.float32)}
        # STAR HOLDS ITS OWN PICTURE (the plan's Q6): the strip under it
        # fades through its own lull (the strip phase layer) and reaches
        # black before the dark point; Star brings the bands it still shows
        # back up to their brightness at the lull's start (hue-kept, capped)
        # so the bands fall in on Star's clock, black ON the dark point.
        if st["peak0"] > 0.0:
            live = lum[st["region"] & (lum > 2.0)]
            if live.size:
                peak = float(np.percentile(live, 95))
                g = min(max(st["peak0"] / max(peak, 1.0), 1.0), LULL_HOLD_MAX)
                if g > 1.0:
                    rgb[...] = hue_gain(rgb, g)
                    lum = rgb.max(axis=2)
        if tim.dark:
            cut = 0.0
        else:
            # the lit AREA shrinks evenly in time (area ~ cut^2), eased at
            # both ends, so the bands keep falling in until the last one goes
            # just before the dark point
            cut = st["top"] * float(np.sqrt(max(
                0.0, 1.0 - float(_smooth(tim.approach / LULL_CUT_END)))))
        prev = st["cut"]
        cut = min(cut, prev)
        st["cut"] = cut
        # shed: the lit cells the cut passed this frame become pieces
        if not tim.dark and prev > cut:
            passed = (st["region"] & (lum > LIT_MIN)
                      & (u > cut - 0.5 * LULL_CUT_SOFT)
                      & (u <= prev - 0.5 * LULL_CUT_SOFT))
            ys, xs = np.nonzero(passed)
            if xs.size:
                keep = self._rng.random(xs.size) < st["prob"]
                room = LULL_PIECE_CAP - st["u"].size
                ys, xs = ys[keep][:max(room, 0)], xs[keep][:max(room, 0)]
            if xs.size:
                cols = rgb[ys, xs]
                _grad, full = self._set_colours(cols)
                uu = u[ys, xs].astype(np.float32)
                st["u"] = np.concatenate([st["u"], uu])
                st["u0"] = np.concatenate([st["u0"], uu])
                st["phi"] = np.concatenate(
                    [st["phi"], angle[ys, xs].astype(np.float32)])
                st["sw"] = np.concatenate(
                    [st["sw"], self._rng.uniform(-1.0, 1.0, xs.size)
                     .astype(np.float32)])
                st["rgb"] = np.concatenate([st["rgb"], full])
                st["b"] = np.concatenate(
                    [st["b"], np.clip(cols.max(axis=1) / 255.0 * 1.4, 0.45, 1.0)
                     .astype(np.float32)])
        # the picture: lit inside the cut only (black once it is gone); the
        # last of it eases out so the panel is black exactly ON the dark point
        end = 0.0 if tim.dark else float(
            _smooth((1.0 - tim.approach) / LULL_END_FADE))
        k = _smooth((cut - u) / LULL_CUT_SOFT).astype(np.float32) * end
        rgb *= k[..., None]
        # fall: pieces spiral into the core, faster when the dark point is
        # near so every one is in by then
        if st["u"].size:
            t_left = None
            if lull_dark.told(cfg):
                t_left = float(cfg.get(lull_dark.DARK_KEY, 0.0) or 0.0) \
                    - self._phase_t
            tau_eff = tau if t_left is None else float(
                np.clip(t_left / 1.5, 0.05, tau))
            st["u"] = np.maximum(
                st["u"] * np.float32(np.exp(-dt / tau_eff))
                - np.float32(LULL_DRIFT_U_S * dt), 0.0)
            st["phi"] = st["phi"] + st["sw"] * np.float32(
                LULL_SWIRL_REV_S * 2 * np.pi * dt)
            gone = st["u"] <= 0.5 * core
            if tim.dark:
                gone[:] = True
            if gone.any():
                h = self._held
                room = LULL_HELD_CAP - h["u0"].size
                g = np.flatnonzero(gone)[:max(room, 0)]
                h["u0"] = np.concatenate([h["u0"], st["u0"][g]])
                h["phi"] = np.concatenate([h["phi"], st["phi"][g]])
                h["rgb"] = np.concatenate([h["rgb"], st["rgb"][g]])
                live = ~gone
                for key in ("u", "u0", "phi", "sw", "rgb", "b"):
                    st[key] = st[key][live]
        if st["u"].size == 0:
            return None
        # a piece melts into the core as it nears it
        fade = _smooth((st["u"] - 0.5 * core) / (0.5 * core))
        bright = st["b"] * fade * end
        on = bright > 0.01
        if not on.any():
            return None
        theta = ((self.spin_total + self.rotation) % 1.0) * 2 * np.pi
        x, y = self._piece_xy(st["u"][on], st["phi"][on], theta)
        layer = np.zeros_like(rgb)
        splat_brighter(layer, x, y, st["rgb"][on] * bright[on, None])
        return layer

    def _begin_snap(self):
        """DROP D3's start (block comment above): the kept pieces leave the
        core along their own angles. Nothing kept, a quiet watchdog release,
        or SpotFX's verdict saying the drop may not paint: the plain bloom."""
        held, self._held = self._held, None
        st = self._bands
        self._bands = None
        if self._silent_drop or not phase_grammar.shock_on(self._config):
            self._snap = None
            return
        u0 = np.zeros(0, np.float32)
        phi = np.zeros(0, np.float32)
        rgb = np.zeros((0, 3), np.float32)
        if held is not None:
            u0, phi, rgb = held["u0"], held["phi"], held["rgb"]
        if st is not None and st["u"].size:
            # a drop landing before the last pieces were in throws them too
            u0 = np.concatenate([u0, st["u0"]])
            phi = np.concatenate([phi, st["phi"]])
            rgb = np.concatenate([rgb, st["rgb"]])
        if u0.size == 0:
            self._snap = None
            return
        scale = lull_handoff.drop_scale(
            lull_handoff.drop_intensity(self._config))
        scale = 1.0 if scale is None else float(scale)
        g = float(self._config.get("drop_snap_gain", DEFAULT_DROP_SNAP_GAIN))
        self._snap = {
            "t": 0.0,
            "u0": u0.astype(np.float32),
            "phi": phi.astype(np.float32),
            "rgb": rgb.astype(np.float32),
            "sw": self._rng.uniform(-1.0, 1.0, u0.size).astype(np.float32),
            "T": (SNAP_T0_S + SNAP_PER_U_S * u0).astype(np.float32),
            "gain": 1.0 + (g - 1.0) * scale,
            "decay": max(0.05, float(self._config.get(
                "drop_snap_decay_s", DEFAULT_DROP_SNAP_DECAY_S)) * scale),
        }

    def _drop_snap(self, rgb, dt):
        """DROP D3, one frame: the colour gain on the bands (hue-kept, in
        place on `rgb`) and the layer of pieces flying back out. Returns the
        layer (or None)."""
        sn = self._snap
        sn["t"] += dt
        t = sn["t"]
        g = 1.0 + (sn["gain"] - 1.0) * (1.0 - float(_smooth(t / sn["decay"])))
        if g > 1.0:
            rgb[...] = hue_gain(rgb, g)
        s = np.clip(t / np.maximum(sn["T"], 1e-3), 0.0, 1.0)
        sn["phi"] = sn["phi"] + sn["sw"] * np.float32(
            SNAP_SWIRL_REV_S * 2 * np.pi * dt)
        u = sn["u0"] * _smooth(s) * (1.0 + SNAP_OVERSHOOT * np.sin(np.pi * s))
        b = np.clip(1.0 - (t - sn["T"]) / SNAP_FADE_S, 0.0, 1.0)
        if t > float(sn["T"].max()) + SNAP_FADE_S and t > sn["decay"]:
            self._snap = None
        on = b > 0.01
        if not on.any():
            return None
        theta = ((self.spin_total + self.rotation) % 1.0) * 2 * np.pi
        x, y = self._piece_xy(u[on], sn["phi"][on], theta)
        layer = np.zeros_like(rgb)
        splat_brighter(layer, x, y, sn["rgb"][on] * b[on, None])
        return layer

    def _track_rotation(self, dt):
        """The live rotation rate (rad/s, smoothed) — what the bands release
        hands its pieces as tangential velocity."""
        cur = float(self.spin_total + self.rotation)
        if self._spin_prev is not None and dt > 0.0:
            d = (cur - self._spin_prev + 0.5) % 1.0 - 0.5
            w = 2.0 * np.pi * d / dt
            self._omega = 0.8 * self._omega + 0.2 * w
        self._spin_prev = cur

    def draw(self):
        self._ensure_source()
        self._refresh_bg_render_state()

        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        dt = float(self.passed) if np.isfinite(self.passed) else 1.0 / 60.0
        dt = min(max(dt, 0.0), 0.1)
        self._phase_step(dt)
        self._base_rotation_step(dt)
        self._track_rotation(dt)
        if self._morph is not None:
            self._morph["t"] += dt
            ms = float(self._config.get("shape_morph_s",
                                        DEFAULT_SHAPE_MORPH_S) or 0.0)
            if ms <= 0.0 or self._morph["t"] >= ms:
                self._morph = None

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

            # Radius modulation based on edges (THE SHAPE MORPH: while an
            # edges change glides, the old shape's shaped radius blends into
            # the new one's)
            shaped = self._shaped_radius(radius, angle, theta, self.edges)
            m = self._morph_mix()
            if m is not None:
                old = self._shaped_radius(
                    self.radius_base.copy(), angle, theta, self._morph["from"])
                shaped = old * (1.0 - m) + shaped * m
            radius = shaped

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
                self.bg_color_use = False
            rgb_array = self._star_phase_frame(
                rgb_array, norm_radius, angle, dt, pixels_in)
            image = Image.fromarray(rgb_array, mode="RGB")
            self.matrix.paste(image)

    def _shaped_radius(self, radius, angle, theta, edges):
        """The vendored radius modulation for `edges` (unchanged), factored
        out so the shape morph can compute two shapes in one frame."""
        if edges == 1:
            ux = np.cos(theta)
            uy = np.sin(theta)
            return np.abs(self.dx * ux + self.dy * uy)
        if edges == 2:
            cos_angle = np.cos(angle)
            sin_angle = np.sin(angle)
            modulation = np.sqrt(cos_angle**2 + 0.25 * sin_angle**2)
            radius *= modulation
        elif edges >= 3:
            if not self.polygon:
                modulation = np.cos((edges * angle) / 2)
                radius *= np.abs(modulation)
            else:
                a = np.pi * 2 / edges
                half_a = a / 2
                angle_mod = (angle + half_a) % a - half_a
                polygon_radius = np.cos(np.pi / edges) / np.clip(
                    np.cos(angle_mod), epsilon, None
                )

                # Optional starburst shaping
                if self.star != 0:
                    ripple = 1 + self.star * np.cos(edges * angle)
                    polygon_radius *= ripple
                radius /= polygon_radius
        return radius

    def _star_phase_frame(self, rgb_array, u, angle, dt, pixels_in):
        """Star's own lull and drop on the frame just mapped (block comment
        above `_lull_mode`): lull B's cut and falling pieces, D3's pieces and
        colour gain, and the breath-hold. Outside all three the frame is
        returned untouched (byte for byte)."""
        self._refresh_palette(pixels_in)
        bands = self._phase == "lull" and self._lull_mode() == "bands"
        breath = 1.0
        if self._phase == "lull":
            breath = phase_grammar.breath_gain(self._config, self._phase_t)
        if not bands and self._snap is None and breath >= 1.0:
            return rgb_array
        rgb = rgb_array.astype(np.float32)
        layers = []
        if bands:
            layer = self._lull_bands(rgb, u, angle, dt)
            if layer is not None:
                layers.append(layer)
        if self._snap is not None:
            layer = self._drop_snap(rgb, dt)
            if layer is not None:
                layers.append(layer)
        for layer in layers:
            lit = (layer @ _LUM) > (rgb @ _LUM)
            rgb[lit] = layer[lit]
        if breath < 1.0:
            rgb *= np.float32(breath)
        return np.clip(rgb, 0, 255).astype(np.uint8)
