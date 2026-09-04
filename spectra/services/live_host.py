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
DEVICE_VERIFY_TIMEOUT_S = 3.0   # per-device json/info read for the live-flag check
DEVICE_LIVE_DEADLINE_S = 25.0  # shared poll-until-live deadline: a real
                                # take-back's WLEDs start receiving realtime
                                # SLOWLY and in VARYING ORDER (first live
                                # flags observed 6.2-6.4s after activation,
                                # different subsets rise first on different
                                # attempts) — a one-shot snapshot races the
                                # ramp and nondeterministically names
                                # whichever devices hadn't come up YET
DEVICE_POLL_INTERVAL_S = 0.5


def _config_expected_active_ids(config: dict) -> set[str]:
    """Every virtual id the persisted fx-live config declares should be
    running an effect: an "effect" key present and not explicitly paused
    via "active": false. This is the ground truth
    fx.virtuals.Virtuals.create_from_config is SUPPOSED to realize — but a
    per-virtual segment-schema or effect-schema restore failure there is
    only ever a logged warning, never raised, and a device load failure in
    fx.devices.Devices.create_from_config is the same shape. Nothing
    upstream of this module ever compared "what the config wanted" against
    "what actually came up" — exactly how the crystal darkfault's partial
    activation reported success (data/spectra-crystal-darkfault/,
    2026-08-13): the darkened virtual was simply excluded from the OLD
    freshness check (fresh() below), which only ever looks at whatever
    ended up `.active`, not at what was supposed to be."""
    expected: set[str] = set()
    for virtual_cfg in config.get("virtuals") or []:
        vid = virtual_cfg.get("id")
        if not vid or "effect" not in virtual_cfg:
            continue
        if virtual_cfg.get("active") is False:
            continue
        expected.add(vid)
    return expected


def _restrict_to_genuinely_driven(declared: set[str]) -> set[str]:
    """Intersect the config-declared active set with the room's genuinely
    driven virtuals (spectra/services/room_topology.py) — the
    "unfalsifiable gate" fix (report gate, 2026-08-14): fx-live/config.json
    inherits the old LedFX world's dynamic tricks (mask/foreground/
    background layers, gap-dummy placeholders, a full-span "crystal"
    duplicate, contextual rooms SPECTRA's scene engine never addresses), so
    "declared active" alone can refuse forever on layers that were never
    supposed to rise. Falls back to the raw declared set (unchanged
    behaviour) when no ground truth is available — an absent ground truth
    must never make verification vacuously pass on an EMPTY expected set."""
    from spectra.services.room_topology import genuinely_driven_virtual_ids

    driven = genuinely_driven_virtual_ids()
    if not driven:
        return declared
    return declared & driven


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
        self.expected_active_ids: set[str] = set()
        #: Virtual ids the LAST activation brought up black instead of
        #: restoring their stored effect — empty on every ordinary
        #: activation, populated only by a quiet take.
        self.blacked_out: list[str] = []

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
        quiet: bool = False,
    ) -> None:
        """Bring the stack up under `grant`. Raises OwnershipError before
        touching anything if the grant is stale; on any later failure the
        caller (the orchestrator) runs deactivate() — every step here is
        reversible and deactivate() tolerates partial assembly.

        `quiet` is THE QUIET TAKE (spectra/services/night_take.py): every
        virtual comes up driving BLACK rather than its stored effect, so the
        stack is fully alive — rendering, flushing, freshness-stamped, ready
        for a capture run's own writes through `fx_seam` — while emitting
        nothing. Everything else about the assembly is identical, which is
        why the activation gate that verifies a take-back can verify this
        one unchanged."""
        light_ownership.require_grant(grant, light_ownership.SPECTRA,
                                      detail="live stack activate")
        if self.active:
            raise RuntimeError("live stack already active")

        host = FxHost(config_dir, live_grant=grant)
        self.host = host          # set before start() so a failed start still
        self.expected_active_ids = _restrict_to_genuinely_driven(
            _config_expected_active_ids(host.config))
        await host.start(blackout=quiet)   # deactivates through us
        #: WHICH VIRTUALS CAME UP BLACK — for the take's own record. A quiet
        #: take that silently blacked nothing out (a config with no stored
        #: effects at all) is a fact worth being able to read afterwards.
        self.blacked_out = list(getattr(host.virtuals, "blacked_out", []))
        self.freshness.attach(host)
        # His per-device timing equalization: install the stored offsets
        # against the ids this host actually holds, so the anchoring
        # minimum is taken over the REAL room (see
        # spectra/services/device_settings.py). Never fatal — a stack that
        # came up must not be refused over a settings file.
        try:
            from spectra.services import device_settings
            device_settings.push_offsets([d.id for d in host.devices.values()])
        except Exception:
            logger.exception("live stack: per-device timing offsets not applied")

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
        self.expected_active_ids = set()
        # Nothing is rendering any more; a stale delay map must not survive
        # into whatever comes up next (a re-activation re-pushes above).
        from fx import device_timing
        device_timing.clear()
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

    def activation_gaps(self, stale_after_s: float = STALE_AFTER_S) -> dict[str, str]:
        """Every config-declared virtual (expected_active_ids) that is NOT
        actually up: missing from the live host, not marked active, or not
        flushing fresh frames. Empty means the config's declared set was
        fully realized. This is the check fresh()/wait_fresh() cannot make:
        a virtual absent from active_virtual_ids() is silently EXCLUDED
        from those (vacuously true) — exactly how the crystal darkfault's
        partial activation went unnoticed. A non-empty return is a LOUD
        failure for the caller to raise, never a success."""
        if self.host is None:
            return {vid: "live stack not active"
                   for vid in self.expected_active_ids}
        ages = self.freshness.ages()
        gaps: dict[str, str] = {}
        for vid in self.expected_active_ids:
            virtual = self.host.virtuals.get(vid)
            if virtual is None:
                gaps[vid] = ("missing from the live host — device, segment, "
                             "or effect restore failed silently at config load")
                continue
            if not virtual.active:
                # Say WHY, from what fx itself recorded at config load
                # (fx/virtuals.py's restore audit, VENDOR.md #29), rather
                # than guessing "restore failed" — the load-order eviction
                # this reason used to misdescribe is a restore that
                # SUCCEEDED and was undone afterwards by a virtual further
                # down the config.
                recorded = getattr(
                    self.host.virtuals, "restore_failures", {}
                ).get(vid)
                if recorded:
                    gaps[vid] = f"not active — {recorded}"
                elif virtual.active_effect is None:
                    gaps[vid] = "not active — no effect instance on the virtual"
                else:
                    gaps[vid] = (
                        f"not active — holds effect "
                        f"'{virtual.active_effect.type}' but runs no render "
                        f"thread, so writes to it land on nothing"
                    )
                continue
            age = ages.get(vid)
            if age is None or age > stale_after_s:
                gaps[vid] = f"not flushing frames (last_flush_age_s={age})"
        return gaps

    def describe_gaps(self, gaps: Optional[dict[str, str]] = None,
                      device_gaps: Optional[dict[str, str]] = None) -> str:
        """Named, human-readable detail for a failed verification — every
        light that could not rise, not just a bare bool. Built for the
        fresh-handover 'nameless refusal' fix (the resume path already
        named gaps via activation_gaps()/CRITICAL logging + the liveness
        endpoint; verify_active() had none of that — this is the shared
        formatter both paths can use). Defaults to the live instance's own
        current activation_gaps() when not given explicitly."""
        gaps = self.activation_gaps() if gaps is None else gaps
        device_gaps = device_gaps or {}
        parts = []
        if gaps:
            named = "; ".join(f"{vid}: {reason}"
                              for vid, reason in sorted(gaps.items()))
            parts.append(f"{len(gaps)} virtual(s) never came up ({named})")
        if device_gaps:
            named = "; ".join(f"{did}: {reason}"
                              for did, reason in sorted(device_gaps.items()))
            parts.append(f"{len(device_gaps)} device(s) unconfirmed ({named})")
        if not parts:
            parts.append("one or more active virtuals stopped flushing frames")
        return "; ".join(parts)

    async def wait_fully_active(self, timeout_s: float = 10.0,
                                stale_after_s: float = STALE_AFTER_S) -> dict[str, str]:
        """Poll until every config-declared virtual is active and fresh AND
        every already-active virtual stays fresh, or the timeout elapses.
        Returns the FINAL gap set — empty means fully realized, matching
        wait_fresh()'s bool contract but naming exactly what's still dark
        instead of silently excluding it."""
        deadline = time.monotonic() + timeout_s
        while True:
            gaps = self.activation_gaps(stale_after_s)
            if not gaps and self.fresh(stale_after_s):
                return {}
            if time.monotonic() >= deadline:
                if not gaps:
                    gaps = {"*": "one or more active virtuals stopped "
                                 "flushing frames"}
                return gaps
            await asyncio.sleep(0.05)

    def expected_device_ids(self) -> set[str]:
        """Every real (non-gap) device id backing an expected-active virtual
        — the set device_gaps() verifies and the activation report counts
        (spectra/services/activation_report.py). Empty when the stack is
        down."""
        if self.host is None:
            return set()
        device_ids: set[str] = set()
        for vid in self.expected_active_ids:
            virtual = self.host.virtuals.get(vid)
            if virtual is None:
                continue
            for seg in getattr(virtual, "_segments", None) or []:
                device_id = seg[0]
                if not device_id.startswith("gap-"):
                    device_ids.add(device_id)
        return device_ids

    async def probe_device_live(self, device_id: str,
                                timeout_s: float = DEVICE_VERIFY_TIMEOUT_S,
                                ) -> Optional[str]:
        """ONE read of one device's own live state — the reason it cannot be
        confirmed driving, or None when it can (or when there is nothing to
        confirm: a non-WLED device, or a WLED whose driver never got far
        enough to have a client). The single definition of "confirmed live"
        device_gaps() polls and the activation report's recheck re-asks
        later — never two."""
        if self.host is None:
            return None
        device = self.host.devices.get(device_id)
        if device is None:
            return None  # devices.create_from_config already warned
        if getattr(device, "type", None) != "wled" \
                or getattr(device, "wled", None) is None:
            return None  # not a WLED device, or not yet initialized
        try:
            wled_info = await asyncio.wait_for(
                device.wled.get_info(), timeout_s)
        except Exception as exc:
            return f"could not confirm live state: {exc!r}"
        if not wled_info.get("live"):
            return ("device reports live=false — not "
                    "receiving realtime data")
        return None

    async def probe_devices(self, device_ids, timeout_s: float = DEVICE_VERIFY_TIMEOUT_S,
                            ) -> dict[str, str]:
        """One pass over `device_ids` with probe_device_live(): every device
        that could NOT be confirmed, by reason. No polling — device_gaps()
        is the poll-until-deadline wrapper."""
        results = await asyncio.gather(
            *(self.probe_device_live(d, timeout_s) for d in device_ids))
        return {device_id: reason
                for device_id, reason in zip(device_ids, results)
                if reason is not None}

    async def device_gaps(self, timeout_s: float = DEVICE_VERIFY_TIMEOUT_S,
                          deadline_s: float = DEVICE_LIVE_DEADLINE_S,
                          poll_interval_s: float = DEVICE_POLL_INTERVAL_S,
                          ) -> dict[str, str]:
        """Device-level verification one layer deeper than our own frame
        stamps (report gate e3, folded in as first-class alongside the
        reconciler by owner order): frame freshness only proves OUR render
        loop pushed a frame, not that the physical device received it. For
        every real (non-dummy, non-gap) device backing an expected-active
        virtual, if it's WLED, read its OWN json/info and require
        live=true (WLED reports the realtime "live" flag only under
        json/info — json/state carries on/bri/seg but never "live").

        A real take-back's WLEDs rise SLOWLY and in VARYING ORDER (measured
        live: first live flags 6.2-6.4s after activation, different subsets
        first on different attempts, some past a 3s snapshot's window
        entirely) — so this POLLS each still-dark device on its own
        `timeout_s`-bounded read until it reports live=true or the shared
        `deadline_s` elapses, mirroring wait_fully_active()'s poll-until-
        deadline shape. Only a device STILL dark at the deadline becomes a
        gap. A device that never answers (unreachable) keeps being retried
        like any other unconfirmed device and, if still unreachable at the
        deadline, is named with the same could-not-confirm reason it always
        had — verified, never assumed. The per-device read itself is
        probe_device_live()."""
        if self.host is None:
            return {}
        device_ids = self.expected_device_ids()
        if not device_ids:
            return {}

        pending = sorted(device_ids)
        gaps: dict[str, str] = {}
        deadline = time.monotonic() + deadline_s
        while True:
            gaps = await self.probe_devices(pending, timeout_s)
            pending = sorted(gaps)
            if not pending or time.monotonic() >= deadline:
                return gaps
            await asyncio.sleep(poll_interval_s)

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
