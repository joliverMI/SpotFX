"""PRE-DROPS — the moment that leads into a drop (predrop plan section 1,
build step 3: detection. What plays from one is step 5's engine:
spectra/services/pre_drop_play.py and fx/effects/pre_drop.py).

Plan: /home/javi/fleet-spotfx/data/predrop-plan/report.md (section 1 is the
detection study, 3.1 the marker). The Admiral: "Some drops have what I want
to call a "Pre-Drop". It is a spike in another frequency band, other than
bass ... There is a higher frequency spike a little bit more than beat
before the drop", and later, of Dopamine's first drop: "a great example of
vocals coming in before the drop ... See if we can easily score pre-drops by
"spike" or "mid intro"/"vocal intro"".

TWO KINDS, TWO RULES, PORTED LINE FOR LINE. The arithmetic below is the
measured thing: `spike` is the study's pd_detect3.detect and `intro` its
pd_intro.detect (evidence/tools/, at the plan's commit), with their bars,
their windows and their tie-breaks unchanged. Both read only the stored
audio shape (`<stem>.npz`, low < 250 Hz, mid 250-4000 Hz, high > 4 kHz, one
value every 12 ms), which is in SONG time like his marks, normalised to the
song's own 99.5th percentile and smoothed over 36 ms exactly as the study
did (and as drop_detector.prep does for its own bands).

  A SPIKE (kind "spike"): one loud, short hit in the HIGH band, standing well
  above the lull around it, before the drop, with nothing comparable after
  it. Five tests (seven margins): LOUD (peak >= 0.7 of the song's ceiling),
  STANDS OUT (>= 3.5x the median of the 1.2 s before it), NOT A BEAT and
  THE LOUDEST OF THE LAST 3 S (its jump >= 1.5x anything in the 1.25 beats
  before it, >= 1.25x every other hit between 3 s before the drop and the
  drop), THE LAST WORD (nothing after it reaches half its peak, and the
  high band from 200 ms after it averages under half), NOT THE DROP (the
  bass does not stay up after it). The marker sits on the hit's ATTACK.

  A VOCAL INTRO (kind "intro"): a line in the MID band that enters out of a
  hush and holds into the drop while the bass is still out. Six tests:
  ENTERS (its first second >= 0.25 of the ceiling), OUT OF A HUSH (>= 3x
  the 1.2 s before it), SHARP (80% of the entry level within 300 ms),
  HOLDS (keeps >= half its entry level to the drop), NO BASS YET (the low
  band under 0.35 of the drop's own bass), NOT A BUILD (the last third at
  most 2x the first). The marker sits on the entry's onset; among passing
  entries the earliest wins (the phrase's own start).

  Each rule's `score` is its weakest margin (1.0 = exactly on a bar); a
  rule FINDS at score >= 1.0.

THE SEARCH WINDOWS ARE THE SCENE BOUNDS' EXTREMES, NOT THE DEFAULTS (plan
3.1: "each kind searches a window at least as wide as any scene may set"):
spike 250-3000 ms, vocal intro 350-4500 ms before the drop. The windows a
scene plays from (his decisions: spike 350-2000 ms, vocal intro 350-4000 ms)
are applied at play time by the engine (plan step 5), so a detection
outside them is stored and simply never plays there. The study measured
the spike at 350-2000 ms (SPIKE_STUDY_MS) and the vocal intro at 350-4500
ms; scripts/check_predrop_detector.py holds the report's numbers at those.

ONE PRE-DROP PER DROP: when both rules find, the higher score names the
kind (on his library one moment is found by both, FINA 158,208, a spike at
1.11 against an intro at 1.01). The choice is made over the search windows,
so a drop whose winning find sits outside a scene's own window plays no
pre-drop in that scene, even where the other kind's would have fitted —
the plan's storage holds one pre-drop per drop (3.1). TIERS (plan 1.4 and
1.6): a spike is confident at score >= 1.07; a vocal intro at score >= 1.18
AND entering within 3.5 s of the drop; anything else found is suggested,
and waits.

THE RE-ANCHOR (plan 1.10, his answer 7): the drop detector sometimes puts
the drop ON the pre-drop — Eyes Cut Deeper drop 1, where a clap carrying
bass took the first-bass-spike rule and he moved the drop 766 ms by hand.
`reanchor` (called from drop_detector.detect, after the first-spike rule)
moves a drop to a sustained bass return 0.5-2 s later ONLY when the drop's
own hit passes the spike test against that return: the study's
pd_reanchor.reanchor finds the return, the spike rule must find a hit
within SAME_HIT_MS of the original drop (the rule's own "the same hit"
distance). Restricted that way it moves exactly that one detection in his
store, to exactly where he moved it (70,350); the blanket rule would move
26 of 613, seven of them drops he had confirmed where they were.

PURE: numpy arithmetic over arrays handed in. It imports nothing from
drop_detector (which imports this module), so its SongData arrives
duck-typed (t, low, mid, high, beat_len).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

PREDROP_VERSION = "1"

KIND_SPIKE = "spike"
KIND_INTRO = "intro"
KINDS = (KIND_SPIKE, KIND_INTRO)

TIER_CONFIDENT = "confident"     # drop_detector.TIER_CONFIDENT
TIER_SUGGESTED = "suggested"     # drop_detector.TIER_SUGGESTED

# The windows each kind searches (the scene bounds' extremes, plan 3.1) and
# the windows the study measured (the acceptance check's).
SPIKE_SEARCH_MS = (250, 3000)
INTRO_SEARCH_MS = (350, 4500)
SPIKE_STUDY_MS = (350, 2000)
INTRO_STUDY_MS = (350, 4500)

FOUND_SCORE = 1.0
SPIKE_CONFIDENT_SCORE = 1.07
INTRO_CONFIDENT_SCORE = 1.18
INTRO_CONFIDENT_LEAD_MS = 3500

# the spike (pd_detect3)
SPIKE_PEAK_MIN = 0.7
SPIKE_RATIO_MIN = 3.5
SPIKE_LOCAL_ISO_MIN = 1.5
SPIKE_GLOBAL_ISO_MIN = 1.25
SPIKE_CTX_MS = 3000
SPIKE_LATER_MAX = 0.5
SPIKE_AFTER_MAX = 0.5
SPIKE_SUSTAIN_MAX = 0.5
SPIKE_MIN_RISE = 0.08
INTRO_MIN_RISE = 0.06
ATTACK_HOLD_FRAMES = 6

# the vocal intro (pd_intro)
INTRO_ENTRY_MIN = 0.25
INTRO_RATIO_MIN = 3.0
INTRO_SHARP_MS = 300
INTRO_HOLD_MIN = 0.5
INTRO_BASS_MAX = 0.35
INTRO_RAMP_MAX = 2.0

# the re-anchor (pd_reanchor, plus the spike test)
REANCHOR_MIN_MS = 500
REANCHOR_MAX_MS = 2000
REANCHOR_GAP_FRAC = 0.4
REANCHOR_MIN_RISE = 0.25
SAME_HIT_MS = 100


# ── the shape ───────────────────────────────────────────────────────────────

@dataclass
class Shape:
    """One song's bands as both rules read them: each band divided by its
    own 99.5th percentile and smoothed over three 12 ms frames, plus `up`
    (the mean of mid and high). `t` is song ms."""
    t: np.ndarray
    n: dict
    beat_len: float
    _rise: dict = field(default_factory=dict, repr=False)

    def idx(self, ms: float) -> int:
        return int(np.searchsorted(self.t, ms))

    def seg(self, band: str, a: float, b: float) -> np.ndarray:
        return self.n[band][self.idx(a):self.idx(b)]

    def mean(self, band: str, a: float, b: float) -> float:
        s = self.seg(band, a, b)
        return float(s.mean()) if len(s) else 0.0

    def rise(self, band: str) -> np.ndarray:
        """The ~48 ms rise every attack is found on (x[i+2] - x[i-2])."""
        r = self._rise.get(band)
        if r is None:
            x = self.n[band]
            r = np.zeros_like(x)
            r[2:-2] = x[4:] - x[:-4]
            self._rise[band] = r
        return r


def make_shape(t: np.ndarray, raw: dict, beat_len: float,
               ceilings: Optional[dict] = None) -> Shape:
    """`raw`: the stored low/mid/high envelopes. `ceilings`: each band's
    99.5th percentile when `raw` is a window cut from a longer song (the
    fixtures); None computes it from `raw` itself (a whole song)."""
    n = {}
    for b in ("low", "mid", "high"):
        x = np.asarray(raw[b], dtype=np.float64)
        top = float(ceilings[b]) if ceilings is not None else float(np.percentile(x, 99.5))
        n[b] = np.convolve(x / (top + 1e-9), np.ones(3) / 3, mode="same")
    n["up"] = 0.5 * (n["mid"] + n["high"])
    return Shape(t=np.asarray(t, dtype=np.int64), n=n, beat_len=float(beat_len))


def shape_of(song) -> Optional[Shape]:
    """The rules' shape for drop_detector's SongData (None when the song
    was loaded without its mid band)."""
    if getattr(song, "mid", None) is None:
        return None
    return make_shape(song.t, {"low": song.low, "mid": song.mid, "high": song.high},
                      song.beat_len)


def _attacks(s: Shape, band: str, a: float, b: float, min_rise: float,
             hold: int = ATTACK_HOLD_FRAMES) -> list[int]:
    """pd_detect3._attacks: the local maxima of a band's rise in [a, b),
    each walked back to the first frame of its rise."""
    t, x, r = s.t, s.n[band], s.rise(band)
    i0, i1 = np.searchsorted(t, [a, b])
    out = []
    i = max(int(i0), 2)
    while i < min(int(i1), len(x) - 2):
        lo, hi = max(0, i - hold), min(len(x), i + hold + 1)
        if r[i] >= min_rise and r[i] >= r[lo:hi].max():
            j = i
            while j > 1 and x[j - 1] < x[j] - 0.005:
                j -= 1
            out.append(j)
            i += hold
        else:
            i += 1
    return out


# ── kind 1: the spike (pd_detect3.detect) ───────────────────────────────────

def _hit(s: Shape, j: int) -> dict:
    t, x = s.t, s.n["high"]
    ms = int(t[j])
    k1 = int(np.searchsorted(t, ms + 150))
    pk_i = j + int(np.argmax(x[j:max(k1, j + 1)]))
    peak = float(x[pk_i])
    p0, p1 = np.searchsorted(t, [ms - 1200, ms - 40])
    pre = x[p0:p1]
    pre_med = float(np.median(pre)) if len(pre) else 0.0
    return dict(ms=ms, pk_ms=int(t[pk_i]), peak=peak, pre_med=pre_med,
                jump=peak - pre_med, ratio=(peak + 0.03) / (pre_med + 0.03))


def spike(s: Shape, drop_ms: float, wmin: float = SPIKE_SEARCH_MS[0],
          wmax: float = SPIKE_SEARCH_MS[1], th: Optional[dict] = None) -> dict:
    """The spike rule at a drop: {"status": found | weak | none |
    no_capture, "score", and, for a hit, its ms, lead, margins, weakest}.
    `th` overrides bars by their study names (the sensitivity check)."""
    T = dict(PEAK_MIN=SPIKE_PEAK_MIN, RATIO_MIN=SPIKE_RATIO_MIN,
             LOCAL_ISO_MIN=SPIKE_LOCAL_ISO_MIN, GLOBAL_ISO_MIN=SPIKE_GLOBAL_ISO_MIN,
             LATER_MAX=SPIKE_LATER_MAX, AFTER_MAX=SPIKE_AFTER_MAX,
             SUSTAIN_MAX=SPIKE_SUSTAIN_MAX)
    if th:
        T.update(th)
    t, x = s.t, s.n["high"]
    D = drop_ms
    if D - wmax - 1300 < t[0]:
        return dict(status="no_capture", score=0.0)
    B = s.beat_len
    low_post = s.mean("low", D, D + 4 * B)
    hits = [_hit(s, j) for j in _attacks(s, "high", min(D - wmax - 1.5 * B, D - SPIKE_CTX_MS),
                                         D - 60, SPIKE_MIN_RISE)]
    best = None
    for h in hits:
        lead = D - h["ms"]
        if not (wmin <= lead <= wmax):
            continue
        before = [o["jump"] for o in hits
                  if h["ms"] - 1.25 * B - 100 <= o["ms"] <= h["ms"] - 100]
        h["local_iso"] = h["jump"] / max(max(before) if before else 0.0, 0.05)
        others = [o["jump"] for o in hits
                  if o is not h and D - SPIKE_CTX_MS <= o["ms"] <= D - 60
                  and abs(o["ms"] - h["ms"]) > 100]
        h["global_iso"] = h["jump"] / max(max(others) if others else 0.0, 0.05)
        a0, a1 = np.searchsorted(t, [h["pk_ms"] + 150, D - 60])
        seg = x[a0:a1]
        h["later"] = float(seg.max() / (h["peak"] + 1e-9)) if len(seg) else 0.0
        b0 = np.searchsorted(t, h["pk_ms"] + 200)
        seg2 = x[b0:a1]
        h["after"] = float(seg2.mean() / (h["peak"] + 1e-9)) if len(seg2) else 0.0
        lo_after = s.mean("low", h["ms"] + 150, D - 40) if D - 40 > h["ms"] + 150 else 0.0
        h["bass_after"] = lo_after / (low_post + 1e-9)
        h["low_at"] = (float(s.seg("low", h["ms"], h["ms"] + 150).max()) / (low_post + 1e-9)
                       if low_post > 0 else 0.0)
        h["lead"] = lead
        margins = dict(
            peak=h["peak"] / T["PEAK_MIN"],
            ratio=h["ratio"] / T["RATIO_MIN"],
            local_iso=h["local_iso"] / T["LOCAL_ISO_MIN"],
            global_iso=h["global_iso"] / T["GLOBAL_ISO_MIN"],
            later=(1.0 - min(h["later"], 1.0)) / (1.0 - T["LATER_MAX"]),
            after=(1.0 - min(h["after"], 1.0)) / (1.0 - T["AFTER_MAX"]),
            sustain=(1.0 - min(h["bass_after"], 1.0)) / (1.0 - T["SUSTAIN_MAX"]),
        )
        h["margins"] = margins
        h["score"] = float(min(margins.values()))
        h["weakest"] = min(margins, key=margins.get)
        h["ok"] = h["score"] >= FOUND_SCORE
        key = (h["ok"], h["jump"] if h["ok"] else h["score"])
        if best is None or key > (best["ok"], best["jump"] if best["ok"] else best["score"]):
            best = h
    if best is None:
        return dict(status="none", score=0.0)
    return dict(status="found" if best["ok"] else "weak", **best)


# ── kind 2: the vocal intro (pd_intro.detect) ───────────────────────────────

def _entry(s: Shape, o: float, e1: float) -> dict:
    """A mid-band onset at `o` measured as an entry: its level over
    [o + 40, e1), the level before it, their ratio, and how long it takes to
    reach 80% of the way up (the vocal intro's first three tests, shared by
    the rule and the entries rail so the two can never disagree)."""
    t, x = s.t, s.n["mid"]
    entry = s.mean("mid", o + 40, e1)
    before = s.mean("mid", o - 1200, o - 80)
    ratio = (entry + 0.02) / (before + 0.02)
    # sharpness: from o until the mid band first reaches 80% of the entry
    k0, k1 = np.searchsorted(t, [o, e1])
    target = before + 0.8 * max(entry - before, 0.0)
    reach = np.nonzero(x[k0:k1] >= target)[0]
    rise_ms = float(t[k0 + reach[0]] - o) if len(reach) else float(e1 - o)
    return dict(entry=entry, before=before, ratio=ratio, rise_ms=rise_ms)


def _entry_tests(e: dict, T: dict) -> dict:
    """Tests 1-3 of the vocal intro as margins (pass at >= 1)."""
    return dict(entry=e["entry"] / T["ENTRY_MIN"], quiet=e["ratio"] / T["RATIO_MIN"],
                sharp=T["SHARP_MS"] / max(e["rise_ms"], 1.0))


def intro(s: Shape, drop_ms: float, wmin: float = INTRO_SEARCH_MS[0],
          wmax: float = INTRO_SEARCH_MS[1], th: Optional[dict] = None) -> dict:
    """The vocal-intro rule at a drop, in the spike's result shape."""
    T = dict(ENTRY_MIN=INTRO_ENTRY_MIN, RATIO_MIN=INTRO_RATIO_MIN,
             SHARP_MS=INTRO_SHARP_MS, HOLD_MIN=INTRO_HOLD_MIN,
             BASS_MAX=INTRO_BASS_MAX, RAMP_MAX=INTRO_RAMP_MAX)
    if th:
        T.update(th)
    t, x = s.t, s.n["mid"]
    D = drop_ms
    if D - wmax - 1300 < t[0]:
        return dict(status="no_capture", score=0.0)
    B = s.beat_len
    low_post = s.mean("low", D, D + 4 * B)
    best = None
    for j in _attacks(s, "mid", D - wmax, D - wmin + 1, INTRO_MIN_RISE):
        o = int(t[j])
        lead = D - o
        if not (wmin <= lead <= wmax):
            continue
        e1 = min(o + 1000, D - 60)
        e = _entry(s, o, e1)
        entry, before, ratio, rise_ms = e["entry"], e["before"], e["ratio"], e["rise_ms"]
        held = s.mean("mid", o + 40, D - 60) / (entry + 1e-9)
        bass = s.mean("low", o, D - 60) / (low_post + 1e-9)
        span = D - 60 - o
        up0 = s.mean("up", o + 40, o + 40 + span / 3)
        up2 = s.mean("up", D - 60 - span / 3, D - 60)
        ramp = (up2 + 0.02) / (up0 + 0.02)
        m = dict(**_entry_tests(e, T), hold=held / T["HOLD_MIN"],
                 no_bass=(1.0 - min(bass, 1.0)) / (1.0 - T["BASS_MAX"]),
                 not_build=T["RAMP_MAX"] / max(ramp, 1e-6))
        score = float(min(m.values()))
        h = dict(ms=o, lead=lead, entry=entry, before=before, ratio=ratio, rise_ms=rise_ms,
                 held=held, bass_after=bass, ramp=ramp, margins=m, score=score,
                 weakest=min(m, key=m.get), ok=score >= FOUND_SCORE)
        if best is None:
            best = h
        elif h["ok"] and not best["ok"]:
            best = h
        elif h["ok"] and best["ok"]:
            if h["ms"] < best["ms"]:
                best = h          # the phrase's own start
        elif not h["ok"] and not best["ok"] and h["score"] > best["score"]:
            best = h
    if best is None:
        return dict(status="none", score=0.0)
    return dict(status="found" if best["ok"] else "weak", **best)


# ── one pre-drop per drop ───────────────────────────────────────────────────

@dataclass
class PreDrop:
    ms: int                  # the marker: the spike's attack, the intro's onset
    kind: str                # KIND_SPIKE | KIND_INTRO
    lead_ms: int             # how far before the drop (positive = earlier)
    score: float
    tier: str                # TIER_CONFIDENT | TIER_SUGGESTED
    tests: dict = field(default_factory=dict)    # the rule's margins
    weakest: Optional[str] = None

    def stored(self) -> dict:
        """What a detected sequence keeps (drop_sequences.json)."""
        return {"ms": int(self.ms), "kind": self.kind, "lead_ms": int(self.lead_ms),
                "score": round(float(self.score), 3), "tier": self.tier}


def tier_for(kind: str, score: float, lead_ms: float) -> Optional[str]:
    """Plan 1.4 / 1.6: None below the find bar."""
    if score < FOUND_SCORE:
        return None
    if kind == KIND_SPIKE:
        return TIER_CONFIDENT if score >= SPIKE_CONFIDENT_SCORE else TIER_SUGGESTED
    if score >= INTRO_CONFIDENT_SCORE and lead_ms <= INTRO_CONFIDENT_LEAD_MS:
        return TIER_CONFIDENT
    return TIER_SUGGESTED


def _as_pre_drop(kind: str, r: dict) -> Optional[PreDrop]:
    if r.get("status") != "found":
        return None
    tier = tier_for(kind, r["score"], r["lead"])
    if tier is None:
        return None
    return PreDrop(ms=int(r["ms"]), kind=kind, lead_ms=int(r["lead"]), score=float(r["score"]),
                   tier=tier, tests={k: float(v) for k, v in r["margins"].items()},
                   weakest=r.get("weakest"))


def detect(s: Optional[Shape], drop_ms: float) -> Optional[PreDrop]:
    """The pre-drop of a drop, or None: both rules at their search windows,
    the higher score naming the kind (a spike on an exact tie)."""
    if s is None:
        return None
    found = [p for p in (_as_pre_drop(KIND_SPIKE, spike(s, drop_ms)),
                         _as_pre_drop(KIND_INTRO, intro(s, drop_ms))) if p is not None]
    if not found:
        return None
    return max(found, key=lambda p: (p.score, p.kind == KIND_SPIKE))


# ── the re-anchor (pd_reanchor.reanchor + the spike test) ───────────────────

def bass_return(s: Shape, att_ms: np.ndarray, att_rise: np.ndarray,
                d0: float) -> Optional[int]:
    """pd_reanchor.reanchor: the strongest bass attack 0.5-2 s after a drop
    at d0 whose four beats stand well above the gap since d0. `att_ms` /
    `att_rise` are drop_detector.prep's bass attacks (the study's own
    find_attacks at min rise 0.12 and a 120 ms hold)."""
    B = s.beat_len
    m = ((att_ms >= d0 + REANCHOR_MIN_MS) & (att_ms <= d0 + REANCHOR_MAX_MS)
         & (att_rise >= REANCHOR_MIN_RISE))
    best = None
    for d1, r in zip(att_ms[m], att_rise[m]):
        gap = s.mean("low", d0 + 200, d1 - 40)
        after = s.mean("low", d1, d1 + 4 * B)
        if after <= 0:
            continue
        if gap <= REANCHOR_GAP_FRAC * after:
            if best is None or float(r) > best[1]:
                best = (int(d1), float(r))
    return best[0] if best else None


def reanchor(s: Optional[Shape], att_ms: np.ndarray, att_rise: np.ndarray,
             d0: int) -> Optional[int]:
    """Where a drop at d0 belongs instead, or None: its sustained bass
    return 0.5-2 s later, ONLY when d0's own hit (within SAME_HIT_MS) passes
    the spike test against that return."""
    if s is None:
        return None
    d1 = bass_return(s, att_ms, att_rise, d0)
    if d1 is None:
        return None
    r = spike(s, d1)
    if r.get("status") != "found" or abs(int(r["ms"]) - int(d0)) > SAME_HIT_MS:
        return None
    return d1


# ── what a dragged pre-drop snaps to, and where ＋ Pre-drop puts one ────────

ENTRY_SPAN_MS = 1000             # the entry's own window when no drop bounds it


def rails(s: Optional[Shape]) -> tuple[list[list], list[list]]:
    """The two pre-drop snap rails over the whole song (predrop plan 3.1):
    HITS — every high-band attack the spike rule weighs, [ms, strength]
    (its jump over the 1.2 s before it); ENTRIES — every mid-band onset that
    passes the vocal intro's first three tests (loud, out of a hush, sharp)
    over its own 1 s, [ms, strength] (its level). Both bands are the rules'
    own normalised ones, so strength reads 0..1. Read-only."""
    if s is None or len(s.t) < 8:
        return [], []
    a, b = float(s.t[0]), float(s.t[-1])
    hits = []
    for j in _attacks(s, "high", a, b, SPIKE_MIN_RISE):
        h = _hit(s, j)
        hits.append([int(h["ms"]), round(max(float(h["jump"]), 0.0), 3)])
    T = dict(ENTRY_MIN=INTRO_ENTRY_MIN, RATIO_MIN=INTRO_RATIO_MIN, SHARP_MS=INTRO_SHARP_MS)
    entries = []
    for j in _attacks(s, "mid", a, b, INTRO_MIN_RISE):
        o = int(s.t[j])
        e = _entry(s, o, o + ENTRY_SPAN_MS)
        if min(_entry_tests(e, T).values()) >= FOUND_SCORE:
            entries.append([o, round(float(e["entry"]), 3)])
    return hits, entries


def place(s: Optional[Shape], drop_ms: float) -> Optional[tuple[int, str]]:
    """Where ＋ Pre-drop puts one (predrop plan 3.1, "fill ... snaps to the
    strongest hit or entry the rules would pick inside the window"): the
    pre-drop the rules find (`detect`), else the strongest candidate either
    rule weighed in its search window, found or not — a spike on a tie.
    (ms, kind), or None when neither rule has a candidate there."""
    if s is None:
        return None
    found = detect(s, drop_ms)
    if found is not None:
        return int(found.ms), found.kind
    cands = []
    for kind, r in ((KIND_SPIKE, spike(s, drop_ms)), (KIND_INTRO, intro(s, drop_ms))):
        if r.get("status") in ("found", "weak") and r.get("ms") is not None:
            cands.append((float(r["score"]), kind == KIND_SPIKE, int(r["ms"]), kind))
    if not cands:
        return None
    _score, _spike, ms, kind = max(cands)
    return ms, kind


def lead_range(kind: str) -> tuple[int, int]:
    """How far before its drop a pre-drop of `kind` may sit: its search
    window, which is at least as wide as any scene may set (plan 3.1)."""
    lo, hi = SPIKE_SEARCH_MS if kind == KIND_SPIKE else INTRO_SEARCH_MS
    return int(lo), int(hi)
