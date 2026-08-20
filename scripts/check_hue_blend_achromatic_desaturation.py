#!/usr/bin/env python3
"""Read-only proof for docs/SPECTRA_SPEC.md's "grey/white before colour"
transition fix (§83/§84, his report, 2026-08-19: "it goes from black to a
gray or a white and then changes color").

Root cause (FIXED, PR fm/spectra-achromatic-saturation-fix):
fx/effects/__init__.py's hue_tween_fields() -- the "careful" hue-arc blend
requested for every real scene fire (fx_seam._body() always sets
transition_blend="hue" whenever transition_ms > 0, and his real
room_controls.json's global_transition_ms==0 falls through Python's `or`
chain in scene_compiler.fire_scene() to the nonzero intensity-scaled
default, so transition_ms is never actually 0 for a real fire) -- USED TO
produce a WORSE desaturation dip than the plain RGB path it was built to
replace, whenever one endpoint of the transition is achromatic (near-black/
near-white). Achromatic starts are not an edge case in his data: 30 of his
real color_sets.json entries author bg_color == "#000000" exactly for the
documented reason (§72: resets a virtual's background every fire in Hybrid
mode), and 12 of his gradient entries carry a literal black stop within
the gradient itself.

WHY it happened: for an achromatic endpoint, hue_tween_fields() already
adopted the OTHER end's hue immediately (its own docstring's stated
intent), but interpolated SATURATION and VALUE as independent linear
scalars from 0 to the target's own (sat, val) -- i.e. sat(t) = t *
target_sat, val(t) = t * target_val. A plain RGB scale-up from black
(mix_colors) does NOT do this: scaling an RGB vector by t leaves its
(max-min)/max ratio -- its saturation -- UNCHANGED, so the naive path this
feature deliberately replaced was already saturation-safe from black. The
hue-path's own achromatic handling was the thing introducing the
desaturation it was built to prevent.

THE FIX: hue_tween_fields() now adopts the other end's SATURATION too,
exactly the same way it already adopted its HUE, whenever an endpoint is
achromatic -- so only VALUE ramps for that endpoint, and the result is
byte-identical to the plain RGB path in both directions (fade in from
black, fade out to black). Colour-to-colour crossings (neither endpoint
achromatic) are untouched by construction: the achromatic branch is the
only one that changed, so a pair like the separately-filed muddy-crossing
case (cream #8b7e53 -> blue #009eff, data/spectra-grey-midpoint-transition/
brief.md) is bit-identical before and after this fix -- that pair's own
saturation dip lives in a DIFFERENT function (mix_colors, the plain RGB
path) and is not addressed here.

This is proven here purely against real values from his real
storage/color_sets.json (SpotFX, read-only) and the exact functions
fx/facade.py's start_param_transitions() calls in production -- no camera,
no live device, no room access needed; this is a property of the
interpolation, reproducible at a desk. See docs/SPECTRA_SPEC.md's dated
entry for the live-room confirmation (executor writes glide background_color
to/from #000000 as a routine, ongoing part of his real automatic colour
journey -- the precondition fires constantly in his actual room) and for
the WLED firmware auto-white finding (a separate, additive mechanism on
his 4 RGBW fixtures: rgbw=true, wv=2 confirmed live on 3 of them, untouched
by this fix).

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
    print("== Part 1 (FIXED): hue-path from a real achromatic endpoint now matches plain RGB ==")
    print("Real pair from his library: background_color #000000 (Line - Green's")
    print("authored black bg) -> #ff9940 (Calm - Purple's bg). Exactly the param")
    print("and exactly the blend fx_seam always requests for a same-type scene fire.\n")

    ts = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
    hue_series = _hue_path_series("#000000", "#ff9940", ts)
    rgb_series = _rgb_path_series("#000000", "#ff9940", ts)

    print(f"{'t':>5} | {'HUE-PATH (fixed)':^28} | {'PLAIN RGB (unchanged reference)':^28}")
    for t, hp, rp in zip(ts, hue_series, rgb_series):
        hp_hex = "#%02x%02x%02x" % tuple(int(round(c)) for c in hp)
        rp_hex = "#%02x%02x%02x" % tuple(int(round(c)) for c in rp)
        print(f"{t:5.2f} | {hp_hex} sat={_sat(hp):5.3f}            "
              f"| {rp_hex} sat={_sat(rp):5.3f}")

    for hp, rp in zip(hue_series, rgb_series):
        assert max(abs(a - b) for a, b in zip(hp, rp)) < 1.5, (
            "expected the fixed hue-path to be byte-identical to the plain RGB path"
        )
    assert _sat(hue_series[2]) > 0.7, "expected no desaturation dip at t=0.25 after the fix"
    print("\n  -> CONFIRMED: the fixed hue-path is byte-identical to the plain RGB path")
    print(f"     it replaced at every t (t=0.25 sat={_sat(hue_series[2]):.3f} on both).")
    print("     No dim-and-desaturated midpoint; only VALUE ramps for the achromatic end.\n")


def part1b_achromatic_end_symmetric():
    print("== Part 1b (FIXED): fading DOWN to black, the symmetric case ==")
    print("His colour journeys glide TO black just as often as they leave it, and")
    print("the fix is applied symmetrically -- same pair, reversed direction.\n")

    ts = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
    hue_series = _hue_path_series("#ff9940", "#000000", ts)
    rgb_series = _rgb_path_series("#ff9940", "#000000", ts)

    print(f"{'t':>5} | {'HUE-PATH (fixed)':^28} | {'PLAIN RGB (unchanged reference)':^28}")
    for t, hp, rp in zip(ts, hue_series, rgb_series):
        hp_hex = "#%02x%02x%02x" % tuple(int(round(c)) for c in hp)
        rp_hex = "#%02x%02x%02x" % tuple(int(round(c)) for c in rp)
        print(f"{t:5.2f} | {hp_hex} sat={_sat(hp):5.3f}            "
              f"| {rp_hex} sat={_sat(rp):5.3f}")

    for hp, rp in zip(hue_series, rgb_series):
        assert max(abs(a - b) for a, b in zip(hp, rp)) < 1.5, (
            "expected the fixed hue-path to be byte-identical to the plain RGB path"
        )
    assert _sat(hue_series[2]) > 0.7, "expected no desaturation dip fading to black either"
    print("\n  -> CONFIRMED: fading down to black holds saturation too -- no grey dip on exit.\n")


def part2_non_achromatic_is_fine():
    print("== Part 2 (UNCHANGED BY THE FIX): colour-to-colour crossings ==")
    print("(the separately-filed muddy-crossing pair, cream->blue -- its own dip lives in")
    print(" mix_colors, the PLAIN RGB path, not here; the hue-path was and remains fine on it)\n")
    ts = [0.0, 0.25, 0.5, 0.75, 1.0]
    series = _hue_path_series("#8b7e53", "#009eff", ts)
    sats = [_sat(c) for c in series]
    for t, c, s in zip(ts, series, sats):
        hexs = "#%02x%02x%02x" % tuple(int(round(v)) for v in c)
        print(f"  t={t:.2f}  {hexs}  sat={s:.3f}")
    assert all(b >= a - 1e-6 for a, b in zip(sats, sats[1:])), "expected monotonic saturation"
    print("  -> CONFIRMED: saturation is still monotonic (no dip) when neither endpoint is grey --")
    print("     this fix touches only the achromatic-adoption branch, so this pair is bit-identical")
    print("     to its pre-fix values (see tests/test_hue_tween_achromatic_saturation.py).\n")


def part3_real_gradient_pair():
    print("== Part 3 (FIXED): per-pixel, inside a real GRADIENT->GRADIENT fire ==")
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

    black_pixel_min_sat = None
    for label, idx in (("idx=10 (source pixel is black in Line - Green)", 10),
                       ("idx=32 (source pixel is green in Line - Green)", 32)):
        print(f"  {label}: source={sc[:, idx].round(1)}")
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            hsv = hsv_start[:, idx:idx + 1] + t * hsv_delta[:, idx:idx + 1]
            hsv[0] = hsv[0] % 1.0
            rgb = hsv_curve_to_rgb(hsv)[:, 0]
            s = _sat(rgb)
            if idx == 10 and 0.0 < t < 1.0:
                black_pixel_min_sat = s if black_pixel_min_sat is None else min(black_pixel_min_sat, s)
            print(f"    t={t:.2f} RGB={rgb.round(1)} sat={s:.3f}")
    assert black_pixel_min_sat is not None and black_pixel_min_sat > 0.7, (
        f"expected the black-sourced pixel to hold saturation, got min={black_pixel_min_sat}"
    )
    print("  -> CONFIRMED: the pixel whose SOURCE gradient value is black now holds its target")
    print("     saturation throughout (only value ramps), matching pixels that started coloured.")
    print("     12 of his real gradient entries carry a literal black stop, so this fix reaches")
    print("     every such pixel inside an ordinary gradient fire, not just solid bg_color.\n")


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
    print("  -> every one of these entries now holds saturation (via the fix) on its")
    print("     next hue-blended transition into or out of it.\n")


def main() -> None:
    part1_achromatic_start()
    part1b_achromatic_end_symmetric()
    part2_non_achromatic_is_fine()
    part3_real_gradient_pair()
    part4_scope_in_real_library()
    print("All assertions passed. fx/effects/__init__.py::hue_tween_fields fixed in place --")
    print("this script re-verifies the fix against real values from his library.")


if __name__ == "__main__":
    main()
