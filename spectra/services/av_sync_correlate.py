"""AV-sync correlation core — PURE numpy, no I/O, no clocks, no hardware.

This is the arithmetic under the phone audio/visual-offset instrument
(spectra/services/av_sync_session.py drives it; spectra/api/av_sync.py is
the wire). It exists because this project spent a week ARGUING an audio
delay against the owner's ears instead of measuring it
(docs/SPECTRA_TIMING_CONVENTIONS.md, failure case studies 1-2): every
number that leaves this module carries a statement of how confident it
is, and a weak correlation yields NO number (``LagEstimate.ok == False``
with a named reason), never a plausible-looking one.

What is estimated, and the ONE sign convention
----------------------------------------------
``estimate_lag(ref, probe)`` answers: by how much does ``probe`` LAG
``ref``? Both are sampled signals with their own timestamps (seconds, any
monotonic clock the caller has already put on a COMMON axis). The result,
``lag_s``, is positive when the same event appears in ``probe`` LATER
than in ``ref``::

    probe(t) ≈ gain · ref(t - lag_s)            lag_s > 0 ⇒ probe is late

The session applies this twice, against the two reference signals it
owns on the server clock, with the phone's two signals as probes:

    light_lag_s = lag(ref=flash pattern / write train,  probe=phone luminance)
    audio_lag_s = lag(ref=server audio-hub envelope,    probe=phone mic envelope)
    av_offset_ms = (light_lag_s - audio_lag_s) × 1000

so ``av_offset_ms > 0`` means the LIGHT reached the phone LATER than the
sound it was meant to land with (lights lag / behind); ``< 0`` means the
lights arrived EARLIER (lights lead / ahead). The phone↔server clock
offset is common to both lags and cancels in the difference — the
session only needs it coarse (a WebSocket ping, ±RTT/2) to centre the
search window, and that residual is named as the uncertainty on the two
INDIVIDUAL lags, never on the difference. This is a MEASURED quantity of
the owner's room as seen from where the phone stood — it belongs to
neither the LEAD nor the OFFSET family in the timing-conventions table
(it is not authored and not applied anywhere by this build); see that
document's master table row for ``av_offset_ms``.

Confidence, and why the estimate can refuse
--------------------------------------------
Cross-correlation always has a maximum; a maximum is not a detection. Two
gates decide whether ``lag_s`` is reported at all:

* ``peak_ratio`` — the correlation peak's height over the correlation's
  own noise floor (std of the correlation outside ±``PEAK_EXCLUDE_S`` of
  the peak). Below ``MIN_PEAK_RATIO`` the peak is not distinguishable
  from the sidelobes → refused (``reason="weak"``).
* ``ambiguity`` — the second-highest peak (outside the exclusion zone)
  relative to the first. Above ``MAX_AMBIGUITY`` two lags explain the
  data about equally well → refused (``reason="ambiguous"``). A periodic
  pattern or a steady beat with no random structure fails exactly here —
  which is why the pattern driver uses RANDOM on/off durations.

Statistical uncertainty (``sigma_s``) comes from re-estimating the lag on
``SUBWINDOWS`` overlapping sub-windows and taking the spread of the
sub-window lags (standard error of their mean, floored by the peak's
parabolic-interpolation resolution). It is a REPEATABILITY figure for
this capture: it says nothing about systematic terms (phone camera/mic
pipeline skew, camera exposure integration, light rise time) — those are
named and bounded by the session's confidence statement, not invented
here. ``sigma_s`` is None when fewer than 2 sub-windows agree, and the
estimate is then refused (``reason="unstable"``) unless the caller asks
for a single-window read (``min_subwindows=1``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ── tunables, all named ────────────────────────────────────────────────────
GRID_HZ = 200.0            # common resampling grid: 5 ms bins
PEAK_EXCLUDE_S = 0.100     # ±100 ms around the peak excluded from the noise floor
EDGE_MATCH_S = 0.035       # "edges" conditioning: ref impulses widened to one camera frame
MIN_PEAK_RATIO = 5.0       # peak / noise-floor std needed to call a detection
MAX_AMBIGUITY = 0.80       # 2nd peak / 1st peak above this = two candidate lags
SUBWINDOWS = 4             # sub-window count for the repeatability estimate
SUBWINDOW_FRAC = 0.5       # each sub-window spans this fraction of the overlap
MIN_OVERLAP_S = 2.0        # refuse outright on less common time than this
ONSET_SMOOTH_S = 0.020     # onset-flux smoothing (box) width
HIGHPASS_S = 1.0           # luminance slow-ambient removal (moving mean) width


@dataclass
class Series:
    """A sampled signal: ``t`` seconds on SOME clock, strictly increasing;
    ``v`` the samples. Irregular spacing is fine (camera frames)."""
    t: np.ndarray
    v: np.ndarray

    def __post_init__(self) -> None:
        self.t = np.asarray(self.t, dtype=float).ravel()
        self.v = np.asarray(self.v, dtype=float).ravel()
        if self.t.shape != self.v.shape:
            raise ValueError("Series: t and v must have the same length")

    @property
    def empty(self) -> bool:
        return self.t.size == 0

    @property
    def span_s(self) -> float:
        return float(self.t[-1] - self.t[0]) if self.t.size > 1 else 0.0


@dataclass
class LagEstimate:
    ok: bool
    lag_s: Optional[float]
    sigma_s: Optional[float]
    peak_ratio: float
    ambiguity: float
    overlap_s: float
    n_ref: int
    n_probe: int
    reason: str = ""                      # "" when ok; else weak/ambiguous/unstable/overlap/empty
    subwindow_lags_s: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "lag_ms": None if self.lag_s is None else round(self.lag_s * 1000.0, 1),
            "sigma_ms": None if self.sigma_s is None else round(self.sigma_s * 1000.0, 1),
            "peak_ratio": round(float(self.peak_ratio), 2),
            "ambiguity": round(float(self.ambiguity), 3),
            "overlap_s": round(float(self.overlap_s), 2),
            "n_ref": int(self.n_ref),
            "n_probe": int(self.n_probe),
            "reason": self.reason,
            "subwindow_lags_ms": [round(x * 1000.0, 1) for x in self.subwindow_lags_s],
        }


# ── signal conditioning ────────────────────────────────────────────────────

def resample(series: Series, t0: float, t1: float, rate_hz: float = GRID_HZ) -> np.ndarray:
    """Linear interpolation of ``series`` onto a uniform grid
    [t0, t1) at ``rate_hz``. Outside the series' own span the edge value
    is held (np.interp semantics) — callers only ever resample over the
    OVERLAP of two series, so this never invents signal."""
    n = int(np.floor((t1 - t0) * rate_hz))
    if n <= 0 or series.empty:
        return np.zeros(0)
    grid = t0 + np.arange(n) / rate_hz
    return np.interp(grid, series.t, series.v)


def onset_flux(log_energy: np.ndarray, rate_hz: float = GRID_HZ) -> np.ndarray:
    """Half-wave-rectified first difference of a log-energy envelope,
    box-smoothed over ONSET_SMOOTH_S — the classic broadband onset
    strength. Applied to BOTH the server hub's and the phone's envelopes
    (the phone only ever sends log-energy frames; the server applies this
    transform to both sides so the two are conditioned identically)."""
    x = np.asarray(log_energy, dtype=float)
    if x.size < 2:
        return np.zeros_like(x)
    d = np.diff(x, prepend=x[0])
    d = np.maximum(d, 0.0)
    return _box_smooth(d, max(1, int(round(ONSET_SMOOTH_S * rate_hz))))


def highpass_mean(x: np.ndarray, rate_hz: float = GRID_HZ, width_s: float = HIGHPASS_S) -> np.ndarray:
    """Subtract a moving mean of ``width_s`` — removes slow ambient
    brightness changes (auto-exposure, room light) from a luminance
    series before correlating it with a flash pattern."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x
    w = max(1, int(round(width_s * rate_hz)))
    return x - _box_smooth(x, w)


def _box_smooth(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1 or x.size == 0:
        return x
    kernel = np.ones(w) / w
    return np.convolve(x, kernel, mode="same")


def _zscore(x: np.ndarray) -> np.ndarray:
    x = x - x.mean()
    s = x.std()
    return x / s if s > 0 else x


# ── the estimator ──────────────────────────────────────────────────────────

def _xcorr_lag(ref: np.ndarray, probe: np.ndarray, rate_hz: float, max_lag_s: float
               ) -> tuple[Optional[float], float, float]:
    """One cross-correlation read over a uniform grid. Returns
    (lag_s | None, peak_ratio, ambiguity). Positive lag ⇒ probe late."""
    if ref.size < 4 or probe.size < 4 or ref.std() == 0 or probe.std() == 0:
        return None, 0.0, 1.0
    r = _zscore(ref)
    p = _zscore(probe)
    max_lag = int(round(max_lag_s * rate_hz))
    # full cross-correlation via FFT; index k corresponds to lag (k - (n-1))
    n = r.size
    full = np.correlate(p, r, mode="full") if n < 4096 else _fft_xcorr(p, r)
    lags = np.arange(-(n - 1), n)
    keep = np.abs(lags) <= max_lag
    corr = full[keep] / float(n)
    lags = lags[keep]
    if corr.size < 3:
        return None, 0.0, 1.0
    k = int(np.argmax(corr))
    peak = float(corr[k])
    excl = int(round(PEAK_EXCLUDE_S * rate_hz))
    mask = np.ones(corr.size, dtype=bool)
    mask[max(0, k - excl): k + excl + 1] = False
    rest = corr[mask]
    if rest.size < 8:
        return None, 0.0, 1.0
    floor_std = float(rest.std())
    peak_ratio = (peak - float(rest.mean())) / floor_std if floor_std > 0 else 0.0
    second = float(rest.max())
    ambiguity = (second / peak) if peak > 0 else 1.0
    # parabolic interpolation around the peak for sub-bin resolution
    if 0 < k < corr.size - 1:
        y0, y1, y2 = corr[k - 1], corr[k], corr[k + 1]
        denom = (y0 - 2 * y1 + y2)
        frac = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
        frac = float(np.clip(frac, -0.5, 0.5))
    else:
        frac = 0.0
    lag_s = (lags[k] + frac) / rate_hz
    return float(lag_s), float(peak_ratio), float(ambiguity)


def _fft_xcorr(p: np.ndarray, r: np.ndarray) -> np.ndarray:
    n = p.size
    size = 1 << int(np.ceil(np.log2(2 * n - 1)))
    P = np.fft.rfft(p, size)
    R = np.fft.rfft(r, size)
    c = np.fft.irfft(P * np.conj(R), size)
    # reorder to np.correlate(p, r, "full") layout: lags -(n-1)..(n-1)
    return np.concatenate([c[-(n - 1):], c[:n]])


def estimate_lag(ref: Series, probe: Series, *, max_lag_s: float,
                 rate_hz: float = GRID_HZ, condition: str = "none",
                 min_subwindows: int = 2) -> LagEstimate:
    """Estimate how much ``probe`` lags ``ref`` (see module docstring).

    ``condition`` selects the per-side conditioning applied after
    resampling both onto the common grid:
      "onset"     — ``onset_flux`` on both (audio envelopes)
      "highpass"  — ``highpass_mean`` on the PROBE only (levels; kept for
                    callers that want the level-vs-level matched filter)
      "edges"     — ``signed_edges`` on both, probe high-passed first —
                    THE flash-pattern conditioning (phone luminance vs the
                    ±1 pattern): sharp peak, see signed_edges' docstring
      "none"      — raw (tests / already-conditioned callers)

    The search window is ±``max_lag_s`` around zero lag on the common
    axis — the caller has already put both clocks on one axis to within
    that window (the session's ping-based clock mapping)."""
    if ref.empty or probe.empty:
        return LagEstimate(False, None, None, 0.0, 1.0, 0.0, ref.t.size,
                           probe.t.size, reason="empty")
    # overlap, padded by the lag window so a lag near the edge isn't cut off
    t0 = max(ref.t[0], probe.t[0] - max_lag_s)
    t1 = min(ref.t[-1], probe.t[-1] + max_lag_s)
    overlap = t1 - t0
    if overlap < MIN_OVERLAP_S:
        return LagEstimate(False, None, None, 0.0, 1.0, max(0.0, overlap),
                           ref.t.size, probe.t.size, reason="overlap")
    r = resample(ref, t0, t1, rate_hz)
    p = resample(probe, t0, t1, rate_hz)
    r, p = _condition(r, p, condition, rate_hz)
    lag, peak_ratio, ambiguity = _xcorr_lag(r, p, rate_hz, max_lag_s)
    # repeatability: sub-window re-reads
    sub_lags: list[float] = []
    n = r.size
    w = int(n * SUBWINDOW_FRAC)
    if w >= int(MIN_OVERLAP_S * rate_hz) and SUBWINDOWS > 1:
        starts = np.linspace(0, n - w, SUBWINDOWS).astype(int)
        for s in starts:
            sl, spr, samb = _xcorr_lag(r[s:s + w], p[s:s + w], rate_hz, max_lag_s)
            if sl is not None and spr >= MIN_PEAK_RATIO * 0.6 and samb <= MAX_AMBIGUITY:
                sub_lags.append(sl)
    sigma: Optional[float] = None
    if len(sub_lags) >= 2:
        spread = float(np.std(sub_lags, ddof=1)) / np.sqrt(len(sub_lags))
        sigma = max(spread, 0.5 / rate_hz)   # floor: a tenth of a grid bin pair
    base = LagEstimate(False, lag, sigma, peak_ratio, ambiguity, overlap,
                       ref.t.size, probe.t.size, subwindow_lags_s=sub_lags)
    if lag is None or peak_ratio < MIN_PEAK_RATIO:
        base.reason = "weak"           # nothing stands out of the floor at all
        return base
    if ambiguity > MAX_AMBIGUITY:
        base.reason = "ambiguous"      # something stands out — in two places
        return base
    if len(sub_lags) < min_subwindows:
        base.reason = "unstable"
        return base
    if sub_lags and sigma is not None:
        # sub-windows disagreeing with the full read by far more than their
        # own spread is a second kind of instability (e.g. the lag drifted
        # mid-capture); refuse rather than average over a moving target.
        if abs(float(np.mean(sub_lags)) - lag) > max(0.050, 4 * sigma):
            base.reason = "unstable"
            return base
    base.ok = True
    return base


def signed_edges(x: np.ndarray, rate_hz: float = GRID_HZ, width_s: float = EDGE_MATCH_S) -> np.ndarray:
    """Signed first difference, box-smoothed to ``width_s`` — turns a ±1
    square wave into ±impulses and a camera-integrated luminance step
    (a one-frame ramp after resampling) into a matching box. Correlating
    EDGES rather than levels is what gives a flash pattern a SHARP peak:
    the level-vs-level matched filter of a random telegraph wave has a
    ~mean-hold-wide triangular peak whose shoulders swamp the noise-floor
    estimate (measured: peak ratio ~4 on a clean synthetic capture)."""
    x = np.asarray(x, dtype=float)
    if x.size < 2:
        return np.zeros_like(x)
    d = np.diff(x, prepend=x[0])
    return _box_smooth(d, max(1, int(round(width_s * rate_hz))))


def _condition(r: np.ndarray, p: np.ndarray, condition: str, rate_hz: float
               ) -> tuple[np.ndarray, np.ndarray]:
    if condition == "onset":
        return onset_flux(r, rate_hz), onset_flux(p, rate_hz)
    if condition == "highpass":
        return r, highpass_mean(p, rate_hz)
    if condition == "edges":
        return signed_edges(r, rate_hz), signed_edges(highpass_mean(p, rate_hz), rate_hz)
    if condition == "none":
        return r, p
    raise ValueError(f"unknown condition {condition!r}")


# ── pattern helpers (shared by the driver and the tests) ───────────────────

def random_edge_schedule(seed: int, duration_s: float, *, min_hold_s: float = 0.15,
                         max_hold_s: float = 0.45) -> list[tuple[float, int]]:
    """A deterministic random ON/OFF schedule: [(t_offset_s, state), ...]
    starting at t=0 with state ON, holds drawn uniformly in
    [min_hold_s, max_hold_s]. Random holds are what make the correlation
    peak UNIQUE (see module docstring: a periodic pattern is refused as
    ambiguous by design)."""
    rng = np.random.default_rng(seed)
    t = 0.0
    state = 1
    out: list[tuple[float, int]] = []
    while t < duration_s:
        out.append((round(t, 4), state))
        t += float(rng.uniform(min_hold_s, max_hold_s))
        state ^= 1
    return out


def edges_to_series(edges: list[tuple[float, int]], *, until_s: float,
                    rate_hz: float = GRID_HZ) -> Series:
    """A ±1 square wave on a uniform grid from an edge list (absolute
    seconds on the reference clock). ``until_s`` closes the final hold."""
    if not edges:
        return Series(np.zeros(0), np.zeros(0))
    t0 = edges[0][0]
    n = max(1, int(np.floor((until_s - t0) * rate_hz)))
    grid = t0 + np.arange(n) / rate_hz
    v = np.zeros(n)
    for i, (t, state) in enumerate(edges):
        t_next = edges[i + 1][0] if i + 1 < len(edges) else until_s
        v[(grid >= t) & (grid < t_next)] = 1.0 if state else -1.0
    return Series(grid, v)


def events_to_series(event_times: list[float], *, t0: float, t1: float,
                     rate_hz: float = GRID_HZ, width_s: float = 0.030) -> Series:
    """A sparse impulse train (short boxes of ``width_s``) on a uniform
    grid — the passive SHOW reference: one impulse per engine write that
    can plausibly produce a luminance edge. Correlated against the
    onset-like derivative of luminance, not the luminance itself."""
    n = max(1, int(np.floor((t1 - t0) * rate_hz)))
    grid = t0 + np.arange(n) / rate_hz
    v = np.zeros(n)
    half = max(1, int(round(width_s * rate_hz / 2)))
    for et in event_times:
        k = int(round((et - t0) * rate_hz))
        v[max(0, k - half): k + half + 1] = 1.0
    return Series(grid, v)
