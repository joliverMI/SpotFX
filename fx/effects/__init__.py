import logging
import math
import threading
import timeit

# from ledfx.effects.audio import FREQUENCY_RANGES
from functools import lru_cache

import numpy as np
import voluptuous as vol
from numpy.typing import NDArray

from fx.color import LEDFX_COLORS, hsv_to_rgb, parse_color, validate_color
from fx.effects.utils.logsec_helper import LogSecHelper
from fx.events import EffectUpdatedEvent
from fx.utils import BaseRegistry, RegistryLoader

_LOGGER = logging.getLogger(__name__)


class DummyEffect:
    config = vol.Schema({})
    _active = True
    is_active = _active
    NAME = name = ""
    logsec = None

    def __init__(self, pixel_count):
        self.pixels = np.zeros((pixel_count, 3))
        self.pixel_count = pixel_count

    def _render(self):
        # we don't need a self.lock as we don't do anything in deactivate
        # self.pixels will be valid while this instance is in scope
        self.render()

    def render(self):
        # we need to clear this each render frame as transitions reuse
        # active effect pixel space
        self.pixels = np.zeros((self.pixel_count, 3))

    def get_pixels(self):
        return self.pixels

    def activate(self):
        pass

    def _deactivate(self):
        self.deactivate()

    def deactivate(self):
        self.pixels = None  # Free the numpy array
        self._active = False
        self.is_active = False


def mix_colors(color_1: tuple, color_2: tuple, ratio: float) -> tuple:
    """
    Mixes two colors based on a given ratio.

    Parameters:
    color_1 (tuple): The first color represented as a tuple of RGB values.
    color_2 (tuple): The second color represented as a tuple of RGB values.
    ratio (float): The ratio of color_1 to color_2 in the final mixed color.

    Returns:
    tuple: The mixed color represented as a tuple of RGB values.
    """
    if np.array_equal(color_2, []):
        return (
            color_1[0] * (1 - ratio) + 0,
            color_1[1] * (1 - ratio) + 0,
            color_1[2] * (1 - ratio) + 0,
        )
    else:
        return (
            color_1[0] * (1 - ratio) + color_2[0] * ratio,
            color_1[1] * (1 - ratio) + color_2[1] * ratio,
            color_1[2] * (1 - ratio) + color_2[2] * ratio,
        )


def rgb_curve_to_hsv(curve: NDArray) -> NDArray:
    """Vectorized RGB→HSV for a (3, n) curve of 0..255 floats. Returns a
    (3, n) array of h, s, v each in 0..1. Achromatic pixels get h=0."""
    rgb = np.clip(np.asarray(curve, dtype=float) / 255.0, 0.0, 1.0)
    r, g, b = rgb
    maxc = rgb.max(axis=0)
    minc = rgb.min(axis=0)
    v = maxc
    delta = maxc - minc
    safe_max = np.where(maxc > 0, maxc, 1.0)
    s = np.where(maxc > 0, delta / safe_max, 0.0)
    safe_delta = np.where(delta > 0, delta, 1.0)
    rc = (maxc - r) / safe_delta
    gc = (maxc - g) / safe_delta
    bc = (maxc - b) / safe_delta
    h = np.where(
        maxc == r, bc - gc, np.where(maxc == g, 2.0 + rc - bc, 4.0 + gc - rc)
    )
    h = np.where(delta > 0, (h / 6.0) % 1.0, 0.0)
    return np.stack([h, s, v])


def hsv_curve_to_rgb(hsv: NDArray) -> NDArray:
    """Vectorized HSV→RGB for a (3, n) curve of h, s, v in 0..1. Returns a
    (3, n) array of 0..255 floats."""
    h, s, v = np.asarray(hsv, dtype=float)
    sector = h * 6.0
    i = np.floor(sector).astype(int) % 6
    f = sector - np.floor(sector)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.clip(np.stack([r, g, b]) * 255.0, 0.0, 255.0)


def hue_tween_fields(
    start_curve: NDArray, target_curve: NDArray, achromatic: float = 0.05
) -> tuple:
    """Precompute HSV endpoints for a hue-path tween between two RGB curves
    (each (3, n), 0..255). Returns (hsv_start, hsv_delta) such that the value
    at progress t is hsv_start + t * hsv_delta (hue wrapped mod 1). Hue takes
    the shortest arc around the wheel; where one end is achromatic (grey /
    black / white, hue undefined) it adopts the other end's hue AND
    saturation, so the blend fades value (brightness) in place instead of
    sweeping through arbitrary red or dipping through grey on the way to/from
    the achromatic endpoint."""
    s_hsv = rgb_curve_to_hsv(start_curve)
    t_hsv = rgb_curve_to_hsv(target_curve)
    s_gray = (s_hsv[1] < achromatic) | (s_hsv[2] < achromatic)
    t_gray = (t_hsv[1] < achromatic) | (t_hsv[2] < achromatic)
    h_s = np.where(s_gray, t_hsv[0], s_hsv[0])
    h_t = np.where(t_gray, h_s, t_hsv[0])
    dh = ((h_t - h_s + 0.5) % 1.0) - 0.5
    sat_s = np.where(s_gray, t_hsv[1], s_hsv[1])
    sat_t = np.where(t_gray, sat_s, t_hsv[1])
    hsv_start = np.stack([h_s, sat_s, s_hsv[2]])
    hsv_delta = np.stack([dh, sat_t - sat_s, t_hsv[2] - s_hsv[2]])
    return hsv_start, hsv_delta


def fill_rainbow(
    pixels: NDArray, initial_hue: float, delta_hue: float
) -> NDArray:
    """
    Fills the given pixels with a rainbow effect.

    Args:
        pixels (numpy.ndarray): Array of pixels to be filled with colors.
        initial_hue (float): Initial hue value for the rainbow effect.
        delta_hue (float): Difference in hue between each pixel.

    Returns:
        numpy.ndarray: Array of RGB values representing the rainbow effect.
    """
    sat = 0.95
    val = 1.0

    # Create an array of hue values starting from 'initial_hue' and increasing
    # by 'delta_hue' for each pixel. The array length is initially set to be longer
    # than the number of pixels.
    hues = np.arange(
        initial_hue, initial_hue + len(pixels) * delta_hue, delta_hue
    )

    # ensure each pixel has a corresponding hue value.
    hues = hues[: len(pixels)]

    return hsv_to_rgb(hues, sat, val)


def blur_pixels(pixels: NDArray, sigma: float) -> NDArray:
    """
    Applies a blur effect to the given pixels.

    Args:
        pixels (ndarray): The input pixel array.
        sigma (float): The standard deviation of the Gaussian kernel.

    Returns:
        ndarray: The blurred pixel array.
    """
    rgb_array = pixels.T
    rgb_array[0] = smooth(rgb_array[0], sigma)
    rgb_array[1] = smooth(rgb_array[1], sigma)
    rgb_array[2] = smooth(rgb_array[2], sigma)
    return rgb_array.T


@lru_cache(maxsize=1024)
def _gaussian_kernel1d(sigma: float, order: int, array_len: int) -> NDArray:
    """
    Produces a 1D Gaussian or Gaussian-derivative filter kernel as a numpy array.

    Args:
        sigma (float): The standard deviation of the filter.
        order (int): The derivative-order to use. 0 indicates a Gaussian function, 1 a 1st order derivative, etc.
        radius (int): The kernel produced will be of length (2*radius+1)

    Returns:
        Array of length (2*radius+1) containing the filter kernel.
    """

    # Choose a radius for the filter kernel large enough to include all significant elements. Using
    # a radius of 4 standard deviations (rounded to int) will only truncate tail values that are of
    # the order of 1e-5 or smaller. For very small sigma values, just use a minimal radius.
    # trapping very small values of sigma to arbitarily 0.00001 to preven div zero crash
    sigma = max(0.00001, sigma)
    radius = max(1, int(round(4.0 * sigma)))
    radius = min(int((array_len - 1) / 2), radius)
    radius = max(radius, 1)

    if order < 0:
        raise ValueError("Order must non-negative")
    if not (isinstance(radius, int) or radius.is_integer()) or radius <= 0:
        raise ValueError("Radius must a positive integer")

    p = np.polynomial.Polynomial([0, 0, -0.5 / (sigma * sigma)])
    x = np.arange(-radius, radius + 1)
    phi_x = np.exp(p(x), dtype=np.double)
    phi_x /= phi_x.sum()

    if order > 0:
        # For Gaussian-derivative filters, the function must be derived one or more times.
        q = np.polynomial.Polynomial([1])
        p_deriv = p.deriv()
        for _ in range(order):
            # f(x) = q(x) * phi(x) = q(x) * exp(p(x))
            # f'(x) = (q'(x) + q(x) * p'(x)) * phi(x)
            q = q.deriv() + q * p_deriv
        phi_x *= q(x)

    return phi_x


def fast_blur_pixels(pixels: NDArray, sigma: float) -> NDArray:
    """
    Applies a fast blur effect to the given pixels using a Gaussian kernel.

    Args:
        pixels (ndarray): The input array of pixels.
        sigma (float): The standard deviation of the Gaussian kernel.

    Returns:
        ndarray: The blurred pixels array.

    Raises:
        ValueError: If the input array is empty.
    """
    if len(pixels) == 0:
        raise ValueError("Cannot smooth an empty array")
    kernel = _gaussian_kernel1d(sigma, 0, len(pixels))
    pixels[:, 0] = np.convolve(pixels[:, 0], kernel, mode="same")
    pixels[:, 1] = np.convolve(pixels[:, 1], kernel, mode="same")
    pixels[:, 2] = np.convolve(pixels[:, 2], kernel, mode="same")
    return pixels


def fast_blur_array(array: NDArray, sigma: float) -> NDArray:
    """
    Apply fast Gaussian blur to a 1-dimensional array.

    Args:
        array (numpy.ndarray): The input array to be blurred.
        sigma (float): The standard deviation of the Gaussian kernel.

    Returns:
        numpy.ndarray: The blurred array.

    Raises:
        ValueError: If the input array is empty.
    """
    if len(array) == 0:
        raise ValueError("Cannot smooth an empty array")
    kernel = _gaussian_kernel1d(sigma, 0, len(array))
    return np.convolve(array, kernel, mode="same")


def smooth(x, sigma):
    """
    Smooths a 1D array via a Gaussian filter.

    Args:
        x (array of floats): The array to be smoothed.
        sigma (float): The standard deviation of the smoothing filter to use.

    Returns:
        Array of same length as x.
    """

    if len(x) == 0:
        raise ValueError("Cannot smooth an empty array")

    # Choose a radius for the filter kernel large enough to include all significant elements. Using
    # a radius of 4 standard deviations (rounded to int) will only truncate tail values that are of
    # the order of 1e-5 or smaller. For very small sigma values, just use a minimal radius.
    kernel_radius = max(1, int(round(4.0 * sigma)))
    filter_kernel = _gaussian_kernel1d(sigma, 0, kernel_radius)

    # The filter kernel will be applied by convolution in 'valid' mode, which includes only the
    # parts of the convolution in which the two signals full overlap, i.e. where the shorter signal
    # is entirely contained within the longer signal, producing an output signal of length equal to
    # the difference in length between the two input signals, plus one. So the input signal must be
    # extended by mirroring the ends (to give realistic values for the first and last pixels after
    # smoothing) until len(x_mirrored) - len(w) + 1 = len(x). This requires adding (len(w)-1)/2
    # values to each end of the input. If len(x) < (len(w)-1)/2, then the mirroring will need to be
    # performed over multiple iterations, as the mirrors can only, at most, triple the length of x
    # each time they are applied.
    extended_input_len = len(x) + len(filter_kernel) - 1
    x_mirrored = x
    while len(x_mirrored) < extended_input_len:
        mirror_len = min(
            len(x_mirrored), (extended_input_len - len(x_mirrored)) // 2
        )
        x_mirrored = np.r_[
            x_mirrored[mirror_len - 1 :: -1],
            x_mirrored,
            x_mirrored[-1 : -(mirror_len + 1) : -1],
        ]

    # Convolve the extended input copy with the filter kernel to apply the filter.
    # Convolving in 'valid' mode clips includes only the parts of the convolution in which the two
    # signals full overlap, i.e. the shorter signal is entirely contained within the longer signal.
    # It produces an output of length equal to the difference in length between the two input
    # signals, plus one. So this relies on the assumption that len(s) - len(w) + 1 >= len(x).
    y = np.convolve(x_mirrored, filter_kernel, mode="valid")

    assert len(y) == len(x)

    return y


@BaseRegistry.no_registration
class Effect(BaseRegistry):
    """
    Manages an effect
    """

    NAME = ""
    # over ride in effect children to hide existing keys from UI
    HIDDEN_KEYS = None
    # extend in effect children
    ADVANCED_KEYS = ["diag", "background_mode"]
    # Shape maps: effects that draw pixel-exact on the device lattice
    # (squiggles, pacman) set True so shape-mapped virtuals identity-sample
    # instead of kernel-resampling their output (see Virtual.flush).
    LATTICE_EXACT = False
    # over ride in effect children to allow edit and show others
    PERMITTED_KEYS = None
    _config = None
    _active = False
    _virtual = None

    # Basic effect properties that can be applied to all effects
    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "blur",
                description="Amount to blur the effect",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=10)),
            vol.Optional(
                "flip", description="Flip the effect", default=False
            ): bool,
            vol.Optional(
                "mirror",
                description="Mirror the effect",
                default=False,
            ): bool,
            vol.Optional(
                "brightness",
                description="Brightness of strip",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "background_color",
                description="Apply a background color",
                default="#000000",
            ): validate_color,
            vol.Optional(
                "background_brightness",
                description="Brightness of the background color",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "diag", description="Enable diagnostic logging", default=False
            ): bool,
            vol.Optional(
                "background_mode",
                description="Blend effect over background color (additive) or replace it (overwrite)",
                default="additive",
            ): vol.In(["additive", "overwrite"]),
            vol.Optional(
                "advanced",
                description=False,
            ): bool,
            # Hidden per-effect override of the LATTICE_EXACT class flag
            # (None = use the class default). See Virtual._wants_lattice_exact.
            vol.Optional(
                "lattice_exact",
                description=False,
                default=None,
            ): vol.Any(None, bool),
        }
    )

    @property
    def lattice_exact(self) -> bool:
        """Whether this effect's output should be identity-sampled (not
        kernel-resampled) on shape-mapped virtuals. Config override wins,
        else the class flag."""
        override = (self._config or {}).get("lattice_exact")
        if override is not None:
            return bool(override)
        return bool(type(self).LATTICE_EXACT)

    def __init__(self, ledfx, config):
        self._ledfx = ledfx
        self._config = {}
        self.lock = threading.Lock()
        self.logsec = LogSecHelper(self)
        self.passed = 0.0
        self._last_frame_time = timeit.default_timer()
        self.now = self._last_frame_time
        self.background_mode = "additive"
        # Active server-side parameter tweens: {param_name: tween_state} or None.
        # Mutated only under self.lock (started from the event loop via
        # start_param_transitions, advanced each frame in _render).
        self._tweens = None
        # Live background color (unscaled RGB) chasing its config target so
        # bg changes FADE over the virtual's transition length instead of
        # snapping — especially black -> color. Brightness stays instant
        # (bass-drop dims rely on it). None until first _apply_config.
        self._bg_live_rgb = None
        self.update_config(config)

    def __del__(self):
        if self._active:
            self._deactivate()

    def activate(self, virtual):
        """Attaches an output channel to the effect"""
        with self.lock:
            self._virtual = virtual
            self.pixels = np.zeros((virtual.effective_pixel_count, 3))
            # Iterate all the base classes and check to see if the base
            # class has an on_activate method. If so, call it
            valid_classes = list(type(self).__bases__)
            valid_classes.append(type(self))
            for base in valid_classes:
                if hasattr(base, "on_activate"):
                    base.on_activate(self, virtual.effective_pixel_count)
            # Dark lock: effects created while the virtual is locked were
            # configured before _virtual existed, so the _apply_config clamp
            # couldn't see the lock — re-clamp on attach (we hold self.lock).
            if (virtual.config or {}).get("dark_lock", False) and (
                self._config.get("background_color") != "#000000"
                or self._config.get("background_brightness") != 0.0
            ):
                self._apply_config(
                    {"background_color": "#000000", "background_brightness": 0.0},
                    validate=False,
                    fire_event=False,
                )
            self._active = True
            _LOGGER.info("Effect %s activated.", self.NAME)

    def _deactivate(self):
        # we need this wrapper to ensure the full chain of
        # deactivation is protected
        with self.lock:
            self.deactivate()

    def deactivate(self):
        """Detaches an output channel from the effect"""
        self.pixels = None
        self._tweens = None  # cancel any in-flight param tweens
        self._virtual = (
            None  # Clear circular reference to allow garbage collection
        )
        # Clear LogSecHelper reference to this effect
        if self.logsec:
            self.logsec.effect = None
            self.logsec.diag = False
        self._active = False
        _LOGGER.info("Effect %s deactivated.", self.NAME)

    @classmethod
    def get_combined_default_schema(cls):
        # Initialize an empty schema
        combined_schema = {}

        # Function to recursively merge schemas from parent classes
        def merge_schema(c):
            for base in c.__bases__:
                merge_schema(base)
            if hasattr(c, "CONFIG_SCHEMA"):
                combined_schema.update(c.CONFIG_SCHEMA({}))

        merge_schema(cls)

        return combined_schema

    def update_config(self, config):
        with self.lock:
            self._apply_config(config, validate=True, fire_event=True)

    def _apply_config(self, config, *, validate=True, fire_event=True):
        """Lock-free core of update_config — CALLER MUST HOLD self.lock.

        Merges `config` into self._config and refreshes all derived state
        (base-attr caches + the per-base config_updated chain). With
        validate=False, fire_event=False this is the cheap per-frame path the
        param-tween engine (_advance_tweens) uses. It must NEVER call
        update_config: self.lock is a non-reentrant threading.Lock(), so
        re-acquiring it from inside the render-thread's locked _render() would
        deadlock.
        """
        validated_config = None
        if validate:
            try:
                validated_config = type(self).schema()(config)
            except vol.Invalid as err:
                _LOGGER.warning(
                    "Error updating effect %s config: %s", self.NAME, err
                )
                return
            # Merge the COERCED values, not the raw input: the schema turns
            # "2.0" into int 2 for integer params, and effects index numpy
            # arrays with these — a raw float in _config crashes render.
            config = {
                k: validated_config[k]
                for k in config
                if k in validated_config
            }

        # SpotFX dark lock: while the owning virtual is locked, no write path
        # (API PUT, tween frame, scene, preset, global apply) may light a
        # background. Clamp the incoming keys before the merge so the
        # bg derivation below always lands on bg_color_use = False. Freshly
        # created effects have no _virtual yet — activate() re-clamps on
        # attach, closing that gap.
        virtual = getattr(self, "_virtual", None)
        if (
            virtual is not None
            and (virtual.config or {}).get("dark_lock", False)
            and ("background_color" in config or "background_brightness" in config)
        ):
            config = {
                **config,
                "background_color": "#000000",
                "background_brightness": 0.0,
            }

        if self._config != {}:
            self._config = {**self._config, **config}
        else:
            self._config = (
                validated_config if validated_config is not None else config
            )

        bg_color = parse_color(self._config["background_color"])
        self._bg_target_rgb = np.array(bg_color, dtype=float)
        self._bg_brightness = float(self._config["background_brightness"])
        if self._bg_live_rgb is None or not self._active:
            # first config / pre-activation (fresh instances on an effect
            # switch fade via the crossfade already): start ON target
            self._bg_live_rgb = self._bg_target_rgb.copy()
        self._refresh_bg_render_state()

        self.flip = self._config["flip"]
        self.mirror = self._config["mirror"]
        self.brightness = self._config["brightness"]
        self.background_mode = self._config["background_mode"]
        self.logsec.diag = self._config.get("diag", False)

        # Iterate all the base classes and check to see if there is a custom
        # implementation of config updates. If so, notify the base class.
        valid_classes = list(type(self).__bases__)
        valid_classes.append(type(self))
        for base in valid_classes:
            if base.config_updated != super(base, base).config_updated:
                base.config_updated(self, self._config)

        if validate:
            _LOGGER.debug(
                "Effect %s config updated to %s.", self.NAME, validated_config
            )

        if fire_event and self._virtual:
            self._ledfx.events.fire_event(
                EffectUpdatedEvent(self.id, self._virtual.id)
            )

    # ── Server-side parameter tweening ──────────────────────────────────────
    # SpotFX (and any client) can ask LedFX to interpolate numeric config
    # params from their current values to targets over a duration, advanced
    # once per render frame. This replaces clients streaming ~40 discrete PUTs
    # per second (network-bound, jittery) with a single PUT — the tween then
    # runs in-process at the virtual's render rate (smooth, zero per-frame I/O).

    @staticmethod
    def _validator_coerces_int(validator):
        """True if a voluptuous validator coerces its value to int
        (vol.Coerce(int), possibly wrapped in vol.All)."""
        if isinstance(validator, vol.Coerce):
            return validator.type is int
        if isinstance(validator, vol.All):
            return any(
                Effect._validator_coerces_int(v)
                for v in getattr(validator, "validators", ())
            )
        return validator is int

    def _integer_param_keys(self):
        """Config keys whose schema coerces to int. The tween engine lerps
        as float but must APPLY these as ints — effects use them as numpy
        sizes/indices and a float there kills the render thread."""
        keys = set()
        try:
            for marker, validator in type(self).schema().schema.items():
                if self._validator_coerces_int(validator):
                    keys.add(str(marker))
        except Exception:
            pass
        return keys

    def _classify_param(self, key, target):
        """Decide how a param should be tweened: "numeric" (float lerp),
        "color" (RGB lerp of a solid colour string), "gradient" (LUT lerp on a
        gradient-capable effect), or "instant" (everything else — applied
        immediately)."""
        current = self._config.get(key)
        if isinstance(target, bool) or isinstance(current, bool):
            return "instant"
        if isinstance(target, (int, float)) and isinstance(
            current, (int, float)
        ):
            return "numeric"
        if isinstance(target, str) and isinstance(current, str):
            if hasattr(self, "_generate_gradient_curve") and (
                "gradient(" in target or "gradient(" in current
            ):
                return "gradient"
            try:
                parse_color(target)
                parse_color(current)
                return "color"
            except Exception:
                return "instant"
        return "instant"

    def _build_gradient_curve(self, gradient_str, length):
        """Render a gradient string into a fresh (3, length) LUT without
        disturbing the effect's live self._gradient_curve."""
        saved = self._gradient_curve
        self._generate_gradient_curve(gradient_str, length)
        curve = np.array(self._gradient_curve, dtype=float)
        self._gradient_curve = saved
        return curve

    def start_param_transitions(
        self, targets, duration_ms, easing="linear", blend="rgb"
    ):
        """Begin tweening config params from their current values to `targets`
        over `duration_ms`, advanced each render frame. duration_ms <= 0 applies
        instantly. Called from the event loop (the REST handler). Params that
        can't be interpolated are applied instantly. A param already mid-tween
        is retargeted from its current interpolated value (no snap).

        blend: how colour/gradient params travel — "rgb" (straight per-channel
        lerp; complementary colours pass through grey) or "hue" (HSV
        shortest-arc rotation around the colour wheel; saturation preserved)."""
        with self.lock:
            if not isinstance(targets, dict) or not targets:
                return
            if duration_ms is None or duration_ms <= 0:
                self._apply_config(dict(targets), validate=True, fire_event=True)
                return

            duration = duration_ms / 1000.0
            tweens = dict(self._tweens) if self._tweens else {}
            int_keys = self._integer_param_keys()
            instant = {}
            for key, target in targets.items():
                kind = self._classify_param(key, target)
                if kind == "instant":
                    instant[key] = target
                    tweens.pop(key, None)
                    continue
                prior = tweens.get(key)
                tw = {
                    "elapsed": 0.0,
                    "duration": duration,
                    "easing": easing,
                    "kind": kind,
                }
                if kind == "numeric":
                    # A prior tween on this key may be gradient-kind (stores
                    # current_curve, not current) if the param was reclassified
                    # between calls — reuse prior's live value only when its
                    # kind actually matches (spectra-room-fault-diagnosis,
                    # KeyError: 'current', 2026-08-14).
                    start = (prior["current"]
                             if prior and prior.get("kind") != "gradient"
                             else self._config.get(key))
                    tw["start"] = float(start)
                    tw["target"] = float(target)
                    tw["current"] = float(start)
                    tw["integer"] = key in int_keys
                elif kind == "color":
                    start = (prior["current"]
                             if prior and prior.get("kind") != "gradient"
                             else self._config.get(key))
                    tw["start"] = str(start)
                    tw["target"] = str(target)
                    tw["current"] = str(start)
                    if blend == "hue":
                        try:
                            sc = np.array(
                                parse_color(str(start)), dtype=float
                            ).reshape(3, 1)
                            tc = np.array(
                                parse_color(str(target)), dtype=float
                            ).reshape(3, 1)
                            tw["hsv_start"], tw["hsv_delta"] = (
                                hue_tween_fields(sc, tc)
                            )
                        except Exception:
                            pass  # fall back to RGB lerp
                else:  # gradient
                    try:
                        n = self.gradient_pixel_count
                        if (
                            prior
                            and prior.get("kind") == "gradient"
                            and prior.get("current_curve") is not None
                        ):
                            start_curve = prior["current_curve"]
                        else:
                            start_curve = self._build_gradient_curve(
                                self._config.get(key), n
                            )
                        tw["start_curve"] = start_curve
                        tw["target_curve"] = self._build_gradient_curve(target, n)
                        tw["current_curve"] = start_curve
                        tw["target_str"] = str(target)
                        if blend == "hue":
                            tw["hsv_start"], tw["hsv_delta"] = (
                                hue_tween_fields(
                                    start_curve, tw["target_curve"]
                                )
                            )
                    except Exception:
                        # Can't render the gradient (e.g. pixel_count unknown) —
                        # apply instantly rather than crash the request.
                        instant[key] = target
                        tweens.pop(key, None)
                        continue
                tweens[key] = tw
            if instant:
                self._apply_config(instant, validate=True, fire_event=True)
            self._tweens = tweens or None

    def _tween_ease(self, easing, t):
        """Map linear progress 0..1 through an easing curve for param tweens.
        Phase 1/2: linear. (Named to avoid colliding with GradientEffect._ease,
        which is an unrelated Bernstein helper.)"""
        return t

    @staticmethod
    def _clamp8(x):
        return max(0, min(255, int(round(x))))

    @staticmethod
    def _hue_lerp(tw, t):
        """Evaluate a hue-path tween's precomputed HSV fields at progress t.
        Returns the interpolated curve as (3, n) RGB 0..255."""
        hsv = tw["hsv_start"] + t * tw["hsv_delta"]
        hsv[0] = hsv[0] % 1.0
        return hsv_curve_to_rgb(hsv)

    def _interp(self, tw, t):
        kind = tw["kind"]
        if kind == "numeric":
            return tw["start"] + (tw["target"] - tw["start"]) * t
        if kind == "color":
            if "hsv_start" in tw:  # hue-path blend (transition_blend="hue")
                r, g, b = self._hue_lerp(tw, t)[:, 0]
            else:
                r, g, b = mix_colors(
                    parse_color(tw["start"]), parse_color(tw["target"]), t
                )
            return "#%02x%02x%02x" % (
                self._clamp8(r),
                self._clamp8(g),
                self._clamp8(b),
            )
        return tw["target"]

    def _advance_tweens(self):
        """Advance active param tweens by one frame. CALLER HOLDS self.lock
        (runs inside _render). Numeric/colour values go through the lock-free
        _apply_config so cached / precomputed effect state (radial geometry,
        bg_color, ...) is rebuilt and the change is visible. Gradient curves are
        lerped at the LUT level and assigned AFTER _apply_config (whose
        config_updated chain nulls _gradient_curve), so render() reads ours.
        Never calls update_config (would deadlock on the non-reentrant lock)."""
        frame = {}
        grad_updates = {}
        done = []
        for key, tw in self._tweens.items():
            tw["elapsed"] += self.passed
            t = tw["elapsed"] / tw["duration"]
            if t >= 1.0:
                t = 1.0
                done.append(key)
            e = self._tween_ease(tw["easing"], t)
            if tw["kind"] == "gradient":
                if "hsv_start" in tw:  # hue-path blend
                    curve = self._hue_lerp(tw, e)
                else:
                    curve = (
                        1.0 - e
                    ) * tw["start_curve"] + e * tw["target_curve"]
                tw["current_curve"] = curve
                grad_updates[key] = (curve, tw["target_str"], t)
            else:
                val = self._interp(tw, e)
                # tw["current"] stays the float lerp (smooth retargets);
                # integer params are APPLIED rounded — effects use them as
                # numpy sizes/indices and a float there crashes render.
                tw["current"] = val
                frame[key] = (
                    int(round(val)) if tw.get("integer") else val
                )

        if frame:
            self._apply_config(frame, validate=False, fire_event=False)

        # Gradient LUTs are set last: _apply_config's config_updated chain nulls
        # _gradient_curve, so our lerped curve must win for this frame's render.
        for key, (curve, target_str, t) in grad_updates.items():
            if t >= 1.0:
                # Finalize on the real target string so persistence + future
                # rebuilds use the intended gradient, not the lerped LUT.
                self._config[key] = target_str
                self._gradient_curve = None
            else:
                self._gradient_curve = curve

        for key in done:
            self._tweens.pop(key, None)
        if not self._tweens:
            self._tweens = None
            # One event when the whole batch lands (never per-frame) so the UI /
            # state poller converges to the final values.
            if self._virtual:
                self._ledfx.events.fire_event(
                    EffectUpdatedEvent(self.id, self._virtual.id)
                )

    def _refresh_bg_render_state(self):
        """Rebuild the render-facing bg fields from the LIVE color and the
        (instant) brightness. bg compositing stays on while either the live
        or the target color is non-black, so fades out finish cleanly."""
        live = self._bg_live_rgb * self._bg_brightness
        self._bg_color = live
        self._bg_color_pil = tuple(int(c) for c in np.clip(live, 0, 255))
        self.bg_color_use = bool(
            (live > 0.5).any() or (self._bg_target_rgb > 0.5).any()
        )

    def _advance_bg_fade(self):
        """Ease the live background color toward its target over the
        virtual's transition length (time constant transition_time / 3, so
        the fade visually completes in about one transition). CALLER HOLDS
        self.lock (runs inside _render). Retargets mid-fade continue from
        the current live color — no snap."""
        if self._bg_live_rgb is None:
            return
        delta = self._bg_target_rgb - self._bg_live_rgb
        if not np.abs(delta).max() > 0.5:
            if (self._bg_live_rgb != self._bg_target_rgb).any():
                self._bg_live_rgb = self._bg_target_rgb.copy()
                self._refresh_bg_render_state()
            return
        duration = 0.5
        virtual = self._virtual
        if virtual is not None:
            try:
                duration = float(
                    (virtual._config or {}).get("transition_time", 0.5)
                )
            except Exception:
                duration = 0.5
        duration = max(duration, 0.05)
        # np.exp, NOT math.exp: the registry's module scan imports the
        # ledfx.effects.math SUBMODULE, which rebinds this module's global
        # `math` name (package attribute == __init__ global) and turns
        # math.exp into an AttributeError that kills the virtual thread.
        alpha = 1.0 - float(np.exp(-3.0 * self.passed / duration))
        self._bg_live_rgb = self._bg_live_rgb + delta * alpha
        self._refresh_bg_render_state()

    def config_updated(self, config):
        """
        Optional event for when an effect's config is updated. This
        should be used by the subclass only if they need to build up
        complex properties off the configuration, otherwise the config
        should just be referenced in the effect's loop directly
        """
        pass

    def _render(self):
        with self.lock:
            # its possible we were waiting on the effect being deactivated
            if self._active:
                self.log_sec()
                if self._tweens:
                    self._advance_tweens()
                self._advance_bg_fade()
                self.render()
                # NaN/inf guard: effects read self.pixels back as their previous
                # frame (feedback), so a single non-finite value — e.g. a
                # divide-by-zero or overflow on a big audio spike — would
                # otherwise latch permanently and the output stays black until
                # the effect is re-initialised. Sanitising in place each frame
                # caps the damage at a single frame instead of a wedge.
                px = self.pixels
                if px is not None and not np.isfinite(px).all():
                    np.nan_to_num(
                        px, copy=False, nan=0.0, posinf=255.0, neginf=0.0
                    )
                    if self.now - getattr(self, "_last_nan_log", 0.0) > 5.0:
                        self._last_nan_log = self.now
                        _LOGGER.warning(
                            "Effect %s produced non-finite pixels; sanitised "
                            "(NaN/inf guard).",
                            self.NAME,
                        )
                self.try_log()

    def render(self):
        """
        To be implemented by child effect
        Must act on self.pixels, setting the values of it
        The effect can use self.pixels to see the previous effect
        frame if it wants to use it for something
        """
        pass

    def get_pixels(self):
        """
        Get the current pixels for the effect and apply flip, mirror, blur, brightness and background color transformations

        Returns:
            numpy.ndarray: The modified pixel array.
        """
        with self.lock:
            pixels = None
            if hasattr(self, "pixels"):
                if self.pixels is not None:
                    pixels = np.copy(self.pixels)
                    # Grab the config and store it here for use in the function - we use it a lot
                    config = self._config

                    # Apply some of the base output filters if necessary
                    if self.flip:
                        pixels = np.flipud(pixels)

                    if self.mirror:
                        # concatenate the pixels for mirror, then take the max of adjacent pixels
                        # prevents average dimming and is best compromise, removes flicker
                        # inherently symetrical
                        mirrored_pixels = np.concatenate(
                            (pixels[::-1], pixels)
                        )
                        pixels = np.maximum(
                            mirrored_pixels[::2], mirrored_pixels[1::2]
                        )

                    if (
                        self.bg_color_use
                        and self.background_mode == "additive"
                    ):
                        pixels += self._bg_color
                    elif (
                        self.bg_color_use
                        and self.background_mode == "overwrite"
                    ):
                        # Background fills dark areas of the effect; bright
                        # effect pixels are shown as-is without color mixing.
                        # Equivalent to the 2D pre-fill approach for 1D effects.
                        effect_alpha = np.clip(
                            np.max(pixels, axis=1, keepdims=True) / 255.0,
                            0,
                            1,
                        )
                        pixels += self._bg_color * (1 - effect_alpha)

                    if self.brightness is not None:
                        np.multiply(
                            pixels,
                            self.brightness,
                            out=pixels,
                            casting="unsafe",
                        )

                    # If the configured blur is greater than 0 and pixel_count > 3, apply blur
                    # The matrix math requires > 3 pixels to work properly
                    # And blurring with a less than 3 pixels seems... redundant
                    # TODO: Handle RGBW properly
                    if config["blur"] != 0.0 and self.pixel_count > 3:
                        kernel = _gaussian_kernel1d(
                            config["blur"], 0, len(pixels)
                        )

                        # Blur the R,G,B portions of the pixel array
                        # Lots of attempts at vectorisation/performance improvements here
                        # This appears to be optimal from a readability/performance point of view
                        # TODO: If we ever move to RGBW pixel arrays, uncomment the last line to operate on the W portion

                        pixels[:, 0] = np.convolve(
                            pixels[:, 0], kernel, mode="same"
                        )  # R
                        pixels[:, 1] = np.convolve(
                            pixels[:, 1], kernel, mode="same"
                        )  # G
                        pixels[:, 2] = np.convolve(
                            pixels[:, 2], kernel, mode="same"
                        )  # B
                        # pixels[:, 3] = np.convolve(pixels[:, 3], kernel, mode="same") # W
                return pixels

    @property
    def is_active(self):
        """Return if the effect is currently active"""
        return self._active

    @property
    def pixel_count(self):
        """Returns the number of pixels for the channel"""
        return len(self.pixels)

    @property
    def name(self):
        return self.NAME

    def log_sec(self):
        self.now = timeit.default_timer()
        self.passed = self.now - self._last_frame_time
        self._last_frame_time = self.now
        self.logsec.log_sec(self.now)

    def try_log(self):
        return self.logsec.try_log()


class Effects(RegistryLoader):
    """Thin wrapper around the effect registry that manages effects"""

    PACKAGE_NAME = "fx.effects"

    def __init__(self, ledfx):
        super().__init__(ledfx=ledfx, cls=Effect, package=self.PACKAGE_NAME)
        self._ledfx.audio = None
