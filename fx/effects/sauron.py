"""SAURON — the Eye of Sauron on the crystal (Matrix).

The Admiral, 2026-10-10: "copy our current scene Effect called [Eye] and
make it look a lot more like the eye of Sauron and incorporate the
flaminess of that eye as a burning effect that uses the color set well".
His follow-up answers settled the shape: a COPY (Eye stays byte-for-byte
untouched), crystal first, the eye looks around and the beat modulates the
slit, the flames surge on bass and on flares; charge/lull/drop choreography
of its own comes after he has tested the scene. The approved plan (v2,
"go with all recs") is /home/javi/fleet-spotfx/data/sauron-eye-plan/
report.md; this module is its phase 1.

WHAT IS COPIED FROM EYE, VERBATIM IN BEHAVIOUR: the gaze model
(`_update_gaze`: eight ring positions, a wandering search that speeds up
with the band, a dart on a hit above `snap_threshold`, the hold, the
micro-saccades), the 3D foreshortening (`gaze_depth`, the pupil leading
into the gaze), the particle hand-off choreography (`_handoff_snapshot` /
`_adopt_handoff`, src "sauron", the same cross-type adoption every other
effect gives "eye"), and the charge/lull/drop state machine Eye already
has (iris grows / slit narrows / flames run inward on a charge, the lids
close on a lull, the drop opens them with an eruption). Those are
INHERITED, not new Sauron choreography — that is a later phase.

ONE DELIBERATE DEPARTURE IN THE COPY: Eye's `snap_threshold` saturating
`>=` (a clipped impulse reaches exactly 1.0, so "1.0 = never" fires
anyway — AGENTS.md "A SATURATING SIGNAL MEETING >=") is fixed here the way
dancer.py's burst_threshold is: `thr < 1.0 and imp >= thr`. Eye keeps its
own defect (captain's call, eye-effect skill).

WHAT IS NEW — THE PICTURE (inside to outside):
  * a black VERTICAL SLIT pupil — a lens of two circle arcs, `pupil_size`
    tall and `pupil_width` wide (fractions of the iris radius). The BEAT
    dilates it: width by `pupil_beat` x (0.55 + 0.45 x bass) and height by
    SLIT_HEIGHT_BEAT (0.3) of that — "as prototyped", easing back over
    BEAT_PULSE_TAU; bass also widens it a little (SLIT_BASS_WIDEN).
    TUNE-UP 1 (the Admiral, 2026-10-11: "the eye slit [doesn't] resolve
    quite right as [it moves] because of the nature of the hex pattern. I
    think we can increase the minimum slit width by a pixel"): wherever
    the lens is narrower, a rounded column keeps its fully dark core at
    least SLIT_MIN_DARK_PX (3) RENDERED pixels wide — one lattice period
    (a row holds a real cell every second column) plus his one pixel —
    stopping short of the tips so they still come to a point, and undoing
    the eyeball turn's sideways squeeze (`slit_min_half`). A charge or the
    narrowest Slit Width now narrows the slit TO that floor, never past it.
  * a WHITE-HOT RIM hugging the slit (`core_white`), flaring on the beat.
  * the IRIS as fire: heat 0.5-0.8 rising toward the slit, radial STREAKS
    from two angular noise layers (`streaks`), and the PERIMETER RING
    where the flames root — since tune-up 1 ("the perimeter should cleanly
    blend with the flame if we increase its thickness") a band RING_WIDTH
    wide (~2 px each side, was ~1) that does not stop at the iris edge: it
    fades into the flames over RING_FADE, roughened by the flame field,
    and is SCREENED with them (1 - (1-a)(1-b)), so there is no step and no
    crease where the flames leave it.
  * the FLAMES — plan method A, chosen over particles and a heat buffer
    (cheapest, erupts ON the mark, centred on the eye the instant it moves):
    a polar simplex-noise field scrolled outward and shaped into `tongues`
    licks whose LENGTH is a fraction of each pixel's own gap from the iris
    rim to the crystal's HEX EDGE along its own ray from the eye (never a
    scalar radius — the crystal-hex-grid lesson). Reach = `flames` x
    (1 + `flame_audio` x bass + 1.6 x surge), so bass lengthens them;
    `flame_speed` scrolls them.
  * the BURNING SKY — a dim ember floor over the whole hex (`sky`, default
    0.14; 0 = black sky).

THE COLOUR SET (`palette_sort`). Every pixel has a HEAT, 0 (flame tip) to
1 (the slit's rim); the colour is the set's gradient sampled at that heat,
after the set's distinct colours are re-ORDERED along the heat:
  authored    the stops exactly as stored
  brightness  darkest colour at the tips .. brightest at the rim (Rec.709)
  warm        coldest hue at the tips .. warmest at the rim (warmth =
              cos(hue - 30 deg); an achromatic colour counts as hottest)
  radial      (tune-up 1) the set cold -> warm walked OUTWARD-IN through
              the eye's own shape, heat only sets brightness: inside the
              iris the fraction of the way from the slit's edge to the
              iris's edge (lens-shaped against the slit, round at the rim —
              his "don't make it perfectly radial, considering the eye
              slit is not radially symmetric"), outside it the fraction of
              the way to the crystal's edge along each ray (following the
              hexagon), tinted RADIAL_HEAT_MIX by the flames (`radial_coord`)
  angle       Eye's rainbow rule: colour by angle around the eye, heat only
              sets brightness
  auto        (default) `brightness`, or `radial` for a RAINBOW set — one
              whose chromatic stops span more than RAINBOW_SPAN_DEG of hue,
              the same test Pulse's rainbow walk and the compiler use. (It
              was `warm`, heat-mapped, until tune-up 1: the Admiral, after
              tuning it live, "the sauron with rainbow colors is too
              messy" — a noisy heat across eight hues speckles.) "auto" is
              resolved with the curve, so a colour journey carrying the set
              across the rainbow line switches the mapping with it.
The sort rewrites only the curve THIS effect samples, once per gradient
change (GradientEffect regenerates its curve only on a config change) —
never his colour-set data and never another effect. A solid colour is
untouched (heat is brightness). Each re-ordered colour keeps its own share
of the gradient (PALETTE_BAND: it holds for that fraction of its share
before blending into the next).

THE SURGE FLARE: SpotFX's `sauron_surge` flare kind pokes the
unregistered, self-resetting `surge` key with the fire's intensity
(fx.device_model.SAURON_SURGE_EFFECTS — the firework_burst / pulse_flash
shape). Edge-detected in config_updated; draw raises the surge envelope to
at least that value and resets the key so an identical later write edges
again. The envelope erupts the fire — reach x(1 + 1.6 s), heat x(0.9 +
0.35 s), sky x(1 + 0.6 s), scroll x(1 + 1.5 s) — and burns back with time
constant SURGE_TAU (~0.55 s). No lead: it erupts ON the mark.

BACKGROUND: like Eye — no `no_background_color` flag, an authored
background reaches the wire and `get_pixels()` paints it once for every
unlit cell. This effect NEVER paints `_bg_color` itself (AGENTS.md "A
colour set's background MODE lands in ONE place"); the lids are literal
black. With the sky on there are almost no unlit cells inside the hex.

CRYSTAL-SHAPED: the flame reach and the sky are bounded by the crystal's
hexagon (fx/effects/blackhole.py's measured faces). On any other Matrix
panel the flames still render, bounded by that same hexagon in the panel's
own normalized frame.
"""

import logging

import numpy as np
import voluptuous as vol
from PIL import Image
from pyfastnoiselite import pyfastnoiselite as fnl

import fx.effects.particle_handoff as particle_handoff
from fx.color import parse_gradient, validate_gradient
from fx.effects import lull_handoff, phase_grammar
from fx.effects.audio import AudioReactiveEffect
from fx.effects.blackhole import _HEX_FACE_D, _HEX_FACE_NX, _HEX_FACE_NY
from fx.effects.gradient import GradientEffect
from fx.effects.pulse import chromatic_span_deg
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

DT_MAX = 0.1
GAZE_N = 8          # ring positions (index 0 is the center "primary")
TARGET_TIMEOUT_S = 4.0   # give up searching and pick a new target
SNAP_LAND_S = 0.08  # a snap dart covers the remaining distance this fast
GAZE_ANGLE_GAIN = 1.4   # radians of eyeball turn per unit of gaze offset
GAZE_ANGLE_MAX = 0.9    # ~52 deg cap
PUPIL_LEAD = 0.5        # slit leads into the gaze by this x sin(theta) x iris_r
# transitions (see particle_handoff) — copied from eye.py
N_RIM = 28          # rim particles in the outgoing snapshot
INFALL_S = 1.1      # seconds adopted particles take to reach the rim
INFALL_CAP = 160    # max adopted particles animated
FORM_S = 0.35       # iris scale-in after a radial implode
BLINK_OPEN_S = 0.4  # lid-reveal opening time (dancer transitions)
# charge/lull/drop — Eye's own state machine, inherited (not new
# choreography): see _phase_step
CHARGE_IRIS_GROW = 0.30    # iris radius gain at full charge
CHARGE_PUPIL_SHRINK = 0.5  # slit width loss at full charge
CHARGE_FLAME_GROW = 1.6    # flame reach gain at full charge (Eye's length x)
CHARGE_RELAX_S = 0.5       # ease charged sizes back after the payoff
LULL_FALLBACK_S = 2.0      # lull closes on this timer if no progress ramp
DROP_OPEN_S = 0.18         # lid snaps open this fast on the drop
DROP_BURST_S = 0.45        # eruption envelope decay constant
DROP_TOTAL_S = 1.2         # drop phase self-resets to "none" after this
LID_PAUSE_START = 0.50     # progress where the lid pauses on the iris
LID_PAUSE_END = 0.75       # progress where the final close begins
# ── the picture (plan v2 prototype, method A) ──────────────────────────
BEAT_PULSE_TAU = 0.16      # the beat's slit dilation eases back over this
SLIT_HEIGHT_BEAT = 0.3     # height dilates by this share of the width's
SLIT_BASS_WIDEN = 0.25     # bass alone widens the slit by up to this
SLIT_MAX_ASPECT = 0.95     # the slit is never wider than this x its height
SURGE_TAU = 0.55           # the surge flare burns back with this constant
SURGE_REACH = 1.6          # reach gain per unit of surge
SURGE_HEAT = 0.35          # flame heat gain per unit of surge (on 0.9)
SURGE_SKY = 0.6            # sky gain per unit of surge
SURGE_SCROLL = 1.5         # outward scroll gain per unit of surge
OVERREACH = 1.12           # a lick may reach this x the gap (past the edge)
# tune-up 1 (the Admiral, 2026-10-11) ─────────────────────────────────────
SLIT_AA_PX = 1.2           # the slit's anti-aliased edge, rendered px
SLIT_MIN_DARK_PX = 3.0     # its fully dark core is never narrower than this
                           # (one lattice period, 2 px, plus one pixel)
SLIT_MIN_TIP = 1.5         # the floor column stops this x its half-width
                           # short of the tips, so they still come to a point
RING_WIDTH = 0.11          # the perimeter ring's half-width (eye units;
                           # ~2 px each side on the crystal; was 0.05)
RING_GAIN = 0.5            # how much the ring heats the iris's edge
RING_OUT_HEAT = 0.9        # the ring's heat where it meets the flames
RING_FADE = 0.2            # it fades into the flames over this (eye units)
RING_FADE_ROUGH = 0.35     # the flame field roughens that fade by this much
# the radial mapping (`palette_sort` radial; auto for a rainbow set)
RADIAL_IRIS_SHARE = 0.3    # the iris spans this much of the colour run
RADIAL_OUTER_SPAN = 0.75   # the outer run ends this far out along the gap
RADIAL_HEAT_MIX = 0.12     # the flames' heat tints the coordinate this much
RAINBOW_SPAN_DEG = 180.0   # "auto" sorts a set spanning more hue cold->warm
PALETTE_BAND = 0.35        # a sorted colour holds this share of its band
SURGE_POKE_FLOOR = 0.001   # a fire at intensity 0 still edges the poke
# a surge's eruption has visibly burned back (5% of it left) after this —
# what the flare preview's ruler draws as the animation's end
SURGE_VISIBLE_S = 3.0 * SURGE_TAU


def surge_visible_s(intensity: float) -> float:
    """Seconds a surge poked at `intensity` stays visible (above 5% of a
    full surge): the envelope decays exp(-t / SURGE_TAU) from `intensity`,
    so a weaker fire burns back sooner. 0 for a fire that never rises
    above that floor."""
    i = max(float(intensity), SURGE_POKE_FLOOR)
    return max(0.0, SURGE_TAU * float(np.log(i / 0.05))) if i > 0.05 else 0.0
PALETTE_SORTS = ["auto", "authored", "brightness", "warm", "radial", "angle"]


# ── the palette sort (pure; tests and scripts/check_sauron.py use these) ──

def luminance(rgb) -> float:
    """Rec.709 relative luminance of an 0..255 rgb triple, 0..1."""
    r, g, b = (float(c) / 255.0 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hue_deg(rgb):
    r, g, b = (float(c) / 255.0 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d < 1e-6:
        return None
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h * 60.0) % 360.0


def warmth(rgb) -> float:
    """-1 (coldest, azure) .. +1 (warmest, orange); an achromatic colour
    counts as hottest — white is the hottest thing in a fire."""
    h = _hue_deg(rgb)
    if h is None:
        return 1.0 + luminance(rgb) * 0.01
    return float(np.cos(np.radians(h - 30.0)))


def resolve_palette_sort(how: str, gradient) -> str:
    """The mapping `how` actually applies to `gradient`: "auto" resolves
    to "radial" for a rainbow set (the Admiral, 2026-10-11: heat-mapping a
    rainbow is too messy) and "brightness" for everything else."""
    if how != "auto":
        return how
    return ("radial" if chromatic_span_deg(gradient) > RAINBOW_SPAN_DEG
            else "brightness")


# the colour ORDER each mapping lays along its coordinate: "radial" walks
# the set cold -> warm outward-in, the order a heat-mapped rainbow used
SORT_ORDER = {"radial": "warm"}


def _stops(gradient):
    """[(rgb tuple, pos)] sorted by position, or None for a solid colour."""
    try:
        parsed = parse_gradient(gradient)
    except Exception:
        return None
    colors = getattr(parsed, "colors", None)
    if not colors:
        return None
    stops = [(tuple(int(v) for v in c), float(p)) for c, p in colors]
    stops.sort(key=lambda s: s[1])
    return stops


def _stops_to_gradient(stops) -> str:
    return "linear-gradient(90deg, " + ", ".join(
        f"rgb({r},{g},{b}) {p * 100:.2f}%" for (r, g, b), p in stops) + ")"


def ordered_gradient(gradient, how: str) -> str:
    """`gradient` with its distinct colours re-ORDERED along the heat for
    `how` ("brightness" or "warm"; anything else returns it unchanged).
    Each colour keeps its own share of the gradient (the width it occupied
    as authored), holds for PALETTE_BAND of that share, then blends into
    the next. A solid colour, or a gradient of one distinct colour, comes
    back as written."""
    if how not in ("brightness", "warm"):
        return gradient
    stops = _stops(gradient)
    if not stops:
        return gradient
    weights: dict = {}
    order: list = []
    for i, (c, p) in enumerate(stops):
        lo = stops[i - 1][1] if i else 0.0
        hi = stops[i + 1][1] if i + 1 < len(stops) else 1.0
        if c not in weights:
            weights[c] = 0.0
            order.append(c)
        weights[c] += (hi - lo) / 2.0
    if len(order) < 2:
        return gradient
    key = {"brightness": lambda c: (luminance(c), warmth(c)),
           "warm": lambda c: (warmth(c), luminance(c))}[how]
    cols = sorted(order, key=key)
    total = sum(weights[c] for c in cols) or 1.0
    out, pos = [], 0.0
    for c in cols:
        out.append((c, pos))
        pos += (weights[c] or (1.0 / len(cols))) / total
    out[-1] = (out[-1][0], 1.0)
    banded = []
    for i, (c, p) in enumerate(out):
        banded.append((c, p))
        if i + 1 < len(out):
            banded.append((c, p + (out[i + 1][1] - p) * PALETTE_BAND))
    return _stops_to_gradient(banded)


def palette_gradient(gradient, how: str) -> str:
    """The gradient string this effect samples for `palette_sort` = how."""
    resolved = resolve_palette_sort(how, gradient)
    return ordered_gradient(gradient, SORT_ORDER.get(resolved, resolved))


class Sauron2d(Twod, GradientEffect):
    NAME = "Sauron"
    # THE DROP SHOCKWAVE (fx/effects/phase_grammar.py): born on the iris
    # rim; its debris burns out as flame licks
    DROP_SHOCK = True
    SHOCK_DEBRIS_FATE = "fade"
    CATEGORY = "Matrix"
    # color_blend stays hidden — colours update in place, recreation would
    # reset the gaze. phase/phase_progress are SpotFX-driven; `surge` is
    # the flare poke (advanced, not hidden, so it can be hand-scrubbed).
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "phase",
        "phase_progress",
        "surge",
        *phase_grammar.BREATH_KEYS,
        lull_handoff.DROP_KEY,
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="The fire's colours, mapped along the heat (see Palette Sort)",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "palette_sort",
                description="Colour order along the heat: auto (brightness; cold to warm for a rainbow set), authored, brightness, warm, or angle (Eye's rainbow-by-angle)",
                default="auto",
            ): vol.In(PALETTE_SORTS),
            vol.Optional(
                "iris_size",
                description="Iris radius as a fraction of the panel's half-height",
                default=0.62,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=0.9)),
            vol.Optional(
                "pupil_size",
                description="Slit height as a fraction of the iris radius",
                default=0.80,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
            vol.Optional(
                "pupil_width",
                description="Slit width as a fraction of the iris radius",
                default=0.17,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.03, max=0.6)),
            vol.Optional(
                "pupil_beat",
                description="How much a beat dilates the slit (width; height at 0.3 of it)",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "core_white",
                description="How white the slit's hot rim goes",
                default=0.65,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "streaks",
                description="Depth of the iris's radial fire streaks",
                default=0.55,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "flames",
                description="Flame reach at rest, as a fraction of the gap from the iris to the panel edge",
                default=0.55,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "flame_audio",
                description="How much bass lengthens the flames",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "flame_speed",
                description="Outward scroll speed of the flames",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=3.0)),
            vol.Optional(
                "tongues",
                description="Flame licks around the eye",
                default=9.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=3.0, max=24.0)),
            vol.Optional(
                "sky",
                description="The dim ember floor over the whole panel; 0 = black sky",
                default=0.14,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.6)),
            vol.Optional(
                "drift_speed",
                description="Base gaze search speed",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
            vol.Optional(
                "gaze_radius",
                description="Radius of the 8-position gaze ring",
                default=0.36,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.6)),
            vol.Optional(
                "gaze_depth",
                description="3D eyeball illusion: the iris foreshortens and the slit leads as the eye looks away from center; 0 = flat",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "snap_threshold",
                description="Audio impulse a beat needs to snap the gaze to a new position; 1 = never",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "snap_hold",
                description="Base seconds the gaze holds after a snap (bigger hits hold longer)",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "speed_audio",
                description="How much the selected band boosts the gaze search speed",
                default=2.9,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
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
                "frequency_range",
                description="Audio band driving the eye and the flames",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "impulse_decay",
                description="Decay filter applied to the audio impulse",
                default=0.06,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.3)),
            vol.Optional(
                "lull_lids_upside_down",
                description="Lull: the lids close upside down (the lull turned 180 degrees about the eye; the drop opens them the same way)",
                default=True,
            ): bool,
            vol.Optional(
                "color_blend",
                description="Restart effect on color change, for transitions",
                default=False,
            ): bool,
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
                "surge",
                description="Surge flare poke: the fire's intensity (written by SpotFX, self-resets)",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            # THE PHASE GRAMMAR (fx/effects/phase_grammar.py): the drop's
            # Shockwave settings (registered) and the breath-hold keys
            # (ride ONLY the lull arm write)
            **phase_grammar.shock_schema_fields(),
            **phase_grammar.breath_schema_fields(),
            **lull_handoff.drop_schema_fields(),
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        # Gaze + fire state lives here (NOT do_once) so it survives config
        # patches — do_once re-runs on every config change.
        self._rng = np.random.default_rng()
        self.gaze = np.zeros(2, dtype=np.float32)   # normalized, eye-space
        self._target_idx = 0
        self._target_t = 0.0
        self._hold_left = 0.0
        self._beat_pending = False
        self._beat_kick = 0.0
        self._rush = 0.0
        self._arc_sign = 1.0
        self._wander_t = 0.0
        self._wander_seed = float(self._rng.uniform(0, 2 * np.pi))
        self._reach_jig = 1.0
        self.impulse = 0.0
        self._t = 0.0
        self._flow_t = 0.0
        self._pulse = 0.0
        self._surge_env = 0.0
        self._burst = 0.0
        self._lid = 0.0
        # the lids are drawn turned 180 degrees about the eye: set when a
        # lull starts (lull_lids_upside_down), kept through the drop until
        # the lids are open again (eye.py's)
        self._lids_rotated = False
        self._drop_slam = False
        self._charge_amt = 0.0
        self.noise = fnl.FastNoiseLite(
            seed=int(self._rng.integers(1, 1 << 30)))
        self.noise.noise_type = fnl.NoiseType.NoiseType_OpenSimplex2
        self.noise.frequency = 1.0
        # transition state (eye.py's)
        self._handoff_pending = True
        self._infall = None
        self._form = None
        self._erupt_hold = None
        self._pacman_hold = None
        self._blink_in = None
        self._pull = None
        span = np.arange(-2, 3)
        kdx, kdy = np.meshgrid(span, span)
        kd = np.sqrt(kdx**2 + kdy**2).ravel()
        keep = kd <= 2.0
        self.dk_dx = kdx.ravel()[keep].astype(np.int32)
        self.dk_dy = kdy.ravel()[keep].astype(np.int32)
        self.dk_w = (1.0 - kd[keep] / 2.6).astype(np.float32)
        # instruments (read by tests and scripts/check_sauron.py only)
        self.last_heat = None
        self.last_d = None
        self.last_flame = None
        self.last_slit = None
        self.last_radial = None
        self.last_ring = None
        self.last_slit_core = None
        self.last_eye_px = (0.0, 0.0)

    def config_updated(self, config):
        super().config_updated(config)
        c = self._config
        for k in ("iris_size", "pupil_size", "pupil_width", "pupil_beat",
                  "core_white", "streaks", "flames", "flame_audio",
                  "flame_speed", "tongues", "sky", "drift_speed",
                  "gaze_radius", "gaze_depth", "snap_threshold", "snap_hold",
                  "speed_audio", "x_offset", "y_offset"):
            setattr(self, k, float(c[k]))
        self.palette_sort = c.get("palette_sort", "auto")
        self.lull_lids_upside_down = bool(c.get("lull_lids_upside_down", True))

        ang = np.arange(GAZE_N) * (2 * np.pi / GAZE_N)
        self.positions = np.zeros((GAZE_N + 1, 2), dtype=np.float32)
        self.positions[1:, 0] = self.gaze_radius * np.cos(ang)
        self.positions[1:, 1] = self.gaze_radius * np.sin(ang)

        # the surge poke: edge-detected like fireworks' burst_rockets (a
        # write that changes the value arms; draw consumes it and resets
        # the key to 0 so an identical later write edges again)
        new_surge = float(c.get("surge", 0.0) or 0.0)
        if not hasattr(self, "_surge_seen"):
            # creation baseline: a stale persisted poke never erupts
            self._surge_seen = new_surge
            self._surge_pending = 0.0
        elif new_surge != self._surge_seen:
            self._surge_seen = new_surge
            if new_surge > 0.0:
                self._surge_pending = max(self._surge_pending, new_surge)

        # charge/lull/drop: edge-detect the phase key (eye.py's shape)
        new_phase = c.get("phase", "none")
        self.phase_progress = float(c.get("phase_progress", 0.0))
        if not hasattr(self, "_phase"):
            self._phase = "none"
            self._phase_t = 0.0
            self._phase_pending = None
            self._phase_done_t = None
            self._drop = None
        else:
            self._phase_pending = new_phase if new_phase != self._phase else None

        self.power_func = self.POWER_FUNCS_MAPPING[c["frequency_range"]]
        self.impulse_filter = self.create_filter(
            alpha_decay=c["impulse_decay"], alpha_rise=0.99
        )

    def _generate_gradient_curve(self, gradient, gradient_length):
        """The curve this effect samples is the set's gradient re-ordered
        for `palette_sort` (authored / angle leave it as written). It runs
        only when GradientEffect regenerates its curve — on a config
        change — never per frame."""
        how = getattr(self, "palette_sort", None) or self._config.get(
            "palette_sort", "auto")
        try:
            self._mapping = resolve_palette_sort(how, gradient)
            gradient = palette_gradient(gradient, how)
        except Exception:                           # noqa: BLE001
            self._mapping = "authored"
            _LOGGER.warning("sauron: palette sort failed; using as authored")
        super()._generate_gradient_curve(gradient, gradient_length)

    def mapping(self) -> str:
        """What the colour section samples this frame: "angle" (around the
        eye), "radial" (outward through the eye's own shape), or anything
        else = the heat. Resolved with the curve, so "auto" follows the set
        it is wearing now (a colour journey can carry a set across the
        rainbow line)."""
        self._assert_gradient()
        return getattr(self, "_mapping", self.palette_sort)

    def audio_data_updated(self, data):
        impulse = self.impulse_filter.update(getattr(data, self.power_func)())
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True

    def do_once(self):
        super().do_once()
        self.cx = (self.r_width - 1) * self.x_offset
        self.cy = (self.r_height - 1) * self.y_offset
        self.sx = max((self.r_width - 1) / 2.0, 1e-6)
        self.sy = max((self.r_height - 1) / 2.0, 1e-6)
        self.s_min = max(min(self.sx, self.sy), 1.0)
        y_idx, x_idx = np.indices((self.r_height, self.r_width))
        self.px_x = x_idx.astype(np.float32)
        self.px_y = y_idx.astype(np.float32)
        # the crystal's hexagon in the panel's own normalized frame
        self.pcx = (self.r_width - 1) / 2.0
        self.pcy = (self.r_height - 1) / 2.0
        self.gx = (self.px_x - self.pcx) / max(self.pcx, 1e-6)
        self.gy = (self.px_y - self.pcy) / max(self.pcy, 1e-6)
        face = np.full_like(self.gx, np.inf)
        for nx, ny, dd in zip(_HEX_FACE_NX, _HEX_FACE_NY, _HEX_FACE_D):
            face = np.minimum(face, dd - (nx * self.gx + ny * self.gy))
        self.inside = np.clip(face / 0.12 + 0.5, 0.0, 1.0).astype(np.float32)

    # ── transitions (particle handoff) — eye.py's, src "sauron" ─────────

    def _handoff_snapshot(self):
        if getattr(self, "r_width", None) is None:
            return None
        eye_px = self.cx + float(self.gaze[0]) * self.sx
        eye_py = self.cy + float(self.gaze[1]) * self.sy
        iris_px = self.iris_size * self.s_min
        a = (np.arange(N_RIM, dtype=np.float32) / N_RIM) * 2 * np.pi
        return {
            "src": "sauron",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": (eye_px + np.cos(a) * iris_px).astype(np.float32),
            "py": (eye_py + np.sin(a) * iris_px).astype(np.float32),
            # the rim is the hottest part of the fire: its colour sits at
            # the top of the heat-mapped curve
            "grad": np.full(N_RIM, 0.92, dtype=np.float32),
            "bright": np.ones(N_RIM, dtype=np.float32),
            "gradient": self._config.get("gradient"),
            "spin_sign": 1.0,
            "blob_size": 2.0,
            "flow": "out",
            "center_px": (float(eye_px), float(eye_py)),
            "captured": np.zeros(N_RIM, dtype=bool),
            "trail": None,
            "native": {
                "gaze": self.gaze.copy(),
                "target_idx": self._target_idx,
                "hold_left": self._hold_left,
                "lid": self._lid,
                "phase": self._phase,
                "phase_t": self._phase_t,
                "phase_progress": self.phase_progress,
                "charge_amt": self._charge_amt,
                "surge": self._surge_env,
                "lids_rotated": self._lids_rotated,
            },
        }

    def deactivate(self):
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        super().deactivate()

    def _adopt_handoff(self, snap=None, allow_hold=True):
        """First-draw adoption (eye.py's): read the live crossfade sibling
        if present, else the registry."""
        virtual = self._virtual
        live = snap is not None
        if snap is None:
            sibling = (
                getattr(virtual, "_transition_effect", None)
                if virtual else None
            )
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
        if not snap or tuple(snap["dims"]) != (self.r_width, self.r_height):
            return
        if snap["src"] == "sauron":
            native = snap.get("native") or {}
            g = native.get("gaze")
            if g is not None and len(g) == 2:
                self.gaze = np.asarray(g, dtype=np.float32).copy()
            self._target_idx = int(native.get("target_idx", self._target_idx))
            self._hold_left = float(native.get("hold_left", 0.0))
            self._lid = float(native.get("lid", 0.0))
            self._charge_amt = float(native.get("charge_amt", 0.0))
            self._surge_env = float(native.get("surge", 0.0))
            ph = native.get("phase", "none")
            if ph in ("charge", "lull"):
                self._phase = ph
                self._phase_t = float(native.get("phase_t", 0.0))
                self.phase_progress = float(
                    native.get("phase_progress", self.phase_progress)
                )
                if ph == "lull":
                    self._lids_rotated = bool(
                        native.get("lids_rotated", self._lids_rotated)
                    )
                if self._phase_pending == ph:
                    self._phase_pending = None
            return
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            # sanctioned in-render config path (we're under the effect lock)
            self._apply_config({"gradient": g}, validate=False,
                               fire_event=False)
        if snap["src"] == "dancer" and live:
            self._lid = 1.0
            self._blink_in = {"t0": particle_handoff.now(), "open": False}
            return
        if snap["src"] == "pacman" and live and allow_hold:
            frac = particle_handoff.transition_progress(virtual)
            if frac is not None and frac < particle_handoff.PACMAN_MORPH_START:
                self._pacman_hold = {
                    "snap": snap, "t0": particle_handoff.now(),
                }
                return
        if snap["src"] == "radial":
            if live and particle_handoff.transition_progress(virtual) is not None:
                self._erupt_hold = {"t0": particle_handoff.now()}
            else:
                self._burst = 1.0
                self._form = 0.0
            return
        px = snap.get("px")
        py = snap.get("py")
        if px is None or len(px) == 0:
            return
        k = int(min(len(px), INFALL_CAP))
        idx = np.linspace(0, len(px) - 1, k).astype(np.int64)
        sx_ = ((np.asarray(px)[idx] - self.cx) / self.s_min).astype(np.float32)
        sy_ = ((np.asarray(py)[idx] - self.cy) / self.s_min).astype(np.float32)
        ex = float(self.gaze[0]) * self.sx / self.s_min
        ey = float(self.gaze[1]) * self.sy / self.s_min
        grad = snap.get("grad")
        if grad is not None and len(grad) == len(px):
            grad = np.asarray(grad)[idx].astype(np.float32)
        else:
            grad = self._rng.random(k).astype(np.float32)
        bright = snap.get("bright")
        if bright is not None and len(bright) == len(px):
            bright = np.clip(np.asarray(bright)[idx], 0.3, 1.0).astype(
                np.float32
            )
        else:
            bright = np.ones(k, dtype=np.float32)
        self._infall = {
            "t": 0.0,
            "sx": sx_,
            "sy": sy_,
            "ang": np.arctan2(sy_ - ey, sx_ - ex).astype(np.float32),
            "grad": grad,
            "bright": bright,
            "dur": (self._rng.uniform(0.75, 1.15, k) * INFALL_S).astype(
                np.float32
            ),
        }

    # ── charge/lull/drop — Eye's state machine, inherited ───────────────

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "lull":
            self._lids_rotated = self.lull_lids_upside_down
        if phase == "drop":
            self._drop = {"t": 0.0, "fired": False}
            self._drop_slam = 0.03 < self._lid < 0.97
        else:
            self._drop = None
            self._drop_slam = False

    def shock_rim(self):
        """The Shockwave's eye (fx/effects/phase_grammar.py): the iris rim as
        drawn this frame — a circle in the eye's own isotropic pixels."""
        last = getattr(self, "_last_iris", None)
        if last is None:
            return (self.cx, self.cy, self.iris_size * self.s_min,
                    self.iris_size * self.s_min)
        ex, ey, iris_r = last
        r = max(iris_r, 0.05) * self.s_min
        return (ex, ey, r, r)

    def _phase_step(self, dt):
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        if self._phase == "none":
            return
        self._phase_t += dt
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "sauron: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            self._drop = {"t": 0.0, "fired": True, "silent": True}
            self._drop_slam = False
            return
        if self._phase == "charge":
            self._charge_amt = float(np.clip(self.phase_progress, 0.0, 1.0))
        elif self._phase == "drop":
            drop = self._drop
            if drop is None:
                drop = self._drop = {"t": 0.0, "fired": False}
            if not drop["fired"] and not self._drop_slam:
                drop["fired"] = True
                self._burst = 1.0
                self._shock_begin()
            drop["t"] += dt
            if drop["t"] >= DROP_TOTAL_S:
                self._phase = "none"
                self._drop = None
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _lid_travel(self, p, y_from, y_to, y_overlap):
        """eye.py's lid travel: fast ease-out to just overlapping the iris
        edge, a near-still pause, then the close."""
        span = y_to - y_from
        if abs(span) < 1e-6:
            return 1.0
        f1 = float(np.clip((y_overlap - y_from) / span, 0.0, 0.9))
        if p <= LID_PAUSE_START:
            q = p / LID_PAUSE_START
            return f1 * (1.0 - (1.0 - q) ** 2.2)
        if p <= LID_PAUSE_END:
            q = (p - LID_PAUSE_START) / (LID_PAUSE_END - LID_PAUSE_START)
            return f1 + 0.02 * q
        q = min((p - LID_PAUSE_END) / (0.93 - LID_PAUSE_END), 1.0)
        return (f1 + 0.02) + (1.0 - f1 - 0.02) * q * q

    def _update_gaze(self, dt, beat):
        """eye.py's gaze model, with the saturating-`>=` snap fixed."""
        imp = self.impulse
        energy = min(self.speed_audio * imp, 1.5)
        self._beat_kick *= float(np.exp(-dt / 0.35))
        self._rush *= float(np.exp(-dt / 0.15))
        self._reach_jig += (1.0 - self._reach_jig) * min(dt * 0.8, 1.0)
        self._reach_jig += float(self._rng.normal(0.0, 0.55)) * float(
            np.sqrt(dt)
        )
        self._reach_jig = float(np.clip(self._reach_jig, 0.45, 1.5))
        in_lull = self._phase == "lull"

        arc = 0.0
        if beat:
            if (
                not in_lull
                and self._pull is None
                # a clipped impulse reaches exactly 1.0, so "1.0 = never"
                # must exclude the top of the range (dancer.py's fix)
                and self.snap_threshold < 1.0
                and imp >= self.snap_threshold
                and self._lid < 0.5
            ):
                choices = [
                    i for i in range(1, GAZE_N + 1) if i != self._target_idx
                ]
                self._target_idx = int(self._rng.choice(choices))
                self._hold_left = self.snap_hold * (0.4 + 1.2 * min(imp, 1.0))
                self._rush = 1.0
                self._arc_sign = 1.0 if self._rng.random() < 0.5 else -1.0
                self._target_t = 0.0
            else:
                self._beat_kick = 1.0

        if in_lull or self._pull is not None:
            target = self.positions[0] if in_lull else self._pull
            v = self.drift_speed * 3.0
        elif self._hold_left > 0.0:
            target = self.positions[self._target_idx]
            dist = float(np.hypot(*(target - self.gaze)))
            if dist <= 0.03:
                self._hold_left -= dt
                return
            v = max(
                self.drift_speed * (1.0 + 8.0 * self._rush),
                dist / SNAP_LAND_S,
            )
        else:
            target = self.positions[self._target_idx]
            self._target_t += dt
            reach = (
                max(0.02, 0.30 * (1.0 - min(energy, 1.0))) * self._reach_jig
            )
            dist = float(np.hypot(*(target - self.gaze)))
            if dist <= reach or self._target_t > TARGET_TIMEOUT_S:
                choices = [
                    i for i in range(1, GAZE_N + 1) if i != self._target_idx
                ]
                self._target_idx = int(self._rng.choice(choices))
                self._target_t = 0.0
                self._arc_sign = 1.0 if self._rng.random() < 0.5 else -1.0
                target = self.positions[self._target_idx]
            v = (
                self.drift_speed
                * (0.25 + 0.75 * energy)
                * (1.0 + 0.9 * self._beat_kick)
            )
            arc = (1.0 - min(energy, 1.0)) * 0.9

        delta = target - self.gaze
        dist = float(np.hypot(*delta))
        step = v * dt
        if dist > 1e-6:
            dhat = delta / dist
            perp = 0.0
            if arc > 0.0:
                self._wander_t += dt * (0.8 + 1.5 * energy)
                perp = self._arc_sign * arc * (
                    0.55 + 0.45 * float(np.sin(self._wander_t * 0.6))
                ) + 0.4 * float(
                    np.sin(self._wander_t * 2.1 + self._wander_seed)
                ) * (1.0 - 0.6 * min(energy, 1.0))
            if step >= dist and abs(perp) < 0.2:
                self.gaze = target.copy()
            else:
                phat = np.array([-dhat[1], dhat[0]], dtype=np.float32)
                move = dhat + perp * phat
                move /= float(np.hypot(*move))
                self.gaze = (
                    self.gaze + move.astype(np.float32)
                    * min(step, dist * 1.5)
                )
        self.gaze = self.gaze + self._rng.normal(
            0.0, 0.004 + 0.008 * min(imp, 1.0), 2
        ).astype(np.float32) * np.sqrt(dt)

    # ── the fire ────────────────────────────────────────────────────────

    def _noise(self, u, v, w):
        coords = np.stack(
            [u.ravel(), v.ravel(), np.full(u.size, w, dtype=np.float32)],
            axis=0,
        ).astype(np.float32)
        return self.noise.gen_from_coords(coords).reshape(u.shape)

    def _edge_gap(self, eye_px, eye_py, iris_r):
        """Per pixel: the gap (eye units) from the iris rim to the crystal's
        hex edge along that pixel's own ray from the eye — the flames' reach
        is a FRACTION of this, never a scalar radius."""
        egx = (eye_px - self.pcx) / max(self.pcx, 1e-6)
        egy = (eye_py - self.pcy) / max(self.pcy, 1e-6)
        ux = self.gx - egx
        uy = self.gy - egy
        nrm = np.maximum(np.sqrt(ux * ux + uy * uy), 1e-6)
        ux = ux / nrm
        uy = uy / nrm
        t = np.full_like(ux, np.inf)
        for nx, ny, dd in zip(_HEX_FACE_NX, _HEX_FACE_NY, _HEX_FACE_D):
            den = nx * ux + ny * uy
            num = dd - (nx * egx + ny * egy)
            cand = np.where(den > 1e-6, num / np.where(den > 1e-6, den, 1.0),
                            np.inf)
            t = np.minimum(t, cand)
        t = np.where(np.isfinite(t), t, 0.0)
        ex = self.pcx + (egx + t * ux) * self.pcx
        ey = self.pcy + (egy + t * uy) * self.pcy
        edist = np.sqrt((ex - eye_px) ** 2 + (ey - eye_py) ** 2) / self.s_min
        return np.maximum(edist - iris_r, 0.02)

    def flame_reach(self, imp, surge, charge=0.0):
        """The flames' reach as a fraction of each pixel's gap to the edge,
        before the per-lick envelope (bass and the surge lengthen it)."""
        return (self.flames * (1.0 + self.flame_audio * imp
                               + SURGE_REACH * surge)
                * (1.0 + CHARGE_FLAME_GROW * charge))

    def _flames(self, d, ang, gap, imp, surge, charge):
        tn = self.tongues
        u = ang * (tn / (2 * np.pi))
        v = d * 2.6 - self._flow_t * 1.6
        n = 0.62 * self._noise(u, v, self._t * 0.25) + 0.38 * self._noise(
            u * 2.0 + 3.7, v * 2.0, self._t * 0.5 + 11.0)
        env = self._noise(u * 0.5, np.zeros_like(u), self._t * 0.35 + 40.0)
        reach = self.flame_reach(imp, surge, charge)
        length = np.clip(reach * (0.55 + 0.65 * env), 0.08, OVERREACH) * gap
        rel = np.clip(d / np.maximum(length, 1e-4), 0.0, 1.5)
        fall = np.clip(1.0 - rel, 0.0, 1.0) ** 0.9
        flame = fall * (0.55 + 0.45 * n)
        flame = np.clip((flame - 0.05) / 0.55, 0.0, 1.0)
        return flame * flame * (3.0 - 2.0 * flame)

    def slit_size(self, iris_r, pulse, imp, charge=0.0, size_gain=1.0):
        """(half-width, half-height) of the slit, eye units: the beat dilates
        the width by pupil_beat and the height by SLIT_HEIGHT_BEAT of that;
        bass widens it a little; a charge narrows it."""
        w = (self.pupil_width * iris_r
             * (1.0 + self.pupil_beat * pulse + SLIT_BASS_WIDEN * imp)
             * (1.0 - CHARGE_PUPIL_SHRINK * charge) * size_gain)
        h = (self.pupil_size * iris_r
             * (1.0 + SLIT_HEIGHT_BEAT * self.pupil_beat * pulse))
        return min(w, h * SLIT_MAX_ASPECT), h

    def slit_min_half(self, cos_eff=1.0, ux=1.0, uy=0.0) -> float:
        """The slit floor's half-width in the slit's own (unforeshortened)
        frame, eye units: SLIT_MIN_DARK_PX of fully dark core (black >= 0.9
        sits 0.4 x the anti-alias inside the edge), scaled back up by how
        much the eyeball turn squeezes the slit's width direction."""
        if SLIT_MIN_DARK_PX <= 0.0:
            return 0.0
        half_px = SLIT_MIN_DARK_PX / 2.0 + 0.4 * SLIT_AA_PX
        squeeze = ux * ux / max(cos_eff, 1e-3) + uy * uy
        return half_px / self.s_min * squeeze

    def radial_coord(self, sd, dist, d, gap, iris_r, heat):
        """The RADIAL colour coordinate (1 at the slit .. 0 out at the
        flames' far reach), measured in the eye's own shape rather than a
        circle — the Admiral, 2026-10-11: "Don't make it perfectly radial,
        considering the eye slit is not radially symmetric."

        Inside the iris it is the fraction of the way from the slit's edge
        to the iris's edge along each point (sd over sd + the gap to the
        rim), so the bands are lens-shaped against the slit and round out
        to circles at the rim. Outside, it is the fraction of the way to
        the crystal's edge along that point's own ray (the flames' own
        measure), so the outer bands follow the hexagon. A little of the
        flames' heat (RADIAL_HEAT_MIX) tints it, so a lick carries the
        warmer colour outward without breaking the bands up."""
        sdp = np.maximum(sd, 0.0)
        to_rim = np.maximum(iris_r - dist, 0.0)
        u = sdp / np.maximum(sdp + to_rim, 1e-4)
        inner = 1.0 - RADIAL_IRIS_SHARE * u
        v = np.clip(d / np.maximum(gap * RADIAL_OUTER_SPAN, 1e-4), 0.0, 1.0)
        outer = (1.0 - RADIAL_IRIS_SHARE) * (1.0 - v)
        rc = np.where(d < 0.0, inner, outer)
        return np.clip((1.0 - RADIAL_HEAT_MIX) * rc
                       + RADIAL_HEAT_MIX * heat, 0.0, 1.0)

    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        self._t += dt
        imp = float(np.clip(self.impulse, 0.0, 1.0))

        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        # the surge poke lands
        if self._surge_pending > 0.0 or self._surge_seen:
            if self._surge_pending > 0.0:
                self._surge_env = max(self._surge_env, self._surge_pending)
            self._surge_pending = 0.0
            # sanctioned in-render config path (under the effect lock)
            self._apply_config({"surge": 0.0}, validate=False,
                               fire_event=False)

        virtual = self._virtual
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
                self._burst = 1.0
                self._form = 0.0
        if self._pacman_hold is not None:
            hold = self._pacman_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._pacman_hold = None
            elif (
                frac is None
                or frac >= particle_handoff.PACMAN_MORPH_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._pacman_hold = None
                sib = getattr(virtual, "_transition_effect", None)
                snap = None
                if sib is not None and sib is not self and hasattr(
                    sib, "_handoff_snapshot"
                ):
                    try:
                        snap = sib._handoff_snapshot()
                    except Exception:
                        snap = None
                self._adopt_handoff(snap=snap or hold["snap"],
                                    allow_hold=False)

        inc = particle_handoff.incoming_sibling(virtual, self)
        inc_name = getattr(inc, "NAME", None) if inc is not None else None
        self._pull = None
        blink_out = None
        if inc_name == "Radial":
            rx = float(inc._config.get("x_offset", 0.5))
            ry = float(inc._config.get("y_offset", 0.5))
            self._pull = np.array([
                ((self.r_width - 1) * rx - self.cx) / max(self.sx, 1e-6),
                ((self.r_height - 1) * ry - self.cy) / max(self.sy, 1e-6),
            ], dtype=np.float32)
        elif inc_name == "Dancer":
            blink_out = particle_handoff.transition_progress(virtual)

        self._phase_step(dt)
        beat = self._beat_pending
        self._beat_pending = False
        self._update_gaze(dt, beat)

        if self._phase not in ("charge", "lull"):
            self._charge_amt = max(0.0, self._charge_amt - dt / CHARGE_RELAX_S)
        charge = self._charge_amt
        size_gain = 1.0
        if self._form is not None:
            self._form += dt / FORM_S
            if self._form >= 1.0:
                self._form = None
            else:
                f = self._form
                size_gain = 0.2 + 0.8 * f * (2.0 - f)
        body_gain = 1.0
        if self._infall is not None:
            body_gain = 0.25 + 0.75 * min(self._infall["t"] / INFALL_S, 1.0)
        body_show = not (
            blink_out is not None
            and blink_out >= particle_handoff.BLOOM_START
        )

        if beat:
            self._pulse = max(self._pulse, 0.55 + 0.45 * imp)
        self._pulse *= float(np.exp(-dt / BEAT_PULSE_TAU))
        self._surge_env *= float(np.exp(-dt / SURGE_TAU))
        if self._surge_env < 1e-3:
            self._surge_env = 0.0
        self._burst *= float(np.exp(-dt / DROP_BURST_S))
        if self._burst < 0.01:
            self._burst = 0.0
        # a drop / radial eruption burns like a full surge
        surge = max(self._surge_env, self._burst)
        pulse = self._pulse
        # the flames scroll outward (inward while a charge builds)
        fdir = -1.0 if charge > 0.05 else 1.0
        self._flow_t += fdir * dt * self.flame_speed * (
            1.0 + 0.8 * imp + SURGE_SCROLL * surge)

        # ── geometry (eye.py's eyeball turn) ────────────────────────────
        eye_px = self.cx + float(self.gaze[0]) * self.sx
        eye_py = self.cy + float(self.gaze[1]) * self.sy
        self.last_eye_px = (eye_px, eye_py)
        dxp = (self.px_x - eye_px) / self.s_min
        dyp = (self.px_y - eye_py) / self.s_min
        g_mag = float(np.hypot(*self.gaze))
        depth = self.gaze_depth
        if depth > 0.001 and g_mag > 1e-4:
            ux = float(self.gaze[0]) / g_mag
            uy = float(self.gaze[1]) / g_mag
            theta = min(g_mag * GAZE_ANGLE_GAIN, GAZE_ANGLE_MAX)
            cos_eff = 1.0 - depth * (1.0 - float(np.cos(theta)))
            lead = depth * PUPIL_LEAD * float(np.sin(theta))
        else:
            ux, uy, cos_eff, lead = 1.0, 0.0, 1.0, 0.0
        if cos_eff < 0.999:
            p_alo = (dxp * ux + dyp * uy) / cos_eff
            p_per = -dxp * uy + dyp * ux
            tx = p_alo * ux - p_per * uy
            ty = p_alo * uy + p_per * ux
        else:
            tx, ty = dxp, dyp
        dist = np.sqrt(tx * tx + ty * ty)
        ang = np.arctan2(ty, tx)
        iris_r = self.iris_size * (1.0 + CHARGE_IRIS_GROW * charge) * size_gain
        self._last_iris = (eye_px, eye_py, iris_r)  # the shock's rim
        d = dist - iris_r

        # ── flames + sky ────────────────────────────────────────────────
        gap = self._edge_gap(eye_px, eye_py, iris_r)
        flame = self._flames(d, ang, gap, imp, surge, charge)
        self.last_flame = np.where(d >= 0.0, flame, 0.0).astype(np.float32)
        # the PERIMETER RING (tune-up 1: thick enough to hold its shape on
        # the hex lattice as the eye moves): a band RING_WIDTH wide centred
        # on the iris edge. Outside the iris it does not stop — it fades
        # into the flames over RING_FADE, its fall roughened by the flame
        # field, and the two are combined by a SCREEN (1 - (1-a)(1-b)), so
        # the flames grow out of the ring with no step and no crease
        ring = np.exp(-((dist - iris_r) / RING_WIDTH) ** 2)
        self.last_ring = ring.astype(np.float32)
        dpos = np.maximum(d, 0.0)
        fade = np.exp(-(dpos / RING_FADE) ** 2) * (
            1.0 - RING_FADE_ROUGH * (1.0 - flame))
        root = RING_OUT_HEAT * np.maximum(ring, fade)
        heat = np.where(d >= 0.0, (1.0 - (1.0 - flame) * (1.0 - root))
                        * (0.9 + SURGE_HEAT * surge), 0.0)
        if self.sky > 0.0:
            sk = self._noise(self.gx * 1.6, self.gy * 1.6 - self._t * 0.12,
                             self._t * 0.07 + 300.0)
            heat = np.maximum(heat, self.sky * (0.45 + 0.55 * sk)
                              * self.inside * (1.0 + SURGE_SKY * surge))

        # ── the iris: heat rising toward the slit, radial streaks ───────
        inside = dist < iris_r
        t_rad = np.clip(dist / max(iris_r, 1e-4), 0.0, 1.0)
        streak = self._noise(ang * 7.0, t_rad * 1.2 - self._t * 0.05, 77.0)
        streak2 = self._noise(ang * 15.0, t_rad * 0.6, 91.0)
        iris_heat = (0.52 + 0.24 * (1.0 - t_rad)
                     + self.streaks * (0.22 * streak + 0.12 * streak2))
        iris_heat = np.clip(iris_heat + RING_GAIN * ring, 0.0, 1.0)
        heat = np.where(inside, iris_heat, heat)

        # ── the slit: a lens of two arcs, leading into the gaze ─────────
        w, h = self.slit_size(iris_r, pulse, imp, charge, size_gain)
        lpx = lead * iris_r * ux
        lpy = lead * iris_r * uy
        qa = ((dxp - lpx) * ux + (dyp - lpy) * uy) / cos_eff
        qp = -(dxp - lpx) * uy + (dyp - lpy) * ux
        qx = qa * ux - qp * uy
        qy = qa * uy + qp * ux
        R = (w * w + h * h) / (2.0 * w)
        c = R - w
        sd = np.maximum(np.sqrt((qx - c) ** 2 + qy ** 2) - R,
                        np.sqrt((qx + c) ** 2 + qy ** 2) - R)
        # THE MINIMUM WIDTH (tune-up 1): wherever the lens is narrower, a
        # rounded column of half-width `wm` keeps the slit's fully dark
        # core at least SLIT_MIN_DARK_PX rendered pixels wide — a lattice
        # row holds a real cell every second column, so a dark band of one
        # period (2 px) can miss a row as the eye moves; one pixel more
        # cannot. Measured in rendered pixels, so the foreshortening that
        # squeezes the slit sideways as the eye turns is undone here
        wm = self.slit_min_half(cos_eff, ux, uy)
        hc = 0.0
        if wm > 0.0:
            hc = max(h - SLIT_MIN_TIP * wm, 0.0)
            sd = np.minimum(sd, np.sqrt(
                qx * qx + np.maximum(np.abs(qy) - hc, 0.0) ** 2) - wm)
        # instrument: the floor column's centre and half-length, rendered px
        # (the slit's height direction squeezed by the eyeball turn)
        self.last_slit_core = (
            eye_px + lpx * self.s_min, eye_py + lpy * self.s_min,
            hc * self.s_min / (uy * uy / max(cos_eff, 1e-3) + ux * ux))
        aa = SLIT_AA_PX / self.s_min
        core = np.exp(-np.maximum(sd, 0.0) / (0.085 + 0.05 * pulse)) * (
            0.9 + 0.35 * pulse)
        heat = np.maximum(heat, np.clip(core, 0.0, 1.0))
        black = np.clip((-sd) / aa + 0.5, 0.0, 1.0)
        heat = heat * (1.0 - black)
        self.last_heat = heat.astype(np.float32)
        self.last_d = d.astype(np.float32)
        self.last_slit = black.astype(np.float32)

        # ── colour: the (sorted) set along the heat ─────────────────────
        hclip = np.clip(heat, 0.0, 1.0)
        how = self.mapping()
        if how == "angle":
            a_norm = (ang * (1.0 / (2 * np.pi))) % 1.0
            rgb = self.get_gradient_color_vectorized1d(
                a_norm.ravel()).astype(np.float32)
            rgb = rgb.reshape(self.r_height, self.r_width, 3) * (
                hclip ** 0.85)[..., None]
        else:
            coord = hclip
            if how == "radial":
                coord = self.radial_coord(sd, dist, d, gap, iris_r, hclip)
                self.last_radial = coord.astype(np.float32)
            rgb = self.get_gradient_color_vectorized1d(
                coord.ravel()).astype(np.float32)
            rgb = rgb.reshape(self.r_height, self.r_width, 3) * (
                np.clip(hclip * 1.15, 0.0, 1.0) ** 0.7)[..., None]
        white = (np.clip(core, 0.0, 1.0) ** 1.8 * self.core_white
                 * (1.0 - black))[..., None]
        rgb = rgb + (255.0 - rgb) * white
        if body_show:
            rgb *= body_gain
        else:
            rgb[:] = 0.0

        # ── infall: predecessor particles falling onto the iris rim ─────
        if self._infall is not None and body_show:
            self._draw_infall(rgb, dt, iris_r)

        # ── eyelids (eye.py's) ──────────────────────────────────────────
        self._step_lid(dt, blink_out, virtual)
        if self._lid <= 0.001 and self._phase != "lull":
            self._lids_rotated = False
        if self._lid > 0.001:
            self._draw_lids(rgb, dxp, dyp, eye_py, iris_r)

        self.matrix = Image.fromarray(
            np.clip(rgb, 0, 255).astype(np.uint8), "RGB"
        )

    def _draw_infall(self, out, dt, iris_r):
        inf = self._infall
        inf["t"] += dt
        e = np.clip(inf["t"] / inf["dur"], 0.0, 1.0)
        if float(e.min()) >= 1.0:
            self._infall = None
            return
        es = e * e * (3.0 - 2.0 * e)
        ex = float(self.gaze[0]) * self.sx / self.s_min
        ey = float(self.gaze[1]) * self.sy / self.s_min
        fx = inf["sx"] + (ex + np.cos(inf["ang"]) * iris_r - inf["sx"]) * es
        fy = inf["sy"] + (ey + np.sin(inf["ang"]) * iris_r - inf["sy"]) * es
        fade = inf["bright"] * np.clip((1.0 - e) / 0.15, 0.0, 1.0)
        alive = fade > 0.01
        if not alive.any():
            return
        xi = np.round(self.cx + fx[alive] * self.s_min).astype(np.int32)
        yi = np.round(self.cy + fy[alive] * self.s_min).astype(np.int32)
        col = self.get_gradient_color_vectorized1d(
            inf["grad"][alive]).astype(np.float32) * fade[alive][:, None]
        n_dot, n_k = xi.size, self.dk_dx.size
        pxs = (xi[:, None] + self.dk_dx[None, :]).ravel()
        pys = (yi[:, None] + self.dk_dy[None, :]).ravel()
        valid = ((pxs >= 0) & (pxs < self.r_width)
                 & (pys >= 0) & (pys < self.r_height))
        idxf = (pys * self.r_width + pxs)[valid]
        kw = np.broadcast_to(self.dk_w[None, :], (n_dot, n_k)).ravel()[valid]
        cells = self.r_width * self.r_height
        for ch in range(3):
            vals = np.broadcast_to(
                col[:, ch][:, None], (n_dot, n_k)).ravel()[valid] * kw
            out[..., ch] += np.bincount(
                idxf, weights=vals, minlength=cells
            ).reshape(self.r_height, self.r_width)

    def _step_lid(self, dt, blink_out, virtual):
        if self._phase == "lull":
            p = max(self.phase_progress,
                    min(self._phase_t / LULL_FALLBACK_S, 1.0))
            self._lid = float(np.clip(p, 0.0, 1.0))
        elif self._phase == "drop":
            if self._drop_slam:
                self._lid = min(1.0, self._lid + dt / 0.06)
                if self._lid >= 1.0:
                    self._drop_slam = False
            else:
                self._lid = max(0.0, self._lid - dt / DROP_OPEN_S)
        elif blink_out is not None:
            if blink_out < particle_handoff.BLOOM_START:
                self._lid = min(blink_out / particle_handoff.BLOOM_START, 1.0)
            else:
                self._lid = max(
                    0.0,
                    1.0 - (blink_out - particle_handoff.BLOOM_START) / 0.25,
                )
        elif self._blink_in is not None:
            hold = self._blink_in
            if not hold["open"]:
                self._lid = 1.0
                frac = particle_handoff.transition_progress(virtual)
                if (
                    frac is None
                    or frac >= particle_handoff.BLOOM_START
                    or particle_handoff.now() - hold["t0"]
                    > particle_handoff.ERUPT_HOLD_MAX_S
                ):
                    hold["open"] = True
            else:
                self._lid = max(0.0, self._lid - dt / BLINK_OPEN_S)
                if self._lid <= 0.0:
                    self._blink_in = None
        else:
            self._lid = max(0.0, self._lid - dt / 0.25)

    def _draw_lids(self, out, dxp, dyp, eye_py, iris_r):
        top_ny = (0.0 - eye_py) / self.s_min
        bot_ny = (float(self.r_height - 1) - eye_py) / self.s_min
        if self._lids_rotated:
            # the lull upside down: the same lids turned 180 degrees about
            # the eye centre (the panel's bottom edge is the turned frame's
            # top)
            dxp, dyp = -dxp, -dyp
            top_ny, bot_ny = -bot_ny, -top_ny
        sag = 0.30 * iris_r
        y_meet = 0.15 * iris_r
        y_open = top_ny - sag - 0.05
        y_lo_start = bot_ny + sag + 0.05
        lw = 2.0 / self.s_min
        f_up = self._lid_travel(self._lid, y_open, y_meet, -0.8 * iris_r)
        f_lo = self._lid_travel(self._lid, y_lo_start, y_meet + lw,
                                0.8 * iris_r)
        y_up = y_open + (y_meet - y_open) * f_up
        y_lo = y_lo_start + (y_meet + lw - y_lo_start) * f_lo
        u = dxp / (self.sx / self.s_min)
        curve = sag * (1.0 - np.clip(u * u, 0.0, 1.0))
        up_edge = y_up + curve
        lo_edge = y_lo + curve
        # the lid lines burn in the fire's hottest colour (the top of the
        # heat-mapped curve)
        lid_rgb = self.get_gradient_color_vectorized1d(
            np.ones(1, dtype=np.float32)).astype(np.float32)[0]
        covered = (dyp <= up_edge) | (dyp >= lo_edge)
        # literal black: get_pixels() supplies the background exactly once
        out[covered] = 0.0
        lw_half = max(1.8 / self.s_min, 0.06 * iris_r)
        for edge in (up_edge, lo_edge):
            line = np.clip(1.0 - np.abs(dyp - edge) / lw_half, 0.0, 1.0)
            lmask = line > 0.0
            if lmask.any():
                out[lmask] += line[lmask][:, None] * lid_rgb
