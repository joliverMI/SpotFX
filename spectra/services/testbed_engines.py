"""The music-analysis test bed's engine registry
(data/spotfx-music-analysis-plan/report.md, Part 1/3/5) — every candidate
engine normalizes to the SAME mark shape
(`{"time_ms", "kind", "label", "score"}`) so the comparison/metrics/render
code never branches on which engine produced a mark.

Two engines ship with this build (report Phase 0 + Phase 1 item 1, and the
Admiral's 2026-09-08 generation-alignment sharpening — beat_this is the
report's top pick for tighter beat/downbeat alignment):

  librosa   — "current" / the production baseline. Derived LIVE from the
              already-computed `.librosa.json` (spectra.services.
              analysis_reader, zero new analysis, zero new dependency) —
              never cached, since re-deriving it is a plain JSON parse.
              kinds: section_boundary, beat, downbeat.
  beat_this — CPJKU 2024 neural beat/downbeat tracker (MIT code + MIT
              weights — data/spotfx-music-analysis-plan/report.md Part
              1.3). Precomputed OFFLINE ONLY by
              scripts/testbed_precompute.py (spectra.services.
              testbed_beatthis actually calls the model; that module is
              never imported from a request handler) and read here from
              spectra.services.testbed_cache. kinds: beat, downbeat.

`librosa`'s "interior boundaries" (report's own Part 1.2 term) are every
section's start_ms EXCEPT the first section's (the song's own opening
boundary is not a "transition" — nothing precedes it), matching the
report's own methodology exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from spectra.services import analysis_reader, testbed_cache

ENGINE_LIBROSA = "librosa"
ENGINE_BEAT_THIS = "beat_this"

ENGINES: dict[str, dict] = {
    ENGINE_LIBROSA: {
        "label": "Current (librosa)",
        "kinds": ["section_boundary", "beat", "downbeat"],
        "live": True,
    },
    ENGINE_BEAT_THIS: {
        "label": "beat_this (CPJKU 2024)",
        "kinds": ["beat", "downbeat"],
        "live": False,
    },
}


@dataclass(frozen=True)
class EngineMark:
    time_ms: float
    kind: str
    label: Optional[str] = None
    score: Optional[float] = None


def librosa_marks_for_stem(stem: Optional[str]) -> Optional[list[EngineMark]]:
    """The librosa baseline's marks off ONE parse of <stem>.librosa.json;
    None when there is no stem or nothing usable in the file."""
    doc = analysis_reader.librosa_analysis_for_stem(stem)
    sections = (doc or {}).get("sections") or None
    beats = (doc or {}).get("beats") or None
    if sections is None and beats is None:
        return None
    out: list[EngineMark] = []
    for sec in (sections or [])[1:]:  # skip the opening boundary
        out.append(EngineMark(time_ms=float(sec.get("start_ms", 0)),
                              kind="section_boundary",
                              label=sec.get("label") or None,
                              score=sec.get("energy_rms")))
    for beat in (beats or []):
        out.append(EngineMark(
            time_ms=float(beat.get("ms", 0)),
            kind="downbeat" if beat.get("is_downbeat") else "beat",
            score=beat.get("rms_total"),
        ))
    return sorted(out, key=lambda m: m.time_ms)


def _librosa_marks(uri: str) -> Optional[list[EngineMark]]:
    return librosa_marks_for_stem(analysis_reader.stem_for_uri(uri))


def marks_for(engine: str, uri: str) -> Optional[list[EngineMark]]:
    """None = not available for this song (either the engine hasn't been
    precomputed for it, or — for librosa — no analysis exists yet)."""
    if engine == ENGINE_LIBROSA:
        return _librosa_marks(uri)
    cached = testbed_cache.load(engine, uri)
    if cached is None:
        return None
    return [EngineMark(time_ms=float(m["time_ms"]), kind=m["kind"],
                       label=m.get("label"), score=m.get("score"))
            for m in cached.get("marks", [])]


def availability_for(uri: str, *,
                     stem_index: Optional[dict[str, str]] = None) -> dict[str, dict]:
    """Per-engine {available, computed_at, mark_count} — the songs/engines
    listing's own status, so the frontend can say "not computed yet"
    instead of an empty lane.

    `stem_index`: a snapshot from analysis_reader.stem_index(), for a
    caller walking the whole corpus — a per-song stem_for_uri() lookup
    rebuilds the entire sidecar index on every miss, i.e. once per song
    that has no captured audio."""
    out: dict[str, dict] = {}
    for key, meta in ENGINES.items():
        if key == ENGINE_LIBROSA:
            if stem_index is None:
                marks = _librosa_marks(uri)
            else:
                marks = librosa_marks_for_stem(stem_index.get(uri))
            out[key] = {
                "label": meta["label"], "kinds": meta["kinds"],
                "available": marks is not None,
                "computed_at": None,
                "mark_count": len(marks) if marks else 0,
            }
        else:
            cached = testbed_cache.load(key, uri)
            out[key] = {
                "label": meta["label"], "kinds": meta["kinds"],
                "available": cached is not None,
                "computed_at": cached.get("computed_at") if cached else None,
                "mark_count": len(cached.get("marks", [])) if cached else 0,
            }
    return out
