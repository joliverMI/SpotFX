"""
SpotFX — Absorb Music's bar: is this song already captured, and if not, how
does it get captured? (data/absorb-music-plan/report.md §8.1-§8.2.)

A song is SKIPPED — filed without playing — only when all of these hold:

    capture_complete AND NOT capture_failed
    AND the npz exists
    AND librosa_version >= 2 AND the .librosa.json exists
    AND first_timestamp_ms <= head_max_ms          (his Q1: the head)
    AND first_timestamp_ms <  duration_ms          (it renders at all)
    AND NOT needs_recapture

Everything else is work, of one of two kinds, and the split is decided by
what the CAPTURE PATH will do with the song, not by a label:

  fresh      no sidecar, or one that is not `capture_complete` (a failed
             attempt, a half-written one). The ordinary capture in
             audio_shape_service.on_track_change starts on its own.
  recapture  a complete shape that fails the bar. on_track_change refuses to
             capture over a complete shape, so only a FORCED capture
             (audio_shape_service.force_uris) replaces it.

THE HEAD. The sidecar does not record where its first sample landed; the
plan expected the phase-0 work to add `first_timestamp_ms` and it did not.
This module reads that field when a sidecar carries it and otherwise reads
the npz's own first timestamp (0.57 ms a file measured on his library), so it
works today and costs nothing the day the field arrives.

`judge` is pure; `read_facts` touches disk (sidecar, npz, librosa json) and is
called through asyncio.to_thread by the runner.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from config import AUDIO_SHAPES_DIR

MIN_LIBROSA_VERSION = 2


@dataclass
class ShapeFacts:
    """What the disk says about one song's shape."""
    uri: str
    has_sidecar: bool = False
    title: str = ""
    duration_ms: int = 0
    capture_complete: bool = False
    capture_failed: bool = False
    npz_exists: bool = False
    librosa_version: int = 0
    librosa_json_exists: bool = False
    needs_recapture: bool = False
    first_ts_ms: Optional[int] = None     # None = could not be read
    head_source: str = ""                 # "sidecar" | "npz" | ""


@dataclass
class Verdict:
    uri: str
    kind: str                              # "skip" | "fresh" | "recapture"
    reasons: list[str] = field(default_factory=list)
    head_ms: Optional[int] = None
    duration_ms: int = 0
    title: str = ""

    @property
    def missing_ms(self) -> int:
        """How much of the song the current shape is missing — the sort key
        for worst-head-first (report §8.5). No usable shape at all counts as
        the whole song."""
        if self.kind == "fresh" or self.head_ms is None:
            return max(self.duration_ms, 1)
        if self.duration_ms and self.head_ms >= self.duration_ms:
            return self.duration_ms           # renders nothing
        return max(0, self.head_ms)


def _sidecar_path(uri: str) -> Optional[Path]:
    from services.audio_analyzer import _shape_filename_for
    stem = _shape_filename_for(uri)
    if stem is None:
        return None
    return AUDIO_SHAPES_DIR / f"{stem}.json"


def first_timestamp_from_npz(npz: Path) -> Optional[int]:
    try:
        with np.load(npz) as data:
            ts = data["timestamps_ms"]
            if ts.size == 0:
                return None
            return int(ts[0])
    except Exception:
        return None


def read_facts(uri: str) -> ShapeFacts:
    """Read one song's shape facts from disk. Never raises."""
    facts = ShapeFacts(uri=uri)
    sidecar = _sidecar_path(uri)
    if sidecar is None:
        return facts
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return facts
    if not isinstance(data, dict):
        return facts
    facts.has_sidecar = True
    facts.title = str(data.get("title") or "")
    facts.duration_ms = int(data.get("duration_ms") or 0)
    facts.capture_complete = bool(data.get("capture_complete"))
    facts.capture_failed = bool(data.get("capture_failed"))
    facts.librosa_version = int(data.get("librosa_version") or 0)
    facts.needs_recapture = bool(data.get("needs_recapture"))
    npz_name = str(data.get("npz_file") or (sidecar.stem + ".npz"))
    npz = AUDIO_SHAPES_DIR / npz_name
    facts.npz_exists = npz.exists()
    stem = Path(npz_name).stem
    facts.librosa_json_exists = (AUDIO_SHAPES_DIR / f"{stem}.librosa.json").exists()
    if isinstance(data.get("first_timestamp_ms"), (int, float)):
        facts.first_ts_ms = int(data["first_timestamp_ms"])
        facts.head_source = "sidecar"
    elif facts.npz_exists:
        facts.first_ts_ms = first_timestamp_from_npz(npz)
        facts.head_source = "npz" if facts.first_ts_ms is not None else ""
    return facts


def judge(facts: ShapeFacts, head_max_ms: int, force_recapture: bool = False) -> Verdict:
    """The bar. `force_recapture` is his run-wide tag (report §8.6): with it
    on, nothing is skipped — a song that would pass is re-captured too."""
    v = Verdict(uri=facts.uri, kind="fresh", head_ms=facts.first_ts_ms,
                duration_ms=facts.duration_ms, title=facts.title)
    if not facts.has_sidecar:
        v.reasons.append("no_shape")
        return v
    if not facts.capture_complete:
        v.reasons.append("failed_before" if facts.capture_failed else "incomplete")
        return v

    reasons: list[str] = []
    if facts.capture_failed:
        reasons.append("capture_failed")
    if not facts.npz_exists:
        reasons.append("no_npz")
    if facts.librosa_version < MIN_LIBROSA_VERSION or not facts.librosa_json_exists:
        reasons.append("no_librosa")
    if facts.needs_recapture:
        reasons.append("needs_recapture")
    if facts.first_ts_ms is None:
        if facts.npz_exists:
            reasons.append("unreadable_head")
    else:
        if facts.duration_ms and facts.first_ts_ms >= facts.duration_ms:
            reasons.append("renders_nothing")
        elif facts.first_ts_ms > head_max_ms:
            reasons.append("headless")
    if reasons:
        v.kind = "recapture"
        v.reasons = reasons
        return v
    if force_recapture:
        v.kind = "recapture"
        v.reasons = ["force_recapture"]
        return v
    v.kind = "skip"
    return v


def classify(uri: str, head_max_ms: int, force_recapture: bool = False) -> Verdict:
    return judge(read_facts(uri), head_max_ms, force_recapture)


def has_head(uri: str, head_max_ms: int) -> tuple[bool, Verdict]:
    """THE SECOND GATE (report §8.4): after a capture commits, does the shape
    on disk pass the bar? A committed-but-headless capture is not progress."""
    v = classify(uri, head_max_ms, force_recapture=False)
    return v.kind == "skip", v
