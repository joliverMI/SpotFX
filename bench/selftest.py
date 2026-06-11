"""
Self-tests for the Phase-1 extraction.

1. Decision-differential test: `_ReferencePlay` is a line-for-line
   transcription of the pre-refactor inline gate cascade from
   auto_offset_service._detect_loop_xcorr (git: feat/debug-xcorr-graphs,
   lines 821-1184 per-window + 1266-1343 post-loop). Thousands of randomized
   window sequences are pushed through BOTH the reference and
   SweepEvaluator; any divergence in winner/snap/save/lock/final decisions
   fails the test. This is the equivalence gate for the 1.2 refactor.

2. End-to-end smoke: replay one corpus song with true_offset=0 clean and
   assert the matcher locks correctly.
"""
from __future__ import annotations

import random
from typing import Optional

from config import settings
from services.xcorr_sweep import SweepConfig, SweepEvaluator
from bench.simulate import FakeEngine


class _ReferencePlay:
    """Verbatim transcription of the pre-refactor decision cascade."""

    def __init__(self, uri, verification, play_type, seed_offset, envelope_lookup):
        self.uri = uri
        self.verification = verification
        self.play_type = play_type
        self.envelope_lookup = envelope_lookup
        self.best_quality = -1.0
        self.best_offset = int(seed_offset)
        self.best_difficulty = 0.0
        self.n_measurements = 0
        self.confirmation_shifts: list[tuple[int, float]] = []
        self.old_r_samples: list[float] = []
        self.baseline_anti_corr = False
        self._anti_neg_streak = 0
        self._agree_now = 0.0

    def add_anchor_vote(self, offset_ms, weight):
        self.confirmation_shifts.append((int(offset_ms), float(weight)))

    def window(self, win_start, win_end, difficulty, new_result, old_r,
               stored_offset_ms, stored_quality,
               engine_current, engine_play_best):
        """Returns (winner_offset, winner_q, winner_r, is_new, is_global_best,
        snap, save) where snap/save are tuples or None."""
        if old_r is not None:
            old_quality = round(old_r * difficulty, 3)
        else:
            old_r, old_quality = 0.0, 0.0
        self.old_r_samples.append(float(old_r))
        if old_r is not None and old_r < -0.05:
            self._anti_neg_streak += 1
            if self._anti_neg_streak >= 3 and not self.baseline_anti_corr:
                self.baseline_anti_corr = True
        else:
            self._anti_neg_streak = 0

        if new_result is not None:
            new_offset_ms, new_r = new_result
            new_quality = round(new_r * difficulty, 3)
        else:
            new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

        # envelope clip
        if new_result is not None and engine_play_best > 0.0:
            env = self.envelope_lookup.get((win_start, win_end))
            if env is not None:
                _safe_neg, _safe_pos = env
                _rel = new_offset_ms - engine_current
                if _rel < _safe_neg or _rel > _safe_pos:
                    new_result = None
                    new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

        stored_q = stored_quality
        base_threshold = stored_q / 10.0
        displacement_threshold = base_threshold * (1.5 if self.play_type == "skip" else 1.0)
        displacement_threshold = min(displacement_threshold, 0.10)
        old_floor = float(getattr(settings, "xcorr_old_correlating_floor", 0.50))
        if old_r >= old_floor:
            old_margin = float(getattr(settings, "xcorr_old_correlating_margin", 0.20))
            displacement_threshold = max(displacement_threshold, old_margin)
        if new_result is not None and new_r > old_r + displacement_threshold:
            win_offset, win_quality, win_r, is_new = new_offset_ms, new_quality, new_r, True
        else:
            win_offset, win_quality, win_r, is_new = stored_offset_ms, old_quality, old_r, False

        is_global_best = win_quality > self.best_quality
        if is_global_best:
            self.best_quality = win_quality
            self.best_offset = win_offset
            self.best_difficulty = difficulty

        seen: set[int] = set()
        _prev_shifts_len = len(self.confirmation_shifts)
        if win_r >= settings.xcorr_global_threshold:
            self.confirmation_shifts.append((win_offset, float(difficulty)))
            seen.add(win_offset)
        if (new_result is not None
                and new_r >= settings.xcorr_global_threshold
                and new_offset_ms not in seen):
            self.confirmation_shifts.append((new_offset_ms, float(difficulty)))
            seen.add(new_offset_ms)
        if (old_r >= settings.xcorr_global_threshold
                and stored_offset_ms not in seen):
            self.confirmation_shifts.append((stored_offset_ms, float(difficulty)))

        self.n_measurements += 1

        # engine snap
        snap = None
        if (self.verification != "user_verified" and win_r >= settings.xcorr_global_threshold):
            far_jump_ms = int(getattr(settings, "engine_snap_far_jump_ms", 1000))
            displacement = abs(int(win_offset) - engine_current)
            skip_snap = False
            if displacement > far_jump_ms:
                tol = int(getattr(settings, "xcorr_save_confirm_tol_ms", 300))
                agreeing = sum(
                    1 for s, _w in self.confirmation_shifts[:_prev_shifts_len]
                    if abs(s - win_offset) <= tol
                )
                high_q_floor = float(getattr(settings, "engine_snap_far_jump_q", 0.85))
                cold_start = engine_play_best == 0.0
                allow = (
                    agreeing >= 1
                    or win_quality >= high_q_floor
                    or (cold_start and self.baseline_anti_corr)
                )
                if not allow:
                    skip_snap = True
            if not skip_snap:
                snap = (int(win_offset), float(win_quality), self.baseline_anti_corr)

        # per-window disk save
        _save_confirm_tol = int(getattr(settings, "xcorr_save_confirm_tol_ms", 300))
        if self.baseline_anti_corr:
            _save_min_confirm = float(getattr(settings, "xcorr_save_min_confirm_anti", 1.5))
        else:
            _save_min_confirm = float(getattr(settings, "xcorr_save_min_confirm", 2))
        _agree_now = sum(
            w for s, w in self.confirmation_shifts
            if abs(s - self.best_offset) <= _save_confirm_tol
        )
        self._agree_now = _agree_now
        _single_save_r = float(getattr(settings, "xcorr_single_window_save_r", 0.78))
        _single_save_q = float(getattr(settings, "xcorr_single_window_save_q", 0.70))
        _single_save_far_r = float(getattr(settings, "xcorr_single_window_save_far_r", 0.90))
        _single_save_far_q = float(getattr(settings, "xcorr_single_window_save_far_q", 0.85))
        _far_jump_ms2 = int(getattr(settings, "xcorr_far_jump_ms", 1000))
        if self.best_quality > 0.5:
            is_far_jump = abs(win_offset - self.best_offset) > _far_jump_ms2
        else:
            is_far_jump = False
        if is_far_jump:
            eff_r, eff_q = _single_save_far_r, _single_save_far_q
        else:
            eff_r, eff_q = _single_save_r, _single_save_q

        save = None
        if (is_global_best
                and self.verification != "user_verified"
                and _agree_now >= _save_min_confirm):
            save = (self.best_offset, self.best_quality, "sweep", self.baseline_anti_corr)
        elif (is_global_best and self.verification != "user_verified"
                and win_r >= eff_r and win_quality >= eff_q):
            save = (win_offset, win_quality, "sweep-single", self.baseline_anti_corr)

        return (win_offset, win_quality, win_r, is_new, is_global_best, snap, save)

    def lock(self, engine_play_best):
        _lock_q = float(getattr(settings, "xcorr_lock_q", 0.75))
        _lock_agree = int(getattr(settings, "xcorr_lock_agree_windows", 3))
        return engine_play_best >= _lock_q and self._agree_now >= _lock_agree

    def finalize(self):
        """Returns (final_save_or_None, is_drifting_or_None)."""
        is_drifting = None
        if self.old_r_samples:
            meaningful = [r for r in self.old_r_samples if abs(r) > 0.05]
            neg_count = sum(1 for r in meaningful if r < -0.10)
            if meaningful:
                is_drifting = neg_count >= max(2, len(meaningful) // 2)

        if self.verification == "user_verified":
            return None, is_drifting
        min_save_q = float(getattr(settings, "xcorr_save_min_quality", 0.50))
        confirm_tol = int(getattr(settings, "xcorr_save_confirm_tol_ms", 300))
        if self.baseline_anti_corr:
            min_confirm = float(getattr(settings, "xcorr_save_min_confirm_anti", 1.5))
        else:
            min_confirm = float(getattr(settings, "xcorr_save_min_confirm", 2))

        def _agree_weight(target):
            return sum(w for s, w in self.confirmation_shifts if abs(s - target) <= confirm_tol)

        cluster_weights = {}
        for s, _w in self.confirmation_shifts:
            cluster_weights[s] = _agree_weight(s)
        best_cluster_centre = (max(cluster_weights, key=cluster_weights.get)
                               if cluster_weights else self.best_offset)
        best_cluster_weight = cluster_weights.get(best_cluster_centre, 0.0)
        best_offset_agree = _agree_weight(self.best_offset)

        if best_cluster_weight > best_offset_agree and best_cluster_weight >= min_confirm:
            cluster_members = [s for s, _w in self.confirmation_shifts
                               if abs(s - best_cluster_centre) <= confirm_tol]
            save_offset = int(round(sum(cluster_members) / len(cluster_members)))
            save_quality = self.best_quality
        else:
            save_offset = self.best_offset
            save_quality = self.best_quality

        agree = _agree_weight(save_offset)
        if save_quality < min_save_q:
            return None, is_drifting
        if agree < min_confirm:
            return None, is_drifting
        return (save_offset, save_quality, "sweep", self.baseline_anti_corr), is_drifting


def decision_differential_test(n_sequences: int = 2000, seed: int = 7,
                               verbose: bool = False) -> int:
    """Push randomized window sequences through reference + SweepEvaluator
    with independent (but identically seeded) FakeEngines. Returns the number
    of diverging sequences (0 = pass)."""
    rng = random.Random(seed)
    failures = 0

    for seq_i in range(n_sequences):
        verification = rng.choice(["auto_verified", "auto_verified", "user_verified"])
        play_type = rng.choice(["first", "natural", "skip"])
        seed_offset = rng.choice([0, 0, 500, -1200, 2400])
        n_windows = rng.randint(1, 10)
        windows = []
        t = rng.randint(0, 8000)
        for _ in range(n_windows):
            windows.append((t, t + 5000))
            t += rng.randint(5500, 20000)
        envelope_lookup = {}
        for w in windows:
            if rng.random() < 0.4:
                envelope_lookup[w] = (-rng.randint(200, 1500), rng.randint(200, 1500))

        ref = _ReferencePlay("bench:diff", verification, play_type, seed_offset, envelope_lookup)
        ev = SweepEvaluator(SweepConfig.from_settings(settings),
                            uri="bench:diff", verification=verification,
                            play_type=play_type, seed_offset_ms=seed_offset,
                            envelope_lookup=envelope_lookup)
        eng_ref = FakeEngine("bench:diff", seed_offset)
        eng_ev = FakeEngine("bench:diff", seed_offset)

        if rng.random() < 0.3:
            off, w = rng.randint(-3000, 3000), rng.uniform(0.5, 4.0)
            ref.add_anchor_vote(off, w)
            ev.add_anchor_vote(off, w)
            if rng.random() < 0.8:   # anchor usually snaps the engine too
                q = rng.uniform(0.3, 0.6) * 1.6
                eng_ref.apply_save("bench:diff", off, q, "anchor")
                eng_ev.apply_save("bench:diff", off, q, "anchor")

        diverged = None
        for wi, (ws, we) in enumerate(windows):
            difficulty = round(rng.uniform(0.0, 1.0), 3)
            old_r = None if rng.random() < 0.1 else round(rng.uniform(-1, 1), 3)
            if rng.random() < 0.2:
                new_result = None
            else:
                new_result = (rng.randint(-4000, 4000), round(rng.uniform(0.0, 1.0), 3))
            stored_quality = round(rng.uniform(0.0, 0.9), 3)
            # OLD test point = each side's own engine offset (live parity)
            old_r_in = float(old_r) if old_r is not None else 0.0

            r_out = ref.window(ws, we, difficulty, new_result, old_r_in,
                               eng_ref._shape_offset_ms, stored_quality,
                               eng_ref._shape_offset_ms, eng_ref._play_best_quality)
            o = ev.process_window(ws, we, difficulty=difficulty,
                                  new_result=new_result, old_r=old_r_in,
                                  stored_offset_ms=eng_ev._shape_offset_ms,
                                  stored_quality=stored_quality,
                                  engine_current_offset_ms=eng_ev._shape_offset_ms,
                                  engine_play_best_quality=eng_ev._play_best_quality)
            e_out = (o.win_offset, o.win_quality, o.win_r, o.is_new,
                     o.is_global_best, o.engine_snap, o.disk_save)
            if r_out != e_out:
                diverged = f"window {wi}: ref={r_out} ev={e_out}"
                break
            # apply side effects identically (snap, then disk save's engine apply)
            if r_out[5] is not None:
                s_off, s_q, s_byp = r_out[5]
                eng_ref.apply_save("bench:diff", s_off, s_q, "sweep-window", bypass_drift_cap=s_byp)
                eng_ev.apply_save("bench:diff", s_off, s_q, "sweep-window", bypass_drift_cap=s_byp)
            if r_out[6] is not None:
                d_off, d_q, d_src, d_byp = r_out[6]
                eng_ref.apply_save("bench:diff", d_off, d_q, d_src, bypass_drift_cap=d_byp)
                eng_ev.apply_save("bench:diff", d_off, d_q, d_src, bypass_drift_cap=d_byp)
            lr = ref.lock(eng_ref._play_best_quality)
            le = ev.lock_and_stop(eng_ev._play_best_quality)
            if lr != le:
                diverged = f"window {wi}: lock ref={lr} ev={le}"
                break
            if lr:
                break

        if diverged is None and ref.n_measurements > 0:
            r_fin = ref.finalize()
            e_final = ev.finalize()
            e_fin = (e_final.disk_save, e_final.is_drifting)
            if r_fin != e_fin:
                diverged = f"finalize: ref={r_fin} ev={e_fin}"

        if diverged:
            failures += 1
            if verbose or failures <= 3:
                print(f"  DIVERGENCE seq {seq_i}: {diverged}")

    return failures


def e2e_smoke(stem: Optional[str] = None) -> bool:
    """Replay one song clean at offset 0 — must store a correct offset."""
    from bench.corpus import load_corpus
    from bench.replay import Scenario, replay_play
    if stem is None:
        stem = load_corpus()["stems"][0]
    res = replay_play(stem, Scenario(name="smoke", true_offset_ms=0, seed="cold"))
    ok = res.correct or (res.final_stored_offset_ms is None
                         and abs(res.engine_final_error_ms) <= 300)
    print(f"  e2e smoke [{stem}]: stored={res.final_stored_offset_ms} "
          f"engine_err={res.engine_final_error_ms}ms windows={res.windows_evaluated} "
          f"anchor={res.anchor_matched} → {'OK' if ok else 'FAIL'}")
    return ok


def fft_parity_test(n_trials: int = 50, seed: int = 11,
                    tol: float = 1e-6) -> float:
    """Max |r_fft − r_loop| over every shift of `n_trials` random windows on
    real corpus songs. The loop scorer below is a verbatim copy of
    xcorr_window's score_at (grid slicing + per-slice z-score)."""
    import numpy as np
    from bench.corpus import load_corpus
    from bench.replay import load_song_assets
    from bench.simulate import load_wav, make_frames
    from services import xcorr_core as xc

    rng = random.Random(seed)
    stems = load_corpus()["stems"][:5]
    worst = 0.0
    for trial in range(n_trials):
        stem = stems[trial % len(stems)]
        cache = getattr(fft_parity_test, "_cache", {})
        if stem not in cache:
            assets = load_song_assets(stem)
            cache[stem] = (assets, make_frames(load_wav(assets["wav_path"])))
            fft_parity_test._cache = cache
        assets, frames = cache[stem]
        dur = int(assets["meta"].duration_ms or 120000)
        ws = rng.randrange(8000, max(9000, dur - 40000), 250)
        we = ws + 5000
        search_ms = rng.choice([2000, 3500, 8000])
        frames_now = [f for f in frames if f[0] <= we + 1000 + search_ms]

        landscape = xc.xcorr_window_full(
            assets["stored_ts"], assets["stored_bands"], frames_now, ws, we,
            search_ms=search_ms)
        if landscape is None:
            continue

        # Loop scorer — verbatim score_at math.
        BIN = xc.XCORR_BIN_MS
        bins = np.arange(ws, we, BIN, dtype=float)
        n_bins = len(bins)
        live_ts = np.array([f[0] for f in frames_now], dtype=float)
        band_info = []
        for band_idx, stored_rms in enumerate(assets["stored_bands"]):
            template = xc.agc_normalize(np.interp(bins, assets["stored_ts"], stored_rms))
            if template.std() < 1e-6:
                continue
            band_info.append((band_idx, (template - template.mean()) / template.std()))
        grid_start = ws - search_ms
        grid_ts = np.arange(grid_start, we + search_ms + BIN, BIN, dtype=float)
        n_grid = len(grid_ts)
        live_grid = {}
        for band_idx, _ in band_info:
            live_rms = xc.agc_normalize(xc.signed_square(
                np.array([f[1 + band_idx] for f in frames_now], dtype=float)))
            live_grid[band_idx] = np.interp(grid_ts, live_ts, live_rms, left=0.0, right=0.0)
        base_idx = int(round((ws - grid_start) / BIN))

        for k, shift in enumerate(landscape.shifts_ms):
            off = base_idx + int(shift) // BIN
            if off < 0 or off + n_bins > n_grid:
                continue
            r_sum, n_valid = 0.0, 0
            for band_idx, tnorm in band_info:
                sig = live_grid[band_idx][off: off + n_bins]
                if sig.std() < 1e-6:
                    continue
                r_sum += float(np.dot(tnorm, (sig - sig.mean()) / sig.std())) / n_bins
                n_valid += 1
            r_loop = (r_sum / n_valid) if n_valid else None
            r_fft = landscape.r[k]
            if r_loop is None:
                if np.isfinite(r_fft):
                    worst = max(worst, abs(float(r_fft)))
            else:
                if not np.isfinite(r_fft):
                    worst = max(worst, abs(r_loop))
                else:
                    worst = max(worst, abs(float(r_fft) - r_loop))
    return worst


def run_selftest() -> bool:
    print("Decision-differential test (2000 random sequences)...")
    failures = decision_differential_test()
    print(f"  {'PASS' if failures == 0 else 'FAIL'} — {failures} divergences")
    print("FFT-vs-loop kernel parity (50 random windows)...")
    worst = fft_parity_test()
    fft_ok = worst < 1e-6
    print(f"  {'PASS' if fft_ok else 'FAIL'} — max |r_fft − r_loop| = {worst:.2e}")
    print("End-to-end smoke replay...")
    smoke_ok = e2e_smoke()
    return failures == 0 and fft_ok and smoke_ok
