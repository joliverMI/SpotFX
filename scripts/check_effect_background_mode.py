"""Does every effect obey a colour set's background MODE?

The Admiral, 2026-10-07: "the fish effect seems to not obey overwrite feom
colors. it may be same with other effects." A colour-set entry carries
`bg_color` + `background_brightness` + `bg_mode` ("overwrite" | "additive");
`spectra/services/scene_compiler._apply_set_colors` writes the mode as the
effect's `background_mode`. The contract, from `fx/effects/__init__.py`'s
`Effect.get_pixels()`:

  additive   every pixel gets the background ADDED under it
  overwrite  the background shows only where the effect is dark:
             pixel += bg * (1 - effect_alpha), effect_alpha = max(rgb)/255

With a PURE-RED foreground and a PURE-BLUE background, every pixel's blue
channel is therefore a function of its red channel alone, and the two modes
have two different expected curves:

  additive   blue == bg_value                       (whatever the red)
  overwrite  blue == bg_value * (1 - red / 255)     (lit red -> no blue)

The probe renders EVERY registered effect on the real `fx.headless`
pipeline (dummy device, synthetic audio, no network, no live storage) in
both modes and reports, per effect, how far the rendered blue channel sits
from each mode's own curve, averaged over the pixels the effect lit — plus
the unlit pixels' blue, which tells the double-application story too
(`v*(2 - v/255)` instead of `v`, the pixel-brightness-chain report §3).
It writes nothing. `tests/test_effect_background_mode.py` asserts the same
contract in pytest.

Usage: .venv/bin/python scripts/check_effect_background_mode.py [effect ...]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx import device_model, headless, utils as fx_utils  # noqa: E402
from fx.effects import particle_handoff  # noqa: E402

VID = headless.DEFAULT_VIRTUAL_ID

FG_RED = "#ff0000"
BG_BLUE = "#0000ff"
BG_BRIGHTNESS = 0.4
BG_VALUE = 255 * BG_BRIGHTNESS                 # 102, the authored background
BG_DOUBLED = BG_VALUE * (2 - BG_VALUE / 255)   # ~163, the §3 double-apply
LIT_RED = 64         # a pixel the effect clearly lit (foreground present)
TOLERANCE = 12.0     # mean blue error (0..255) a mode's curve may miss by

# The registry's `noise` is the effect class `noise2d`.
EFFECT_CLASS_ALIAS = {"noise": "noise2d"}

# Per-effect nudges so the probe gets lit pixels, and so the foreground
# really is pure red (no hue walk, no accent colour, no beat gating).
EFFECT_TWEAKS: dict[str, dict] = {
    "fish": {"color_shift": 0, "particle_count": 8, "camera_follow": 0},
    "orbits": {"particle_count": 8},
    "squiggles": {"spawn_rate": 4.0, "max_blobs": 6},
    "blackhole": {"spawn_rate": 8.0},
    "fireworks": {"spawn_rate": 8.0, "beat_burst": False},
    "fireworks1d": {"spawn_rate": 8.0, "beat_burst": False},
    "power": {"sparks_color": "#000000"},
    "radial": {"base_rotation": 0.5},
    "gifplayer": {"image_location": "__RED_GIF__"},
    "keybeat2d": {"image_location": "__RED_GIF__", "tint": FG_RED},
}
COLOR_PARAMS = ("gradient", "color", "color_lows", "color_mids", "color_high")

ROWS_2D, COLS_2D = 37, 72


class FakeAudio:
    """The surface the vendored effects read in `audio_data_updated`: a
    steady loud power on every band, a 120 bpm beat, a 1.0 volume."""

    def __init__(self, power: float = 0.9):
        self.power = power
        self.t = 0.0
        self._tempo = 120.0
        self._config = {"min_volume": 0.2, "mic_rate": 44100,
                        "sample_rate": 60, "fft_size": 4096, "delay_ms": 0}

    def _p(self, filtered: bool = True):
        return self.power

    beat_power = bass_power = lows_power = mids_power = high_power = _p

    def volume(self, filtered: bool = True):
        return 1.0

    def beat_oscillator(self):
        return (self.t * self._tempo / 60.0) % 1.0

    def bar_oscillator(self):
        return (self.t * self._tempo / 240.0) % 4.0

    def bpm_beat_now(self):
        phase = (self.t * self._tempo / 60.0) % 1.0
        return phase < (1 / 60.0) * self._tempo / 60.0 + 1e-6

    onset = bpm_beat_now
    volume_beat_now = bpm_beat_now


def registered_effects() -> list[str]:
    reg = json.load(open(ROOT / "config/effect_params.json"))
    eff = reg.get("effects") or reg
    return sorted(k for k in eff if isinstance(eff[k], dict) and "params" in eff[k])


def _write_red_gif(config_dir: str) -> str:
    from PIL import Image
    path = os.path.join(config_dir, "probe-red.gif")
    frames = [Image.new("RGB", (16, 8), (255, 0, 0)) for _ in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    return path


def _probe_config(effect_type: str, mode: str, schema_keys: set[str],
                  config_dir: str) -> dict:
    cfg: dict = {}
    for key in COLOR_PARAMS:
        if key in schema_keys:
            cfg[key] = FG_RED
    cfg.update({
        "background_color": BG_BLUE,
        "background_brightness": 0.0 if mode == "none" else BG_BRIGHTNESS,
        "background_mode": "additive" if mode == "none" else mode,
        "brightness": 1.0,
        "blur": 0.0,
    })
    for k, v in EFFECT_TWEAKS.get(effect_type, {}).items():
        if v == "__RED_GIF__":
            v = _write_red_gif(config_dir)
        cfg[k] = v
    return cfg


async def _render(effect_type: str, mode: str, config_dir: str,
                  n_frames: int = 120) -> tuple[np.ndarray, bool]:
    two_d = device_model.effect_dimension(effect_type) == "2d"
    kwargs = ({"pixel_count": ROWS_2D * COLS_2D, "rows": ROWS_2D}
              if two_d else {"pixel_count": 64, "rows": 1})
    # Every probe host reuses ONE virtual id and the fake clock restarts at
    # the same instant, so a previous effect's particle-handoff snapshot
    # (fx/effects/particle_handoff.py, keyed by virtual id, 2 s max age)
    # would otherwise be ADOPTED by the next effect's first draw and paint
    # its colours into this measurement — Fish after Pacman measured
    # Pacman's ghost colours. Drain it: this probe is one effect at a time.
    particle_handoff.take(VID, max_age=float("inf"))
    host = await headless.start_headless_host(config_dir, **kwargs)
    fx_utils.init_image_cache(config_dir)   # the GIF effects' local-file gate
    host.audio._volume = 1.0
    virtual = host.virtuals.get(VID)
    audio_ok = True
    try:
        cls_id = EFFECT_CLASS_ALIAS.get(effect_type, effect_type)
        cls = host.effects.get_class(cls_id)
        schema_keys = {str(k) for k in cls.schema().schema}
        config = _probe_config(effect_type, mode, schema_keys, config_dir)
        audio = FakeAudio()
        frames = []
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, cls_id, config)
            for i in range(n_frames):
                audio.t = i / 60.0
                if audio_ok and hasattr(effect, "audio_data_updated"):
                    try:
                        with effect.lock:
                            effect.audio_data_updated(audio)
                    except Exception:
                        audio_ok = False      # reads a surface we don't fake
                frames += headless.render_frames(virtual, 1, clock=clock,
                                                 dt=1 / 60)
    finally:
        await host.shutdown()
    # average the back half: particle effects flicker frame to frame
    return np.mean(np.stack(frames[n_frames // 2:]), axis=0), audio_ok


def measure(frame: np.ndarray, own_blue: float = 0.0) -> dict:
    """`own_blue`: the mean blue the effect paints into its lit pixels with
    NO background at all (its own colour content), subtracted before the
    rendered blue is compared against either mode's curve."""
    r, b = frame[:, 0], frame[:, 2]
    lit = r > LIT_RED
    dark = r < 1.0
    out = {
        "lit_px": int(lit.sum()),
        "dark_px": int(dark.sum()),
        "lit_blue": float(b[lit].mean()) if lit.any() else None,
        "lit_red": float(r[lit].mean()) if lit.any() else None,
        "dark_blue": float(b[dark].mean()) if dark.any() else None,
        "err_additive": None, "err_overwrite": None,
    }
    if lit.any():
        exp_add = np.full(lit.sum(), BG_VALUE)
        exp_ow = BG_VALUE * (1 - r[lit] / 255.0)
        bl = b[lit] - own_blue
        out["err_additive"] = float(np.abs(bl - exp_add).mean())
        out["err_overwrite"] = float(np.abs(bl - exp_ow).mean())
    return out


def probe(effect_type: str) -> dict:
    out = {"effect": effect_type,
           "bg_blocked": device_model.bg_color_blocked(effect_type)}
    with tempfile.TemporaryDirectory() as tmp:
        none, _ = asyncio.run(_render(effect_type, "none", os.path.join(tmp, "none")))
        own = measure(none)
        own_blue = own["lit_blue"] or 0.0
        out["own_blue"] = own_blue
        for mode in ("overwrite", "additive"):
            frame, audio_ok = asyncio.run(
                _render(effect_type, mode, os.path.join(tmp, mode)))
            out[mode] = measure(frame, own_blue)
            out[mode]["audio_driven"] = audio_ok
    return out


def verdict(res: dict) -> tuple[str, bool]:
    """Plain words: does each mode land on its OWN curve? Returns (text,
    bad) where bad means the effect is not honouring the authored mode."""
    ow, ad = res["overwrite"], res["additive"]
    if ow["lit_blue"] is None:
        return ("no lit pixels - lit side cannot be judged", False)
    parts, bad = [], False
    if res["own_blue"] > TOLERANCE and ad["lit_blue"] is not None:
        # The effect paints blue of its own into its lit pixels (Dancer's
        # white flashes, Pacman's maze), unevenly, so a per-pixel curve
        # cannot be read off a scalar correction. The two modes' MEANS still
        # must differ by exactly what overwrite withholds: bg * lit-ness.
        delta = ad["lit_blue"] - ow["lit_blue"]
        expected = BG_VALUE * ow["lit_red"] / 255.0
        if abs(delta - expected) > TOLERANCE:
            return (f"mode difference {delta:.0f} vs the {expected:.0f} overwrite "
                    f"should withhold (own colour content, read by difference)", True)
        return (f"obeys both modes by difference ({delta:.0f} withheld, "
                f"{expected:.0f} expected; own colour content)", False)
    if ow["err_overwrite"] > TOLERANCE:
        bad = True
        if ow["err_additive"] <= TOLERANCE:
            parts.append("IGNORES overwrite (lit pixels carry the full background, i.e. additive)")
        else:
            parts.append(f"overwrite off-curve by {ow['err_overwrite']:.0f}")
    else:
        parts.append("obeys overwrite")
    if ad["lit_blue"] is not None:
        if ad["err_additive"] > TOLERANCE:
            bad = True
            parts.append(f"additive off-curve by {ad['err_additive']:.0f}")
        else:
            parts.append("obeys additive")
    return ("; ".join(parts), bad)


def dark_verdict(res: dict) -> tuple[str, bool]:
    ow = res["overwrite"]["dark_blue"]
    if ow is None:
        return ("no dark pixels", False)
    if abs(ow - BG_DOUBLED) < TOLERANCE:
        return (f"DOUBLED background on dark pixels ({ow:.0f} vs authored {BG_VALUE:.0f})", True)
    if abs(ow - BG_VALUE) < TOLERANCE:
        return ("dark pixels carry the authored background", False)
    return (f"dark pixels at {ow:.0f} (authored {BG_VALUE:.0f})", True)


def main(argv: list[str]) -> int:
    names = argv or registered_effects()
    print(f"foreground {FG_RED}, background {BG_BLUE} @ {BG_BRIGHTNESS} "
          f"(authored blue {BG_VALUE:.0f}, doubled {BG_DOUBLED:.0f}); "
          f"err = mean |blue - mode's own curve| over lit pixels (red > {LIT_RED})")
    print(f"{'effect':12} {'mode':9} {'lit px':>7} {'lit blue':>9} "
          f"{'err ow':>7} {'err add':>8} {'dark px':>8} {'dark blue':>9}")
    bad, unrendered = [], []
    for name in names:
        try:
            res = probe(name)
        except Exception as exc:
            print(f"{name:12} could not render offline: {type(exc).__name__}: {exc}")
            unrendered.append(name)
            continue
        for mode in ("overwrite", "additive"):
            m = res[mode]
            f = lambda v: "-" if v is None else f"{v:.0f}"
            print(f"{name:12} {mode:9} {m['lit_px']:7d} {f(m['lit_blue']):>9} "
                  f"{f(m['err_overwrite']):>7} {f(m['err_additive']):>8} "
                  f"{m['dark_px']:8d} {f(m['dark_blue']):>9}"
                  + ("" if m["audio_driven"] else "   (silent: audio surface not faked)"))
        v, vbad = verdict(res)
        dv, dbad = dark_verdict(res)
        flag = " [bg blocked in production]" if res["bg_blocked"] else ""
        own = f" (own blue {res['own_blue']:.0f} subtracted)" if res["own_blue"] > 1 else ""
        print(f"{'':12} -> {v}; {dv}{flag}{own}")
        if vbad or dbad:
            bad.append(name)
    print()
    print("effects not honouring the background mode as intended:",
          ", ".join(bad) if bad else "none")
    if unrendered:
        print("effects this offline probe could not render (not judged):",
              ", ".join(unrendered))
    return 0


if __name__ == "__main__":
    try:
        status = main(sys.argv[1:])
    except Exception:
        import traceback
        traceback.print_exc()
        status = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
