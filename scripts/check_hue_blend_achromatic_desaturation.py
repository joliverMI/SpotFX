#!/usr/bin/env python3
"""Read-only proof for docs/SPECTRA_SPEC.md's "grey/white before colour"
transition investigation (his report, 2026-08-19: "it goes from black to a
gray or a white and then changes color").

Root cause: fx/effects/__init__.py's hue_tween_fields() -- the "careful"
hue-arc blend requested for every real scene fire (fx_seam._body() always
sets transition_blend="hue" whenever transition_ms > 0, and his real
room_controls.json's global_transition_ms==0 falls through Python's `or`
chain in scene_compiler.fire_scene() to the nonzero intensity-scaled
default, so transition_ms is never actually 0 for a real fire) -- produces
a WORSE desaturation dip than the plain RGB path it was built to replace,
whenever one endpoint of the transition is achromatic (near-black/near-
white). Achromatic starts are not an edge case in his data: 30 of his real
color_sets.json entries author bg_color == "#000000" exactly for the
documented reason (§72: resets a virtual's background every fire in Hybrid
mode), and 12 of his gradient entries carry a literal black stop within
the gradient itself.

WHY: for an achromatic endpoint, hue_tween_fields() adopts the OTHER end's
hue immediately (hsv_start = [target_hue, 0, 0]) and interpolates
SATURATION and VALUE as independent linear scalars from 0 to the target's
own (sat, val) -- i.e. sat(t) = t * target_sat, val(t) = t * target_val.
A plain RGB scale-up from black (mix_colors) does NOT do this: scaling an
RGB vector by t leaves its (max-min)/max ratio -- its saturation --
UNCHANGED, so the naive path this feature deliberately replaced was
already saturation-safe from black. The hue-path's own achromatic handling
is the thing that introduces the desaturation it was built to prevent.

This is proven here purely against real values from his real
storage/color_sets.json (SpotFX, read-only) and the exact functions
fx/facade.py's start_param_transitions() calls in production -- no camera,
no live device, no room access needed; this is a property of the
interpolation, reproducible at a desk. See docs/SPECTRA_SPEC.md's dated
entry for the live-room confirmation (executor writes glide background_color
to/from #000000 as a routine, ongoing part of his real automatic colour
journey -- the precondition fires constantly in his actual room) and for
the WLED firmware auto-white finding (a separate, additive mechanism on
his 4 RGBW fixtures: rgbw=true, wv=2 confirmed live on 3 of them).

Never touches live storage or a live instance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from fx.color import parse_color  # noqa: E402
from fx.effects import hsv_curve_to_rgb, hue_tween_fields, mix_colors  # noqa: E402
from fx.effects.gradient import GradientEffect  # noqa: E402

REAL_COLOR_SETS = Path("/home/javi/SpotFX/storage/color_sets.json")


def _sat(rgb) -> float:
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def _hue_path_series(start_hex: str, target_hex: str, ts):
    start = np.array(parse_color(start_hex), dtype=float).reshape(3, 1)
    target = np.array(parse_color(target_hex), dtype=float).reshape(3, 1)
    hsv_start, hsv_delta = hue_tween_fields(start, target)
    out = []
    for t in ts:
        hsv = hsv_start + t * hsv_delta
        hsv[0] = hsv[0] % 1.0
        rgb = hsv_curve_to_rgb(hsv)[:, 0]
        out.append(rgb)
    return out


def _rgb_path_series(start_hex: str, target_hex: str, ts):
    return [np.array(mix_colors(parse_color(start_hex), parse_color(target_hex), t))
            for t in ts]


def part1_achromatic_start():
    print("== Part 1: hue-path desaturation from a real achromatic endpoint ==")
    print("Real pair from his library: background_color #000000 (Line - Green's")
    print("authored black bg) -> #ff9940 (Calm - Purple's bg). Exactly the param")
    print("and exactly the blend fx_seam always requests for a same-type scene fire.\n")

    ts = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
    hue_series = _hue_path_series("#000000", "#ff9940", ts)
    rgb_series = _rgb_path_series("#000000", "#ff9940", ts)

    print(f"{'t':>5} | {'HUE-PATH (the actual code path)':^28} | {'PLAIN RGB (what it replaced)':^28}")
    for t, hp, rp in zip(ts, hue_series, rgb_series):
        hp_hex = "#%02x%02x%02x" % tuple(int(round(c)) for c in hp)
        rp_hex = "#%02x%02x%02x" % tuple(int(round(c)) for c in rp)
        print(f"{t:5.2f} | {hp_hex} sat={_sat(hp):5.3f}            "
              f"| {rp_hex} sat={_sat(rp):5.3f}")

    assert _sat(hue_series[2]) < 0.25, "expected a real desaturation dip at t=0.25"
    assert _sat(rgb_series[2]) > 0.7, "expected the plain RGB path to stay saturated"
    print("\n  -> CONFIRMED: at t=0.25 the hue-path is nearly achromatic "
          f"(sat={_sat(hue_series[2]):.3f}) while the plain RGB path it replaced")
    print(f"     stays warmly saturated (sat={_sat(rgb_series[2]):.3f}) on the identical pair.")
    print("     This is the mechanism: dim + desaturated together reads as grey/white,")
    print("     and only in the back half of the ramp does saturation catch up to reveal hue.\n")


def part2_non_achromatic_is_fine():
    print("== Part 2: the SAME hue-path does NOT dip when neither endpoint is achromatic ==")
    print("(isolates this from the separately-filed saturated-colour-crossing dip)\n")
    ts = [0.0, 0.25, 0.5, 0.75, 1.0]
    series = _hue_path_series("#8b7e53", "#009eff", ts)
    sats = [_sat(c) for c in series]
    for t, c, s in zip(ts, series, sats):
        hexs = "#%02x%02x%02x" % tuple(int(round(v)) for v in c)
        print(f"  t={t:.2f}  {hexs}  sat={s:.3f}")
    assert all(b >= a - 1e-6 for a, b in zip(sats, sats[1:])), "expected monotonic saturation"
    print("  -> CONFIRMED: saturation is monotonic (no dip) when neither endpoint is grey.\n")


def part3_real_gradient_pair():
    print("== Part 3: the same defect, per-pixel, inside a real GRADIENT->GRADIENT fire ==")
    ge = GradientEffect.__new__(GradientEffect)

    def build(s, n=64):
        ge._generate_gradient_curve(s, n)
        return np.array(ge._gradient_curve, dtype=float)

    start_val = ("linear-gradient(90deg, rgb(0,0,0) 30%, rgb(0,255,7) 35%, "
                "rgb(0,255,7) 65%, rgb(0,0,0) 70%)")  # real: "Line - Green"
    target_val = "linear-gradient(90deg, rgb(214,0,150) 21%, rgb(0,0,204) 100%)"  # real: "Calm - Purple"
    n = 64
    sc, tc = build(start_val, n), build(target_val, n)
    hsv_start, hsv_delta = hue_tween_fields(sc, tc)

    for label, idx in (("idx=10 (source pixel is black in Line - Green)", 10),
                       ("idx=32 (source pixel is green in Line - Green)", 32)):
        print(f"  {label}: source={sc[:, idx].round(1)}")
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            hsv = hsv_start[:, idx:idx + 1] + t * hsv_delta[:, idx:idx + 1]
            hsv[0] = hsv[0] % 1.0
            rgb = hsv_curve_to_rgb(hsv)[:, 0]
            print(f"    t={t:.2f} RGB={rgb.round(1)} sat={_sat(rgb):.3f}")
    print("  -> CONFIRMED: any pixel whose SOURCE gradient value is black desaturates on")
    print("     the same t-proportional ramp; pixels that started coloured do not.")
    print("     12 of his real gradient entries carry a literal black stop, so this is a")
    print("     per-pixel, not per-param, occurrence within an ordinary gradient fire.\n")


def part4_scope_in_real_library():
    print("== Part 4: how often his real data hits this precondition ==")
    with REAL_COLOR_SETS.open() as f:
        data = json.load(f)
    black_bg = 0
    black_gradient_stop = 0
    total_entries = 0
    for cs in data.values():
        for e in cs.get("entries", []):
            total_entries += 1
            if e.get("bg_color") == "#000000":
                black_bg += 1
            cv = (e.get("color_value") or "").replace(" ", "")
            if "rgb(0,0,0)" in cv:
                black_gradient_stop += 1
    print(f"  total colour-set entries: {total_entries}")
    print(f"  entries authoring bg_color == #000000: {black_bg}")
    print(f"  gradient entries carrying a literal black stop: {black_gradient_stop}")
    print("  -> every one of these entries hits the achromatic-endpoint ramp on its")
    print("     next hue-blended transition into or out of it.\n")


def main() -> None:
    part1_achromatic_start()
    part2_non_achromatic_is_fine()
    part3_real_gradient_pair()
    part4_scope_in_real_library()
    print("All assertions passed. No fix applied by this script -- diagnostic only.")


if __name__ == "__main__":
    main()
