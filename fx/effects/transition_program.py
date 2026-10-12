"""THE TRANSITION PROGRAM — one cloud, three verbs (transitions-drop plan,
phase 3; /home/javi/fleet-spotfx/data/transitions-drop-plan/report.md,
"The method: one cloud, three verbs"). SpotFX-authored, not fork code;
fx/VENDOR.md #70 records the two vendored hooks it needs. Read this before
touching anything that switches a Matrix effect on a scene change.

WHY. An ordinary effect-type switch rides the virtual's stored crossfade
(Add, 0.5 s on his matrices): two half-bright pictures added for half a
second, with every hand-off choreography squeezed inside it, so a Black
Hole <-> particles change reads as a pop. The Admiral's ask, verbatim:
"Ideas for transitions should smoothly form into the particles and black
hole, etc, and vice versa." A PROGRAM replaces that mix for a registered
(outgoing, incoming) pair with its own clock (~1.4 s by default, his
answer to Q4) and draws ONE picture at a time:

  RELEASE  the outgoing form hands its particles to a free cloud (its
           `_handoff_snapshot`, which now carries each particle's velocity
           `vx`/`vy` and a `gesture` word, particle_handoff's docstring);
           its last picture decays under the cloud.
  FLIGHT   a shared field moves the cloud on the program's own clock.
  FORM     the incoming effect draws its formation from the arriving
           cloud. Where the incoming form MOVES, the targets are its own
           LIVE kinematics running during the program — never a mirror of
           its physics — and each particle's velocity is blended into the
           incoming effect's own motion, so the hand-off frame continues
           one motion instead of throwing the velocity away.

THE PROGRAMS. Phase 3 built the first two here (INFALL, ERUPTION);
phase 4 (fx/effects/transition_cloud.py — its docstring is the binding
statement for them) adds LENSING / FOUNTAIN (Fireworks <-> Black Hole),
FLAME LICK / IGNITION (Sauron or Eye <-> the particle effects), SHOAL
BREAK / SHOALING (Fish <-> Orbits / Squiggles) and UNRAVEL (Squiggles <->
Orbits / Fish), all in the one registry below:

  INFALL    particles -> Black Hole (orbits / fish / squiggles -> blackhole
            — fireworks LENS in instead, below; his "I like this upgrade
            for Infall"). Every piece leaves on the velocity it had and
            bends onto an accelerating spiral into the horizon
            (`transition_infall_spin` extra turns), the horizon ignites as
            it feeds (the incoming Black Hole fades up over the second
            half of the flight), and over the last
            `transition_velocity_blend_ms` every piece's velocity is blended
            into the Black Hole's own field at its radius
            (Blackhole2d._program_field_velocity). The real Black Hole then
            ADOPTS the cloud with that velocity (its cross-type adopt now
            continues an inherited velocity instead of freezing it and
            winding up from zero — the Lensing fix).
  ERUPTION  Black Hole -> particles (blackhole -> orbits / fish /
            squiggles). The ring and its blobs contract to the centre on
            the motion they had, a bloom in the colour set's brightest stop
            marks the ANCHOR, ejecta spray out across the whole set by
            angle and decelerate, and then — his newest comment, "this one
            should implode into the orbits like the shoaling" — every
            ejecta converges onto a LIVE, MOVING formation point of the
            incoming effect (`_formation_points()`: orbit blobs, fish,
            chain heads), each on a cubic Hermite in coordinates relative
            to its moving target, so it leaves with its own velocity and
            arrives ON the target WITH the target's velocity. Nothing
            parks; the incoming effect fades up as its pieces arrive.

ONE PICTURE, COMPOSED BY MAX. The program composes onto the incoming
effect's own matrix inside `Twod.render` (after `draw()`, before the pixel
mapping — the `_transition_program` hook, VENDOR #68): `out = max(cloud
layer, release picture, incoming * gain)`. Never an add, so a solid-colour
set can never saturate toward white, and every colour is the set's own
(his ruling: "set colours only" — the bloom is the set's brightest stop at
full, never a white term).

THE ANCHOR. Each program names where its payoff lands (`anchor_frac`):
the infall's ignition (the start of its FORM stage), the eruption's bloom.
The trigger clock fires a scene change that many ms EARLY
(spectra/services/scene_transition_lead.program_lead_ms) so that moment
lands on the mark. A DROP-LED switch (spectra/services/drop_switch.py's
HANDOFF_PROGRAM rows) is already a cut ON the mark, so it runs the
program `on_mark`: anchor 0 — the eruption blooms on its first frame, and
the infall shows the incoming Black Hole (and its drop) from the first
frame while the cloud spirals into it.

THE CLOCK is `particle_handoff.now()` (timeit.default_timer), the same
clock every effect's `self.passed` reads, so fx.headless's fake clock
steps a program deterministically.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from PIL import Image

import fx.effects.particle_handoff as particle_handoff

_LOGGER = logging.getLogger(__name__)

INFALL = "infall"
ERUPTION = "eruption"
# phase 4 (fx/effects/transition_cloud.py)
LENSING = "lensing"
FOUNTAIN = "fountain"
FLAME_LICK = "flame_lick"
IGNITION = "ignition"
SHOAL_BREAK = "shoal_break"
SHOALING = "shoaling"
UNRAVEL = "unravel"

# Infall feeds the Black Hole from every particle effect but Fireworks,
# whose sparks LENS in instead (phase 4); the Black Hole erupts into every
# particle effect but Fireworks, which it FOUNTAINS into.
INFALL_SOURCES = ("orbits", "fish", "squiggles")
ERUPTION_TARGETS = ("orbits", "fish", "squiggles")
# The eye effects, and the particle effects they explode into (FLAME LICK)
# and ignite from (IGNITION).
EYES = ("sauron", "eye")
EYE_PARTNERS = ("blackhole", "orbits", "fish", "squiggles", "fireworks")


def _registry() -> dict[tuple[str, str], str]:
    table: dict[tuple[str, str], str] = {}
    for src in INFALL_SOURCES:
        table[(src, "blackhole")] = INFALL
    for dst in ERUPTION_TARGETS:
        table[("blackhole", dst)] = ERUPTION
    table[("fireworks", "blackhole")] = LENSING
    table[("blackhole", "fireworks")] = FOUNTAIN
    for eye in EYES:
        for other in EYE_PARTNERS:
            table[(eye, other)] = FLAME_LICK
            table[(other, eye)] = IGNITION
    for dst in ("orbits", "squiggles"):
        table[("fish", dst)] = SHOAL_BREAK
    table[("orbits", "fish")] = SHOALING
    for other in ("orbits", "fish"):
        table[("squiggles", other)] = UNRAVEL
    table[("orbits", "squiggles")] = UNRAVEL
    return table


# (outgoing effect type, incoming effect type) -> program name.
PROGRAMS: dict[tuple[str, str], str] = _registry()


def program_name(out_type: Optional[str], in_type: Optional[str]) -> Optional[str]:
    """The program registered for a switch, or None (the switch then rides
    the virtual's stored crossfade exactly as before)."""
    if not out_type or not in_type:
        return None
    return PROGRAMS.get((out_type, in_type))


# ── settings (the room's tunables, pushed with each switch) ────────────────
# fx/ may not import spectra/, so SpotFX sends the room's values in the
# effect write itself (`"program": {...}`, spectra/services/room_controls.
# transition_program_request) and the facade builds the program from them.
DEFAULT_DURATION_S = 1.4
MIN_DURATION_S = 0.6
MAX_DURATION_S = 2.5
DEFAULT_VELOCITY_BLEND_S = 0.5
DEFAULT_INFALL_SPIN = 0.75
DEFAULT_ERUPTION_COUNT = 60
DEFAULT_ERUPTION_SPEED = 1.0
# phase 4 (transition_cloud.py)
DEFAULT_EXPLODE_FRAC = 0.5      # his "say half for now"
DEFAULT_LENSING_PULL = 1.0
DEFAULT_IGNITION_TURNS = 0.6
DEFAULT_SCATTER = 1.0


def _clamp(v, lo, hi, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return min(max(f, lo), hi)


@dataclass(frozen=True)
class ProgramSettings:
    duration_s: float = DEFAULT_DURATION_S
    velocity_blend_s: float = DEFAULT_VELOCITY_BLEND_S
    infall_spin: float = DEFAULT_INFALL_SPIN
    eruption_count: int = DEFAULT_ERUPTION_COUNT
    eruption_speed: float = DEFAULT_ERUPTION_SPEED
    explode_frac: float = DEFAULT_EXPLODE_FRAC
    lensing_pull: float = DEFAULT_LENSING_PULL
    ignition_turns: float = DEFAULT_IGNITION_TURNS
    scatter: float = DEFAULT_SCATTER
    on_mark: bool = False
    seed: Optional[int] = None

    @classmethod
    def from_request(cls, req: Optional[dict]) -> "ProgramSettings":
        req = req if isinstance(req, dict) else {}
        d = cls()
        dur = _clamp(req.get("duration_ms", d.duration_s * 1000.0),
                     MIN_DURATION_S * 1000.0, MAX_DURATION_S * 1000.0,
                     d.duration_s * 1000.0) / 1000.0
        blend = _clamp(req.get("velocity_blend_ms", d.velocity_blend_s * 1000.0),
                       50.0, 1500.0, d.velocity_blend_s * 1000.0) / 1000.0
        seed = req.get("seed")
        return cls(
            duration_s=dur,
            velocity_blend_s=blend,
            infall_spin=_clamp(req.get("infall_spin", d.infall_spin),
                               0.0, 3.0, d.infall_spin),
            eruption_count=int(_clamp(req.get("eruption_count", d.eruption_count),
                                      10, 150, d.eruption_count)),
            eruption_speed=_clamp(req.get("eruption_speed", d.eruption_speed),
                                  0.5, 2.0, d.eruption_speed),
            explode_frac=_clamp(req.get("explode_frac", d.explode_frac),
                                0.0, 1.0, d.explode_frac),
            lensing_pull=_clamp(req.get("lensing_pull", d.lensing_pull),
                                0.2, 3.0, d.lensing_pull),
            ignition_turns=_clamp(req.get("ignition_turns", d.ignition_turns),
                                  0.0, 3.0, d.ignition_turns),
            scatter=_clamp(req.get("scatter", d.scatter), 0.0, 2.0, d.scatter),
            on_mark=bool(req.get("on_mark", False)),
            seed=int(seed) if isinstance(seed, (int, float)) else None,
        )

    def infall_form_s(self) -> float:
        """The infall's FORM stage: the last velocity_blend_s, never more
        than half the program."""
        return min(self.velocity_blend_s, 0.5 * self.duration_s)


# The eruption's stage boundaries, as fractions of the program.
ERUPTION_ANCHOR = 0.3      # the bloom (the payoff) — contraction before it
ERUPTION_FORM_AT = 0.6     # the implosion onto the live targets begins
ON_MARK_FORM_AT = 0.45     # on the mark there is no contraction stage


# Phase 4's anchors (transition_cloud.py's docstring says why each sits
# where it does): FLAME LICK's eye explodes ON the mark, the shoal breaks
# ON the mark, a chain unspools ON the mark; the fountain sprays, the
# ignition's rim catches, the shoal and the threads are formed at these.
FOUNTAIN_ANCHOR = 0.3
IGNITION_ANCHOR = 0.55
SHOALING_ANCHOR = 0.35
THREAD_ANCHOR = 0.5
_FIXED_ANCHORS = {
    ERUPTION: ERUPTION_ANCHOR,
    FOUNTAIN: FOUNTAIN_ANCHOR,
    FLAME_LICK: 0.0,
    IGNITION: IGNITION_ANCHOR,
    SHOAL_BREAK: 0.0,
    SHOALING: SHOALING_ANCHOR,
}


def anchor_frac(name: Optional[str], settings: ProgramSettings,
                out_type: Optional[str] = None,
                in_type: Optional[str] = None) -> float:
    """Where the program's payoff lands, as a fraction of its duration.
    UNRAVEL's depends on its direction (out of Squiggles a chain unspools
    on the mark; into Squiggles the threads complete at THREAD_ANCHOR), so
    callers that know the pair pass it."""
    if name is None or settings.on_mark:
        return 0.0
    if name in (INFALL, LENSING):
        return 1.0 - settings.infall_form_s() / settings.duration_s
    if name == UNRAVEL:
        return THREAD_ANCHOR if in_type == "squiggles" else 0.0
    return _FIXED_ANCHORS.get(name, 0.5)


def lead_ms(name: Optional[str], settings: ProgramSettings,
            out_type: Optional[str] = None,
            in_type: Optional[str] = None) -> int:
    """LEAD family (positive = fire EARLIER): how early a scene change must
    fire for this program's payoff to land on its mark."""
    if name is None:
        return 0
    return int(round(anchor_frac(name, settings, out_type, in_type)
                     * settings.duration_s * 1000.0))


def program_class(name: Optional[str]):
    """The class that runs a program name (phase 4's live in transition_
    cloud.py, imported lazily: it builds on this module)."""
    if name == INFALL:
        return InfallProgram
    if name == ERUPTION:
        return EruptionProgram
    if name is None:
        return None
    from fx.effects import transition_cloud
    return transition_cloud.PROGRAM_CLASSES.get(name)


def stages(out_type: Optional[str], in_type: Optional[str],
           settings: ProgramSettings) -> list[dict]:
    """The program's named stages as fractions of its duration — what the
    previews draw on their rulers ({"label", "from", "to"}, "anchor": True
    on the stage the payoff opens). [] when no program runs."""
    cls = program_class(program_name(out_type, in_type))
    if cls is None:
        return []
    out = [dict(s) for s in cls.stage_fracs(settings, out_type, in_type)
           if s["to"] - s["from"] > 1e-6]
    if out and not any(s.get("anchor") for s in out):
        # on the mark the stage before the payoff has no length: the
        # payoff opens the program
        out[0]["anchor"] = True
    return out


def build(out_type: Optional[str], in_type: Optional[str],
          request: Optional[dict]) -> Optional["TransitionProgram"]:
    """The facade's one call: a program for this switch, or None."""
    cls = program_class(program_name(out_type, in_type))
    if cls is None:
        return None
    settings = ProgramSettings.from_request(request)
    return cls(settings, out_type, in_type)


# ── drawing helpers ────────────────────────────────────────────────────────

_SPLAT_R = 2
_sp = np.arange(-_SPLAT_R, _SPLAT_R + 1)
_SDX, _SDY = (a.ravel() for a in np.meshgrid(_sp, _sp))


def splat_max(layer: np.ndarray, x: np.ndarray, y: np.ndarray,
              rgb: np.ndarray, size: float = 1.1) -> None:
    """Soft dots composed by MAX into `layer` (H, W, 3): overlapping
    particles never add up toward white."""
    if x.size == 0:
        return
    h, w = layer.shape[:2]
    ix = np.floor(x).astype(np.int32)
    iy = np.floor(y).astype(np.int32)
    cx = ix[:, None] + _SDX[None, :]
    cy = iy[:, None] + _SDY[None, :]
    d2 = (cx + 0.5 - x[:, None]) ** 2 + (cy + 0.5 - y[:, None]) ** 2
    wgt = np.exp(-d2 / (2.0 * size * size)).astype(np.float32)
    ok = (cx >= 0) & (cx < w) & (cy >= 0) & (cy < h) & (wgt > 0.02)
    if not ok.any():
        return
    flat = (cy * w + cx)[ok]
    vals = (wgt[..., None] * rgb[:, None, :])[ok]
    out = layer.reshape(-1, 3)
    for ch in range(3):
        np.maximum.at(out[:, ch], flat, vals[:, ch].astype(np.float32))


SUBSTEPS = 3


def splat_path(layer, x0, y0, x1, y1, rgb, size: float = 0.9) -> None:
    """A dot's path this frame, sub-sampled so a fast piece reads as a
    streak rather than a dotted line (Orbits' own SUBSTEPS, by max)."""
    for k in range(1, SUBSTEPS + 1):
        f = k / SUBSTEPS
        splat_max(layer, x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, rgb, size)


def _smoothstep(s):
    s = np.clip(s, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def _sample_rgb(effect: Any, grad: np.ndarray) -> Optional[np.ndarray]:
    """The effect's own gradient at `grad` (n, 3) in 0..255, or None."""
    fn = getattr(effect, "get_gradient_color_vectorized1d", None)
    if fn is None or grad.size == 0:
        return None
    try:
        rgb = np.asarray(fn(np.clip(grad, 0.0, 1.0)), dtype=np.float32)
    except Exception:
        return None
    if rgb.ndim != 2 or rgb.shape[1] != 3:
        return None
    return rgb


PALETTE_GRID = np.linspace(0.0, 1.0, 64, dtype=np.float32)


def palette_rgb(palette: Optional[np.ndarray], grad: np.ndarray) -> Optional[np.ndarray]:
    """A palette sampled on PALETTE_GRID, read at `grad` (n,) by linear
    interpolation — the outgoing set's colours after it has deactivated."""
    if palette is None:
        return None
    g = np.clip(np.asarray(grad, np.float32), 0.0, 1.0)
    return np.stack([np.interp(g, PALETTE_GRID, palette[:, c]) for c in range(3)],
                    axis=1).astype(np.float32)


def brightest_stop(effect: Any) -> np.ndarray:
    """The colour set's brightest colour as the effect samples it — the
    bloom's colour (his ruling: no white term, the set's own brightest)."""
    rgb = _sample_rgb(effect, np.linspace(0.0, 1.0, 64, dtype=np.float32))
    if rgb is None:
        return np.array([255.0, 255.0, 255.0], dtype=np.float32)
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    c = rgb[int(np.argmax(lum))]
    peak = float(c.max())
    return (c * (255.0 / peak)).astype(np.float32) if peak > 0 else c


class TransitionProgram:
    """The clock, the layers and the hand-off every program shares. A
    subclass supplies `_setup` (first frame, geometry known), `_step` (move
    the cloud, return the incoming gain) and `_hand_off`."""

    name = "program"
    RELEASE_HALF_LIFE_S = 0.12   # the outgoing's last picture fades this fast
    TRAIL_HALF_LIFE_S = 0.09     # the cloud's own streaks
    # begin() takes the outgoing's registry snapshot so the incoming adopts
    # nothing of its own — the program owns the pieces. A program whose
    # FORM is the incoming effect's own adoption (SHOALING) leaves it.
    TAKE_REGISTRY = True

    @classmethod
    def stage_fracs(cls, settings: ProgramSettings, out_type=None,
                    in_type=None) -> list[dict]:
        """The stages a preview ruler draws (see stages())."""
        a = anchor_frac(cls.name, settings, out_type, in_type)
        if cls.name == INFALL:
            return [{"label": "spiral in", "from": 0.0, "to": a},
                    {"label": "ignite", "from": a, "to": 1.0, "anchor": True}]
        if cls.name == ERUPTION:
            if settings.on_mark:
                return [{"label": "erupt", "from": 0.0, "to": ON_MARK_FORM_AT,
                         "anchor": True},
                        {"label": "implode", "from": ON_MARK_FORM_AT, "to": 1.0}]
            return [{"label": "contract", "from": 0.0, "to": a},
                    {"label": "erupt", "from": a, "to": ERUPTION_FORM_AT,
                     "anchor": True},
                    {"label": "implode", "from": ERUPTION_FORM_AT, "to": 1.0}]
        return [{"label": "release", "from": 0.0, "to": a},
                {"label": "form", "from": a, "to": 1.0, "anchor": True}]

    def __init__(self, settings: ProgramSettings, out_type: str, in_type: str):
        self.settings = settings
        self.out_type = out_type
        self.in_type = in_type
        self.duration = settings.duration_s
        self.anchor = anchor_frac(self.name, settings, out_type, in_type)
        self.rng = np.random.default_rng(settings.seed)
        self.done = False
        self.virtual = None
        self.incoming = None
        self.snap: Optional[dict] = None
        self.release: Optional[np.ndarray] = None
        self.trail: Optional[np.ndarray] = None
        self.t0: Optional[float] = None
        self.t_last = 0.0
        self._ready = False
        self.handed_off = False
        # a record of the last frame's stage + gain, for tests/telemetry
        self.last_gain = 0.0
        self.frames = 0

    # ── the virtual's two calls ──────────────────────────────────────────
    def capture(self, virtual, outgoing) -> bool:
        """Before the outgoing effect deactivates: read its live particles
        and its last picture. False (no particles, wrong shape, not a 2D
        particle effect) means no program — the switch rides its ordinary
        path."""
        if outgoing is None or not hasattr(outgoing, "_handoff_snapshot"):
            return False
        try:
            snap = outgoing._handoff_snapshot()
        except Exception:
            _LOGGER.exception("transition program: outgoing snapshot failed")
            return False
        if not snap or snap.get("px") is None or len(snap["px"]) == 0:
            return False
        w, h = snap["dims"]
        self.snap = snap
        self.dims = (int(w), int(h))
        grad = np.asarray(snap["grad"], dtype=np.float32)
        rgb = _sample_rgb(outgoing, grad)
        if rgb is None:
            rgb = np.full((grad.size, 3), 200.0, dtype=np.float32)
        self.rgb_out = rgb
        # the outgoing set's colours, sampled while it can still be asked
        # (a deactivated effect has no pixels to size its gradient by)
        self.out_palette = _sample_rgb(outgoing, PALETTE_GRID)
        self.release = self._last_picture(outgoing, (h, w))
        if self.release is None and isinstance(snap.get("trail"), np.ndarray) \
                and snap["trail"].shape == (h, w, 3):
            self.release = snap["trail"].astype(np.float32).copy()
        self.virtual = virtual
        return True

    def begin(self, virtual, incoming) -> None:
        """After the incoming effect is attached: own its render, and make
        sure it starts FRESH — the outgoing's deactivate() just left the
        same particles in the registry, and the program owns them now."""
        if self.TAKE_REGISTRY:
            particle_handoff.take(getattr(virtual, "id", "") or "")
        self.virtual = virtual
        self.incoming = incoming
        incoming._transition_program = self
        self.t0 = particle_handoff.now()
        self.t_last = 0.0

    # ── Twod.render's hook ───────────────────────────────────────────────
    def compose(self, effect) -> None:
        """Called by the incoming effect's Twod.render after its draw(),
        before its pixel mapping: one picture, composed by max."""
        if self.done or effect is not self.incoming:
            return
        h, w = effect.r_height, effect.r_width
        if (w, h) != self.dims:
            self.finish()
            return
        t = particle_handoff.now() - self.t0
        dt = min(max(t - self.t_last, 0.0), 0.1)
        self.t_last = t
        if not self._ready:
            self._ready = True
            self.trail = np.zeros((h, w, 3), dtype=np.float32)
            self._setup(effect)
        if dt > 0.0:
            self.trail *= np.float32(0.5 ** (dt / self.TRAIL_HALF_LIFE_S))
            if self.release is not None:
                self.release *= np.float32(0.5 ** (dt / self.RELEASE_HALF_LIFE_S))
        layer = np.zeros((h, w, 3), dtype=np.float32)
        gain = self._step(effect, t, dt, layer)
        np.maximum(self.trail, layer, out=self.trail)
        inc = np.asarray(effect.matrix, dtype=np.float32)
        if isinstance(gain, np.ndarray):
            # a per-cell gain (IGNITION's reveal mask, transition_cloud.py)
            out = np.maximum(self.trail, inc * gain[..., None])
            gain = float(gain.max()) if gain.size else 0.0
        else:
            gain = float(gain)
            out = np.maximum(self.trail, inc * gain)
        if self.release is not None:
            np.maximum(out, self.release, out=out)
        self.last_gain = gain
        self.frames += 1
        old = effect.matrix
        effect.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB")
        try:
            old.close()
        except Exception:
            pass
        if t >= self.duration:
            self.finish()

    def finish(self) -> None:
        """End now: hand the cloud over (at most once) and let go of the
        incoming effect's render. Also what a NEW switch arriving
        mid-program calls (Virtual.set_effect), so nothing is ever left
        half-handed."""
        if self.done:
            return
        self.done = True
        inc = self.incoming
        if inc is not None:
            if self._ready and not self.handed_off:
                self.handed_off = True
                try:
                    self._hand_off(inc)
                except Exception:
                    _LOGGER.exception("transition program: hand-off failed")
                self._merge_trail(inc)
            if getattr(inc, "_transition_program", None) is self:
                inc._transition_program = None
        virtual = self.virtual
        if virtual is not None and getattr(virtual, "_program", None) is self:
            virtual._program = None

    # ── shared pieces ────────────────────────────────────────────────────
    @staticmethod
    def _last_picture(effect, shape) -> Optional[np.ndarray]:
        """The outgoing effect's last rendered matrix in render space —
        unless a flip/mirror/rotate has already transposed it."""
        if getattr(effect, "flip2d", False) or getattr(effect, "mirror2d", False) \
                or getattr(effect, "rotate_t", 0):
            return None
        m = getattr(effect, "matrix", None)
        if m is None:
            return None
        try:
            arr = np.asarray(m, dtype=np.float32)
        except Exception:
            return None
        if arr.shape != (shape[0], shape[1], 3):
            return None
        return arr.copy()

    def _merge_trail(self, inc) -> None:
        tr = getattr(inc, "trail", None)
        if isinstance(tr, np.ndarray) and self.trail is not None \
                and tr.shape == self.trail.shape:
            np.maximum(tr, self.trail, out=tr)

    def _snap_arrays(self):
        s = self.snap
        n = len(s["px"])
        px = np.asarray(s["px"], dtype=np.float32).copy()
        py = np.asarray(s["py"], dtype=np.float32).copy()
        vx = np.asarray(s.get("vx", np.zeros(n)), dtype=np.float32)[:n].copy()
        vy = np.asarray(s.get("vy", np.zeros(n)), dtype=np.float32)[:n].copy()
        vx = np.where(np.isfinite(vx), vx, 0.0).astype(np.float32)
        vy = np.where(np.isfinite(vy), vy, 0.0).astype(np.float32)
        grad = np.asarray(s["grad"], dtype=np.float32).copy()
        bright = np.clip(np.asarray(s["bright"], dtype=np.float32), 0.0, 1.0)
        rgb = self.rgb_out
        keep = np.isfinite(px) & np.isfinite(py) & (bright > 0.03)
        return (px[keep], py[keep], vx[keep], vy[keep], grad[keep],
                bright[keep], rgb[keep])

    # subclass API
    def _setup(self, effect) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _step(self, effect, t, dt, layer) -> float:  # pragma: no cover
        raise NotImplementedError

    def _hand_off(self, effect) -> None:  # pragma: no cover
        raise NotImplementedError


# ── INFALL: particles -> Black Hole ────────────────────────────────────────

# A cloud of only a few pieces (three orbit blobs) reads as three dots, not
# a stream feeding the horizon: each piece is split into this many before
# the flight (a few px apart, staggered arrival), the last stretch reading
# as a tidal streak.
INFALL_MIN_PIECES = 24
INFALL_ARRIVE_MIN = 0.55   # the earliest piece reaches the horizon at this
                           # fraction of the flight; the latest at its end
INFALL_BALLISTIC = 0.35    # fraction of each piece's own flight over which
                           # its inherited velocity bends onto the spiral
INFALL_RING_EASE_S = 0.3   # an arrived piece eases onto the ring's own rate


class InfallProgram(TransitionProgram):
    name = INFALL

    def _setup(self, bh) -> None:
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        n = px.size
        if 0 < n < INFALL_MIN_PIECES:
            reps = int(math.ceil(INFALL_MIN_PIECES / n))
            jit = self.rng.normal(0.0, 1.1, (2, n * reps)).astype(np.float32)
            px = np.repeat(px, reps) + jit[0]
            py = np.repeat(py, reps) + jit[1]
            vx = np.repeat(vx, reps) * self.rng.uniform(0.85, 1.15, n * reps).astype(np.float32)
            vy = np.repeat(vy, reps) * self.rng.uniform(0.85, 1.15, n * reps).astype(np.float32)
            grad = np.repeat(grad, reps)
            bright = np.repeat(bright, reps)
            rgb = np.repeat(rgb, reps, axis=0)
            n = px.size
        self.n = n
        self.p0x, self.p0y = px, py
        self.v0x, self.v0y = vx, vy
        self.grad = grad
        self.bright = np.clip(bright, 0.35, 1.0)
        self.rgb_from = rgb
        rgb_in = _sample_rgb(bh, grad)
        self.rgb_to = rgb_in if rgb_in is not None else rgb
        self.x, self.y = px.copy(), py.copy()
        self.vx, self.vy = vx.copy(), vy.copy()
        # the Black Hole's own geometry, read live off the incoming effect
        self.cx, self.cy = float(bh.cx), float(bh.cy)
        self.sx, self.sy = max(float(bh.sx), 1e-6), max(float(bh.sy), 1e-6)
        gx = (px - self.cx) / self.sx
        gy = (py - self.cy) / self.sy
        self.r0 = np.hypot(gx, gy).astype(np.float32)
        self.th0 = np.arctan2(gy, gx).astype(np.float32)
        sw = float(getattr(bh, "swirl", 1.0) or 1.0)
        self.spin = 1.0 if sw >= 0 else -1.0
        flight = self.duration - self.settings.infall_form_s()
        self.T = (flight * self.rng.uniform(INFALL_ARRIVE_MIN, 1.0, n)).astype(np.float32)
        self.form_start = self.duration - self.settings.infall_form_s()
        self._form_v = None   # velocities carried into FORM (polar)

    def _rh(self, bh) -> float:
        try:
            return float(bh._horizon_radius())
        except Exception:
            return 0.2

    def _trajectory(self, t, rh):
        """The spiral each piece flies (pixel space), bent from its own
        inherited straight line over its first INFALL_BALLISTIC."""
        s = np.clip(t / np.maximum(self.T, 1e-3), 0.0, 1.0)
        e = s * s                       # faster as it falls
        r = self.r0 + (rh - self.r0) * e
        th = self.th0 + self.spin * 2.0 * np.pi * self.settings.infall_spin * e
        # once arrived, ride the ring at the rate the spiral ended on
        over = np.maximum(t - self.T, 0.0)
        end_rate = self.spin * 4.0 * np.pi * self.settings.infall_spin / np.maximum(self.T, 1e-3)
        th = th + end_rate * over
        tx = self.cx + r * np.cos(th) * self.sx
        ty = self.cy + r * np.sin(th) * self.sy
        b = _smoothstep(t / np.maximum(self.T * INFALL_BALLISTIC, 1e-3))
        bx = self.p0x + self.v0x * t
        by = self.p0y + self.v0y * t
        return bx + (tx - bx) * b, by + (ty - by) * b

    def _step(self, bh, t, dt, layer) -> float:
        rh = self._rh(bh)
        px, py = self.x.copy(), self.y.copy()
        if t < self.form_start:
            nx, ny = self._trajectory(t, rh)
            if dt > 0:
                self.vx = (nx - self.x) / dt
                self.vy = (ny - self.y) / dt
            self.x, self.y = nx, ny
        else:
            # FORM: the velocity the flight carried, blended into the Black
            # Hole's own field at each piece's radius over velocity_blend_s
            if self._form_v is None:
                self._form_v = self._polar(self.vx, self.vy)
            w = float(np.clip((t - self.form_start) / max(self.settings.infall_form_s(), 1e-3), 0.0, 1.0))
            w = w * (2.0 - w)
            cvx, cvy = self._cart(self._form_v)
            fvx, fvy = self._field(bh, self.x, self.y)
            self.vx = (1.0 - w) * cvx + w * fvx
            self.vy = (1.0 - w) * cvy + w * fvy
            self.x = self.x + self.vx * dt
            self.y = self.y + self.vy * dt
        # colour slides from what it was to the Black Hole's own gradient
        c = float(_smoothstep(t / max(self.form_start, 1e-3)))
        rgb = self.rgb_from + (self.rgb_to - self.rgb_from) * c
        splat_path(layer, px, py, self.x, self.y, rgb * self.bright[:, None])
        if self.settings.on_mark:
            return 1.0
        # the horizon ignites as it feeds: the Black Hole fades up over the
        # second half of the flight and is whole at the anchor
        return float(_smoothstep((t - 0.5 * self.form_start) / max(0.5 * self.form_start, 1e-3)))

    def _polar(self, vx, vy):
        gx = (self.x - self.cx) / self.sx
        gy = (self.y - self.cy) / self.sy
        th = np.arctan2(gy, gx)
        nvx, nvy = vx / self.sx, vy / self.sy
        vr = nvx * np.cos(th) + nvy * np.sin(th)
        vt = -nvx * np.sin(th) + nvy * np.cos(th)
        return vr, vt

    def _cart(self, polar):
        vr, vt = polar
        gx = (self.x - self.cx) / self.sx
        gy = (self.y - self.cy) / self.sy
        th = np.arctan2(gy, gx)
        nvx = vr * np.cos(th) - vt * np.sin(th)
        nvy = vr * np.sin(th) + vt * np.cos(th)
        return nvx * self.sx, nvy * self.sy

    @staticmethod
    def _field(bh, x, y):
        fn = getattr(bh, "_program_field_velocity", None)
        if fn is None:
            return np.zeros_like(x), np.zeros_like(y)
        return fn(x, y)

    def _hand_off(self, bh) -> None:
        """The real Black Hole adopts the loaded cloud with the velocity it
        has (its own field by now) — appended to what it already spawned."""
        adopt = getattr(bh, "_adopt_handoff", None)
        if adopt is None:
            return
        snap = {
            "src": "program",
            "t": particle_handoff.now(),
            "dims": self.dims,
            "px": self.x.astype(np.float32),
            "py": self.y.astype(np.float32),
            "vx": self.vx.astype(np.float32),
            "vy": self.vy.astype(np.float32),
            "grad": self.grad.astype(np.float32),
            "bright": self.bright.astype(np.float32),
            "gradient": bh._config.get("gradient"),
            "spin_sign": 0.0,
            "blob_size": float(getattr(bh, "blob_size", 0.0)) or None,
            "trail": None,          # merged by finish() into bh.trail
            "append": True,
            "gesture": "infall",
        }
        adopt(snap=snap, allow_hold=False)


# ── ERUPTION: Black Hole -> particles ──────────────────────────────────────

ERUPT_BLOOM_S = 0.28        # the bloom's own fade
ERUPT_BLOOM_SIGMA = 2.2     # px
ERUPT_SPEED_PX = 85.0       # ejecta launch speed at eruption_speed 1
ERUPT_DRAG = 2.0            # 1/s: the ejecta decelerate
ERUPT_CONTRACT_TURNS = 0.35 # extra spin the contraction adds


class EruptionProgram(TransitionProgram):
    name = ERUPTION

    def _setup(self, inc) -> None:
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        c = self.snap.get("center_px") or (inc.r_width / 2.0, inc.r_height / 2.0)
        self.ccx, self.ccy = float(c[0]), float(c[1])
        self.bloom_rgb = brightest_stop(inc)
        # the outgoing blobs (ring included): they contract to the centre
        self.bx0, self.by0 = px, py
        self.bvx, self.bvy = vx, vy
        self.brgb = rgb * np.clip(bright, 0.3, 1.0)[:, None]
        dx, dy = px - self.ccx, py - self.ccy
        self.b_rho0 = np.hypot(dx, dy).astype(np.float32)
        self.b_phi0 = np.arctan2(dy, dx).astype(np.float32)
        # each blob's own angular rate about the centre (its swirl)
        rho = np.maximum(self.b_rho0, 1e-3)
        self.b_om = ((dx * vy - dy * vx) / (rho * rho)).astype(np.float32)
        self.ba_x, self.ba_y = px.copy(), py.copy()
        self.t_bloom = self.anchor * self.duration
        self.t_form = (ON_MARK_FORM_AT if self.settings.on_mark
                       else ERUPTION_FORM_AT) * self.duration
        self.ejecta = False
        self.e_n = 0
        self.form = None
        self._tq = None       # target positions last frame (velocity estimate)
        self._tu = None

    def _spawn_ejecta(self, inc) -> None:
        n = int(self.settings.eruption_count)
        rng = self.rng
        ang = (np.arange(n) + rng.uniform(0.0, 1.0, n)) / n * 2.0 * np.pi
        ang = ang.astype(np.float32)
        spd = (ERUPT_SPEED_PX * self.settings.eruption_speed
               * rng.uniform(0.55, 1.0, n)).astype(np.float32)
        self.ex = np.full(n, self.ccx, dtype=np.float32) + rng.normal(0, 0.4, n).astype(np.float32)
        self.ey = np.full(n, self.ccy, dtype=np.float32) + rng.normal(0, 0.4, n).astype(np.float32)
        self.evx = np.cos(ang) * spd
        self.evy = np.sin(ang) * spd * (inc.r_height / max(inc.r_width, 1))  # panel aspect
        if self.settings.on_mark:
            # no contraction on the mark: the Black Hole's own blobs erupt
            # straight out on the motion they had, plus an outward kick
            dx, dy = self.bx0 - self.ccx, self.by0 - self.ccy
            d = np.maximum(np.hypot(dx, dy), 1e-3)
            k = ERUPT_SPEED_PX * 0.5 * self.settings.eruption_speed
            self.ex = np.concatenate([self.ex, self.bx0])
            self.ey = np.concatenate([self.ey, self.by0])
            self.evx = np.concatenate([self.evx, self.bvx + dx / d * k])
            self.evy = np.concatenate([self.evy, self.bvy + dy / d * k])
            ang = np.concatenate(
                [ang, (np.arctan2(dy, dx) % (2 * np.pi)).astype(np.float32)])
        n = self.ex.size
        # hue by angle: the whole colour set around the bloom
        self.egrad = (ang / (2.0 * np.pi)) % 1.0
        rgb = _sample_rgb(inc, self.egrad)
        self.ergb = rgb if rgb is not None else np.full((n, 3), 220.0, dtype=np.float32)
        self.e_n = n
        self.ejecta = True

    def _targets(self, inc, dt):
        fn = getattr(inc, "_formation_points", None)
        if fn is None:
            return None
        try:
            qx, qy = fn()
        except Exception:
            return None
        qx = np.asarray(qx, dtype=np.float32)
        qy = np.asarray(qy, dtype=np.float32)
        if qx.size == 0:
            return None
        if self._tq is not None and self._tq[0].size == qx.size and dt > 0:
            ux = (qx - self._tq[0]) / dt
            uy = (qy - self._tq[1]) / dt
            if self._tu is not None:
                a = 0.5
                ux = a * ux + (1 - a) * self._tu[0]
                uy = a * uy + (1 - a) * self._tu[1]
        else:
            ux = np.zeros_like(qx)
            uy = np.zeros_like(qy)
        self._tq = (qx, qy)
        self._tu = (ux, uy)
        return qx, qy, ux, uy

    def _step(self, inc, t, dt, layer) -> float:
        targets = self._targets(inc, dt)
        # 1. CONTRACTION (before the bloom): the ring and its blobs fall to
        # the centre on the swirl they had, brightening as they gather
        if not self.settings.on_mark and t < self.t_bloom:
            s = t / max(self.t_bloom, 1e-3)
            e = float(_smoothstep(s))
            rho = self.b_rho0 * (1.0 - e)
            spin_up = 1.0 + 2.0 * e
            phi = self.b_phi0 + self.b_om * t * spin_up \
                + np.sign(self.b_om) * 2 * np.pi * ERUPT_CONTRACT_TURNS * e * e
            tx = self.ccx + rho * np.cos(phi)
            ty = self.ccy + rho * np.sin(phi)
            b = float(_smoothstep(s / 0.4))
            bx = self.bx0 + self.bvx * t
            by = self.by0 + self.bvy * t
            px, py = self.ba_x, self.ba_y
            self.ba_x = bx + (tx - bx) * b
            self.ba_y = by + (ty - by) * b
            splat_path(layer, px, py, self.ba_x, self.ba_y,
                       np.minimum(self.brgb * (1.0 + 0.4 * e), 255.0), 0.75)
            return 0.0
        if not self.ejecta:
            self._spawn_ejecta(inc)
        # 2. THE BLOOM: the set's brightest stop, on the mark
        tb = t - self.t_bloom
        if tb < ERUPT_BLOOM_S:
            g = 1.0 - tb / ERUPT_BLOOM_S
            h, w = layer.shape[:2]
            yy, xx = np.mgrid[0:h, 0:w]
            d2 = (xx + 0.5 - self.ccx) ** 2 + (yy + 0.5 - self.ccy) ** 2
            sig = ERUPT_BLOOM_SIGMA * (1.0 + 1.5 * tb / ERUPT_BLOOM_S)
            glow = np.exp(-d2 / (2 * sig * sig)).astype(np.float32) * g
            np.maximum(layer, glow[..., None] * self.bloom_rgb, out=layer)
        # 3. FLIGHT, then 4. FORM: implode onto the live, moving targets
        if t < self.t_form or targets is None:
            decay = np.float32(math.exp(-ERUPT_DRAG * dt))
            self.evx *= decay
            self.evy *= decay
            px, py = self.ex, self.ey
            self.ex = self.ex + self.evx * dt
            self.ey = self.ey + self.evy * dt
            splat_path(layer, px, py, self.ex, self.ey, self.ergb)
            if t >= self.t_form and targets is None:
                # nothing to form onto: the ejecta simply fade out
                f = 1.0 - float(np.clip((t - self.t_form) / max(self.duration - self.t_form, 1e-3), 0, 1))
                layer *= np.float32(f)
                return float(_smoothstep((t - self.t_form) / max(self.duration - self.t_form, 1e-3)))
            return 0.0
        qx, qy, ux, uy = targets
        m = qx.size
        if self.form is None:
            # each piece implodes onto the target NEAREST where it will be
            # once the convergence is half done (its drifting position
            # against the target's moving one) — never across the panel
            tau0 = max(self.duration - self.t_form, 1e-3)
            fx_ = self.ex + self.evx * 0.25 * tau0
            fy_ = self.ey + self.evy * 0.25 * tau0
            gx_ = qx + ux * 0.5 * tau0
            gy_ = qy + uy * 0.5 * tau0
            j = np.argmin((fx_[:, None] - gx_[None, :]) ** 2
                          + (fy_[:, None] - gy_[None, :]) ** 2, axis=1)
            self.form = {
                "j": j,
                "d0x": self.ex - qx[j], "d0y": self.ey - qy[j],
                "e0x": self.evx - ux[j], "e0y": self.evy - uy[j],
            }
        f = self.form
        j = f["j"] % m
        tau = max(self.duration - self.t_form, 1e-3)
        s = float(np.clip((t - self.t_form) / tau, 0.0, 1.0))
        h00 = 2 * s ** 3 - 3 * s ** 2 + 1
        h10 = s ** 3 - 2 * s ** 2 + s
        dh00 = (6 * s ** 2 - 6 * s) / tau
        dh10 = (3 * s ** 2 - 4 * s + 1)
        nx = qx[j] + h00 * f["d0x"] + h10 * tau * f["e0x"]
        ny = qy[j] + h00 * f["d0y"] + h10 * tau * f["e0y"]
        self.evx = ux[j] + dh00 * f["d0x"] + dh10 * f["e0x"]
        self.evy = uy[j] + dh00 * f["d0y"] + dh10 * f["e0y"]
        fade = np.float32(1.0 - s ** 3)
        px, py = self.ex, self.ey
        self.ex, self.ey = nx, ny
        splat_path(layer, px, py, nx, ny, self.ergb * fade)
        return s * s

    def _hand_off(self, inc) -> None:
        # Nothing to adopt: every piece has already arrived ON a live
        # formation point with its velocity, and has faded into it. The
        # cloud's streaks are merged into the incoming trail by finish().
        return
