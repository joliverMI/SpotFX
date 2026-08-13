"""SPECTRA's live light stack — the device layer + Stage-2 audio ingest hub
wiring that lets SPECTRA actually run the room, ALL behind the ownership
gate. With ownership at spot-effects (the shipped default) nothing here can
run: activate() demands an ActivationGrant, FxHost.start() re-demands it for
any non-dummy device, and the audio device opens only inside activate().
Nothing in main.py or spectra/app.py constructs this at import or startup —
the handover orchestrator (services/handover.py) is the only caller.

What activate() assembles, in order (deactivate() reverses it):
  1. FxHost on SPECTRA's OWN fx config dir (storage/spectra/fx-live — seeded
     from the live LedFX config by scripts/seed_spectra_fx_live.py on go-day;
     never the live LedFX ~/.ledfx). Real driver init happens here: Hue DTLS
     handshakes, DDP senders — which is why the quiesce step must already
     have stopped the old writer.
  2. The frame-freshness tap: a VIRTUAL_UPDATE listener stamping a monotonic
     time per virtual on every displayed frame. VirtualUpdateEvent is fired
     by the real render/write loop (fx/virtuals.py thread_function) after
     assemble+flush, so these stamps ARE per-virtual frame-flush freshness —
     the SPECTRA LIVENESS ENDPOINT CONTRACT's required signal, observed
     in-process from the real path.
  3. The audio ingest hub: one capture stream (fx.audio_ingest.
     LiveDeviceSource — the module's only hardware path, opened with
     allow_device=True here and nowhere else) fanned out to the hub-fed
     melbank (HubMelbankSource installed as host.audio, with the module
     class rebound so AudioReactiveEffect.activate's identity check adopts
     it instead of constructing a hardware-touching source), pumped by one
     asyncio task. Audio is NOT an exclusivity concern (the PipeWire monitor
     is multi-reader — merge-scout §4d) but it is still gated: dark SPECTRA
     must touch no input.

wait_fresh() is the activation verification: the same freshness signal the
liveness endpoint serves, required to go green before the handover commits.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from fx import light_ownership
from fx.audio_ingest import AudioIngestHub, HubMelbankSource, LiveDeviceSource
from fx.events import Event
from fx.host import FxHost

logger = logging.getLogger(__name__)

STALE_AFTER_S = 2.0     # a live render loop flushes every ~16-40 ms; 2 s of
                        # silence on an active virtual is a dead write path
AUDIO_PUMP_SLEEP_S = 0.01


class FrameFreshness:
    """Per-virtual monotonic stamp of the last displayed frame, fed by the
    render loop's own VIRTUAL_UPDATE events."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.marks: dict[str, float] = {}
        self._remove: Optional[Callable] = None

    def attach(self, host: FxHost) -> None:
        def on_update(event) -> None:
            self.marks[event.virtual_id] = self._clock()

        self._remove = host.events.add_listener(on_update, Event.VIRTUAL_UPDATE)

    def detach(self) -> None:
        if callable(self._remove):
            self._remove()
        self._remove = None

    def ages(self) -> dict[str, float]:
        now = self._clock()
        return {vid: now - mark for vid, mark in self.marks.items()}


class LiveLights:
    """The one live stack. A module-level instance (`live`) is shared by the
    handover orchestrator and the liveness endpoint; `active` False means
    SPECTRA is provably dark — no host, no device, no audio."""

    def __init__(self):
        self.host: Optional[FxHost] = None
        self.freshness = FrameFreshness()
        self.hub: Optional[AudioIngestHub] = None
        self.audio_source = None
        self.melbank: Optional[HubMelbankSource] = None
        self._melbank_sub = None
        self._pump_task: Optional[asyncio.Task] = None
        self._prev_audio_cls = None

    @property
    def active(self) -> bool:
        return self.host is not None

    async def activate(
        self,
        grant: light_ownership.ActivationGrant,
        config_dir: str,
        *,
        open_audio: bool = True,
        audio_source_factory: Optional[Callable[[AudioIngestHub], object]] = None,
    ) -> None:
        """Bring the stack up under `grant`. Raises OwnershipError before
        touching anything if the grant is stale; on any later failure the
        caller (the orchestrator) runs deactivate() — every step here is
        reversible and deactivate() tolerates partial assembly."""
        light_ownership.require_grant(grant, light_ownership.SPECTRA,
                                      detail="live stack activate")
        if self.active:
            raise RuntimeError("live stack already active")

        host = FxHost(config_dir, live_grant=grant)
        self.host = host          # set before start() so a failed start still
        await host.start()        # deactivates through us
        self.freshness.attach(host)

        if open_audio:
            self.hub = AudioIngestHub()
            self._install_hub_melbank(host)
            factory = audio_source_factory or (
                lambda hub: LiveDeviceSource(hub))
            self.audio_source = factory(self.hub)
            self.audio_source.open(allow_device=True)
            self._pump_task = asyncio.create_task(
                self._pump_audio(), name="spectra-audio-pump")
        logger.warning("SPECTRA live stack ACTIVE: %d devices, %d virtuals, "
                       "audio=%s", len(list(host.devices.values())),
                       len(list(host.virtuals.values())),
                       "open" if open_audio else "off")

    async def deactivate(self) -> None:
        """Tear the stack down in reverse — audio first (stop feeding), then
        the host (joins render threads, deactivates devices: the Hue driver
        releases its DTLS session, DDP senders stop). Safe on partial
        assembly; idempotent."""
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            self._pump_task = None
        if self.audio_source is not None:
            try:
                self.audio_source.close()
            except Exception:
                logger.exception("live stack: audio source close failed")
            self.audio_source = None
        self._uninstall_hub_melbank()
        self.hub = None
        self.freshness.detach()
        self.freshness.marks.clear()
        if self.host is not None:
            host, self.host = self.host, None
            await host.shutdown()
        logger.warning("SPECTRA live stack deactivated — dark")

    # ── verification (the same signal the liveness endpoint serves) ─────────

    def active_virtual_ids(self) -> list[str]:
        if self.host is None:
            return []
        return [v.id for v in self.host.virtuals.values() if v.active]

    def fresh(self, stale_after_s: float = STALE_AFTER_S) -> bool:
        """Every ACTIVE virtual flushed a frame within stale_after_s. Vacuously
        true with no active virtuals (nothing claims to be driving lights)."""
        ages = self.freshness.ages()
        return all(ages.get(vid, float("inf")) <= stale_after_s
                   for vid in self.active_virtual_ids())

    async def wait_fresh(self, timeout_s: float = 10.0,
                         stale_after_s: float = STALE_AFTER_S) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            active = self.active_virtual_ids()
            ages = self.freshness.ages()
            if all(vid in ages and ages[vid] <= stale_after_s
                   for vid in active):
                return True
            await asyncio.sleep(0.05)
        return False

    def liveness(self, stale_after_s: float = STALE_AFTER_S) -> dict:
        """Per-virtual frame-flush freshness for the liveness endpoint."""
        if self.host is None:
            return {}
        ages = self.freshness.ages()
        out = {}
        for virtual in self.host.virtuals.values():
            age = ages.get(virtual.id)
            out[virtual.id] = {
                "active": bool(virtual.active),
                "last_flush_age_s": round(age, 3) if age is not None else None,
                "fresh": age is not None and age <= stale_after_s,
            }
        return out

    # ── audio internals ─────────────────────────────────────────────────────

    def _install_hub_melbank(self, host: FxHost) -> None:
        """Install the hub-fed melbank as the host's audio source AND rebind
        the module class AudioReactiveEffect.activate identity-checks
        (fx/effects/audio.py:1572), so effect activation adopts the hub
        source instead of constructing the hardware-enumerating one — the
        same mechanism headless.silence_audio() uses."""
        from fx.effects import audio as fx_audio
        self._prev_audio_cls = fx_audio.AudioAnalysisSource
        fx_audio.AudioAnalysisSource = HubMelbankSource
        self.melbank = HubMelbankSource(host)
        self._melbank_sub = self.hub.subscribe("spectra-melbank")
        host.audio = self.melbank

    def _uninstall_hub_melbank(self) -> None:
        if self._prev_audio_cls is not None:
            from fx.effects import audio as fx_audio
            fx_audio.AudioAnalysisSource = self._prev_audio_cls
            self._prev_audio_cls = None
        if self._melbank_sub is not None and self.hub is not None:
            self.hub.unsubscribe(self._melbank_sub)
        self._melbank_sub = None
        self.melbank = None

    async def _pump_audio(self) -> None:
        """Drain the melbank's hub subscription on the loop — the single
        ingest() caller the HubMelbankSource contract requires."""
        while True:
            for _ts, block in self._melbank_sub.drain():
                self.melbank.ingest(block)
            await asyncio.sleep(AUDIO_PUMP_SLEEP_S)


live = LiveLights()
