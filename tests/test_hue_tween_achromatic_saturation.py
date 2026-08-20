"""Regression coverage for the black<->grey<->colour transition fix
(docs/SPECTRA_SPEC.md §83, PR fm/spectra-achromatic-saturation-fix).

fx/effects/__init__.py::hue_tween_fields already adopted the OTHER end's
HUE for an achromatic endpoint (its own docstring's stated intent) but
still ramped SATURATION from 0, producing a dim-and-desaturated (grey)
midpoint the plain RGB path it replaced never produced. The fix: when one
endpoint is achromatic, also adopt the other end's SATURATION (delta sat
= 0), so only VALUE ramps. See scripts/check_hue_blend_achromatic_desaturation.py
for the reproducible before/after proof against real values from his
library.
"""
from __future__ import annotations

import numpy as np

from fx.color import parse_color
from fx.effects import hsv_curve_to_rgb, hue_tween_fields, mix_colors


def _sat(rgb) -> float:
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def _hue_path_rgb(start_hex: str, target_hex: str, t: float):
    start = np.array(parse_color(start_hex), dtype=float).reshape(3, 1)
    target = np.array(parse_color(target_hex), dtype=float).reshape(3, 1)
    hsv_start, hsv_delta = hue_tween_fields(start, target)
    hsv = hsv_start + t * hsv_delta
    hsv[0] = hsv[0] % 1.0
    return hsv_curve_to_rgb(hsv)[:, 0]


def _rgb_path_rgb(start_hex: str, target_hex: str, t: float):
    return np.array(mix_colors(parse_color(start_hex), parse_color(target_hex), t))


def test_fade_in_from_black_matches_plain_rgb_at_every_step():
    for t in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        hue_rgb = _hue_path_rgb("#000000", "#ff9940", t)
        rgb_rgb = _rgb_path_rgb("#000000", "#ff9940", t)
        assert np.allclose(hue_rgb, rgb_rgb, atol=1.5), (t, hue_rgb, rgb_rgb)


def test_fade_out_to_black_matches_plain_rgb_at_every_step():
    """Symmetric case: 30 of his color_sets.json entries author a black
    background, and glides land on black from a colour just as often as
    they leave it."""
    for t in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        hue_rgb = _hue_path_rgb("#ff9940", "#000000", t)
        rgb_rgb = _rgb_path_rgb("#ff9940", "#000000", t)
        assert np.allclose(hue_rgb, rgb_rgb, atol=1.5), (t, hue_rgb, rgb_rgb)


def test_no_desaturation_dip_at_quarter_point_from_black():
    """The originally-reported defect, pinned: sat=0.187 (near grey) before
    the fix, must now match the plain-RGB path's sat=0.749 on the identical
    pair."""
    rgb = _hue_path_rgb("#000000", "#ff9940", 0.25)
    assert _sat(rgb) > 0.7, f"expected no desaturation dip, got sat={_sat(rgb):.3f}"


def test_colour_to_colour_crossing_is_byte_identical_to_before_the_fix():
    """Neither endpoint is achromatic, so the fix (which only changes the
    achromatic-adoption branch) must not move this pair at all -- this is
    the separately-filed muddy-crossing pair (data/spectra-grey-midpoint-
    transition/brief.md), left untouched by design."""
    ts = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    start = np.array(parse_color("#8b7e53"), dtype=float).reshape(3, 1)
    target = np.array(parse_color("#009eff"), dtype=float).reshape(3, 1)
    hsv_start, hsv_delta = hue_tween_fields(start, target)
    # Neither endpoint is gray, so this must equal the pre-fix formula
    # exactly: hsv_start[1] == start's own saturation, delta == target - start.
    from fx.effects import rgb_curve_to_hsv

    s_hsv = rgb_curve_to_hsv(start)
    t_hsv = rgb_curve_to_hsv(target)
    assert np.allclose(hsv_start[1], s_hsv[1])
    assert np.allclose(hsv_delta[1], t_hsv[1] - s_hsv[1])

    sats = []
    for t in ts:
        hsv = hsv_start + t * hsv_delta
        hsv[0] = hsv[0] % 1.0
        rgb = hsv_curve_to_rgb(hsv)[:, 0]
        sats.append(_sat(rgb))
    assert all(b >= a - 1e-6 for a, b in zip(sats, sats[1:])), "expected monotonic saturation (unchanged)"


def test_hue_and_value_fields_are_unaffected_by_the_fix():
    """Only the saturation field of hsv_start/hsv_delta may change; hue and
    value must be bit-identical to the pre-fix formula for every pair."""
    from fx.effects import rgb_curve_to_hsv

    def old_fields(start_curve, target_curve, achromatic=0.05):
        s_hsv = rgb_curve_to_hsv(start_curve)
        t_hsv = rgb_curve_to_hsv(target_curve)
        s_gray = (s_hsv[1] < achromatic) | (s_hsv[2] < achromatic)
        t_gray = (t_hsv[1] < achromatic) | (t_hsv[2] < achromatic)
        h_s = np.where(s_gray, t_hsv[0], s_hsv[0])
        h_t = np.where(t_gray, h_s, t_hsv[0])
        dh = ((h_t - h_s + 0.5) % 1.0) - 0.5
        hsv_start = np.stack([h_s, s_hsv[1], s_hsv[2]])
        hsv_delta = np.stack([dh, t_hsv[1] - s_hsv[1], t_hsv[2] - s_hsv[2]])
        return hsv_start, hsv_delta

    for pair in (("#000000", "#ff9940"), ("#ff9940", "#000000"), ("#8b7e53", "#009eff")):
        start = np.array(parse_color(pair[0]), dtype=float).reshape(3, 1)
        target = np.array(parse_color(pair[1]), dtype=float).reshape(3, 1)
        old_start, old_delta = old_fields(start, target)
        new_start, new_delta = hue_tween_fields(start, target)
        assert np.allclose(old_start[0], new_start[0]), "hue start changed"
        assert np.allclose(old_delta[0], new_delta[0]), "hue delta changed"
        assert np.allclose(old_start[2], new_start[2]), "value start changed"
        assert np.allclose(old_delta[2], new_delta[2]), "value delta changed"
