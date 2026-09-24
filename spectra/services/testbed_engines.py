"""The music-analysis test bed's engine registry
(data/spotfx-music-analysis-plan/report.md, Part 1/3/5) — every candidate
engine normalizes to the SAME mark shape
(`{"time_ms", "kind", "label", "score"}`) so the comparison/metrics/render
code never branches on which engine produced a mark.

Four engines ship with this build (report Phase 0 + Phase 1 item 1, the
Admiral's 2026-09-08 generation-alignment sharpening, and
data/transition-alignment-plan/report.md section 4's tuning-loop lanes):

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
  generator — "what the room will do" (data/transition-alignment-plan/
              report.md section 4). kinds: stored (triggers.json's own
              GENERATED cues for this song, exactly as currently written —
              never recomputed here, so this is where a generator defect
              like the report's own Finding 1, the capture-offset frame
              bug, becomes visible on the lane before it's fixed), preview
              (spectra.services.midsong_generator.candidate_moments run
              fresh, read-only, against the CURRENT placement rule — R3
              then R1 since 2026-09-23, data/transition-alignment-plan/
              report.md section 5 task 3 — no trigger store write). Preview
              takes window_beats/sensitivity/direction from the page's own
              knobs (the same three the `edges` engine reads); snap_enabled
              and the density cap stay at the live room default. See
              _generator_marks's own docstring for why neither kind is
              capture-offset shifted by spectra/api/testbed.py::
              _estimate_for the way every other engine's marks are.
  edges     — bass-energy rhythmic edges (spectra.services.rhythmic_edges,
              data/transition-alignment-plan/report.md section 2.3/4) —
              bass_up, bass_down, gap_stop, gap_resume, tunable via
              window_beats/sensitivity/direction. Derived from the same
              `.librosa.json` beats librosa's own engine reads, so it
              shares that engine's raw (WAV-time) frame and IS shifted by
              _estimate_for like every analysis-derived engine.

`librosa`'s "interior boundaries" (report's own Part 1.2 term) are every
section's start_ms EXCEPT the first section's (the song's own opening
boundary is not a "transition" — nothing precedes it), matching the
report's own methodology exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from spectra.services import (analysis_reader, midsong_generator, rhythmic_edges,
                              testbed_cache, trigger_store)

ENGINE_LIBROSA = "librosa"
ENGINE_BEAT_THIS = "beat_this"
ENGINE_GENERATOR = "generator"
ENGINE_EDGES = "edges"

GENERATOR_KIND_STORED = "stored"
GENERATOR_KIND_PREVIEW = "preview"

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
    ENGINE_GENERATOR: {
        "label": "Generator (room)",
        "kinds": [GENERATOR_KIND_STORED, GENERATOR_KIND_PREVIEW],
        "live": True,
    },
    ENGINE_EDGES: {
        "label": "Rhythmic edges (bass)",
        "kinds": list(rhythmic_edges.KINDS),
        "live": True,
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


def _generator_stored_marks(uri: str) -> list[EngineMark]:
    """triggers.json's own currently-stored GENERATED cues for this song
    (source != "authored"), exactly as written — no recomputation. This is
    what the room will actually fire today, bugs (e.g. the report's own
    Finding 1 frame defect) included; see the module docstring for why
    that is deliberate."""
    out = [
        EngineMark(time_ms=float(t.timestamp_ms), kind=GENERATOR_KIND_STORED,
                   label=t.action.kind, score=None)
        for t in trigger_store.list_for_song(uri)
        if t.source != "authored"
    ]
    return sorted(out, key=lambda m: m.time_ms)


def _generator_preview_marks(
    uri: str, *, window_beats: int, sensitivity: float, direction: str,
) -> list[EngineMark]:
    """spectra.services.midsong_generator.candidate_moments(uri), run
    read-only against the CURRENT placement rule (R3 then R1, 2026-09-23)
    at the page's own window/sensitivity/direction knob values — what
    generation would produce right now, without writing anything to the
    trigger store. `snap_enabled`/`max_per_song` are deliberately NOT
    threaded from here — they stay at the live room default, so this lane
    also reflects the room's own snap-to-beat toggle and density cap, not
    a third, test-bed-only copy of either (data/transition-alignment-plan/
    report.md section 5 task 3 item (f): only place_cue's own knobs are
    the page's to explore here — the density "use as room default" knob
    is a later, separate task)."""
    out = [
        EngineMark(time_ms=float(m.timestamp_ms), kind=GENERATOR_KIND_PREVIEW,
                   label=m.snap_grid, score=m.intensity)
        for m in midsong_generator.candidate_moments(
            uri, window_beats=window_beats, sensitivity=sensitivity, direction=direction)
    ]
    return sorted(out, key=lambda m: m.time_ms)


def _generator_marks(
    uri: str, *, window_beats: int, sensitivity: float, direction: str,
) -> Optional[list[EngineMark]]:
    """Both generator kinds, combined — the caller (marks_for's own
    consumer, spectra/api/testbed.py::_estimate_for) filters by mark_kind
    the same way it does for every other multi-kind engine. None only when
    there is genuinely nothing to show either way (no stored generated
    cues AND no analysis to preview from)."""
    marks = (_generator_stored_marks(uri)
            + _generator_preview_marks(uri, window_beats=window_beats,
                                       sensitivity=sensitivity, direction=direction))
    return sorted(marks, key=lambda m: m.time_ms) if marks else None


def _edges_marks(uri: str, *, window_beats: int, sensitivity: float,
                 direction: str = rhythmic_edges.DEFAULT_DIRECTION) -> Optional[list[EngineMark]]:
    edges = rhythmic_edges.edges_for_uri(uri, window_beats=window_beats,
                                        sensitivity=sensitivity, direction=direction)
    if edges is None:
        return None
    out = [EngineMark(time_ms=m.time_ms, kind=m.kind)
          for marks in edges.values() for m in marks]
    return sorted(out, key=lambda m: m.time_ms)


def marks_for(
    engine: str, uri: str, *,
    window_beats: int = rhythmic_edges.DEFAULT_WINDOW_BEATS,
    sensitivity: float = rhythmic_edges.DEFAULT_SENSITIVITY,
    direction: str = rhythmic_edges.DEFAULT_DIRECTION,
) -> Optional[list[EngineMark]]:
    """None = not available for this song (either the engine hasn't been
    precomputed for it, or — for librosa/generator/edges — no analysis
    exists yet). `window_beats`/`sensitivity`/`direction` are read by both
    the `edges` engine and the `generator` engine's own preview kind
    (2026-09-23, the R3 placement rule); every other engine ignores them."""
    if engine == ENGINE_LIBROSA:
        return _librosa_marks(uri)
    if engine == ENGINE_GENERATOR:
        return _generator_marks(uri, window_beats=window_beats,
                                sensitivity=sensitivity, direction=direction)
    if engine == ENGINE_EDGES:
        return _edges_marks(uri, window_beats=window_beats, sensitivity=sensitivity,
                            direction=direction)
    cached = testbed_cache.load(engine, uri)
    if cached is None:
        return None
    return [EngineMark(time_ms=float(m["time_ms"]), kind=m["kind"],
                       label=m.get("label"), score=m.get("score"))
            for m in cached.get("marks", [])]


def availability_for(uri: str, *,
                     stem_index: Optional[dict[str, str]] = None,
                     count_marks: bool = True) -> dict[str, dict]:
    """Per-engine {available, computed_at, mark_count} — the songs/engines
    listing's own status, so the frontend can say "not computed yet"
    instead of an empty lane.

    `stem_index`: a snapshot from analysis_reader.stem_index(), for a
    caller walking the whole corpus — a per-song stem_for_uri() lookup
    rebuilds the entire sidecar index on every miss, i.e. once per song
    that has no captured audio.

    `count_marks=False`: answer AVAILABILITY without parsing the engine's
    output, and report `mark_count: None` rather than a fabricated 0 — the
    whole-corpus listing's shape. librosa's own marks come out of a
    <stem>.librosa.json that is 400KB+ on his real corpus and are then
    discarded; the listing reads only `available`. The full parse stays on
    the per-song routes (/engines, /engine-marks), where exactly one song
    pays for it."""
    stem = (analysis_reader.stem_for_uri(uri) if stem_index is None
           else stem_index.get(uri))
    out: dict[str, dict] = {}
    for key, meta in ENGINES.items():
        if key == ENGINE_LIBROSA:
            if not count_marks:
                out[key] = {
                    "label": meta["label"], "kinds": meta["kinds"],
                    "available": analysis_reader.has_librosa_analysis(stem),
                    "computed_at": None,
                    "mark_count": None,
                }
                continue
            marks = librosa_marks_for_stem(stem)
            out[key] = {
                "label": meta["label"], "kinds": meta["kinds"],
                "available": marks is not None,
                "computed_at": None,
                "mark_count": len(marks) if marks else 0,
            }
        elif key == ENGINE_GENERATOR:
            # Fast path shares librosa's own has_librosa_analysis stat —
            # the preview kind needs analysis to produce anything, and the
            # stored kind's own emptiness can't be answered without a full
            # triggers.json parse anyway (the whole-corpus caller's reason
            # for count_marks=False in the first place).
            if not count_marks:
                out[key] = {
                    "label": meta["label"], "kinds": meta["kinds"],
                    "available": analysis_reader.has_librosa_analysis(stem),
                    "computed_at": None,
                    "mark_count": None,
                }
                continue
            # `stem is None` means the caller's own stem_index snapshot (or
            # a fresh lookup) already found no analysis for this song — skip
            # candidate_moments entirely rather than let it re-resolve the
            # stem itself and pay stem_for_uri's rebuild-on-miss a second
            # time (the property test_availability_with_a_stem_index_
            # snapshot_matches_the_lookup_path holds this function to).
            marks = _generator_stored_marks(uri) + (
                _generator_preview_marks(
                    uri, window_beats=rhythmic_edges.DEFAULT_WINDOW_BEATS,
                    sensitivity=rhythmic_edges.DEFAULT_SENSITIVITY,
                    direction=rhythmic_edges.DEFAULT_DIRECTION)
                if stem is not None else [])
            out[key] = {
                "label": meta["label"], "kinds": meta["kinds"],
                "available": bool(marks),
                "computed_at": None,
                "mark_count": len(marks),
            }
        elif key == ENGINE_EDGES:
            if not count_marks:
                out[key] = {
                    "label": meta["label"], "kinds": meta["kinds"],
                    "available": analysis_reader.has_librosa_analysis(stem),
                    "computed_at": None,
                    "mark_count": None,
                }
                continue
            # Same rebuild-avoidance as ENGINE_GENERATOR above — edges_for_uri
            # re-resolves the stem itself via beats_for_uri/stem_for_uri.
            marks = (_edges_marks(uri, window_beats=rhythmic_edges.DEFAULT_WINDOW_BEATS,
                                 sensitivity=rhythmic_edges.DEFAULT_SENSITIVITY)
                    if stem is not None else None)
            out[key] = {
                "label": meta["label"], "kinds": meta["kinds"],
                "available": marks is not None,
                "computed_at": None,
                "mark_count": len(marks) if marks else 0,
            }
        elif not count_marks:
            out[key] = {
                "label": meta["label"], "kinds": meta["kinds"],
                "available": testbed_cache.has_cache(key, uri),
                "computed_at": None,
                "mark_count": None,
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
