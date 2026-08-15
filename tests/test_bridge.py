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
