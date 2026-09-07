"""THE MICROPHONE HALF, and the one rule it exists to keep: a stream this
client cannot vouch for is a REFUSAL, never a number.

The A/V-sync measurement is a difference between two lags, and the audio lag
is half of it. A mic that is not there, an `arecord` that will not start, a
capture that dies mid-run — every one of them can be made to look like a
working stream (zeros are a valid envelope; the correlator would refuse with
"weak" and a human would go looking at the room). So every one of them
raises `AudioUnavailable` with the device named, and the client exits
non-zero saying so.

BOUND BY NAME, NEVER BY CARD INDEX. `arecord -l` numbers cards in USB
enumeration order, which is not a promise about anything: the Brio can be
card 2 today and card 1 after a reboot with the reSpeaker unplugged. This
module resolves a NAME the human gave ("BRIO") against the card ids ALSA
itself publishes and then opens `plughw:CARD=<id>,DEV=<n>` — a name, not a
number, all the way to the device. A name matching more than one card is
refused with both named rather than resolved to whichever came first.

`plughw:` rather than `hw:` deliberately: a UVC microphone advertises the
rate and channel count its firmware feels like, and ALSA's plug layer is
what turns that into the 48 kHz mono S16 this reduction wants. It costs a
small, constant buffer — which is part of the capture latency the server
already names as a systematic (`SYSTEMATIC_MIC_UNKNOWN`) — and it is what
makes "point it at the Brio" work without a table of which mic supports
what.

NO SOFTWARE DSP IN THIS PATH, which is one place the kiosk is BETTER than
the phone rather than worse. The browser page has to explicitly switch off
echo cancellation, noise suppression and automatic gain control, because
every one of them reshapes the envelope and adds its own latency; ALSA hands
over what the device produced. What this cannot reach is a MICROPHONE'S OWN
FIRMWARE processing, if it has any — that is not something a capture API can
turn off, and it is why the envelope is correlated on its ONSETS (which a
slow gain ride does not move) rather than on its levels.

WHAT IS ON THE WIRE: nothing but the envelope. Raw audio never leaves this
machine — `avsync_reduce.pcm16_hop_db` turns each ~11 ms hop into one number
and the bytes are dropped. That is the same promise the phone page makes,
kept by the same construction rather than by a policy.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from spectra.capture_client.avsync_reduce import (SILENCE_FLOOR_DB,
                                                  SampleClock, pcm16_hop_db)

logger = logging.getLogger(__name__)

#: The capture format, chosen to match the two implementations this stream
#: has to agree with. 512 samples at 48 kHz is 10.67 ms — the browser
#: worklet's 4×128-sample render quanta exactly, and the same hop the
#: server's own reference tap uses (`av_sync_audio_ref.HOP_SAMPLES`).
SAMPLE_RATE = 48000
HOP_SAMPLES = 512
CHANNELS = 1
SAMPLE_BYTES = 2
#: Hops per `audio` message — the browser's AUDIO_BATCH_HOPS. ~85 ms of
#: envelope per message, ~12 messages a second.
BATCH_HOPS = 8
#: ALSA period and buffer, in FRAMES. Small on purpose: the period is what
#: the device hands over at a time, so it is the floor on how stale the
#: newest sample in a read can be. Four periods of buffer is enough that an
#: ordinary scheduling hiccup does not overrun.
PERIOD_FRAMES = 512
BUFFER_FRAMES = 4096
#: How long `arecord` gets to produce its first bytes before this is called
#: a device that will not capture. Generous — a USB mic can take a moment.
FIRST_BYTES_TIMEOUT_S = 8.0
#: A hop at or under this is silence, counted so "the mic was muted" is a
#: fact the run can report rather than something a human infers from a
#: refused correlation.
SILENT_HOP_DB = SILENCE_FLOOR_DB + 0.5


class AudioUnavailable(Exception):
    """No trustworthy microphone stream — named, and fatal to a run."""


@dataclass
class CaptureCard:
    card_index: int
    card_id: str
    card_name: str
    device_index: int
    device_name: str

    @property
    def alsa_device(self) -> str:
        return f"plughw:CARD={self.card_id},DEV={self.device_index}"

    def describe(self) -> str:
        return (f"card {self.card_index} [{self.card_id}] "
                f"{self.card_name} — device {self.device_index} "
                f"{self.device_name}")


_CARD_LINE = re.compile(
    r"^card (?P<ci>\d+): (?P<cid>\S+) \[(?P<cname>[^\]]*)\], "
    r"device (?P<di>\d+): (?P<dname>[^\[]*)\[(?P<dlong>[^\]]*)\]")


def parse_arecord_l(text: str) -> list:
    """Every capture device ALSA declares, from `arecord -l`'s own output.
    Parsed rather than assumed: this is the device's answer, not a table of
    what a Brio usually is."""
    cards = []
    for line in text.splitlines():
        m = _CARD_LINE.match(line.strip())
        if not m:
            continue
        cards.append(CaptureCard(
            card_index=int(m.group("ci")), card_id=m.group("cid"),
            card_name=m.group("cname").strip(),
            device_index=int(m.group("di")),
            device_name=(m.group("dname").strip()
                         or m.group("dlong").strip())))
    return cards


def list_capture_cards(*, run=None) -> list:
    """`arecord -l`, or a named refusal when the tool is not installed."""
    runner = run or _run
    if shutil.which("arecord") is None and run is None:
        raise AudioUnavailable(
            "arecord is not installed on this machine, and the A/V-sync "
            "client reads the microphone through it "
            "(sudo apt install alsa-utils)")
    code, out = runner(["arecord", "-l"])
    if code != 0 and "card" not in out:
        raise AudioUnavailable(
            f"arecord -l would not list this machine's capture devices "
            f"(exit {code}): {out.strip()[:300] or 'no output'}")
    return parse_arecord_l(out)


def resolve_card(wanted: str, *, run=None) -> CaptureCard:
    """THE ONE MATCHING RULE. A NAME, matched case-insensitively against the
    card ids and card names ALSA publishes, resolved to the card itself —
    so everything that has an opinion about which microphone was meant
    (the device string this opens, and the doctor's own report) reads the
    same answer rather than two rules that agree on most machines."""
    cards = list_capture_cards(run=run)
    if not cards:
        raise AudioUnavailable(
            "this machine has no ALSA capture device at all (arecord -l "
            "lists none), so there is no microphone to measure with")
    needle = wanted.lower()
    hits = [c for c in cards
            if needle in c.card_id.lower() or needle in c.card_name.lower()]
    if not hits:
        known = "; ".join(c.describe() for c in cards)
        raise AudioUnavailable(
            f"no capture device on this machine is called {wanted!r}. "
            f"What it does have: {known}")
    by_card = {c.card_id for c in hits}
    if len(by_card) > 1:
        named = "; ".join(sorted(by_card))
        raise AudioUnavailable(
            f"{wanted!r} matches more than one capture card ({named}) — "
            f"name one of them exactly, or pass an ALSA device such as "
            f"plughw:CARD={sorted(by_card)[0]},DEV=0")
    return sorted(hits, key=lambda c: c.device_index)[0]


def resolve_device(wanted: str, *, run=None) -> str:
    """The ALSA device string for what the human asked for.

    An explicit ALSA device (anything with a `:` in it, or `default`) is
    passed through untouched — a person who typed `hw:2,0` meant it. Any
    other string goes through `resolve_card`."""
    wanted = (wanted or "").strip()
    if not wanted:
        raise AudioUnavailable(
            "no microphone was named for the A/V-sync measurement "
            "(--audio-device, or SPECTRA_CAPTURE_AUDIO_DEVICE)")
    if ":" in wanted or wanted in ("default", "null"):
        return wanted
    return resolve_card(wanted, run=run).alsa_device


def _run(args: list, timeout: float = 5.0) -> tuple:
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


@dataclass
class AudioBatch:
    """One `audio` message's worth of envelope, on the client's own
    monotonic clock. `t0_s` is the time of the FIRST SAMPLE of the first
    hop — not the time the read returned; see `SampleClock`."""
    t0_s: float
    hop_ms: float
    values: list

    def as_message(self) -> dict:
        return {"type": "audio", "t0_ms": self.t0_s * 1000.0,
                "hop_ms": self.hop_ms, "v": self.values}


class ArecordSource:
    """A microphone as a stream of envelope batches, and nothing else.

    `open()` starts the capture and refuses by name if it cannot; `batch()`
    returns the next `AudioBatch`, or raises `AudioUnavailable` if the
    stream ended — a client that kept sending after the capture died would
    be putting silence on the wire and calling it a measurement."""

    def __init__(self, device: str, *, rate_hz: int = SAMPLE_RATE,
                 hop_samples: int = HOP_SAMPLES,
                 batch_hops: int = BATCH_HOPS,
                 clock=None, spawn=None) -> None:
        self.device = device
        self.rate_hz = int(rate_hz)
        self.hop_samples = int(hop_samples)
        self.batch_hops = int(batch_hops)
        self._clock = clock or time.monotonic
        self._spawn = spawn or self._spawn_arecord
        self._proc = None
        self._stdout = None
        self.clock = SampleClock(self.rate_hz)
        self.hops = 0
        self.silent_hops = 0
        self.opened = False

    # ── the numbers a reader can check ────────────────────────────────────
    @property
    def hop_ms(self) -> float:
        return 1000.0 * self.hop_samples / self.rate_hz

    @property
    def batch_bytes(self) -> int:
        return self.hop_samples * self.batch_hops * SAMPLE_BYTES * CHANNELS

    def describe(self) -> dict:
        return {"kind": "arecord", "device": self.device,
                "sample_rate": self.rate_hz, "hop_ms": round(self.hop_ms, 4),
                "hop_samples": self.hop_samples, "channels": CHANNELS,
                "period_frames": PERIOD_FRAMES,
                "buffer_frames": BUFFER_FRAMES}

    def stats(self) -> dict:
        return {"hops": self.hops, "silent_hops": self.silent_hops,
                "reads": self.clock.reads,
                "anchor_frozen": self.clock.frozen,
                "anchor_spread_ms": round(self.clock.spread_s * 1000.0, 2),
                "anchor_freeze_cost_ms": round(
                    self.clock.freeze_cost_s * 1000.0, 2)}

    # ── lifecycle ─────────────────────────────────────────────────────────
    def arecord_args(self) -> list:
        return ["arecord", "-D", self.device, "-t", "raw", "-f", "S16_LE",
                "-c", str(CHANNELS), "-r", str(self.rate_hz),
                f"--period-size={PERIOD_FRAMES}",
                f"--buffer-size={BUFFER_FRAMES}", "-q"]

    async def _spawn_arecord(self):
        if shutil.which("arecord") is None:
            raise AudioUnavailable(
                "arecord is not installed on this machine, and the A/V-sync "
                "client reads the microphone through it "
                "(sudo apt install alsa-utils)")
        try:
            return await asyncio.create_subprocess_exec(
                *self.arecord_args(), stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            raise AudioUnavailable(
                f"arecord would not start for {self.device}: {exc}") from None

    async def open(self) -> None:
        self._proc = await self._spawn()
        self._stdout = self._proc.stdout
        # PROVE IT IS ACTUALLY CAPTURING before anything downstream treats
        # this as a working microphone: read one whole batch. An arecord
        # that exits immediately (a busy device, a rate the card refuses)
        # produces no bytes, and its own complaint is the useful half.
        try:
            first = await asyncio.wait_for(
                self._stdout.readexactly(self.batch_bytes),
                timeout=FIRST_BYTES_TIMEOUT_S)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            err = await self._stderr_text()
            await self.close()
            raise AudioUnavailable(
                f"{self.device} produced no audio"
                + (f" ({err})" if err else
                   f" within {FIRST_BYTES_TIMEOUT_S:.0f}s")) from None
        self.opened = True
        self._first = first

    async def batch(self) -> AudioBatch:
        """The next batch of envelope numbers. Raises `AudioUnavailable`
        when the capture has ended — never returns silence instead."""
        if not self.opened:
            raise AudioUnavailable("the microphone stream is not open")
        pcm = getattr(self, "_first", None)
        if pcm is None:
            try:
                pcm = await self._stdout.readexactly(self.batch_bytes)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                err = await self._stderr_text()
                raise AudioUnavailable(
                    f"the microphone stream from {self.device} ended "
                    f"mid-measurement" + (f" ({err})" if err else "")) from None
        else:
            self._first = None
        t_read = self._clock()
        samples = len(pcm) // SAMPLE_BYTES
        t0 = self.clock.observe(t_read, samples)
        step = self.hop_samples * SAMPLE_BYTES
        values = []
        for i in range(0, len(pcm) - step + 1, step):
            db = pcm16_hop_db(pcm[i:i + step])
            values.append(round(db, 3))
            if db <= SILENT_HOP_DB:
                self.silent_hops += 1
        self.hops += len(values)
        return AudioBatch(t0_s=t0, hop_ms=self.hop_ms, values=values)

    async def _stderr_text(self) -> str:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(proc.stderr.read(2000), timeout=1.0)
        except (asyncio.TimeoutError, OSError):
            return ""
        return (data or b"").decode(errors="replace").strip()[-300:]

    async def close(self) -> None:
        self.opened = False
        proc, self._proc = self._proc, None
        self._stdout = None
        if proc is None:
            return
        try:
            proc.terminate()
        except (OSError, ProcessLookupError):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except (asyncio.TimeoutError, OSError):
            try:
                proc.kill()
            except (OSError, ProcessLookupError):
                pass


def probe_device(wanted: str, *, run=None) -> dict:
    """A read-only answer to "is the microphone this run needs there?" —
    for `--doctor`. Never opens the device: presence and identity only, so
    it cannot take a capture away from a run that is using it."""
    try:
        cards = [c.describe() for c in list_capture_cards(run=run)]
    except AudioUnavailable:
        cards = []
    wanted = (wanted or "").strip()
    try:
        device = resolve_device(wanted, run=run)
        card = (None if ":" in wanted or wanted in ("default", "null")
                else resolve_card(wanted, run=run))
    except AudioUnavailable as exc:
        return {"ok": False, "wanted": wanted, "detail": str(exc),
                "capture_devices": cards}
    out = {"ok": True, "wanted": wanted, "device": device,
           "detail": f"{wanted!r} resolves to {device}",
           "capture_devices": cards}
    if card is not None:
        # The PCM node this card's capture device lives at, so a caller can
        # ask about access without this module opening anything.
        out.update(card_index=card.card_index,
                   device_index=card.device_index,
                   pcm_node=f"/dev/snd/pcmC{card.card_index}D"
                            f"{card.device_index}c")
    return out
