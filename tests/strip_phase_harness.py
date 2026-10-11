"""A headless room for the strip phase layer (fx/effects/strip_phase.py).

The real render pipeline (fx.headless, dummy devices, a fake clock — also
behind time.time_ns, which Melt's own clock reads) driven by the PRODUCTION
ResponseEngine on the FacadeExecutor: every phase arm, every flare and every
punch reaches the effects exactly the way they reach his room. Audio is a
deterministic stand-in fed straight to each effect's audio callback (rising
energy at a moderate level — a strip already at full colour has no headroom
for a hue-kept gain — and a beat every 15 frames), and numpy's RNG is
seeded, so two runs of the same script render the same bytes.

Used by tests/test_strip_phase.py and scripts/check_strip_phase.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from random import Random
from types import SimpleNamespace

import numpy as np

from fx import facade, headless

FPS = 60
DT = 1.0 / FPS
STRIP_PX = 560
PALETTE = "linear-gradient(90deg, #ff2000 0%, #ff00a0 50%, #2040ff 100%)"


class _AudioFrame:
    """One deterministic audio frame: lows rise and fall, a beat every 15."""

    def __init__(self, i: int):
        self.i = i

    def lows_power(self, filtered: bool = True) -> float:
        return 0.18 + 0.12 * np.sin(self.i / 9.0)

    # the other bands a particle strip reads (the Black Hole strip's band
    # colouring and its frequency_range choice) — the same gentle swell
    def beat_power(self, filtered: bool = True) -> float:
        return self.lows_power(filtered)

    def bass_power(self, filtered: bool = True) -> float:
        return self.lows_power(filtered)

    def mids_power(self, filtered: bool = True) -> float:
        return 0.12 + 0.08 * np.sin(self.i / 7.0)

    def high_power(self, filtered: bool = True) -> float:
        return 0.08 + 0.05 * np.sin(self.i / 5.0)

    def onset(self) -> bool:
        return self.i % 15 == 0

    def bpm_beat_now(self) -> bool:
        return self.i % 15 == 0


def _config(config_dir: str, shapes: dict) -> None:
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    devices = [{"id": f"{vid}-dev", "type": "dummy",
                "config": {"name": f"{vid}-dev", "pixel_count": n}}
               for vid, (n, _rows) in shapes.items()]
    virtuals = [{"id": vid, "is_device": False, "auto_generated": False,
                 "config": {"name": vid, "mapping": "span", "rows": rows},
                 "segments": [[f"{vid}-dev", 0, n - 1, False]]}
                for vid, (n, rows) in shapes.items()]
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


def scene_for(entries: dict, kinds=(), bands=None):
    """A SceneV2 whose devices are `entries` ({vid: effect_type}), with the
    given flare kinds attached to one 0..1 "flare" band (or `bands`:
    {class: {kind name: scale}})."""
    from spectra.models.scene import (FlareBand, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = list(kinds)
    responses = {}
    bands = bands if bands is not None else (
        {"flare": {k.name: 1.0 for k in kinds}} if kinds else {})
    for cls, attached in bands.items():
        responses[cls] = ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds=dict(attached))])
    return SceneV2(
        name="Strip phase room",
        devices=[SceneDeviceConfig(target_kind="virtual", target=vid,
                                   effect_type=et)
                 for vid, et in entries.items()],
        flare_kinds=kinds, responses=responses)


class Room:
    """`effects`: {vid: (effect_type, pixel_count, rows, config)}."""

    def __init__(self, tmp_dir: str, effects: dict, *, strength: float = 1.0,
                 lull_dark_max_s: float = 3.0, layer: bool = True,
                 scene=None, flare_blocked=frozenset(), house_reason=None):
        self.tmp_dir = tmp_dir
        self.spec = effects
        self.strength = strength
        self.lull_dark_max_s = lull_dark_max_s
        self.layer = layer
        self.scene = scene
        self.flare_blocked = frozenset(flare_blocked)
        self.house_reason = house_reason
        self.frames: dict[str, list[np.ndarray]] = {v: [] for v in effects}
        self.i = 0

    def room_controls(self):
        from spectra.services import room_controls as rc
        return rc.RoomControlState(strip_phase_strength=self.strength,
                                   lull_dark_max_s=self.lull_dark_max_s)

    async def __aenter__(self):
        from fx.host import FxHost
        from spectra.services import color_journey as cj
        from spectra.services import scene_response
        from spectra.services.drift_conductor import DriftConductor
        from spectra.services.fx_executor import FacadeExecutor
        from spectra.services.scene_response import ResponseEngine

        np.random.seed(7)
        config_dir = os.path.join(self.tmp_dir, "fx-room")
        _config(config_dir, {v: (n, rows) for v, (_et, n, rows, _c)
                             in self.spec.items()})
        headless.silence_audio()
        self.host = FxHost(config_dir)
        await self.host.start()
        self.host.audio = headless.SyntheticAudioSource()
        facade.set_host(self.host)
        self._clock_cm = headless.fake_clock()
        self.clock = self._clock_cm.__enter__()
        self._real_ns = time.time_ns
        time.time_ns = lambda: int(self.clock.now * 1e9)
        self._real_house = scene_response._house_owns_the_look
        scene_response._house_owns_the_look = lambda: self.house_reason
        self.virtuals = {v: self.host.virtuals.get(v) for v in self.spec}
        self.effects = {}
        for vid, (et, n, _rows, cfg) in self.spec.items():
            eff = headless.attach_effect(self.host, self.virtuals[vid], et,
                                         dict(cfg))
            if not self.layer:
                eff._strip_phase = False   # the effect exactly as before
            if hasattr(eff, "melbank"):
                eff.melbank = (lambda filtered=True, size=None, _n=n:
                               0.2 + 0.2 * np.sin(np.linspace(0, 6, size or _n)
                                                  + self.i / 7.0))
            self.effects[vid] = eff
        room = [cj.RoomColorState()]
        self.executor = FacadeExecutor(clock=lambda: self.clock.now,
                                       room_controls_load=self.room_controls)
        self.conductor = DriftConductor(
            executor=self.executor, clock=lambda: self.clock.now,
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            room_load=lambda: room[0],
            room_save=lambda st: room.__setitem__(0, st),
            set_cards=lambda: [], gradient_profiles=lambda: {},
            room_controls=self.room_controls, rng=Random(3))
        self.responder = ResponseEngine(
            conductor=self.conductor, executor=self.executor, rng=Random(5),
            clock=lambda: self.clock.now, curve_profiles=lambda: {},
            room_load=lambda: room[0],
            room_save=lambda st: room.__setitem__(0, st),
            room_controls=self.room_controls,
            flare_blocked=lambda: self.flare_blocked)
        scene = self.scene or scene_for(
            {vid: et for vid, (et, *_r) in self.spec.items()})
        self.conductor.on_scene_fire(scene, [
            {"virtual_id": vid, "effect_type": et, "config": dict(cfg),
             "entry_id": "", "color_mode": "set"}
            for vid, (et, _n, _rows, cfg) in self.spec.items()])
        return self

    async def __aexit__(self, *exc):
        from spectra.services import scene_response
        scene_response._house_owns_the_look = self._real_house
        time.time_ns = self._real_ns
        self._clock_cm.__exit__(None, None, None)
        facade.set_host(None)
        await self.host.shutdown()

    def step(self, n: int = 1):
        for _ in range(n):
            self.clock.advance(DT)
            self.i += 1
            audio = _AudioFrame(self.i)
            for vid, v in self.virtuals.items():
                eff = self.effects[vid]
                if type(eff)._strip_phase and hasattr(eff, "audio_data_updated"):
                    with eff.lock:
                        eff.audio_data_updated(audio)
                f = v.assemble_frame()
                if f is not None:
                    v.flush(f)
                    self.frames[vid].append(
                        np.array(f, dtype=np.float64, copy=True))

    async def phase(self, event_class: str, gap_ms=None, intensity=0.7):
        return await self.responder.on_event(event_class, intensity,
                                             gap_ms=gap_ms)

    async def flare(self, intensity: float = 0.8):
        return await self.responder.on_event("flare", intensity)


def run(coro):
    return asyncio.run(coro)


def lum(frame: np.ndarray) -> float:
    """Mean perceived luminance of a frame, 0..1."""
    f = np.clip(np.asarray(frame, dtype=float), 0, 255) / 255.0
    return float((0.2126 * f[:, 0] + 0.7152 * f[:, 1]
                  + 0.0722 * f[:, 2]).mean())


def whiter_than_set(frame: np.ndarray, palette: np.ndarray,
                    tol: float = 0.02) -> int:
    """How many lit pixels of `frame` are whiter (a larger grey share,
    min/max channel) than the set's own colour at their hue — measured
    against the palette with NO code from the layer under test: for each
    pixel, the most grey any palette colour within 3 degrees of its hue
    carries (a hue the palette never reaches: its nearest palette hue)."""
    import colorsys
    pal = np.asarray(palette, dtype=float)
    ph, pg = [], []
    for r, g, b in pal:
        mx = max(r, g, b)
        if mx <= 1.0:
            continue
        h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        ph.append(h)
        pg.append(1.0 - s)
    ph, pg = np.array(ph), np.array(pg)
    count = 0
    for r, g, b in np.asarray(frame, dtype=float):
        mx = max(r, g, b)
        if mx <= 2.0:
            continue
        h, s, _v = colorsys.rgb_to_hsv(r / mx, g / mx, b / mx)
        if s <= 1e-6 and pg.max() < 1.0 - tol:
            count += 1
            continue
        dist = np.minimum(np.abs(ph - h), 1.0 - np.abs(ph - h))
        near = pg[dist <= 3.0 / 360.0]
        allow = near.max() if near.size else pg[int(np.argmin(dist))]
        if (1.0 - s) > allow + tol:
            count += 1
    return count


def palette_of(effect, n: int = STRIP_PX) -> np.ndarray:
    return np.asarray(effect.get_gradient_color_vectorized1d(
        np.linspace(0.0, 1.0, n)), dtype=float)


__all__ = ["Room", "run", "lum", "whiter_than_set", "palette_of",
           "scene_for", "FPS", "DT", "STRIP_PX", "PALETTE", "SimpleNamespace"]
