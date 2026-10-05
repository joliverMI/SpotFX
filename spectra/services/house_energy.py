"""HOUSE LIGHTING phase 3 — ENERGY AND NETWORK while a mode drives the room
(plan: /home/javi/fleet-spotfx/data/standard-lighting-plan/report.md §6;
his ask, 2026-10-04: "Ensure we aren't going to waste a bunch of energy by
constantly streaming to all these devices").

MEASURED BEFORE ANY OF THIS (the plan's §6.1, his Living Room, no music,
Hue held by Ambient): SPECTRA holding the room cost 44% of one CPU core and
~345-368 UDP packets/s, against 2-4% and 11/s released. Render work was only
~9% of a core; the rest was audio analysis, the transports and the per-frame
plumbing. The target for this phase: Standard at <= 15% of a core and ~170
packets/s.

═══ WHAT THIS PHASE DOES, AND WHERE EACH PART LIVES ═══

  RESTING CAPS        a calm mode renders slower: settings.energy.
                      resting_fps (Matrix 20, Strips 20, Singles 10) as the
                      default under every mode's own fixture settings —
                      house.py `resting_caps()`, pushed with the mode's caps
                      through fx/device_rate.py (VENDOR #43, only ever lowers:
                      the crystal's 30 is a ceiling)
  PARKING             a virtual none of whose fixtures takes its frames
                      renders at 2 frames/s — his `radial-dummy` (a dummy
                      device: no light at all), a strip lent to Hyperion, a
                      fixture switched off or unpowered, a Hue area held
                      over the bridge. Decided LIVE per frame on the render
                      thread (fx/device_rate.py PARKING, VENDOR #47); this
                      module only switches it on while a mode drives
  SEND ON CHANGE      a fixture whose picture is not moving (a Light Show
                      Steady/Freeze/Dark hold, a dark "off" fading out, a
                      static look) is sent only a keep-alive every
                      settings.energy.keepalive_s (fx/device_output.py, VENDOR
                      #48); this module switches it on while a mode drives
  OFF = NO STREAM     a mode's `off` on a WLED: house.py fades it to black,
                      house_fixtures.py then withholds it and switches it off
  AUDIO PAUSE         after settings.energy.audio_pause_after_s (120 s) with
                      no music, SPECTRA stops listening to the room: the
                      capture stream is closed and its pump stopped
                      (live_host.pause_audio). Listening resumes the moment
                      music plays
  MAINS OFF           Home Assistant reports the kitchen sconces' mains off
                      (PUT /api/house/mains): no stream, and no search for
                      them at all until it reports the mains on —
                      house_fixtures.py and activation_report.py

═══ THE GATE ═══

Everything here acts only while `house.layer_active()` — a mode is set,
SPECTRA holds the room, nothing has it on standby. Otherwise parking and
send-on-change are switched OFF and the audio is listening: with no mode set
(the shipped state) the room renders and listens exactly as before, and a
preview, a camera run or a night run gets every frame and the full rate.

═══ WHY PAUSING THE AUDIO DOES NOT CHANGE THE PICTURE ═══

Effects animate on their own clocks (Fish, Melt, Noise, a breathing
gradient, radial's `base_rotation`); their AUDIO inputs are smoothed filters
that decay to the silence state within seconds of the music stopping. The
pause waits two minutes of CONFIRMED quiet (`playing is False` from the
bridge, continuously), so what each effect holds when the feed stops is
already silence: freezing it changes nothing on the fixtures. What does
change is CPU — the capture callback, the 100 Hz pump on the event loop, and
the melbank DSP all stop.

  * An UNKNOWN playback read (the bridge down — a SpotFX restart) neither
    pauses nor resumes; it breaks the quiet clock, so two minutes of quiet
    must be confirmed again after it.
  * Anyone else LISTENING (an A/V-sync measurement holds its own hub
    subscription) keeps the audio on, and resumes it within a tick.
  * A stream that will not reopen is retried every tick and named in the
    status (`resume_error`) — a silent deaf show is the failure to avoid.
  * Music from anywhere but Spotify does not count as music here (the show
    itself only starts for Spotify); a resting audio-reactive effect would
    not react to it while paused. Named, not solved — the plan dropped
    "music from anywhere" for now.

═══ HOW TO READ THE STATUS ═══

`status()` (the `energy` key of GET /api/house/mode and engine status's
`lighting`) carries, per fixture, the frames per second ACTUALLY handed to
the transport and skipped as unchanged over the last ~10 s — read off the
device objects' own counters (fx/devices/__init__.py `_emit_frame`), never
inferred from a setting — and an ESTIMATED packets per second from them
(DDP: ceil(bytes / 1440) packets per frame; a Hue frame is one datagram). It
is labelled an estimate: the host-wide counters (scripts/
measure_room_energy.py) are the measurement.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: how long the per-fixture frame counters are averaged over for status
SAMPLE_WINDOW_S = 10.0
#: DDP payload bytes per packet (fx/devices/ddp.py DDPDevice.MAX_DATALEN)
DDP_MAX_DATALEN = 1440


@dataclass
class _Runtime:
    active: bool = False
    park_pushed: Optional[bool] = None
    keepalive_pushed: Any = "unset"
    quiet_since: Optional[float] = None
    last_playing: Optional[bool] = None
    last_reason: Optional[str] = None
    #: device id -> deque[(clock, sent, skipped)]
    samples: dict = field(default_factory=dict)
    recent: list = field(default_factory=list)


_rt = _Runtime()
#: one pass at a time: house.tick() runs from the supervisor AND from the API
#: routes, and a pause awaits mid-way (the pump's cancellation)
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def reset() -> None:
    """Tests: forget the module's memory."""
    global _rt, _lock
    _rt = _Runtime()
    _lock = None


def _settings():
    from spectra.services import house_store
    try:
        return house_store.load_library().settings.energy
    except Exception:                                    # noqa: BLE001
        from spectra.models.house_mode import HouseEnergy
        logger.exception("house energy: settings unreadable — defaults used")
        return HouseEnergy()


def _live():
    from spectra.services.live_host import live
    return live


def _note(kind: str, detail: dict) -> None:
    entry = {"at_ms": int(time.time() * 1000), "kind": kind, **detail}
    _rt.recent.append(entry)
    del _rt.recent[:-8]
    try:
        from spectra.services import fire_history
        fire_history.record_fire("house", kind, detail)
    except Exception:                                    # noqa: BLE001
        logger.debug("house energy: fire-history write failed", exc_info=True)


# ── the pass ───────────────────────────────────────────────────────────────

async def tick() -> None:
    """One pass, run after every house tick. Never raises."""
    async with _get_lock():
        try:
            await _tick()
        except Exception:                                # noqa: BLE001
            logger.exception("house energy: pass failed")


async def _tick() -> None:
    from spectra.services import house
    settings = _settings()
    active = house.layer_active()
    _rt.active = active
    _push_fx_flags(active, settings)
    await _audio(active, settings, house)
    _sample_counters()


def _push_fx_flags(active: bool, settings) -> None:
    from fx import device_output, device_rate
    park = bool(active and settings.park_idle)
    if park != _rt.park_pushed:
        device_rate.set_park_idle(park)
        _rt.park_pushed = park
    keepalive = float(settings.keepalive_s) if (active and settings.send_on_change) else None
    if keepalive != _rt.keepalive_pushed:
        device_output.set_send_on_change(keepalive)
        _rt.keepalive_pushed = keepalive


async def _audio(active: bool, settings, house) -> None:
    live = _live()
    if live.host is None or live.audio_source is None:
        _rt.quiet_since = None
        return
    now = time.monotonic()
    try:
        playing = house.deps.playing()
    except Exception:                                    # noqa: BLE001
        playing = None
    _rt.last_playing = playing
    if playing is False:
        if _rt.quiet_since is None:
            _rt.quiet_since = now
    else:
        # music, or an unknown read: two minutes of quiet must be confirmed
        # again from scratch
        _rt.quiet_since = None
    after = float(settings.audio_pause_after_s)
    listeners = live.audio_listeners()

    if live.audio_paused:
        why = None
        if not active:
            why = house.inactive_reason() or "no house mode drives the room"
        elif after <= 0:
            why = "audio pausing switched off"
        elif playing is True:
            why = "music is playing"
        elif listeners:
            why = f"{', '.join(listeners)} is listening"
        if why is not None:
            if await live.resume_audio(why):
                _note("audio_resumed", {"why": why})
        return

    if (active and after > 0 and playing is False and not listeners
            and _rt.quiet_since is not None and now - _rt.quiet_since >= after):
        why = f"no music for {int(now - _rt.quiet_since)}s while a house mode drives the room"
        if await live.pause_audio(why):
            _note("audio_paused", {"why": why})


# ── measuring what actually leaves ─────────────────────────────────────────

def _packets_per_frame(dev) -> Optional[int]:
    kind = str(getattr(dev, "type", "") or "").lower()
    if kind == "dummy":
        return 0
    if kind == "hue":
        return 1
    if kind in ("wled", "ddp"):
        try:
            nbytes = int(dev.pixel_count) * 3
        except Exception:                                # noqa: BLE001
            return None
        return max(1, math.ceil(nbytes / DDP_MAX_DATALEN))
    return None


def _sample_counters() -> None:
    live = _live()
    host = live.host
    if host is None:
        _rt.samples.clear()
        return
    now = time.monotonic()
    seen = set()
    for did in list(host.devices):
        dev = host.devices.get(did)
        if dev is None or str(did).startswith("gap-"):
            continue
        seen.add(did)
        q = _rt.samples.setdefault(did, collections.deque())
        q.append((now, int(getattr(dev, "_frames_sent", 0)),
                  int(getattr(dev, "_frames_skipped", 0))))
        while len(q) > 2 and now - q[0][0] > SAMPLE_WINDOW_S:
            q.popleft()
    for did in list(_rt.samples):
        if did not in seen:
            _rt.samples.pop(did, None)


def fixture_rates() -> dict:
    """device id -> {sent_fps, skipped_fps, packets_per_s (estimate)} over
    the last SAMPLE_WINDOW_S, from the devices' own counters."""
    live = _live()
    host = live.host
    out: dict = {}
    if host is None:
        return out
    for did, q in _rt.samples.items():
        if len(q) < 2:
            continue
        t0, s0, k0 = q[0]
        t1, s1, k1 = q[-1]
        span = t1 - t0
        if span <= 0:
            continue
        sent = max(0, s1 - s0) / span
        skipped = max(0, k1 - k0) / span
        dev = host.devices.get(did)
        ppf = _packets_per_frame(dev) if dev is not None else None
        out[did] = {"sent_fps": round(sent, 1), "skipped_fps": round(skipped, 1),
                    "packets_per_s": (round(sent * ppf, 1) if ppf is not None else None)}
    return out


def parked_virtuals() -> list[str]:
    """Active virtuals the render loop is parking RIGHT NOW (the same
    function the render thread asks, fx/device_rate.idle)."""
    from fx import device_rate
    live = _live()
    host = live.host
    if host is None or not device_rate.park_idle():
        return []
    out = []
    for v in list(host.virtuals.values()):
        if not getattr(v, "active", False):
            continue
        try:
            if device_rate.idle(v._devices):
                out.append(v.id)
        except Exception:                                # noqa: BLE001
            continue
    return sorted(out)


def status() -> dict:
    """The `energy` block of the house status."""
    from fx import device_output, device_rate
    from spectra.services import house_store
    settings = _settings()
    live = _live()
    rates = fixture_rates()
    fixtures = {}
    from spectra.services import house
    labels = house.fixture_labels()
    for did, r in sorted(rates.items()):
        fixtures[labels.get(did, did)] = {**r, "id": did}
    total = [r["packets_per_s"] for r in rates.values() if r["packets_per_s"] is not None]
    st = house_store.state()
    quiet_for = (round(time.monotonic() - _rt.quiet_since, 1)
                 if _rt.quiet_since is not None else None)
    return {
        "acting": _rt.active,
        "settings": settings.model_dump(),
        "parking": device_rate.park_idle(),
        "parked": parked_virtuals(),
        "send_on_change_s": device_output.send_on_change_setting(),
        "audio": {**live.audio_status(), "quiet_for_s": quiet_for},
        "fixtures": fixtures,
        "packets_per_s_estimate": round(sum(total), 1) if total else None,
        "mains_off": {did: since for did, since in st.mains_off.items()},
        "recent": list(reversed(_rt.recent[-5:])),
    }
