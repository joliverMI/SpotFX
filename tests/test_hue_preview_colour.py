"""spectra/services/hue_preview_colour.py — the conversions that let the
device preview draw a HELD Hue bulb's real colour instead of whatever its
driving virtual happens to be rendering underneath the freeze (see that
module's own docstring for the full defect this fixes)."""
from __future__ import annotations

from spectra.services import hue_preview_colour as hpc


def test_kelvin_to_rgb_is_warm_at_low_temperatures_never_green_dominant():
    for kelvin in (2000, 2700, 3500, 6500):
        r, g, b = hpc.kelvin_to_rgb(kelvin)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
        # the signature of the naive "x/y used as R/G" bug this was built to
        # catch: green clearly the brightest channel. A real blackbody tint
        # never does that — red leads or (near 6500K) all three are close.
        assert not (g > r + 10 and g > b + 10), (kelvin, r, g, b)


def test_kelvin_to_rgb_matches_the_houseSummary_ts_fit_exactly():
    # Hand-computed from the IDENTICAL Tanner Helland formula
    # (houseSummary.ts::kelvinToHex) — the acceptance bar for "uses the
    # same correct conversion" named in the task brief.
    assert hpc.kelvin_to_rgb(2000) == (255, 137, 14)
    assert hpc.kelvin_to_rgb(2700) == (255, 167, 87)
    assert hpc.kelvin_to_rgb(3500) == (255, 193, 141)
    assert hpc.kelvin_to_rgb(6500) == (255, 254, 250)


def test_kelvin_2095_the_house_modes_default_tv_paused_dining_look():
    # DJ's live read at 14:42: dining held at mirek 477 ≈ 2095 K. Must be a
    # plausible warm white, not yellow-green.
    r, g, b = hpc.kelvin_to_rgb(2095)
    assert r == 255
    assert r > g > b
    assert b < 60


def test_xy_point_from_the_live_bridge_is_a_plausible_warm_white():
    # The exact xy the Admiral's bridges reported for the 2100K hold.
    r, g, b = hpc.xy_to_rgb(0.5163, 0.4145, 1.0)
    assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
    assert r >= g >= b           # warm-white ordering
    assert not (g > r)           # the naive x->R, y->G bug would not even
                                  # need this to fail, but assert it anyway


def test_xy_white_point_is_near_white():
    r, g, b = hpc.xy_to_rgb(0.3127, 0.3290, 1.0)
    assert min(r, g, b) > 230


def test_xy_degenerate_y_is_black_not_a_crash():
    assert hpc.xy_to_rgb(0.5, 0.0) == (0, 0, 0)


def test_held_hex_for_look_off_is_black():
    assert hpc.held_hex_for_look(("living", "off", None, None, 0.0)) == "#000000"


def test_held_hex_for_look_show_is_not_held():
    assert hpc.held_hex_for_look(("*", "show", None, None, 100.0)) is None


def test_held_hex_for_look_none_is_not_held():
    assert hpc.held_hex_for_look(None) is None


def test_held_hex_for_look_mirek_scales_by_brightness():
    full = hpc.held_hex_for_look(("dining-hues", "hold", 477, None, 100.0))
    half = hpc.held_hex_for_look(("dining-hues", "hold", 477, None, 50.0))
    assert full == hpc.rgb_to_hex(hpc.kelvin_to_rgb(1_000_000 / 477))
    full_rgb = hpc.hex_to_rgb(full)
    half_rgb = hpc.hex_to_rgb(half)
    assert half_rgb[0] < full_rgb[0]
    assert half_rgb == hpc.scale_rgb(full_rgb, 0.5)


def test_held_hex_for_look_authored_colour_is_used_as_is():
    look = ("living", "hold", None, "#ff9d31", 29.0)
    assert hpc.held_hex_for_look(look) == hpc.rgb_to_hex(
        hpc.scale_rgb(hpc.hex_to_rgb("#ff9d31"), 0.29))


def test_scale_and_hex_roundtrip():
    assert hpc.hex_to_rgb(hpc.rgb_to_hex((10, 20, 30))) == (10, 20, 30)
    assert hpc.scale_rgb((200, 100, 50), 1.0) == (200, 100, 50)
    assert hpc.scale_rgb((200, 100, 50), 0.0) == (0, 0, 0)
