"""FROM PER-DEVICE MEASUREMENTS TO PROPOSED PER-DEVICE OFFSETS.

The /avsync instrument can now flash ONE device at a time
(av_sync_pattern.PatternDriver.start(device_id=...)), so a run's
`av_offset_ms` is that device's own light-vs-sound offset. This module is
the arithmetic that turns a SET of those into the offsets that would make
the fixtures land together — and nothing else. **It NEVER writes**:
applying is his press through the device page or
PUT /api/devices/{id}/timing, the same rule the room lead's own apply
dialogue follows.

WHY THE DIFFERENCES ARE THE ANSWER. Each per-device measurement is

    av_offset_ms(d) = light_lag(d) - audio_lag

and `audio_lag` is the SAME term in every run — the phone's own mic
pipeline, the room's speakers, SPECTRA's audio hub. Subtracting one
device's measurement from another's cancels it exactly, along with every
systematic common to both runs (the phone's camera pipeline, the server's
audio-hub input latency). So the between-device DIFFERENCES are a far
better-conditioned quantity than either absolute figure — which is why
this module reports them and why the equalization depends on nothing but
them.

MEASURED WITH THE CURRENT OFFSETS ALREADY IN THE LIGHT PATH — so the
proposal SUBTRACTS them, the same discipline the room lead's ADD rule
exists for. The flash pattern's writes leave through the same delayed
device flush as everything else, so a device already held back 100 ms
measures 100 ms later than its own hardware would. Each device's
INTRINSIC arrival is therefore

    intrinsic(d) = av_offset_ms(d) - applied_delay(d)

where `applied_delay(d) = offset(d) - min_j offset(j)`, exactly what
fx/device_timing.py computes. Skipping that subtraction would make every
re-measure chase its own tail: the correction already applied would be
counted again.

THE REFERENCE IS THE SLOWEST DEVICE, so every proposal is a WAIT. A
fixture can only be made to wait — nothing can send a frame to a light
before the renderer drew it — so the device whose light arrives LATEST
(the largest intrinsic) sets the pace at 0, and each faster device is
asked to hold back the difference. In HIS convention (OFFSET family,
negative = fires earlier, positive = fires later):

    proposed_offset_ms(d) = max_j(intrinsic(j)) - intrinsic(d)   >= 0

Non-negative for every device, exactly 0 for the reference. The other
reading — pinning the FASTEST device and proposing negatives — is
identical arithmetic at the lights (only differences matter) but reads as
"everything is late" instead of "the slow one sets the pace", and hides
which fixture is actually the laggard.

HIS HUE-SLOWER-THAN-WLED BELIEF IS A HYPOTHESIS THIS MEASURES, not a fact
encoded anywhere here. Nothing in this module knows or cares what type a
device is; the ordering falls out of the measurements.

AFTER EQUALIZATION THE WHOLE ROOM MOVES. Holding every device back to
meet the slowest makes the room as a whole land later, by exactly the
spread. That global shift is absorbed by the EXISTING room loop —
re-measure on /avsync and apply the room lead (av_sync_lead.py, LEAD
family, positive = earlier) — not by anything here. Every result this
module returns says so in words (`after_note`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from spectra.models.device_settings import OFFSET_LIMIT_MS

# A device measured more often than this keeps only its newest runs for the
# median — enough to see stability, few enough that a stale run from before
# a change cannot dominate.
RUNS_PER_DEVICE = 5

AFTER_NOTE = (
    "Equalizing holds every device back to meet the slowest, so the room as "
    "a whole lands later by the spread. That global shift is absorbed by the "
    "existing room loop: re-measure on the AV Sync page and apply the room "
    "A/V sync lead. These per-device offsets only line the fixtures up with "
    "each other.")


@dataclass
class DeviceMeasurement:
    device_id: str
    av_offset_ms: float          # as measured, with today's delay in the path
    intrinsic_ms: float          # that, minus today's applied delay
    applied_delay_ms: int
    runs: int
    sigma_ms: Optional[float] = None
    spread_ms: Optional[float] = None       # max-minus-min across its own runs
    at_iso: Optional[str] = None

    def as_dict(self) -> dict:
        return {"device_id": self.device_id,
                "av_offset_ms": round(self.av_offset_ms, 1),
                "intrinsic_ms": round(self.intrinsic_ms, 1),
                "applied_delay_ms": self.applied_delay_ms,
                "runs": self.runs,
                "sigma_ms": None if self.sigma_ms is None else round(self.sigma_ms, 1),
                "spread_ms": None if self.spread_ms is None else round(self.spread_ms, 1),
                "at_iso": self.at_iso}


@dataclass
class EqualizationProposal:
    applicable: bool
    reason: str = ""
    measured: list = field(default_factory=list)
    reference_device_id: Optional[str] = None
    proposals: list = field(default_factory=list)
    spread_ms: Optional[float] = None
    out_of_range: list = field(default_factory=list)
    after_note: str = AFTER_NOTE

    def as_dict(self) -> dict:
        return {"applicable": self.applicable, "reason": self.reason,
                "measured": [m.as_dict() for m in self.measured],
                "reference_device_id": self.reference_device_id,
                "proposals": self.proposals,
                "spread_ms": None if self.spread_ms is None else round(self.spread_ms, 1),
                "out_of_range": self.out_of_range,
                "after_note": self.after_note}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def applied_delays_ms(offsets: dict[str, int]) -> dict[str, int]:
    """The same translation fx/device_timing.py makes, in ms: a device's
    delay is its offset above the smallest authored offset. Recomputed here
    rather than read off the live registry so a proposal can be produced
    with the room down."""
    if not offsets:
        return {}
    base = min(offsets.values())
    return {did: int(value) - int(base) for did, value in offsets.items()}


def per_device_measurements(records: list[dict],
                            offsets: Optional[dict[str, int]] = None
                            ) -> list[DeviceMeasurement]:
    """Collapse the stored measurement log into ONE number per device: the
    median of its newest RUNS_PER_DEVICE accepted runs, with today's
    applied delay subtracted back out. Only records the instrument itself
    stood behind (`ok`) and that name a device are counted — a refused run
    contributes nothing rather than a guess."""
    delays = applied_delays_ms(offsets or {})
    by_device: dict[str, list[dict]] = {}
    for record in records:
        if not record.get("ok"):
            continue
        device_id = record.get("device_id")
        offset = record.get("av_offset_ms")
        if not device_id or offset is None:
            continue
        by_device.setdefault(str(device_id), []).append(record)

    out: list[DeviceMeasurement] = []
    for device_id, runs in by_device.items():
        newest = runs[-RUNS_PER_DEVICE:]
        values = [float(r["av_offset_ms"]) for r in newest]
        sigmas = [float(r["sigma_ms"]) for r in newest
                  if r.get("sigma_ms") is not None]
        measured = _median(values)
        delay = int(delays.get(device_id, 0))
        out.append(DeviceMeasurement(
            device_id=device_id,
            av_offset_ms=measured,
            intrinsic_ms=measured - delay,
            applied_delay_ms=delay,
            runs=len(newest),
            sigma_ms=max(sigmas) if sigmas else None,
            spread_ms=(max(values) - min(values)) if len(values) > 1 else None,
            at_iso=newest[-1].get("at_iso")))
    out.sort(key=lambda m: m.intrinsic_ms)
    return out


def proposal(records: list[dict], offsets: Optional[dict[str, int]] = None
             ) -> EqualizationProposal:
    """The equalization his press would apply, or a stated refusal. Never
    writes anything."""
    offsets = dict(offsets or {})
    measured = per_device_measurements(records, offsets)
    if len(measured) < 2:
        return EqualizationProposal(
            applicable=False,
            measured=measured,
            reason=("measure at least two devices first — the useful quantity "
                    "is the DIFFERENCE between devices, so one device on its "
                    "own says nothing about how to line them up"))

    reference = max(measured, key=lambda m: m.intrinsic_ms)
    proposals: list[dict] = []
    out_of_range: list[str] = []
    for m in measured:
        value = int(round(reference.intrinsic_ms - m.intrinsic_ms))
        if value > OFFSET_LIMIT_MS:
            out_of_range.append(m.device_id)
            value = OFFSET_LIMIT_MS
        now = int(offsets.get(m.device_id, 0))
        proposals.append({
            "device_id": m.device_id,
            "measured_av_offset_ms": round(m.av_offset_ms, 1),
            "current_timing_offset_ms": now,
            "proposed_timing_offset_ms": value,
            "delta_ms": value - now,
            "is_reference": m.device_id == reference.device_id,
            "sentence": _sentence(m.device_id, value,
                                  m.device_id == reference.device_id),
        })
    proposals.sort(key=lambda p: -p["proposed_timing_offset_ms"])
    return EqualizationProposal(
        applicable=True,
        measured=measured,
        reference_device_id=reference.device_id,
        proposals=proposals,
        spread_ms=reference.intrinsic_ms - measured[0].intrinsic_ms,
        out_of_range=out_of_range)


def _sentence(device_id: str, value: int, is_reference: bool) -> str:
    if is_reference:
        return (f"{device_id} is the slowest — it sets the pace and is left "
                f"alone.")
    if value == 0:
        return f"{device_id} already lands with the slowest device."
    return (f"{device_id} waits {value} ms so it lands with the slowest "
            f"device.")
