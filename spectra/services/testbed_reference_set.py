"""The plan's own four-song acceptance table, live on the /testbed page
(data/transition-alignment-plan/report.md section 4, ship task 4: "a small
'reference set' row on the Metrics card that runs /compare for the current
rule over the pinned songs (four calls, off the loop) and prints the
recall-at-one-beat table from section 1, so a knob change is judged on all
four at once, not one song at a time. This is the octave scout's
methodology on the page.")

The same four songs `scripts/check_transition_alignment.py` scores offline
(Soy Peor / Contra / Dopamine / El Apagón) — duplicated here rather than
imported, because that script repoints storage under a throwaway temp root
and must never be imported by a live request handler (the reverse is also
true: nothing here should be imported by that script, which builds its own
isolated copies of every store it touches).

Scored against the `generator:preview` lane ONLY — the placement rule
computed live with the CALLER'S knobs, never the `stored` lane (which
reflects whenever the room last actually generated, not what today's
knobs would produce). ONE-BEAT tolerance per song (60000 / that song's own
tempo_bpm), matching the report's own methodology (section 2: "the
complaint is in beats") — deliberately NOT the page's own tolerance
slider, which scores a different lane at a possibly non-beat tolerance.

`available=False` only when there is genuinely nothing to measure (no
tempo, i.e. no analysis at all) — a song with zero authored transitions or
zero preview candidates still reports (recall/precision naturally read 0),
since that is itself informative, not an error to hide."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from spectra.services import analysis_reader, testbed_engines, testbed_marks, testbed_metrics

REFERENCE_SONGS: list[tuple[str, str]] = [
    ("Soy Peor", "spotify:track:1JxhrUWZjuI8AOjDJ1JpMN"),
    ("Contra", "spotify:track:2zVg53xdC6RMpthWju6LRT"),
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT"),
    ("El Apagón", "spotify:track:0UvZcEfpzVyx47QsRbjyBz"),
]


@dataclass(frozen=True)
class ReferenceSongResult:
    name: str
    uri: str
    available: bool
    tolerance_ms: Optional[float]
    metrics: Optional[dict]


def compute(*, window_beats: int, sensitivity: float, direction: str,
            max_per_song: Optional[int] = None) -> list[ReferenceSongResult]:
    """One row per REFERENCE_SONGS entry, at the caller's own knob values.
    Runs the generator's preview kind fresh (read-only, nothing written) —
    the exact function generator:preview's own lane calls."""
    out: list[ReferenceSongResult] = []
    for name, uri in REFERENCE_SONGS:
        tempo = analysis_reader.tempo_bpm_for_uri(uri)
        if not tempo or tempo <= 0:
            out.append(ReferenceSongResult(name, uri, available=False,
                                           tolerance_ms=None, metrics=None))
            continue
        marks = testbed_engines.marks_for(
            testbed_engines.ENGINE_GENERATOR, uri,
            window_beats=window_beats, sensitivity=sensitivity,
            direction=direction, max_per_song=max_per_song,
        ) or []
        preview = [m.time_ms for m in marks
                  if m.kind == testbed_engines.GENERATOR_KIND_PREVIEW]
        transitions, _flares = testbed_marks.reference_marks_for_song(uri)
        tolerance_ms = 60000.0 / tempo
        result = testbed_metrics.match_marks(
            [m.timestamp_ms for m in transitions], preview, tolerance_ms)
        out.append(ReferenceSongResult(
            name, uri, available=True, tolerance_ms=tolerance_ms,
            metrics=testbed_metrics.match_result_dict(result),
        ))
    return out


def compute_dicts(**kwargs) -> list[dict]:
    return [
        {"name": r.name, "uri": r.uri, "available": r.available,
         "tolerance_ms": r.tolerance_ms, "metrics": r.metrics}
        for r in compute(**kwargs)
    ]
