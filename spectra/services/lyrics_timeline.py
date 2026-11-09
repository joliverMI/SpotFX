"""One song's sung words, scored, on one stated clock — the test bed's Sung
words lane (data/lyrics-timing-plan, build step 2).

THIS HAS NO EFFECT ON THE ROOM. Nothing in the show reads this module: no
flare, colour change or scene comes from it, and the page cannot push one of
its marks to his real triggers (spectra/services/testbed_promote.py refuses
the engine). Labels, matching and colour events are later steps of the plan.

THE LANE'S CLOCK IS THE CAPTURE'S LABEL CLOCK, deliberately, and it is the
one the show runs on. A word's `ms` is the capture label of that moment in
the audio (the job looks it up frame by frame in the song's `.npz`). A
trigger's `timestamp_ms` is compared directly with the show clock, and the
sync lock measures the live audio against those same labels, so a word at
`ms` = X and a flare at `timestamp_ms` = X happen together in the room. The
lane draws both at their stored numbers with nothing converted, which also
makes it what the later steps act on: an imprint within 2 s of a flare is a
distance on this clock. docs/SPECTRA_TIMING_CONVENTIONS.md's "Sung-word
times" row is the recorded statement.

WHERE THAT CANNOT BE MADE TRUE, THE SONG IS FLAGGED AND NOT DRAWN AS ALIGNED.
His marks were placed through the Timeline's beat grid, which reaches song
time as `beat + first label` (the "naive" frame: position in the WAV plus the
capture's first label). On most captures the naive frame and the labels agree
to within a few milliseconds. On about a third of the library the WAV loses
time against its labels (drift, holes), by up to several seconds, and there
the two truths part: the place a mark was put and the place it fires are no
longer the same moment, so a word and a flare he meant together would draw
apart while a pair he did not mean could draw together. No single position
is right for both, so `Clock.flagged` is set and the page says so, drawing
the words without the alignment guides and withholding the scores. The slip
is measured per word from the sidecar's own two positions (`ms` against
`wav_ms + capture_offset_ms`), and SLIP_FLAG_MS is the beat lanes' own tightest
tolerance: past it the mismatch is a visible, score-changing distance.

The waveform and the beat lanes beside this one are on the naive frame too,
which is one more thing the flag warns about.

Runs on a worker thread (spectra/api/testbed.py), like every other per-song
read on this page: it parses the sidecar, the `.librosa.json` and the `.npz`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from spectra import config
from spectra.services import analysis_reader, lyrics_emphasis, lyrics_sidecar

LANE_CLOCK = "capture_label"

# The largest distance between a word's label and its naive position at which
# a word and a mark can still honestly be drawn as aligned. This is the beat
# lanes' tightest tolerance on the test bed (min(200 ms, 0.4 of a beat)).
SLIP_FLAG_MS = 200.0

STATUS_OK = "ok"
STATUS_NONE = "none"          # no word timeline imported for this song
STATUS_INVALID = "invalid"    # the file is there but is not a usable timeline
STATUS_STALE = "stale"        # the capture changed after it was aligned


@dataclass(frozen=True)
class Clock:
    lane_clock: str
    max_slip_ms: Optional[float]
    flagged: bool
    note: Optional[str]

    def as_dict(self) -> dict:
        return {"lane_clock": self.lane_clock, "max_slip_ms": self.max_slip_ms,
                "flagged": self.flagged, "note": self.note}


@dataclass(frozen=True)
class Timeline:
    uri: str
    status: str
    note: Optional[str] = None
    lang: Optional[str] = None
    provenance: Optional[str] = None
    mode: Optional[str] = None
    clock: Clock = field(default_factory=lambda: Clock(LANE_CLOCK, None, False, None))
    scored: tuple[lyrics_emphasis.ScoredWord, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status == STATUS_OK


# Punctuation a printed word sheds at its edges ("life," draws as "life",
# "¿Qué?" as "Qué"); a word's own apostrophes and hyphens stay.
_EDGE_PUNCTUATION = ".,;:!?¡¿\"“”()[]…—–-'’"


def display_word(word: str) -> str:
    return word.strip(_EDGE_PUNCTUATION) or word


def measure_clock(words: Sequence[dict], capture_offset_ms: float) -> Clock:
    """How far the two ways of reaching song time disagree over this song's
    own words: a word's label against its naive position. Measured over the
    sung words because that is where a comparison will be made."""
    if not words:
        return Clock(LANE_CLOCK, None, False, None)
    slip = max(abs(float(w["ms"]) - (float(w["wav_ms"]) + float(capture_offset_ms)))
               for w in words)
    flagged = slip > SLIP_FLAG_MS
    note = None
    if flagged:
        note = (f"This capture's audio slips against its time labels by up to "
                f"{slip / 1000:.1f} s, so your marks and the words below cannot "
                "be compared here: a mark was placed by the audio, and fires by "
                "the labels. The words are drawn where they are sung, the "
                "waveform and beat lanes are not, and no scores are shown.")
    return Clock(LANE_CLOCK, round(slip, 1), flagged, note)


def build_timeline(uri: str, doc: dict, frames: Optional[lyrics_emphasis.Frames],
                   beats: Sequence[dict]) -> Timeline:
    """The pure half: an already-validated sidecar and its stored analysis to
    a scored Timeline."""
    words = doc["words"]
    clock = measure_clock(words, float(doc["stamp"]["capture_offset_ms"]))
    return Timeline(
        uri=uri, status=STATUS_OK, lang=doc.get("lang"), provenance=doc.get("provenance"),
        mode=doc.get("mode"), clock=clock,
        scored=tuple(lyrics_emphasis.score_words(words, frames, beats)))


def timeline_for_uri(uri: str, *, stem_index: Optional[dict[str, str]] = None) -> Timeline:
    """Read and score one song. A missing, malformed or out-of-date sidecar
    comes back as a status with a sentence, never an exception, so the lane
    can say which of those it is."""
    stem = (analysis_reader.stem_for_uri(uri) if stem_index is None
            else stem_index.get(uri))
    if not analysis_reader.has_lyrics(stem):
        return Timeline(uri, STATUS_NONE, "No sung words have been imported for this song.")

    doc = analysis_reader.lyrics_for_stem(stem)
    problems = lyrics_sidecar.validate(doc, expected_stem=stem)
    if problems:
        return Timeline(uri, STATUS_INVALID,
                        f"This song's word timeline cannot be used ({', '.join(problems)}).")

    changed = lyrics_sidecar.problems_against_capture(doc, config.AUDIO_SHAPES_DIR,
                                                      require_wav=False)
    if changed:
        return Timeline(uri, STATUS_STALE,
                        "This song was captured again after its words were aligned, "
                        f"so the word times no longer apply ({', '.join(changed)}).")

    loudness = analysis_reader.capture_loudness_for_stem(stem)
    frames = lyrics_emphasis.Frames(*loudness) if loudness is not None else None
    analysis = analysis_reader.librosa_analysis_for_stem(stem) or {}
    return build_timeline(uri, doc, frames, analysis.get("beats") or [])


def emphasized_words(timeline: Timeline,
                     sensitivity: Optional[float]) -> list[lyrics_emphasis.ScoredWord]:
    return lyrics_emphasis.emphasized(timeline.scored, sensitivity)


def payload(timeline: Timeline) -> dict:
    """What GET /api/testbed/lyrics returns. Every word with its score and
    none of the slider's decisions: which words are emphasized at a given
    sensitivity is the engine lane's own read, so it is computed in one
    place and never stored."""
    return {
        "uri": timeline.uri,
        "status": timeline.status,
        "note": timeline.note,
        "lang": timeline.lang,
        "provenance": timeline.provenance,
        "mode": timeline.mode,
        "clock": timeline.clock.as_dict(),
        "default_sensitivity": lyrics_emphasis.DEFAULT_SENSITIVITY,
        "words": [{"word": display_word(w.word), "line": w.line, "ms": w.ms,
                   "end_ms": w.end_ms, "score": w.score} for w in timeline.scored],
    }
