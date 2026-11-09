"""How much a sung word stands out — one number per word, from five things
he ruled on (2026-11-09, data/lyrics-timing-plan/grilling-notes.md, Q1): sung
louder than the words around it, held long, landing on a strong beat, last
word of a line, and repeated in the hook.

THIS MODULE IS PURE. Words in, numbers out: no model, no audio playback, no
file or network I/O, nothing the show's event loop could wait on. The caller
(spectra/services/lyrics_timeline.py) reads the stored analysis and hands it
in, off the loop, and nothing downstream stores what comes out: the score
is recomputed from the sidecar on every read, so moving the sensitivity
slider or changing a weight here needs no re-import and leaves nothing
stale behind.

EACH FEATURE IS MEASURED ON THE CLOCK ITS OWN DATA IS ON, so no conversion
happens here at all:

  loud   — the capture's frames carry label timestamps, so a word's level
           is read over its label span (`ms`..`end_ms`).
  beat   — librosa's beats are positions in the WAV, so a word is compared
           with them by its WAV position (`wav_ms`).
  held, line end, hook — no clock in them.

EVERY NUMBER IS RELATIVE TO THIS SONG. Loudness and length are judged against
the words around the word, so a whispered ballad and a shouted chorus are
held to the same standard, and rap (short words, close together) is not read
as "nothing is held". No word list is involved either: the hook test works
from what repeats, so a Spanish song and an English one go through the same
arithmetic. Function words ("the", "de") are not filtered by name; they rank
low because they sit in the verses as well as the hook.

`conf` (the aligner's confidence) is deliberately not an input: the job's own
report found it does not identify which words are wrong, so gating on it
would throw away good words at random.

The weights and scales below are first guesses, set by looking at what they
pick on real songs (scripts/check_lyrics_emphasis.py). They are his to tune
by eye through the page's sensitivity slider; the labels and colour work that
consume the score are later steps of the plan.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Mapping, Optional, Sequence

import numpy as np

# How the five features add up. They sum to 1, so a score is 0..1.
WEIGHT_LOUD = 0.30
WEIGHT_HELD = 0.25
WEIGHT_BEAT = 0.20
WEIGHT_LINE_END = 0.10
WEIGHT_HOOK = 0.15

# "The words around it": this many words on each side.
NEIGHBOURS = 6

# Loud: full marks at this many dB above the neighbouring words' median.
# Masters are heavily limited (about 10 dB between a song's quietest and
# loudest sections), so a few dB is already a clear step up. Measured across
# 290 aligned songs: at 4 dB a loud word is about a third of what gets picked,
# at 6 dB about a seventh.
LOUD_FULL_DB = 4.0
# A word's level is this percentile of its frames, so a long note's fading
# tail does not count against it.
LOUD_PERCENTILE = 75.0
# Below this a frame is silence, and a level in dB would run off to -inf.
_RMS_FLOOR = 1e-5

# Held: a word's time per letter against its neighbours', so a long word is
# not "held" for being long. Very short words count as this many letters, or
# a quick "I" would read as a held note.
HELD_MIN_LETTERS = 3
# Full marks at this multiple of the neighbours' time per letter.
HELD_FULL_RATIO = 3.0
# Nothing shorter than this is held, however quick the words around it are.
HELD_MIN_MS = 220.0

# Beat: a word counts as landing on a beat within this distance, or a fifth
# of a beat on a fast song, whichever is tighter.
BEAT_WINDOW_MS = 90.0
BEAT_WINDOW_FRACTION = 0.2
# How strong each position in the bar is.
DOWNBEAT_STRENGTH = 1.0
MID_BAR_STRENGTH = 0.7
OTHER_BEAT_STRENGTH = 0.4

# Hook: a line sung this many times is a hook line.
HOOK_MIN_REPEATS = 2
# Full marks for a line sung this many times.
HOOK_FULL_REPEATS = 4

MIN_SENSITIVITY = 0.0
MAX_SENSITIVITY = 1.0
# 0.6 means a word has to reach 0.40: about one word in ten across the 290
# aligned songs (the middle four fifths of songs fall between 5% and 19%). The
# page's slider starts here; moving it stores nothing.
DEFAULT_SENSITIVITY = 0.6


@dataclass(frozen=True)
class Frames:
    """The capture's loudness curve: `timestamps_ms` are labels (the capture's
    clock), never decreasing; `rms` one value per timestamp."""
    timestamps_ms: np.ndarray
    rms: np.ndarray


@dataclass(frozen=True)
class WordFeatures:
    """Each 0..1. `line_end` is 0 or 1."""
    loud: float
    held: float
    beat: float
    line_end: float
    hook: float

    def as_dict(self) -> dict[str, float]:
        return {"loud": round(self.loud, 3), "held": round(self.held, 3),
                "beat": round(self.beat, 3), "line_end": round(self.line_end, 3),
                "hook": round(self.hook, 3)}


@dataclass(frozen=True)
class ScoredWord:
    index: int
    word: str
    norm: str
    line: int
    ms: float
    end_ms: float
    score: float
    features: WordFeatures


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _word_levels_db(words: Sequence[Mapping], frames: Optional[Frames]) -> list[Optional[float]]:
    """Each word's level in dB over its own label span; None where the
    capture holds no frame inside it (nothing was measured, so nothing is
    claimed)."""
    if frames is None or len(frames.timestamps_ms) == 0:
        return [None] * len(words)
    stamps = frames.timestamps_ms
    out: list[Optional[float]] = []
    for w in words:
        lo = int(np.searchsorted(stamps, float(w["ms"]), side="left"))
        hi = int(np.searchsorted(stamps, float(w["end_ms"]), side="left"))
        if hi <= lo:
            out.append(None)
            continue
        level = float(np.percentile(frames.rms[lo:hi], LOUD_PERCENTILE))
        out.append(20.0 * math.log10(max(level, _RMS_FLOOR)))
    return out


def _neighbour_values(values: Sequence[Optional[float]], i: int) -> list[float]:
    lo = max(0, i - NEIGHBOURS)
    hi = min(len(values), i + NEIGHBOURS + 1)
    return [v for j in range(lo, hi) if j != i and (v := values[j]) is not None]


def _loud_features(levels: Sequence[Optional[float]]) -> list[float]:
    out: list[float] = []
    for i, level in enumerate(levels):
        around = _neighbour_values(levels, i)
        if level is None or not around:
            out.append(0.0)
            continue
        out.append(_clamp01((level - median(around)) / LOUD_FULL_DB))
    return out


def _time_per_letter(word: Mapping) -> float:
    letters = max(HELD_MIN_LETTERS, len(str(word.get("n") or word.get("w") or "")))
    return max(0.0, float(word["end_ms"]) - float(word["ms"])) / letters


def _held_features(words: Sequence[Mapping]) -> list[float]:
    rates: list[Optional[float]] = [_time_per_letter(w) for w in words]
    out: list[float] = []
    for i, w in enumerate(words):
        around = _neighbour_values(rates, i)
        duration = float(w["end_ms"]) - float(w["ms"])
        typical = median(around) if around else 0.0
        if duration < HELD_MIN_MS or typical <= 0.0:
            out.append(0.0)
            continue
        ratio = float(rates[i] or 0.0) / typical
        out.append(0.0 if ratio <= 1.0
                   else _clamp01(math.log(ratio) / math.log(HELD_FULL_RATIO)))
    return out


def _beat_strengths(beats: Sequence[Mapping]) -> list[float]:
    """Bar position, from librosa's own downbeat flags: the downbeat, then
    the bar's middle, then everything else."""
    strengths: list[float] = []
    since_downbeat: Optional[int] = None
    for beat in beats:
        if beat.get("is_downbeat"):
            since_downbeat = 0
        elif since_downbeat is not None:
            since_downbeat += 1
        if since_downbeat == 0:
            strengths.append(DOWNBEAT_STRENGTH)
        elif since_downbeat == 2:
            strengths.append(MID_BAR_STRENGTH)
        else:
            strengths.append(OTHER_BEAT_STRENGTH)
    return strengths


def _beat_features(words: Sequence[Mapping], beats: Sequence[Mapping]) -> list[float]:
    if not beats:
        return [0.0] * len(words)
    ordered = sorted(beats, key=lambda b: float(b.get("ms", 0.0)))
    times = np.array([float(b.get("ms", 0.0)) for b in ordered], dtype=np.float64)
    strengths = _beat_strengths(ordered)
    window = BEAT_WINDOW_MS
    if len(times) >= 2:
        typical_beat = float(np.median(np.diff(times)))
        if typical_beat > 0.0:
            window = min(BEAT_WINDOW_MS, BEAT_WINDOW_FRACTION * typical_beat)
    out: list[float] = []
    for w in words:
        t = float(w.get("wav_ms", -1.0))
        if t < 0.0:
            out.append(0.0)
            continue
        i = int(np.searchsorted(times, t))
        candidates = [j for j in (i - 1, i) if 0 <= j < len(times)]
        j = min(candidates, key=lambda k: abs(times[k] - t))
        distance = abs(float(times[j]) - t)
        out.append(0.0 if distance > window
                   else strengths[j] * (1.0 - distance / (2.0 * window)))
    return out


def _line_end_features(words: Sequence[Mapping]) -> list[float]:
    last_of_line: dict[int, int] = {}
    for i, w in enumerate(words):
        last_of_line[int(w["line"])] = i
    return [1.0 if last_of_line[int(w["line"])] == i else 0.0 for i, w in enumerate(words)]


def _hook_features(words: Sequence[Mapping]) -> list[float]:
    """A hook line is a line sung at least HOOK_MIN_REPEATS times, compared
    by its words' normalised text. A word scores for how often its line is
    sung, scaled by the share of that word's occurrences that sit in hook
    lines: "Roxanne" appears only in the hook and keeps it all, while "the"
    is in the verses too and loses most of it."""
    by_line: dict[int, list[int]] = {}
    for i, w in enumerate(words):
        by_line.setdefault(int(w["line"]), []).append(i)
    text_of = {line: " ".join(str(words[i].get("n") or "") for i in members)
               for line, members in by_line.items()}
    repeats = Counter(text_of.values())
    hook_lines = {line for line, text in text_of.items()
                  if text and repeats[text] >= HOOK_MIN_REPEATS}
    total = Counter(str(w.get("n") or "") for w in words)
    in_hook = Counter(str(words[i].get("n") or "")
                      for line in hook_lines for i in by_line[line])
    span = max(1, HOOK_FULL_REPEATS - 1)
    out: list[float] = []
    for w in words:
        line = int(w["line"])
        norm = str(w.get("n") or "")
        if line not in hook_lines or not total[norm]:
            out.append(0.0)
            continue
        line_strength = _clamp01((repeats[text_of[line]] - 1) / span)
        out.append(line_strength * (in_hook[norm] / total[norm]))
    return out


def score_words(words: Sequence[Mapping], frames: Optional[Frames],
                beats: Sequence[Mapping]) -> list[ScoredWord]:
    """One ScoredWord per input word, in the same order. A word with no
    frames under it, or a song with no beats, simply earns nothing for that
    feature: an absent measurement is never read as a measured zero's
    opposite, and never raises."""
    if not words:
        return []
    loud = _loud_features(_word_levels_db(words, frames))
    held = _held_features(words)
    beat = _beat_features(words, beats)
    line_end = _line_end_features(words)
    hook = _hook_features(words)
    out: list[ScoredWord] = []
    for i, w in enumerate(words):
        f = WordFeatures(loud[i], held[i], beat[i], line_end[i], hook[i])
        score = (WEIGHT_LOUD * f.loud + WEIGHT_HELD * f.held + WEIGHT_BEAT * f.beat
                 + WEIGHT_LINE_END * f.line_end + WEIGHT_HOOK * f.hook)
        out.append(ScoredWord(index=i, word=str(w.get("w") or ""), norm=str(w.get("n") or ""),
                              line=int(w["line"]), ms=float(w["ms"]), end_ms=float(w["end_ms"]),
                              score=round(score, 4), features=f))
    return out


def clamp_sensitivity(value: Optional[float]) -> float:
    if value is None:
        return DEFAULT_SENSITIVITY
    return max(MIN_SENSITIVITY, min(MAX_SENSITIVITY, float(value)))


def threshold_for(sensitivity: Optional[float]) -> float:
    """The score a word must reach. Higher sensitivity picks more words:
    1 picks every word and 0 picks only a perfect score."""
    return 1.0 - clamp_sensitivity(sensitivity)


def emphasized(scored: Sequence[ScoredWord], sensitivity: Optional[float]) -> list[ScoredWord]:
    threshold = threshold_for(sensitivity)
    return [w for w in scored if w.score >= threshold]
