"""spectra/services/bridge.py — is_playing(), offline proof.

The single playback signal Ambient's music-precedence gate reads
(services/ambient_music_gate.py). No socket, no live process — direct
construction + handle_message() only, the same socket-free protocol seam
the module's own docstring describes.
"""
from __future__ import annotations

import asyncio

from spectra.services.bridge import SpotEffectsBridge


def _run(coro):
    return asyncio.run(coro)


def test_is_playing_none_when_no_signal_has_ever_arrived():
    """Fully unknown — a fresh bridge, no message ever received — must not
    be read as 'not playing' (the fail-safe direction the music-precedence
    gate relies on for its very first decision)."""
    bridge = SpotEffectsBridge()
    assert bridge.is_playing() is None


def test_is_playing_false_once_a_state_message_reports_no_track():
    """A real 'state' broadcast with no active session — nothing to play
    is not playing."""
    bridge = SpotEffectsBridge()
    _run(bridge.handle_message({"type": "state", "paused": False, "track": None}))
    assert bridge.is_playing() is False


def test_is_playing_reflects_the_broadcast_track():
    bridge = SpotEffectsBridge()
    _run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True, "progress_ms": 0},
    }))
    assert bridge.is_playing() is True

    _run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": False, "progress_ms": 12000},
    }))
    assert bridge.is_playing() is False, "a deliberate pause mid-song also reads as not playing"


def test_is_playing_survives_a_transient_disconnect():
    """A reconnect gap (connected flips False) must not erase the last
    reported state — is_playing() reads the same last-known signal every
    other feed on this class already trusts across a blip."""
    bridge = SpotEffectsBridge()
    _run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True, "progress_ms": 0},
    }))
    bridge.connected = False
    assert bridge.is_playing() is True


def test_device_name_is_none_with_no_track():
    """No signal yet, or a state message reporting no track — never a
    guessed empty string. The house music-device gate (spectra/services/
    house.py) treats this as 'not an allowed device'."""
    bridge = SpotEffectsBridge()
    assert bridge.device_name() is None
    _run(bridge.handle_message({"type": "state", "paused": False, "track": None}))
    assert bridge.device_name() is None


def test_device_name_reflects_the_broadcast_track():
    """The exact field api/spotify_client.py's own `device.name` read off
    Spotify's playback API lands on, broadcast as track.device_name —
    root's own on_target_device/spotify_device_names match against the
    identical field."""
    bridge = SpotEffectsBridge()
    _run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                 "progress_ms": 0, "device_name": "Serenity"},
    }))
    assert bridge.device_name() == "Serenity"

    _run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                 "progress_ms": 0, "device_name": "Javi's iPhone"},
    }))
    assert bridge.device_name() == "Javi's iPhone"


def test_device_name_empty_string_reads_as_none():
    """An empty device name (a track dict with no device_name key, or an
    empty string) is treated the same as 'unknown' — never a device that
    happens to be named ''."""
    bridge = SpotEffectsBridge()
    _run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True, "progress_ms": 0},
    }))
    assert bridge.device_name() is None
