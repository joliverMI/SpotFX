"""SPECTRA's per-device settings store and the offset -> delay arithmetic.

The LIGHT-level proof lives in tests/test_device_timing_landing.py; this
covers the record's own shape (the clamp, the lazily-gained default, the
one-record write), and the translation his sign convention needs:
delay_i = offset_i - min_j(offset_j), never negative, and identity when
every device agrees.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from fx import device_timing
from spectra.models.device_settings import OFFSET_LIMIT_MS, DeviceSettings
from spectra.services import device_settings as store


# ── the record ──────────────────────────────────────────────────────────────

def test_the_default_record_is_zero_and_reads_as_default():
    rec = DeviceSettings()
    assert rec.timing_offset_ms == 0
    assert rec.is_default


def test_an_unknown_device_reads_as_the_default_record():
    """A device with no stored entry and a device stored at its defaults
    are the same thing at the lights — nothing had to be migrated for this
    feature to ship."""
    assert store.get("never-seen").timing_offset_ms == 0
    assert store.load_all() == {}


@pytest.mark.parametrize("value", [-OFFSET_LIMIT_MS - 1, OFFSET_LIMIT_MS + 1])
def test_an_out_of_range_offset_is_refused_not_silently_clamped(value):
    with pytest.raises(ValidationError):
        DeviceSettings(timing_offset_ms=value)


def test_saving_one_device_leaves_every_other_record_untouched():
    store.set_timing_offset_ms("a", -120)
    store.set_timing_offset_ms("b", 40)
    store.set_timing_offset_ms("a", -60)
    assert store.get("a").timing_offset_ms == -60
    assert store.get("b").timing_offset_ms == 40


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_all_equal_offsets_produce_no_delay_at_all():
    for value in (0, -250, 250):
        assert device_timing.apply_offsets({"a": value, "b": value, "c": value}) \
            == {"a": 0.0, "b": 0.0, "c": 0.0}
        assert device_timing.delays_ms() == {}


def test_negative_is_earlier_implemented_as_delay_for_everyone_else():
    """A fixture can only be made to WAIT: the device authored earliest is
    delayed by exactly nothing, and the rest are held back by the gap."""
    delays = device_timing.apply_offsets({"early": -100, "mid": 0, "late": 150})
    assert delays == {"early": 0.0, "mid": 0.1, "late": 0.25}
    assert min(delays.values()) == 0.0


def test_a_delay_is_never_negative_for_any_authored_set():
    for offsets in ({"a": -1000, "b": 1000}, {"a": 1000, "b": -1000},
                    {"a": 5}, {"a": -7, "b": -7, "c": -8}):
        assert all(d >= 0.0 for d in device_timing.apply_offsets(offsets).values())


def test_a_device_outside_the_pushed_set_takes_no_delay():
    """The anchoring minimum is taken over exactly the ids handed in — a
    device that is not part of the equalization is not delayed by it."""
    device_timing.apply_offsets({"a": -100, "b": 0})
    assert device_timing.delay_s("some-other-device") == 0.0


def test_resolve_offsets_fills_zero_for_every_unset_device():
    """What makes a single early device delay every OTHER REAL fixture,
    rather than delaying nothing: the unset devices participate at 0."""
    store.set_timing_offset_ms("a", -100)
    resolved = store.resolve_offsets(["a", "b", "c"])
    assert resolved == {"a": -100, "b": 0, "c": 0}
    assert store.push_offsets(["a", "b", "c"]) == {"a": 0.0, "b": 0.1, "c": 0.1}


def test_push_falls_back_to_the_stored_ids_when_the_stack_is_down():
    store.set_timing_offset_ms("a", -100)
    store.set_timing_offset_ms("b", 0)
    assert store.push_offsets() == {"a": 0.0, "b": 0.1}


def test_saving_pushes_the_new_offsets_without_a_restart():
    store.set_timing_offset_ms("a", 0)
    store.set_timing_offset_ms("b", 0)
    assert device_timing.delay_s("b") == 0.0
    store.set_timing_offset_ms("a", -300)
    assert device_timing.delay_s("a") == 0.0
    assert device_timing.delay_s("b") == pytest.approx(0.3)


def test_a_garbage_entry_is_ignored_rather_than_poisoning_the_room():
    delays = device_timing.apply_offsets({"a": None, "b": "nope", "c": 0, "d": 100})
    assert delays == {"c": 0.0, "d": 0.1}
