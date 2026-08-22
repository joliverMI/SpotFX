"""The AV-sync correlation core (spectra/services/av_sync_correlate.py) —
pure-numpy proofs with KNOWN lags: the sign convention (positive = probe
late), recovery through a frame-rate camera with exposure integration,
recovery of an audio envelope lag, and the two refusals that keep a weak
or ambiguous correlation from ever becoming a number."""
from __future__ import annotations

import numpy as np
import pytest

from spectra.services import av_sync_correlate as c

T0 = 1000.0


def _pattern(seed=7, duration=12.0):
    edges = [(T0 + t, s) for t, s in c.random_edge_schedule(seed, duration)]
    return edges, c.edges_to_series(edges, until_s=T0 + duration + 0.5)


def _camera_lum(edges, true_lag, fps=30.0, noise=3.0, seed=1, integrate=True):
    rng = np.random.default_rng(seed)
    n = int(13.5 * fps)
    ft = T0 - 0.5 + np.arange(n) / fps + rng.uniform(-0.002, 0.002, n)
    sub = np.linspace(0, 1 / fps, 8) if integrate else np.array([1 / fps])

    def state(ts):
        tt = ts - true_lag
        v = np.zeros_like(tt)
        for i, (et, s) in enumerate(edges):
            nxt = edges[i + 1][0] if i + 1 < len(edges) else T0 + 99
            v[(tt >= et) & (tt < nxt)] = s
        return v
    lum = np.array([state(f - 1 / fps + sub).mean() for f in ft])
    return c.Series(ft, 40 + 120 * lum + rng.normal(0, noise, n))


def test_light_lag_recovered_positive_means_probe_late():
    edges, ref = _pattern()
    est = c.estimate_lag(ref, _camera_lum(edges, 0.123), max_lag_s=1.5, condition="edges")
    assert est.ok, est.as_dict()
    # the camera integrates a full 33 ms frame, so the edge is seen ~half a
    # frame late: 123 + 16.7 — the exposure systematic the session names
    assert abs(est.lag_s - (0.123 + 0.5 / 30)) < 0.006, est.as_dict()
    assert est.sigma_s is not None and est.sigma_s < 0.010
    assert est.peak_ratio >= c.MIN_PEAK_RATIO and est.ambiguity <= c.MAX_AMBIGUITY


def test_light_lag_negative_when_probe_leads():
    edges, ref = _pattern(seed=3)
    est = c.estimate_lag(ref, _camera_lum(edges, -0.200, fps=60, integrate=False),
                         max_lag_s=1.5, condition="edges")
    assert est.ok, est.as_dict()
    assert -0.215 < est.lag_s < -0.185, est.as_dict()


@pytest.mark.parametrize("fps,noise", [(24, 8.0), (30, 15.0), (60, 3.0)])
def test_light_lag_survives_frame_rates_and_sensor_noise(fps, noise):
    edges, ref = _pattern(seed=11)
    est = c.estimate_lag(ref, _camera_lum(edges, 0.080, fps=fps, noise=noise, seed=fps),
                         max_lag_s=1.5, condition="edges")
    assert est.ok, est.as_dict()
    assert abs(est.lag_s - (0.080 + 0.5 / fps)) < 0.010, est.as_dict()


def _song(rate=86.0, dur=20.0, seed=5):
    rng = np.random.default_rng(seed)
    n = int(dur * rate)
    t = T0 + np.arange(n) / rate
    env = np.full(n, -45.0)
    for o in np.sort(rng.choice(n, size=60, replace=False)):
        L = min(n - o, int(0.3 * rate))
        env[o:o + L] = np.maximum(env[o:o + L], -12 - 30 * np.arange(L) / max(1, L))
    return t, env + rng.normal(0, 0.7, n)


def test_audio_lag_recovered_from_onset_envelopes():
    rng = np.random.default_rng(2)
    t, env = _song()
    ref = c.Series(t, env)
    probe = c.Series(t + 0.380 + rng.uniform(-0.001, 0.001, t.size),
                     env + rng.normal(0, 3.0, t.size) - 15)
    est = c.estimate_lag(ref, probe, max_lag_s=3.0, condition="onset")
    assert est.ok, est.as_dict()
    assert abs(est.lag_s - 0.380) < 0.006, est.as_dict()


def test_periodic_pattern_is_refused_as_ambiguous():
    rng = np.random.default_rng(0)
    per = [(T0 + 0.3 * i, i % 2) for i in range(40)]
    ref = c.edges_to_series(per, until_s=T0 + 12.0)
    ft = T0 - 0.5 + np.arange(0, 13.5, 1 / 30)
    lum = np.interp(ft - 0.1, ref.t, ref.v) + rng.normal(0, 0.05, ft.size)
    est = c.estimate_lag(ref, c.Series(ft, lum), max_lag_s=1.5, condition="edges")
    assert not est.ok and est.reason in ("ambiguous", "weak"), est.as_dict()
    assert est.ambiguity > c.MAX_AMBIGUITY        # the diagnostic says WHY either way
    assert est.lag_s is not None   # the raw peak is still reported for diagnostics…
    assert est.as_dict()["ok"] is False  # …but never as a measurement


def test_unrelated_signals_are_refused_as_weak():
    rng = np.random.default_rng(4)
    _, ref = _pattern()
    ft = T0 - 0.5 + np.arange(0, 13.5, 1 / 30)
    est = c.estimate_lag(ref, c.Series(ft, rng.normal(0, 1, ft.size)), max_lag_s=1.5,
                         condition="edges")
    assert not est.ok and est.reason == "weak", est.as_dict()


def test_short_overlap_and_empty_are_refused_by_name():
    _, ref = _pattern()
    est = c.estimate_lag(ref, c.Series(np.array([T0, T0 + 0.5]), np.array([1.0, 2.0])),
                         max_lag_s=0.1)
    assert not est.ok and est.reason == "overlap"
    est = c.estimate_lag(ref, c.Series(np.zeros(0), np.zeros(0)), max_lag_s=1.0)
    assert not est.ok and est.reason == "empty"


def test_random_edge_schedule_is_deterministic_random_and_bounded():
    a = c.random_edge_schedule(42, 10.0)
    b = c.random_edge_schedule(42, 10.0)
    assert a == b
    assert a[0] == (0.0, 1)
    holds = np.diff([t for t, _ in a])
    assert holds.min() >= 0.15 - 1e-9 and holds.max() <= 0.45 + 1e-9
    assert len(set(np.round(holds, 3))) > 5          # genuinely random, not periodic
    assert c.random_edge_schedule(43, 10.0) != a


def test_events_to_series_marks_each_event_once():
    s = c.events_to_series([T0 + 1.0, T0 + 2.0], t0=T0, t1=T0 + 3.0)
    on = s.v > 0
    assert on.sum() > 0
    # two separate boxes
    changes = np.diff(on.astype(int))
    assert (changes == 1).sum() == 2
