"""THE DROP DETECTOR — break and return (drop-detection plan, phase 2).

The Admiral approved the plan on 2026-10-05 ("Do all recs"): find each drop
where the bass comes back after a break, place its lull and charge from it,
and keep the three as one sequence. Plan and evidence:
/home/javi/fleet-spotfx/data/drop-detection-plan/report.md (sections 5-7)
and its testbed/ (dd_feat.py, dd_methods.py, drop_testbed.py). This module
is METHOD B of that testbed, ported line for line — the arithmetic is the
measured thing, so it is reproduced exactly rather than re-derived, and
scripts/check_drop_detector.py holds the port to the testbed's own output
on the four test songs.

WHAT IT READS. Only what every captured song already has: the stored audio
shape (`<stem>.npz` — total/low/high energy every ~12 ms, ALREADY IN SONG
TIME) and the librosa file (`<stem>.librosa.json` — tempo and beats, in
recording time, shifted to song time by the shape's own first timestamp:
the capture offset, testbed_audio.capture_offset_ms's own definition).
No re-capture, no WAV, no new analysis run. Every time this module returns
is SONG time — the show clock's frame, the same frame his triggers are in.

THE RULE, in plain words (report section 5, method B):

  A CANDIDATE is a bass spike: a local maximum of the ~60 ms rise of the
  song-normalised low band (find_attacks), at least CANDIDATE_MIN_RISE.
  A candidate is a DROP when the bass hits hard (rise >= 0.25) AND the
  level steps up (contrast >= 0.22) AND EITHER there was a break of at
  least 3/4 beat that followed loud music ("loud -> quiet -> loud", so an
  intro's first bass entry does not count) OR the bar before had clearly
  thinner bass. Score = the step up + a bonus for the break. A second
  path accepts "dense kick roll, gap, hard hit" where the level does not
  step up (Dopamine's second drop). Candidates closer than NMS_BEATS keep
  the strongest, then each moves to the FIRST strong spike of its hit
  (his rule: "the drop should be on the first bass/beat spike").

  Two tiers (decision 2): CONFIDENT at score >= 1.0 (fires on its own —
  spectra/services/drop_firing.py), SUGGESTED at >= 0.7 (shown, waits for
  his confirm). Both thresholds are room settings (drop_confident_score /
  drop_suggested_score) so the test bed's Drops lane can tune them by eye.

  THE LULL ("right after the last beat spike leading into the drop") —
  rule `tail`: find where the bass goes quiet before the drop; if the last
  hit before that quiet is short (the quiet starts within 1.25 beats of
  its onset) the lull is where the bass goes quiet; if it rings on for
  1.25-3 beats the lull is that hit's own onset; a longer fade, one beat
  before it ends. A drop with no break before it gets NO lull, and no
  charge either (the plan's "drop only" shape).

  THE CHARGE ("one section or more before the lull") — rule `build2`: the
  strongest change in the music (energy step + rising highs + a kick roll
  starting) between 5.5 and 16.5 beats before the lull — where his own
  charges sit, median 10 beats — on the nearest bass/beat spike; 10 beats
  before the lull when nothing stands out.

THE GUARDS (report section 7.4), applied after detection and recorded on
each sequence so nothing is silently moved:

  EDGES. A drop in the song's first or last EDGE_MS (15 s) is EXCLUDED —
  the High/Low cue rule (show_cues.EDGE_MS) — and listed with that reason.
  CAP. At most one CONFIDENT sequence per CAP_SECONDS_PER_CONFIDENT (45 s)
  of song, strongest first; the rest are DEMOTED to suggested (22 songs
  of his library would otherwise get five or more).
  SPACING. A later sequence's charge may not start before the earlier
  drop's two-bar tail (TAIL_BEATS) ends: it moves to the first beat at or
  after the tail, or is dropped when that leaves no room before its lull;
  a lull inside the tail takes the charge with it (the later sequence
  becomes drop-only). Every detected sequence counts as "earlier", either
  tier — a suggestion can be confirmed, and its tail is then real.
  CAPTURE START. A capture that starts mid-song cannot yield anything
  before its first sample; `captured_from_ms` says where it starts so a
  surface can say "not captured" there instead of showing nothing.

Pure: analyse() reads the two files (through analysis_reader and the
config paths, nothing else), detect() is arithmetic over that. The store,
the stamp and the merge with his edits are spectra/services/
drop_sequences.py.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from spectra import config
from spectra.services import analysis_reader

logger = logging.getLogger(__name__)

DETECTOR_VERSION = "1"
"""Bump whenever detection or placement changes what an unchanged song
would produce: it is part of every stored detection's stamp, so a bump
re-detects every song on its next play (drop_sequences.py)."""

FRAME_MS = 12.0
ATTACK_MIN_RISE = 0.12        # every bass spike the rules count or snap to
ATTACK_HOLD_MS = 120.0
CANDIDATE_MIN_RISE = 0.18     # a bass spike that could be a drop
NMS_BEATS = 6.0               # drops closer than this keep the strongest

CONFIDENT_SCORE = 1.0         # report section 5: "confident", may fire alone
SUGGESTED_SCORE = 0.7         # report section 5: "suggested", waits for him

EDGE_MS = 15_000
CAP_SECONDS_PER_CONFIDENT = 45
TAIL_BEATS = 8.0              # the protected two bars after a drop
RAMP_FLOOR_MS = 200           # the engine's own ramp floor (scene_response)

MIN_FRAMES = 500
MIN_BEATS = 16

TIER_CONFIDENT = "confident"
TIER_SUGGESTED = "suggested"


# ── the song ───────────────────────────────────────────────────────────────

@dataclass
class SongData:
    """Everything detection reads for one song, already in SONG time."""
    uri: str
    stem: str
    t: np.ndarray            # envelope timestamps, song ms (int64)
    low: np.ndarray
    high: np.ndarray
    total: np.ndarray
    tempo: float
    beat_ms: np.ndarray      # song ms (float)
    duration_ms: int

    @property
    def beat_len(self) -> float:
        return 60000.0 / self.tempo if self.tempo > 0 else 500.0

    @property
    def offset_ms(self) -> int:
        return int(self.t[0])


class Unavailable(Exception):
    """This song cannot be analysed (no capture, too short, no beats). The
    message is the sentence a surface shows."""


def load_song(uri: str) -> SongData:
    """Read one song's stored audio shape and beats. Raises Unavailable
    (with the reason) when either is missing or too short to judge."""
    stem = analysis_reader.stem_for_uri(uri)
    if stem is None:
        raise Unavailable("this song has no captured audio shape yet")
    npz_path = config.AUDIO_SHAPES_DIR / f"{stem}.npz"
    if not npz_path.exists():
        raise Unavailable("this song's audio shape is missing")
    doc = analysis_reader.librosa_analysis_for_stem(stem)
    if not doc:
        raise Unavailable("this song has no beat analysis yet")
    try:
        z = np.load(npz_path)
        t = z["timestamps_ms"].astype(np.int64)
        low = z["rms_low"].astype(np.float64)
        high = z["rms_high"].astype(np.float64)
        total = z["rms_total"].astype(np.float64)
    except Exception as exc:                             # noqa: BLE001
        raise Unavailable(f"this song's audio shape could not be read ({exc})") from exc
    if len(t) < MIN_FRAMES:
        raise Unavailable("this song's audio shape is too short to judge")
    beats = doc.get("beats") or []
    if len(beats) < MIN_BEATS:
        raise Unavailable("this song has too few beats in its analysis")
    off = int(t[0])
    beat_ms = np.array([float(b.get("ms", 0.0) or 0.0) for b in beats], dtype=float) + off
    try:
        tempo = float(doc.get("tempo_bpm") or 120.0)
    except (TypeError, ValueError):
        tempo = 120.0
    sidecar = analysis_reader.capture_sidecar(uri) or {}
    try:
        duration = int(sidecar.get("duration_ms") or t[-1])
    except (TypeError, ValueError):
        duration = int(t[-1])
    return SongData(uri=uri, stem=stem, t=t, low=low, high=high, total=total,
                    tempo=tempo, beat_ms=beat_ms, duration_ms=duration)


# ── the shape, prepared (dd_feat.prep) ─────────────────────────────────────

def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same") if n > 1 else x


def find_attacks(t: np.ndarray, xs: np.ndarray, min_rise: float,
                 hold_ms: float = ATTACK_HOLD_MS) -> tuple[np.ndarray, np.ndarray]:
    """Bass spikes: local maxima of the ~60 ms rise of a normalised
    envelope. The onset is the first frame of that rise."""
    r = np.zeros_like(xs)
    r[2:-2] = xs[4:] - xs[:-4]
    step = max(1, int(hold_ms / FRAME_MS))
    out_t, out_r = [], []
    n = len(r)
    i = 2
    while i < n - 2:
        if r[i] >= min_rise and r[i] >= r[max(0, i - step):i + step + 1].max():
            j = i
            while j > 1 and xs[j - 1] < xs[j] - 0.01:
                j -= 1
            out_t.append(int(t[j]))
            out_r.append(float(r[i]))
            i += step
        else:
            i += 1
    return np.array(out_t, dtype=np.int64), np.array(out_r)


@dataclass
class Prep:
    song: SongData
    low: np.ndarray          # normalised (99.5th percentile = 1), 36 ms smoothed
    high: np.ndarray
    total: np.ndarray
    cs: dict                 # cumulative sums for O(1) window means
    att_ms: np.ndarray       # every bass spike (rise >= ATTACK_MIN_RISE)
    att_rise: np.ndarray

    def mean(self, band: str, a_ms: float, b_ms: float) -> float:
        t = self.song.t
        i0, i1 = np.searchsorted(t, [a_ms, b_ms])
        if i1 <= i0:
            return 0.0
        c = self.cs[band]
        return float((c[i1] - c[i0]) / (i1 - i0))


def prep(song: SongData) -> Prep:
    bands = {}
    for b in ("low", "high", "total"):
        x = getattr(song, b)
        bands[b] = _smooth(x / (np.percentile(x, 99.5) + 1e-9), 3)
    cs = {b: np.concatenate([[0.0], np.cumsum(v)]) for b, v in bands.items()}
    att_ms, att_rise = find_attacks(song.t, bands["low"], ATTACK_MIN_RISE)
    return Prep(song, bands["low"], bands["high"], bands["total"], cs, att_ms, att_rise)


def find_break(p: Prep, band: str, a_ms: float, thr: float, max_back_ms: float,
               pickup_ms: float, min_len_ms: float) -> tuple[float, float]:
    """The BREAK before a hit at a_ms: the latest stretch where the band sat
    below `thr` for at least min_len_ms, ending no earlier than pickup_ms
    before the hit (a riser or vocal pickup may fill the last beat). Blips
    under 60 ms do not end a break. (a_ms, a_ms) when there is none."""
    t = p.song.t
    x = getattr(p, band)
    i1 = int(np.searchsorted(t, a_ms - 12))
    i0 = int(np.searchsorted(t, a_ms - max_back_ms))
    if i1 - i0 < 4:
        return a_ms, a_ms
    q = x[i0:i1] < thr
    n = len(q)
    j = 0
    while j < n:
        if not q[j]:
            k = j
            while k < n and not q[k]:
                k += 1
            if k - j <= 5 and j > 0 and k < n:
                q[j:k] = True
            j = k
        else:
            j += 1
    j = n - 1
    limit = n - 1 - int(pickup_ms / FRAME_MS)
    while j >= max(0, limit) and not q[j]:
        j -= 1
    if j < max(0, limit) or j < 0 or not q[j]:
        return a_ms, a_ms
    end = j
    while j >= 0 and q[j]:
        j -= 1
    start = j + 1
    if (end - start + 1) * FRAME_MS < min_len_ms:
        return a_ms, a_ms
    return float(t[i0 + start]), float(t[min(i0 + end + 1, len(t) - 1)])


def break_bounds(p: Prep, drop_ms: float) -> tuple[float, float]:
    """(bass break start, everything break start) before a hit at drop_ms
    — drop_ms itself when that band never went quiet."""
    B = p.song.beat_len
    post4 = p.mean("low", drop_ms, drop_ms + 4 * B)
    post4t = p.mean("total", drop_ms, drop_ms + 4 * B)
    bs_low, _ = find_break(p, "low", drop_ms, max(0.02, 0.35 * post4), 24 * B, 1.5 * B, 0.5 * B)
    bs_tot, _ = find_break(p, "total", drop_ms, max(0.03, 0.45 * post4t), 24 * B, 1.5 * B, 0.5 * B)
    return bs_low, bs_tot


# ── scoring one candidate (dd_feat.candidate_features + dd_methods.score_B) ──

@dataclass(frozen=True)
class Candidate:
    ms: int
    score: float
    rise: float
    step: float              # the contrast: how far the level stepped up
    break_beats: float       # the break before it, in beats
    loud_before: bool        # the music was loud before the break
    path: str                # "step" | "roll" | "none"


def score_candidate(p: Prep, a_ms: float, rise: float) -> Candidate:
    B = p.song.beat_len
    post4 = p.mean("low", a_ms, a_ms + 4 * B)
    post4t = p.mean("total", a_ms, a_ms + 4 * B)
    pre_low_4 = p.mean("low", a_ms - 4 * B, a_ms - 20)
    pre_total_4 = p.mean("total", a_ms - 4 * B, a_ms - 20)
    con_low_4 = post4 - pre_low_4
    con_total_4 = post4t - pre_total_4
    bs_low, _ = find_break(p, "low", a_ms, max(0.02, 0.35 * post4), 24 * B, 1.5 * B, 0.5 * B)
    bs_tot, _ = find_break(p, "total", a_ms, max(0.03, 0.45 * post4t), 24 * B, 1.5 * B, 0.5 * B)
    bs = min(bs_low, bs_tot)
    brk = (a_ms - bs) / B
    pre_brk_total = p.mean("total", bs - 8 * B, bs)
    r8 = np.searchsorted(p.att_ms, [bs - 8 * B, bs])
    r16 = np.searchsorted(p.att_ms, [bs - 16 * B, bs - 8 * B])
    roll8 = (r8[1] - r8[0]) / 8.0
    roll_accel = (r8[1] - r8[0]) / 8.0 - (r16[1] - r16[0]) / 8.0

    contrast = max(0.0, con_low_4) + max(0.0, con_total_4)
    loud_before = pre_brk_total >= 0.35 * post4t
    thin = pre_low_4 <= 0.6 * post4
    has_break = brk >= 0.75 and loud_before
    ok = rise >= 0.25 and contrast >= 0.22 and (has_break or (thin and loud_before))
    step_score = contrast + (0.08 * min(brk, 4.0) if has_break else 0.0)
    roll_ok = rise >= 0.5 and has_break and roll8 >= 1.75 and roll_accel >= 0.75
    roll_score = 0.55 + 0.1 * min(roll8, 3.0) + max(0.0, contrast)
    a = step_score if ok else 0.0
    b = roll_score if roll_ok else 0.0
    path = "none" if a == 0.0 and b == 0.0 else ("roll" if b > a else "step")
    return Candidate(ms=int(a_ms), score=float(max(a, b)), rise=float(rise),
                     step=float(contrast), break_beats=float(brk),
                     loud_before=bool(loud_before), path=path)


# ── analysis (the expensive half, memoised per song) ───────────────────────

@dataclass
class SongAnalysis:
    song: SongData
    prep: Prep
    candidates: list[Candidate]

    @property
    def cand_ms(self) -> np.ndarray:
        return np.array([c.ms for c in self.candidates], dtype=np.int64)

    @property
    def cand_score(self) -> np.ndarray:
        return np.array([c.score for c in self.candidates], dtype=float)


def analyse_song(song: SongData) -> SongAnalysis:
    p = prep(song)
    keep = p.att_rise >= CANDIDATE_MIN_RISE
    cands = [score_candidate(p, float(a), float(r))
             for a, r in zip(p.att_ms[keep], p.att_rise[keep])]
    return SongAnalysis(song=song, prep=p, candidates=cands)


_memo: "OrderedDict[tuple, SongAnalysis]" = OrderedDict()
_memo_lock = threading.Lock()
MEMO_SONGS = 8


def _input_signature(uri: str) -> Optional[tuple]:
    """(path, mtime_ns, size) of the files analyse() reads — a cheap stat,
    so a recapture is seen at once and an unchanged song is not re-read."""
    stem = analysis_reader.stem_for_uri(uri)
    if stem is None:
        return None
    sig = []
    for suffix in (".npz", ".librosa.json", ".json"):
        path = config.AUDIO_SHAPES_DIR / f"{stem}{suffix}"
        try:
            st = path.stat()
            sig.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(path), None, None))
    return tuple(sig)


def analyse(uri: str) -> SongAnalysis:
    """The scored candidates for one song (raises Unavailable). Memoised on
    the input files' own stat signature, bounded to MEMO_SONGS songs, so
    the test bed can re-run detect() at new thresholds for free."""
    sig = _input_signature(uri)
    key = (uri, sig)
    with _memo_lock:
        hit = _memo.get(key)
        if hit is not None:
            _memo.move_to_end(key)
            return hit
    result = analyse_song(load_song(uri))
    with _memo_lock:
        for k in [k for k in _memo if k[0] == uri]:
            _memo.pop(k, None)
        _memo[key] = result
        while len(_memo) > MEMO_SONGS:
            _memo.popitem(last=False)
    return result


def reset_memo() -> None:
    """Tests."""
    with _memo_lock:
        _memo.clear()


# ── choosing drops (dd_methods.detect_B + first_spike) ─────────────────────

def _nms_indices(ms: np.ndarray, score: np.ndarray, min_gap_ms: float) -> list[int]:
    """Strongest first, nothing within min_gap_ms of a kept one — the
    testbed's nms() exactly (same argsort, so ties break the same way),
    returning indices so the winning candidate itself is kept."""
    order = np.argsort(-score)
    kept: list[int] = []
    for i in order:
        if all(abs(ms[i] - ms[k]) >= min_gap_ms for k in kept):
            kept.append(int(i))
    return kept


def first_spike(p: Prep, ms: int) -> int:
    """His rule: the drop is on the FIRST strong spike of the hit — a drop
    is often two or three hits in quick succession (within 0.6 beat)."""
    B = p.song.beat_len
    m = (p.att_ms >= ms - 0.6 * B) & (p.att_ms <= ms)
    if not m.any():
        return ms
    idx = np.where(m)[0]
    top = p.att_rise[idx].max()
    for k in idx:
        if p.att_rise[k] >= 0.6 * top:
            return int(p.att_ms[k])
    return ms


def strongest_attack_near(p: Prep, t_ms: float, radius_ms: float,
                          min_rise: float = CANDIDATE_MIN_RISE) -> Optional[tuple[int, float]]:
    m = (np.abs(p.att_ms - t_ms) <= radius_ms) & (p.att_rise >= min_rise)
    if not m.any():
        return None
    idx = np.where(m)[0]
    k = idx[int(np.argmax(p.att_rise[idx]))]
    return int(p.att_ms[k]), float(p.att_rise[k])


# ── placing the lull and the charge (dd_methods.place_lull / place_charge) ──

def blob_start(p: Prep, end_ms: float, band: str = "low", back_beats: float = 4.0) -> float:
    """Start of the last contiguous loud run that ends at end_ms (the final
    hit and its tail before the music goes quiet)."""
    s = p.song
    x = getattr(p, band)
    t = s.t
    i = int(np.searchsorted(t, end_ms)) - 1
    lo = int(np.searchsorted(t, end_ms - back_beats * s.beat_len))
    seg = x[lo:i + 1]
    if len(seg) < 4:
        return end_ms
    level = max(0.05, 0.5 * float(np.percentile(seg[-max(4, len(seg) // 4):], 80)))
    j = i
    while j > lo and x[j] < level:
        j -= 1
    dip = 0
    start = j
    while j > lo:
        if x[j] >= level:
            dip = 0
            start = j
        else:
            dip += 1
            if dip > 3:
                break
        j -= 1
    return float(t[start])


def place_lull(p: Prep, drop_ms: float) -> Optional[int]:
    """The lull rule `tail` (report section 6.1). None when there is no
    break of at least 3/4 beat before the drop."""
    B = p.song.beat_len
    bs_low, bs_tot = break_bounds(p, drop_ms)
    c_any = min(bs_low, bs_tot)
    if drop_ms - c_any < 0.75 * B:
        return None
    c_low = bs_low if drop_ms - bs_low >= 0.75 * B else c_any
    ev = blob_start(p, c_low)
    d = c_low - ev
    if d <= 1.25 * B:
        return int(c_low)
    if d <= 3.0 * B:
        return int(ev)
    return int(max(c_any, c_low - B))


CHARGE_BACK_MIN_BEATS = 5.5
CHARGE_BACK_MAX_BEATS = 16.5
CHARGE_DEFAULT_BEATS = 10.0


def _to_beat(s: SongData, t_ms: float) -> int:
    return int(s.beat_ms[int(np.argmin(np.abs(s.beat_ms - t_ms)))])


def place_charge(p: Prep, anchor_ms: float) -> int:
    """The charge rule `build2` (report section 6.2), anchored on the lull."""
    s = p.song
    B = s.beat_len
    best_t, best_sc = None, 0.06
    beats = s.beat_ms[(s.beat_ms >= anchor_ms - CHARGE_BACK_MAX_BEATS * B)
                      & (s.beat_ms <= anchor_ms - CHARGE_BACK_MIN_BEATS * B)]
    for b in beats:
        e = p.mean("total", b, b + 4 * B) - p.mean("total", b - 4 * B, b)
        h = p.mean("high", b, b + 4 * B) - p.mean("high", b - 4 * B, b)
        a1 = np.searchsorted(p.att_ms, [b, b + 4 * B])
        a0 = np.searchsorted(p.att_ms, [b - 4 * B, b])
        roll = ((a1[1] - a1[0]) - (a0[1] - a0[0])) / 4.0
        sc = abs(e) + max(0.0, h) + 0.12 * max(0.0, roll)
        if sc > best_sc:
            best_sc, best_t = sc, b
    if best_t is None:
        return _to_beat(s, anchor_ms - CHARGE_DEFAULT_BEATS * B)
    hit = strongest_attack_near(p, best_t, 0.5 * B, min_rise=ATTACK_MIN_RISE)
    return int(hit[0]) if hit else int(best_t)


# ── detection ──────────────────────────────────────────────────────────────

@dataclass
class DetectedSequence:
    """One detected charge -> lull -> drop. `key` identifies it for his
    overrides (drop_sequences.py): the drop time it was found at."""
    key: str
    drop_ms: int
    lull_ms: Optional[int]
    charge_ms: Optional[int]
    score: float
    tier: str
    break_beats: float
    step: float
    rise: float
    path: str
    loud_before: bool
    capped: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DetectedSequence":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Excluded:
    drop_ms: int
    score: float
    reason: str


@dataclass
class SongDetection:
    uri: str
    detector_version: str
    confident_score: float
    suggested_score: float
    tempo_bpm: float
    beat_ms: float
    captured_from_ms: int
    captured_to_ms: int
    duration_ms: int
    sequences: list[DetectedSequence] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "uri": self.uri, "detector_version": self.detector_version,
            "confident_score": self.confident_score,
            "suggested_score": self.suggested_score,
            "tempo_bpm": self.tempo_bpm, "beat_ms": self.beat_ms,
            "captured_from_ms": self.captured_from_ms,
            "captured_to_ms": self.captured_to_ms,
            "duration_ms": self.duration_ms,
            "sequences": [s.as_dict() for s in self.sequences],
            "excluded": [asdict(e) for e in self.excluded],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SongDetection":
        return cls(
            uri=d["uri"], detector_version=str(d.get("detector_version")),
            confident_score=float(d.get("confident_score", CONFIDENT_SCORE)),
            suggested_score=float(d.get("suggested_score", SUGGESTED_SCORE)),
            tempo_bpm=float(d.get("tempo_bpm") or 120.0),
            beat_ms=float(d.get("beat_ms") or 500.0),
            captured_from_ms=int(d.get("captured_from_ms") or 0),
            captured_to_ms=int(d.get("captured_to_ms") or 0),
            duration_ms=int(d.get("duration_ms") or 0),
            sequences=[DetectedSequence.from_dict(s) for s in d.get("sequences") or []],
            excluded=[Excluded(**e) for e in d.get("excluded") or []],
        )


def drop_key(drop_ms: int) -> str:
    return f"drop:{int(drop_ms)}"


def key_ms(key: str) -> Optional[int]:
    """The drop time a key names, or None when it is not a detection key."""
    if not isinstance(key, str) or not key.startswith("drop:"):
        return None
    try:
        return int(key.split(":", 1)[1])
    except ValueError:
        return None


def tier_for(score: float, confident_score: float, suggested_score: float) -> Optional[str]:
    """Inverted thresholds never hide a detection: anything at or above
    the lower one is at least suggested, and confident wins where both
    apply."""
    if score >= confident_score:
        return TIER_CONFIDENT
    if score >= min(confident_score, suggested_score):
        return TIER_SUGGESTED
    return None


def raw_drops(analysis: SongAnalysis, floor: float) -> list[tuple[int, Candidate]]:
    """Every drop at or above `floor`, thinned and on its first spike:
    [(drop_ms, the candidate that won the hit)] in time order."""
    if not analysis.candidates:
        return []
    ms = analysis.cand_ms
    sc = analysis.cand_score
    m = sc >= floor
    if not m.any():
        return []
    idx = np.where(m)[0]
    kept = _nms_indices(ms[m], sc[m], NMS_BEATS * analysis.song.beat_len)
    out, seen = [], set()
    for k in kept:
        cand = analysis.candidates[int(idx[k])]
        f = first_spike(analysis.prep, cand.ms)
        if f not in seen:
            seen.add(f)
            out.append((f, cand))
    return sorted(out, key=lambda x: (x[0], x[1].score))


def place_sequence(p: Prep, drop_ms: int) -> tuple[Optional[int], Optional[int], float]:
    """(lull, charge, break_beats) for a drop — the recommended rules."""
    L = place_lull(p, drop_ms)
    C = place_charge(p, L) if L is not None else None
    bs_low, bs_tot = break_bounds(p, drop_ms)
    return L, C, round((drop_ms - min(bs_low, bs_tot)) / p.song.beat_len, 2)


def first_beat_at_or_after(song: SongData, t_ms: float) -> int:
    after = song.beat_ms[song.beat_ms >= t_ms]
    return int(after[0]) if len(after) else int(round(t_ms))


def apply_spacing(seqs: list[DetectedSequence], beat_len: float,
                  song: Optional[SongData] = None) -> None:
    """THE SPACING GUARD, in place, time order: a later sequence's charge
    may not start before an earlier drop's two-bar tail ends; a lull inside
    it takes the charge with it. With `song` the moved charge lands on the
    first beat at or after the tail; without, on the tail's end itself."""
    tail_end: Optional[float] = None
    for s in sorted(seqs, key=lambda q: q.drop_ms):
        if tail_end is not None:
            if s.lull_ms is not None and s.lull_ms < tail_end:
                s.notes.append(
                    f"lull and charge left out: they fell inside the previous drop's "
                    f"two bars (until {int(tail_end)} ms)")
                s.lull_ms = None
                s.charge_ms = None
            elif s.charge_ms is not None and s.charge_ms < tail_end:
                moved = (first_beat_at_or_after(song, tail_end) if song is not None
                         else int(round(tail_end)))
                limit = (s.lull_ms if s.lull_ms is not None else s.drop_ms) - RAMP_FLOOR_MS
                if moved <= limit:
                    s.notes.append(
                        f"charge moved from {s.charge_ms} ms to {moved} ms: it started "
                        f"inside the previous drop's two bars")
                    s.charge_ms = moved
                else:
                    s.notes.append(
                        "charge left out: no room after the previous drop's two bars")
                    s.charge_ms = None
        end = s.drop_ms + TAIL_BEATS * beat_len
        tail_end = end if tail_end is None else max(tail_end, end)


def detect(analysis: SongAnalysis, *, confident_score: float = CONFIDENT_SCORE,
           suggested_score: float = SUGGESTED_SCORE) -> SongDetection:
    """Drop sequences for one analysed song at these thresholds, with the
    guards applied. Cheap: all the audio work is in `analysis`."""
    song = analysis.song
    p = analysis.prep
    B = song.beat_len
    out = SongDetection(
        uri=song.uri, detector_version=DETECTOR_VERSION,
        confident_score=float(confident_score), suggested_score=float(suggested_score),
        tempo_bpm=round(song.tempo, 3), beat_ms=round(B, 3),
        captured_from_ms=int(song.t[0]), captured_to_ms=int(song.t[-1]),
        duration_ms=int(song.duration_ms))
    floor = min(confident_score, suggested_score)
    for drop_ms, cand in raw_drops(analysis, floor):
        tier = tier_for(cand.score, confident_score, suggested_score)
        if tier is None:
            continue
        if drop_ms < EDGE_MS or drop_ms > song.duration_ms - EDGE_MS:
            out.excluded.append(Excluded(
                drop_ms=int(drop_ms), score=round(cand.score, 3),
                reason="in the song's first or last 15 s"))
            continue
        lull, charge, brk = place_sequence(p, drop_ms)
        out.sequences.append(DetectedSequence(
            key=drop_key(drop_ms), drop_ms=int(drop_ms), lull_ms=lull, charge_ms=charge,
            score=round(cand.score, 3), tier=tier, break_beats=brk,
            step=round(cand.step, 3), rise=round(cand.rise, 3), path=cand.path,
            loud_before=cand.loud_before))
    _apply_cap(out.sequences, song.duration_ms)
    apply_spacing(out.sequences, B, song)
    return out


def confident_cap(duration_ms: int) -> int:
    return max(1, int(duration_ms // (CAP_SECONDS_PER_CONFIDENT * 1000)))


def _apply_cap(seqs: list[DetectedSequence], duration_ms: int) -> None:
    cap = confident_cap(duration_ms)
    confident = [s for s in seqs if s.tier == TIER_CONFIDENT]
    if len(confident) <= cap:
        return
    ranked = sorted(confident, key=lambda s: (-s.score, s.drop_ms))
    for s in ranked[cap:]:
        s.tier = TIER_SUGGESTED
        s.capped = True
        s.notes.append(
            f"suggested, not confident: this song allows {cap} confident "
            f"sequence{'s' if cap != 1 else ''} (one per {CAP_SECONDS_PER_CONFIDENT} s) "
            f"and stronger ones took them")


def detect_uri(uri: str, *, confident_score: float = CONFIDENT_SCORE,
               suggested_score: float = SUGGESTED_SCORE) -> SongDetection:
    """analyse + detect for one song (raises Unavailable)."""
    return detect(analyse(uri), confident_score=confident_score,
                  suggested_score=suggested_score)
