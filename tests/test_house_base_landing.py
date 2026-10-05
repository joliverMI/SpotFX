"""HOUSE LIGHTING's base layer, measured AT THE TRANSPORT on the real render
pipeline (the rig of tests/test_device_output_landing.py: one virtual
spanning two dummy devices, the vendored singleColor effect, every frame
each device's real flush() is handed).

A base level that round-trips through a dict proves nothing about a light.
These prove, on the frames that reach the device:

  * a mode's level on ONE fixture of a shared virtual dims that fixture and
    leaves its neighbour exactly as the show renders it;
  * a Light Show Level on top multiplies (base × show), and End show fades
    back to the BASE — the mode's look — not an undimmed picture;
  * clearing the base hands the fixture back to the show untouched.
"""
from __future__ import annotations

from spectra.services import show_output
from tests.test_device_output_landing import D1, D2, _peak, _run_sync


def test_a_mode_level_dims_one_fixture_and_leaves_its_neighbour(tmp_path):
    def script(i, _e):
        if i == 10:
            show_output.set_base({D1: 0.25}, {})
    log = _run_sync(tmp_path, script, tag="base", color="#ff0000")
    assert _peak(log.frames[D1][5]) > 240
    assert 55 < _peak(log.frames[D1][-1]) < 72        # 255 × 0.25
    assert all(_peak(f) > 240 for f in log.frames[D2])


def test_a_show_level_multiplies_and_end_show_returns_to_the_mode(tmp_path):
    def script(i, _e):
        if i == 10:
            show_output.set_base({D1: 0.5}, {})
        if i == 30:
            show_output.add_level([D1], 0.5, until="released")
        if i == 60:
            show_output.release_all(fade_ms=0)
    log = _run_sync(tmp_path, script, tag="compose", color="#ff0000")
    assert 120 < _peak(log.frames[D1][20]) < 135      # base alone: half
    assert 60 < _peak(log.frames[D1][50]) < 68        # base × show: a quarter
    assert 120 < _peak(log.frames[D1][-1]) < 135      # End show → the mode, not 255


def test_a_mode_off_is_dark_and_clearing_hands_the_fixture_back(tmp_path):
    def script(i, _e):
        if i == 10:
            show_output.set_base({}, {D1: "dark"})
        if i == 40:
            show_output.set_base({}, {})
    log = _run_sync(tmp_path, script, tag="off", color="#ff0000")
    assert _peak(log.frames[D1][30]) == 0.0
    assert _peak(log.frames[D1][-1]) > 240
    assert all(_peak(f) > 240 for f in log.frames[D2])
