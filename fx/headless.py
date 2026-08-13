"""Headless dummy-device test bed for the vendored render pipeline
(SpotFX-authored; report §4e).

Everything here is offline by construction: virtuals render onto the vendored
DummyDevice (fx/devices/dummy.py — flush is a no-op), no network I/O, and
`silence_audio()` guarantees PortAudio is never initialized — effects that
subscribe for audio get a synthetic source instead, and synthetic PCM buffers
can be pushed to their callbacks by hand.

Two driving modes:
  - Deterministic frame-stepping: `attach_effect()` + `render_frames()` call
    the real Virtual.assemble_frame()/flush() pipeline directly, one frame per
    call, WITHOUT the per-virtual render thread. Combine with `fake_clock()`
    (patches timeit.default_timer, the clock behind Effect.log_sec) for
    bit-reproducible runs.
  - Live mode: fire through fx/facade.py (or ledfx_client with
    settings.fx_in_process on); Virtual.set_effect spawns the real render
    thread, frames flow to the dummy device at its refresh rate. That is the
    thread-per-virtual behavior Stage 1 measures.

Frame capture: `FrameTap` collects VirtualUpdateEvent frames as numpy arrays;
`save_png()` writes any captured frame as an image for eyeballing/archiving.
"""
from __future__ import annotations

import contextlib
import json
import os
import timeit as _timeit_module
from typing import Callable, Iterator, Optional

import numpy as np
from PIL import Image

from fx.events import Event
from fx.host import FxHost

DEFAULT_DEVICE_ID = "headless-dummy"
DEFAULT_VIRTUAL_ID = "headless-dummy"


def write_headless_config(
    config_dir: str,
    *,
    pixel_count: int = 64,
    rows: int = 8,
    device_id: str = DEFAULT_DEVICE_ID,
    initial_effect: Optional[dict] = None,
) -> None:
    """Write an fx config.json describing one dummy device with a matching
    matrix virtual, the way LedFX persists a device+virtual pair. The virtual
    id equals the device id (is_device convention), transitions kept at the
    LedFX default (0.4s Add) so crossfade code paths stay exercised.

    initial_effect ({"type": ..., "config": {...}}) restores an effect at
    host start — the production reality every SpotFX-driven virtual lives in
    (the fork's effects PUT 400s on a virtual with no active effect). Note it
    also ACTIVATES the virtual at start, i.e. spawns its render thread."""
    os.makedirs(config_dir, exist_ok=True)
    virtual_entry = {
        "id": device_id,
        "is_device": device_id,
        "auto_generated": False,
        "config": {
            "name": device_id,
            "mapping": "span",
            "rows": rows,
        },
        "segments": [[device_id, 0, pixel_count - 1, False]],
    }
    if initial_effect is not None:
        virtual_entry["effect"] = initial_effect
    config = {
        "configuration_version": _current_config_version(),
        "devices": [
            {
                "id": device_id,
                "type": "dummy",
                "config": {"name": device_id, "pixel_count": pixel_count},
            }
        ],
        "virtuals": [virtual_entry],
    }
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(config, f)


def _current_config_version() -> str:
    from fx.consts import CONFIGURATION_VERSION

    return CONFIGURATION_VERSION


async def start_headless_host(config_dir: str, **config_kwargs) -> FxHost:
    """write_headless_config + FxHost start, with audio silenced."""
    write_headless_config(config_dir, **config_kwargs)
    silence_audio()
    host = FxHost(config_dir)
    await host.start()
    # Pre-install the synthetic source so AudioReactiveEffect.activate's
    # class-identity check finds a matching instance and never constructs one.
    host.audio = SyntheticAudioSource()
    return host


# ── Audio: never touch hardware ──────────────────────────────────────────────

class SyntheticAudioSource:
    """Stands in for AudioAnalysisSource in headless runs. Implements the
    surface AudioReactiveEffect and the vendored effects actually use outside
    the data callback: subscribe/unsubscribe, volume(), _config, melbanks.
    Audio data never flows unless a test pushes it via push_callbacks()."""

    melbanks = None

    def __init__(self, ledfx=None, config=None):
        # Signature-compatible with AudioAnalysisSource(ledfx, config) so
        # AudioReactiveEffect.activate can construct it after silence_audio().
        self._callbacks: list[Callable] = []
        self._config = {"min_volume": 0.2, "mic_rate": 44100,
                        "sample_rate": 60, "fft_size": 4096, "delay_ms": 0}
        self._volume = 0.0

    def subscribe(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def volume(self, filtered: bool = True) -> float:
        return self._volume

    def push_callbacks(self) -> None:
        """Invoke every subscribed effect callback once — the synthetic
        equivalent of one audio frame arriving. Tests that feed synthetic
        buffers set state on this source first (e.g. _volume)."""
        for callback in list(self._callbacks):
            callback()


def silence_audio() -> SyntheticAudioSource:
    """Replace the AudioAnalysisSource class referenced by
    AudioReactiveEffect.activate with SyntheticAudioSource, so effect
    activation can never construct the real source (whose init enumerates
    host audio hardware through PortAudio). Idempotent; process-wide for the
    test run."""
    from fx.effects import audio as fx_audio

    if fx_audio.AudioAnalysisSource is not SyntheticAudioSource:
        fx_audio._RealAudioAnalysisSource = fx_audio.AudioAnalysisSource
        fx_audio.AudioAnalysisSource = SyntheticAudioSource
    return SyntheticAudioSource()


# ── Deterministic clock ───────────────────────────────────────────────────────

class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@contextlib.contextmanager
def fake_clock(start: float = 1000.0) -> Iterator[FakeClock]:
    """Patch timeit.default_timer — the clock behind Effect.log_sec, so
    self.now / self.passed inside every effect — with a manually advanced
    counter. Restores the real clock on exit."""
    clock = FakeClock(start)
    real = _timeit_module.default_timer
    _timeit_module.default_timer = clock
    try:
        yield clock
    finally:
        _timeit_module.default_timer = real


# ── Deterministic frame-stepping (no render thread) ─────────────────────────

def attach_effect(host: FxHost, virtual, effect_type: str, config: dict):
    """Create an effect and attach it to the virtual WITHOUT spawning the
    render thread (Virtual.set_effect auto-activates; this is the harness
    path for frame-stepped runs). Also activates the underlying devices so
    flush() has somewhere to scatter."""
    effect = host.effects.create(ledfx=host, type=effect_type, config=config)
    effect.activate(virtual)
    virtual._active_effect = effect
    virtual.transitions = type(virtual.transitions)(virtual.effective_pixel_count)
    virtual.frame_transitions = virtual.transitions[
        virtual._config["transition_mode"]
    ]
    # Mark active and register segments on the devices (what activate() does
    # minus the thread) so flush() scatters into the dummy device's buffer.
    virtual.activate_segments(virtual._segments)
    virtual._active = True
    return effect


def render_frames(
    virtual,
    n_frames: int,
    *,
    clock: Optional[FakeClock] = None,
    dt: float = 1 / 60,
) -> list[np.ndarray]:
    """Step the real assemble/flush pipeline n_frames times, returning a copy
    of each assembled frame (pixel_count, 3). With a FakeClock, advances it dt
    per frame so effect time marches identically across runs."""
    frames = []
    for _ in range(n_frames):
        if clock is not None:
            clock.advance(dt)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)
            frames.append(np.array(frame, copy=True))
    return frames


# ── Capture ───────────────────────────────────────────────────────────────────

class FrameTap:
    """Collects frames a virtual pushes through VirtualUpdateEvent — the
    signal the live render thread emits once per displayed frame."""

    def __init__(self, host: FxHost, virtual_id: str):
        self.frames: list[np.ndarray] = []
        self._virtual_id = virtual_id

        def on_update(event) -> None:
            if event.virtual_id == self._virtual_id:
                self.frames.append(np.array(event.pixels, copy=True))

        self._remove = host.events.add_listener(
            on_update, Event.VIRTUAL_UPDATE
        )

    def close(self) -> None:
        if callable(self._remove):
            self._remove()


def save_png(frame: np.ndarray, path: str, *, rows: int = 1) -> None:
    """Write one captured frame as a PNG (matrix frames reshaped to
    rows × cols)."""
    pixels = np.clip(np.asarray(frame, dtype=float), 0, 255).astype(np.uint8)
    cols = len(pixels) // rows
    image = Image.fromarray(pixels[: rows * cols].reshape(rows, cols, 3), "RGB")
    image.save(path)
