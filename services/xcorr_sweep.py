"""
SpotFX — xcorr per-play decision state machine (pure logic, no I/O).

Extracted from the inline gate cascade in
`auto_offset_service._detect_loop_xcorr` so the offline bench harness can
drive the EXACT production decision logic. All numeric gates, ordering, and
log lines are transcribed verbatim from the original loop; the service (or
the harness) performs the side effects described by each `WindowOutcome`
(engine snap, disk save, WS broadcast) and then calls `lock_and_stop()` with
the engine's post-snap play-best quality — that ordering matters, because the
original loop read `engine._play_best_quality` *after* this window's
apply_save had already run.

State owned here: global best (offset/quality/difficulty), confirmation
shifts (difficulty-weighted votes incl. anchor votes), OLD r samples and the
anti-correlated-baseline streak, and the measurement count. The post-loop
cluster-override + final save gates live in `finalize()`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SweepConfig:
    """Snapshot of every settings.* knob the decision cascade reads.
    Built once per play via `from_settings` — the live loop re-read settings
    each window, but they only change via the settings UI mid-play (rare and
    benign), so a per-play snapshot is behaviorally equivalent.
    """
    global_threshold: float
    old_correlating_floor: float
    old_correlating_margin: float
    save_confirm_tol_ms: int
    save_min_confirm: float
    save_min_confirm_anti: float
    save_min_quality: float
    single_save_r: float
    single_save_q: float
    single_save_far_r: float
    single_save_far_q: float
    far_jump_ms: int
    engine_snap_far_jump_ms: int
    engine_snap_far_jump_q: float
    lock_q: float
    lock_agree_windows: int
    # Phase 3: evidence accumulation (active only when an accumulator is
    # attached to the evaluator).
    accum_lock_mass: float = 1.6
    accum_dominance: float = 0.5

    @classmethod
    def from_settings(cls, settings) -> "SweepConfig":
        return cls(
            global_threshold=float(settings.xcorr_global_threshold),
            old_correlating_floor=float(getattr(settings, "xcorr_old_correlating_floor", 0.50)),
            old_correlating_margin=float(getattr(settings, "xcorr_old_correlating_margin", 0.20)),
            save_confirm_tol_ms=int(getattr(settings, "xcorr_save_confirm_tol_ms", 300)),
            save_min_confirm=float(getattr(settings, "xcorr_save_min_confirm", 2)),
            save_min_confirm_anti=float(getattr(settings, "xcorr_save_min_confirm_anti", 1.5)),
            save_min_quality=float(getattr(settings, "xcorr_save_min_quality", 0.50)),
            single_save_r=float(getattr(settings, "xcorr_single_window_save_r", 0.78)),
            single_save_q=float(getattr(settings, "xcorr_single_window_save_q", 0.70)),
            single_save_far_r=float(getattr(settings, "xcorr_single_window_save_far_r", 0.90)),
            single_save_far_q=float(getattr(settings, "xcorr_single_window_save_far_q", 0.85)),
            far_jump_ms=int(getattr(settings, "xcorr_far_jump_ms", 1000)),
            engine_snap_far_jump_ms=int(getattr(settings, "engine_snap_far_jump_ms", 1000)),
            engine_snap_far_jump_q=float(getattr(settings, "engine_snap_far_jump_q", 0.85)),
            lock_q=float(getattr(settings, "xcorr_lock_q", 0.75)),
            lock_agree_windows=int(getattr(settings, "xcorr_lock_agree_windows", 3)),
            accum_lock_mass=float(getattr(settings, "xcorr_accum_lock_mass", 1.6)),
            accum_dominance=float(getattr(settings, "xcorr_accum_dominance", 0.5)),
        )


@dataclass
class SearchStage:
    name: str               # narrow | wide | global
    center_offset_ms: int   # OFFSET-domain center
    span_ms: int            # half-width

    @property
    def shift_bounds(self) -> tuple[int, int]:
        """Shift-domain (lo, hi) for xcorr_window_fft_full: offset range
        [c−span, c+span] ⇔ shift range [−c−span, −c+span]."""
        return (-self.center_offset_ms - self.span_ms,
                -self.center_offset_ms + self.span_ms)


class SearchLadder:
    """Phase 4 search escalation: narrow → wide → global. Starts narrow when
    the slot has history (centered on it + any observed cut-in), else wide.
    Escalates after N consecutive windows with no accepted NEW measurement,
    or immediately when the baseline is flagged anti-correlated. Never
    de-escalates within a play."""

    def __init__(self, *, history_center_ms: Optional[int],
                 wide_span_ms: int, narrow_span_ms: int,
                 global_span_ms: int, duration_ms: int,
                 escalate_after: int = 2) -> None:
        g_span = min(int(global_span_ms), max(int(duration_ms), int(wide_span_ms)))
        stages = []
        if history_center_ms is not None:
            stages.append(SearchStage("narrow", int(history_center_ms), int(narrow_span_ms)))
        stages.append(SearchStage("wide", int(history_center_ms or 0), int(wide_span_ms)))
        stages.append(SearchStage("global", 0, g_span))
        self.stages = stages
        self._idx = 0
        self._empty_streak = 0
        self.escalate_after = int(escalate_after)

    @property
    def current(self) -> SearchStage:
        return self.stages[self._idx]

    def note_window(self, found: bool) -> Optional[SearchStage]:
        """Record a window result. Returns the new stage when escalating."""
        if found:
            self._empty_streak = 0
            return None
        self._empty_streak += 1
        if (self._empty_streak >= self.escalate_after
                and self._idx < len(self.stages) - 1):
            self._idx += 1
            self._empty_streak = 0
            return self.current
        return None

    def escalate(self) -> Optional[SearchStage]:
        """Advance one stage manually (Phase 5 mismatch recovery: position
        re-syncs are small — the next stage almost always contains the
        truth, while global is where twins live)."""
        if self._idx < len(self.stages) - 1:
            self._idx += 1
            self._empty_streak = 0
            return self.current
        return None

    def escalate_to_global(self) -> Optional[SearchStage]:
        if self._idx < len(self.stages) - 1:
            self._idx = len(self.stages) - 1
            self._empty_streak = 0
            return self.current
        return None


@dataclass
class MonitorConfig:
    """Phase 5: continuous mismatch monitor knobs (sibling of SweepConfig —
    kept separate so the decision-differential selftest's SweepConfig
    transcription stays untouched)."""
    interval_ms: int = 2000
    span_ms: int = 4000
    min_r: float = 0.20
    confirm_checks: int = 2
    max_recoveries: int = 2
    spike_lookback_ms: int = 15000
    spike_halfwin_ms: int = 2500
    demote_q: float = 0.40
    accum_decay: float = 0.5

    @classmethod
    def from_settings(cls, settings) -> "MonitorConfig":
        return cls(
            interval_ms=int(getattr(settings, "xcorr_monitor_interval_ms", 2000)),
            span_ms=int(getattr(settings, "xcorr_monitor_span_ms", 4000)),
            min_r=float(getattr(settings, "xcorr_monitor_min_r", 0.20)),
            confirm_checks=int(getattr(settings, "xcorr_monitor_confirm_checks", 2)),
            max_recoveries=int(getattr(settings, "xcorr_monitor_max_recoveries", 2)),
            spike_lookback_ms=int(getattr(settings, "xcorr_monitor_spike_lookback_ms", 15000)),
            spike_halfwin_ms=int(getattr(settings, "xcorr_monitor_spike_halfwin_ms", 2500)),
            demote_q=float(getattr(settings, "xcorr_monitor_demote_q", 0.40)),
            accum_decay=float(getattr(settings, "xcorr_monitor_accum_decay", 0.5)),
        )


class MismatchMonitor:
    """Phase 5 wrong-lock detector. States: ok → suspect (1..K−1 consecutive
    low checks) → confirmed (returns 'confirmed' once, capped per play).

    Rules: a None rolling_r (flat/quiet span) is NEUTRAL — no increment, no
    reset (silence can't hide a wrong lock); an unlocked engine
    (play_best ≤ 0) resets (not-locked is not mismatch); recoveries are
    capped per play — after the cap the monitor keeps reporting state but
    never confirms again.
    """

    def __init__(self, cfg: MonitorConfig) -> None:
        self.cfg = cfg
        self.low_streak = 0
        self.recoveries = 0
        self.state = "ok"            # ok | suspect | recovering
        self.last_r: Optional[float] = None

    def note_check(self, rolling_r: Optional[float],
                   engine_play_best: float) -> str:
        """Returns 'none' or 'confirmed'."""
        self.last_r = rolling_r
        if rolling_r is None:
            return "none"
        if engine_play_best <= 0.0:
            self.low_streak = 0
            self.state = "ok"
            return "none"
        if rolling_r < self.cfg.min_r:
            self.low_streak += 1
            if (self.low_streak >= self.cfg.confirm_checks
                    and self.recoveries < self.cfg.max_recoveries):
                self.low_streak = 0
                self.recoveries += 1
                self.state = "recovering"
                return "confirmed"
            self.state = "suspect"
        else:
            self.low_streak = 0
            self.state = "ok"
        return "none"

    def recovery_done(self) -> None:
        self.state = "ok"


@dataclass
class WindowOutcome:
    """Everything the caller needs to perform this window's side effects."""
    win_start: int
    win_end: int
    # Winner
    win_offset: int
    win_quality: float
    win_r: float
    is_new: bool
    is_global_best: bool
    displacement_threshold: float
    # NEW candidate after the envelope clip (None when rejected/absent)
    new_result: Optional[tuple[int, float]]
    new_offset_ms: int
    new_r: float
    new_quality: float
    envelope_clipped: bool
    # OLD candidate
    old_offset_ms: int
    old_r: float
    old_quality: float
    difficulty: float
    # Side effects for the caller
    engine_snap: Optional[tuple[int, float, bool]]   # (offset, quality, bypass_drift_cap)
    disk_save: Optional[tuple[int, float, str, bool]]  # (offset, quality, source, bypass)
    # Diagnostics
    agree_now: float
    baseline_anti_corr: bool


@dataclass
class FinalDecision:
    """Post-loop result: what to persist and report."""
    best_offset: int
    best_quality: float
    best_difficulty: float
    n_measurements: int
    disk_save: Optional[tuple[int, float, str, bool]]  # (offset, quality, source, bypass)
    is_drifting: Optional[bool]   # None = not enough meaningful OLD samples
    baseline_anti_corr: bool


class SweepEvaluator:
    """Per-play xcorr decision state machine. See module docstring."""

    def __init__(
        self,
        cfg: SweepConfig,
        *,
        uri: str,
        verification: str,
        play_type: str,
        seed_offset_ms: int,
        envelope_lookup: Optional[dict[tuple[int, int], tuple[int, int]]] = None,
        accumulator=None,   # services.xcorr_evidence.EvidenceAccumulator | None
    ) -> None:
        self.cfg = cfg
        self.uri = uri
        self.verification = verification
        self.play_type = play_type
        self.envelope_lookup = envelope_lookup or {}
        # Phase 3: when an accumulator is attached, disk saves and
        # lock-and-stop read the accumulated evidence function instead of
        # the discrete confirmation clusters. None = legacy behavior.
        self.accumulator = accumulator
        self._last_accum_save_offset: Optional[int] = None

        self.best_quality: float = -1.0
        # Seed best_offset with the stored offset for this slot so the post-loop
        # save defaults to "no change" if nothing convincingly displaces it.
        # (best_quality stays at -1.0 — we don't seed it, otherwise legitimate
        # corrections at lower Q than the historical lock could never displace.)
        self.best_offset: int = int(seed_offset_ms)
        self.best_difficulty: float = 0.0
        self.n_measurements: int = 0
        # (shift_ms, weight) pairs from windows where r >= xcorr_global_threshold.
        # Weight is the window's `difficulty` (intrinsic uniqueness). Both NEW
        # and OLD candidates are tracked when above threshold — even when a
        # candidate loses the per-window displacement gate, it still counts
        # toward cluster detection.
        self.confirmation_shifts: list[tuple[int, float]] = []
        # Per-window OLD r values — drives the "OLD is broken" detector.
        self.old_r_samples: list[float] = []
        self.baseline_anti_corr: bool = False
        self._anti_neg_streak: int = 0
        self._last_agree_now: float = 0.0

    # ── Anchor / progressive votes ────────────────────────────────────────────
    def add_anchor_vote(self, offset_ms: int, weight: float) -> None:
        """The anchor's offset becomes a vote in the sweep's cluster gate.
        Weight = match_r × eligible_count (cross-validation strength)."""
        self.confirmation_shifts.append((int(offset_ms), float(weight)))
        if self.accumulator is not None:
            self.accumulator.add_gaussian(int(offset_ms), float(weight))

    def add_progressive_vote(self, offset_ms: int, weight: float) -> None:
        """A progressive early-match vote (same dual bookkeeping as anchor)."""
        self.confirmation_shifts.append((int(offset_ms), float(weight)))
        if self.accumulator is not None:
            self.accumulator.add_gaussian(int(offset_ms), float(weight))

    def note_mismatch_confirmed(self, decay: float = 0.5) -> None:
        """Phase 5: a confirmed live mismatch means this play's converged
        state is suspect. Haircut best_quality so corrective windows can
        become global-best again, and decay accumulated evidence so the
        wrong peak can be out-voted by fresh measurements. Deliberately
        does NOT set baseline_anti_corr — that would relax save gates and
        bypass drift caps on a possibly-false confirmation (e.g. a DJ
        edit); the dynamic window's OLD eval feeds the anti-corr streak
        organically instead. That non-relaxation is the disk-damage
        firewall."""
        if self.best_quality > 0:
            self.best_quality *= float(decay)
        if self.accumulator is not None:
            self.accumulator.decay(float(decay))
        self._last_accum_save_offset = None

    # ── Per-window evaluation ─────────────────────────────────────────────────
    def process_window(
        self,
        win_start: int,
        win_end: int,
        *,
        difficulty: float,
        new_result: Optional[tuple[int, float]],
        old_r: Optional[float],
        stored_offset_ms: int,
        stored_quality: float,
        engine_current_offset_ms: int,
        engine_play_best_quality: float,
        landscape=None,   # xcorr_core.Landscape | None (FFT path, Phase 3)
        envelope_exempt: bool = False,   # global-stage search (Phase 4): the
                                         # U-Score envelopes were vetted only
                                         # over ±12 beats — skip the clip
    ) -> WindowOutcome:
        """Evaluate one completed window. `stored_offset_ms` is the OLD test
        point (the engine's runtime offset, or the disk median fallback);
        `stored_quality` is the slot's stored quality used for the
        displacement threshold. `landscape` feeds the evidence accumulator
        when one is attached."""
        cfg = self.cfg

        if old_r is not None:
            old_quality = round(old_r * difficulty, 3)
        else:
            old_r, old_quality = 0.0, 0.0
        self.old_r_samples.append(float(old_r))
        # Track consecutive negative-OLD-r windows. When this hits 3+, the
        # loaded baseline is provably wrong for this play and the downstream
        # gates relax to allow a corrective save.
        if old_r is not None and old_r < -0.05:
            self._anti_neg_streak += 1
            if self._anti_neg_streak >= 3 and not self.baseline_anti_corr:
                self.baseline_anti_corr = True
                logger.info(
                    "Auto-offset xcorr: baseline flagged anti-correlated for %s "
                    "(%d consecutive windows with OLD r<0) — relaxing save gates",
                    self.uri, self._anti_neg_streak,
                )
        else:
            self._anti_neg_streak = 0

        if new_result is not None:
            new_offset_ms, new_r = new_result
            new_quality = round(new_r * difficulty, 3)
        else:
            new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

        # Round 9.5: envelope clip. Each window has a precomputed safe-shift
        # range — outside it, the matcher's peak likely landed on a twin
        # rather than the truth. Reject the NEW measurement when it falls
        # outside `engine_current ± envelope`. Skip the clip during cold-start
        # (engine has not snapped yet this play) so a far-from-loaded truth
        # can still be discovered.
        envelope_clipped = False
        if new_result is not None and engine_play_best_quality > 0.0 and not envelope_exempt:
            env = self.envelope_lookup.get((win_start, win_end))
            if env is not None:
                _safe_neg, _safe_pos = env
                _rel = new_offset_ms - engine_current_offset_ms
                if _rel < _safe_neg or _rel > _safe_pos:
                    logger.info(
                        "xcorr reject: window [%d–%d]ms envelope clip — NEW %+dms "
                        "(%+dms from engine %+dms) outside [%+d, %+d] for %s",
                        win_start, win_end, new_offset_ms, _rel, engine_current_offset_ms,
                        _safe_neg, _safe_pos, self.uri,
                    )
                    envelope_clipped = True
                    new_result = None
                    new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

        # ── Pick winner for this window ───────────────────────────────────
        # NEW must beat OLD's r by displacement_threshold to displace.
        base_threshold = stored_quality / 10.0
        displacement_threshold = base_threshold * (1.5 if self.play_type == "skip" else 1.0)
        displacement_threshold = min(displacement_threshold, 0.10)
        # Round 8 — OLD-aware displacement floor. When OLD is positively
        # correlating, a NEW measurement at a DIFFERENT offset only deserves
        # to displace if it beats OLD by a wide margin.
        if old_r >= cfg.old_correlating_floor:
            displacement_threshold = max(displacement_threshold, cfg.old_correlating_margin)
        if new_result is not None and new_r > old_r + displacement_threshold:
            win_offset, win_quality, win_r, is_new = new_offset_ms, new_quality, new_r, True
        else:
            win_offset, win_quality, win_r, is_new = stored_offset_ms, old_quality, old_r, False

        is_global_best = win_quality > self.best_quality
        if is_global_best:
            self.best_quality = win_quality
            self.best_offset = win_offset
            self.best_difficulty = difficulty

        # Multi-window confirmation: record BOTH the per-window winner AND any
        # losing candidate that cleared the global threshold.
        seen: set[int] = set()
        _prev_shifts_len = len(self.confirmation_shifts)  # round 9: snapshot for engine-snap stickiness gate
        if win_r >= cfg.global_threshold:
            self.confirmation_shifts.append((win_offset, float(difficulty)))
            seen.add(win_offset)
        if (new_result is not None
                and new_r >= cfg.global_threshold
                and new_offset_ms not in seen):
            self.confirmation_shifts.append((new_offset_ms, float(difficulty)))
            seen.add(new_offset_ms)
        if (old_r >= cfg.global_threshold
                and stored_offset_ms not in seen):
            self.confirmation_shifts.append((stored_offset_ms, float(difficulty)))

        self.n_measurements += 1

        # Phase 3: feed the full landscape into the evidence accumulator
        # (offset domain = −shift), weighted by window difficulty. The
        # envelope clip above only nulls the discrete NEW result — the curve
        # itself is still evidence.
        if self.accumulator is not None and landscape is not None:
            self.accumulator.add_curve(
                -np.asarray(landscape.shifts_ms, dtype=float),
                landscape.r, float(difficulty),
            )

        # ── Engine snap decision (round 9 stickiness gate) ─────────────────
        engine_snap: Optional[tuple[int, float, bool]] = None
        if self.verification != "user_verified" and win_r >= cfg.global_threshold:
            displacement = abs(int(win_offset) - engine_current_offset_ms)
            skip_snap = False
            if displacement > cfg.engine_snap_far_jump_ms:
                agreeing = sum(
                    1 for s, _w in self.confirmation_shifts[:_prev_shifts_len]
                    if abs(s - win_offset) <= cfg.save_confirm_tol_ms
                )
                cold_start = engine_play_best_quality == 0.0
                allow = (
                    agreeing >= 1
                    or win_quality >= cfg.engine_snap_far_jump_q
                    or (cold_start and self.baseline_anti_corr)
                )
                if not allow:
                    logger.info(
                        "Engine: skip snap — far jump %+dms (Δ=%dms, Q=%.2f) without prior agreement for %s",
                        int(win_offset), displacement, float(win_quality), self.uri,
                    )
                    skip_snap = True
            if not skip_snap:
                engine_snap = (int(win_offset), float(win_quality), self.baseline_anti_corr)

        # ── Per-window DISK save decision ───────────────────────────────────
        if self.baseline_anti_corr:
            _save_min_confirm = cfg.save_min_confirm_anti
        else:
            _save_min_confirm = cfg.save_min_confirm
        _agree_now = sum(
            w for s, w in self.confirmation_shifts
            if abs(s - self.best_offset) <= cfg.save_confirm_tol_ms
        )
        self._last_agree_now = _agree_now
        # Single-window high-r escape hatch, tiered by distance from the
        # sweep's current best offset (round 8).
        if self.best_quality > 0.5:
            is_far_jump = abs(win_offset - self.best_offset) > cfg.far_jump_ms
        else:
            is_far_jump = False
        if is_far_jump:
            eff_r, eff_q = cfg.single_save_far_r, cfg.single_save_far_q
        else:
            eff_r, eff_q = cfg.single_save_r, cfg.single_save_q

        disk_save: Optional[tuple[int, float, str, bool]] = None
        single_escape = (is_global_best and self.verification != "user_verified"
                         and win_r >= eff_r and win_quality >= eff_q)
        if self.accumulator is not None:
            # Phase 3: the accumulated-evidence peak replaces the discrete
            # cluster vote. The single-window high-r escape survives as an
            # explicit special case (one great window can't reach the mass
            # bar alone). Repeat saves of the same peak are suppressed.
            peak = self.accumulator.dominant()
            sanity_r = (landscape.r_at(-peak.offset_ms)
                        if (peak is not None and landscape is not None) else None)
            if (peak is not None
                    and self.verification != "user_verified"
                    and peak.mass >= cfg.accum_lock_mass
                    and peak.dominance >= cfg.accum_dominance
                    and peak.support >= 2
                    and sanity_r is not None
                    and sanity_r >= cfg.global_threshold
                    and peak.offset_ms != self._last_accum_save_offset):
                logger.info(
                    "Auto-offset xcorr: SAVING accumulated-evidence peak — %+dms mass=%.2f dom=%.2f support=%d sanity_r=%.2f for %s",
                    peak.offset_ms, peak.mass, peak.dominance, peak.support,
                    sanity_r, self.uri,
                )
                disk_save = (peak.offset_ms, max(0.0, self.best_quality),
                             "sweep-accum", self.baseline_anti_corr)
                self._last_accum_save_offset = peak.offset_ms
            elif single_escape:
                tag = "far-jump" if is_far_jump else "near"
                logger.info(
                    "Auto-offset xcorr: SAVING single-window high-r [%s] — %+dms r=%.2f Q=%.2f (accum %s, but r≥%.2f & Q≥%.2f)",
                    tag, win_offset, win_r, win_quality,
                    f"mass={peak.mass:.2f}" if peak else "empty", eff_r, eff_q,
                )
                disk_save = (win_offset, win_quality, "sweep-single", self.baseline_anti_corr)
        elif (is_global_best
                and self.verification != "user_verified"
                and _agree_now >= _save_min_confirm):
            disk_save = (self.best_offset, self.best_quality, "sweep", self.baseline_anti_corr)
        elif single_escape:
            tag = "far-jump" if is_far_jump else "near"
            logger.info(
                "Auto-offset xcorr: SAVING single-window high-r [%s] — %+dms r=%.2f Q=%.2f (cluster %.2f<%.1f, but r≥%.2f & Q≥%.2f)",
                tag, win_offset, win_r, win_quality, _agree_now, _save_min_confirm,
                eff_r, eff_q,
            )
            disk_save = (win_offset, win_quality, "sweep-single", self.baseline_anti_corr)
        elif is_global_best and self.verification != "user_verified":
            logger.info(
                "Auto-offset xcorr: per-window save deferred — %+dms only weighted=%.2f/%.1f within ±%dms (r=%.2f<%.2f or Q=%.2f<%.2f for single-win)",
                self.best_offset, _agree_now, _save_min_confirm, cfg.save_confirm_tol_ms,
                win_r, cfg.single_save_r, win_quality, cfg.single_save_q,
            )

        return WindowOutcome(
            win_start=win_start, win_end=win_end,
            win_offset=win_offset, win_quality=win_quality, win_r=win_r,
            is_new=is_new, is_global_best=is_global_best,
            displacement_threshold=displacement_threshold,
            new_result=new_result, new_offset_ms=new_offset_ms,
            new_r=new_r, new_quality=new_quality,
            envelope_clipped=envelope_clipped,
            old_offset_ms=stored_offset_ms, old_r=old_r, old_quality=old_quality,
            difficulty=difficulty,
            engine_snap=engine_snap, disk_save=disk_save,
            agree_now=_agree_now, baseline_anti_corr=self.baseline_anti_corr,
        )

    # ── Lock-and-stop (call AFTER applying this window's engine snap) ─────────
    def lock_and_stop(self, engine_play_best_quality: float) -> bool:
        """True when the engine has snapped at high Q AND the evidence agrees
        on the offset — the marginal value of trailing windows is nil."""
        if self.accumulator is not None:
            peak = self.accumulator.dominant()
            if (engine_play_best_quality >= self.cfg.lock_q
                    and peak is not None
                    and peak.mass >= self.cfg.accum_lock_mass
                    and peak.dominance >= self.cfg.accum_dominance):
                logger.info(
                    "Auto-offset xcorr: lock-and-stop at Q=%.2f — accum peak %+dms mass=%.2f dom=%.2f for %s",
                    engine_play_best_quality, peak.offset_ms, peak.mass,
                    peak.dominance, self.uri,
                )
                return True
            return False
        if (engine_play_best_quality >= self.cfg.lock_q
                and self._last_agree_now >= self.cfg.lock_agree_windows):
            logger.info(
                "Auto-offset xcorr: lock-and-stop at Q=%.2f after %.1f agreeing weight (≥%d) for %s",
                engine_play_best_quality, self._last_agree_now,
                self.cfg.lock_agree_windows, self.uri,
            )
            return True
        return False

    def _finalize_cluster(self, cfg: SweepConfig) -> Optional[tuple[int, float, str, bool]]:
        """Legacy weighted-cluster save gate (pre-Phase-3) — the final
        authority when no accumulator is attached, and the Phase-5 fallback
        when a post-recovery accumulator hasn't rebuilt enough mass.
        Save guard: don't pollute the stored offset with weak or
        one-window-only measurements. Cluster confirmation_shifts within
        ±tol and prefer the most-agreed cluster when it beats
        best_offset's agreement."""
        if self.baseline_anti_corr:
            min_confirm = cfg.save_min_confirm_anti
        else:
            min_confirm = cfg.save_min_confirm

        def _agree_weight(target: int) -> float:
            return sum(w for s, w in self.confirmation_shifts
                       if abs(s - target) <= cfg.save_confirm_tol_ms)

        cluster_weights: dict[int, float] = {}
        for s, _w in self.confirmation_shifts:
            cluster_weights[s] = _agree_weight(s)
        best_cluster_centre = (max(cluster_weights, key=cluster_weights.get)
                               if cluster_weights else self.best_offset)
        best_cluster_weight = cluster_weights.get(best_cluster_centre, 0.0)
        best_offset_agree = _agree_weight(self.best_offset)

        # Prefer cluster centre when its weighted agreement strictly beats
        # the single-best-Q offset's.
        if best_cluster_weight > best_offset_agree and best_cluster_weight >= min_confirm:
            cluster_members = [s for s, _w in self.confirmation_shifts
                               if abs(s - best_cluster_centre) <= cfg.save_confirm_tol_ms]
            save_offset = int(round(sum(cluster_members) / len(cluster_members)))
            save_quality = self.best_quality
            logger.info(
                "Auto-offset xcorr: cluster override — saving %+dms (cluster weight=%.2f) "
                "instead of single-best %+dms (weight=%.2f)",
                save_offset, best_cluster_weight, self.best_offset, best_offset_agree,
            )
        else:
            save_offset = self.best_offset
            save_quality = self.best_quality

        agree = _agree_weight(save_offset)

        if save_quality < cfg.save_min_quality:
            logger.info(
                "Auto-offset xcorr: NOT saving — best Q=%.2f < min %.2f "
                "(measured=%+dms, stored offset unchanged)",
                save_quality, cfg.save_min_quality, save_offset,
            )
            return None
        if agree < min_confirm:
            logger.info(
                "Auto-offset xcorr: NOT saving — weighted %.2f confirmed "
                "%+dms within ±%dms (need %.1f) "
                "(measured Q=%.2f, stored offset unchanged)",
                agree, save_offset, cfg.save_confirm_tol_ms, min_confirm, save_quality,
            )
            return None
        return (save_offset, save_quality, "sweep", self.baseline_anti_corr)

    # ── Post-loop finalization ────────────────────────────────────────────────
    def finalize(self) -> FinalDecision:
        """Cluster-override + final save gates (the post-loop logic)."""
        cfg = self.cfg

        # OLD-anti-correlated detector: majority of meaningful OLD samples
        # negative → the stored baseline doesn't fit this play.
        is_drifting: Optional[bool] = None
        if self.old_r_samples:
            meaningful = [r for r in self.old_r_samples if abs(r) > 0.05]
            neg_count = sum(1 for r in meaningful if r < -0.10)
            if meaningful:
                is_drifting = neg_count >= max(2, len(meaningful) // 2)

        disk_save: Optional[tuple[int, float, str, bool]] = None
        if self.verification == "user_verified":
            logger.info(
                "Auto-offset xcorr: user_verified — NOT saving "
                "(measured=%+dms Q=%.2f, stored offset unchanged)",
                self.best_offset, self.best_quality,
            )
        elif self.accumulator is not None:
            # Phase 3: final save reads the accumulated evidence function.
            peak = self.accumulator.dominant()
            if (peak is not None
                    and peak.mass >= cfg.accum_lock_mass
                    and peak.dominance >= cfg.accum_dominance
                    and peak.support >= 2
                    and self.best_quality >= cfg.save_min_quality):
                disk_save = (peak.offset_ms, self.best_quality,
                             "sweep-accum", self.baseline_anti_corr)
            else:
                logger.info(
                    "Auto-offset xcorr: accum peak below save gates %s (need mass≥%.1f dom≥%.1f support≥2, Q=%.2f≥%.2f) — trying cluster fallback",
                    (f"{peak.offset_ms:+d}ms mass={peak.mass:.2f} dom={peak.dominance:.2f} "
                     f"support={peak.support}") if peak else "empty",
                    cfg.accum_lock_mass, cfg.accum_dominance,
                    self.best_quality, cfg.save_min_quality,
                )
                # Phase 5: cluster fallback. After a mismatch recovery the
                # accumulator's mass was deliberately decayed — the few
                # post-recovery windows may not rebuild it past the mass bar
                # even when they clearly agree. The pre-Phase-3 weighted
                # cluster gate (≥2.0 within ±300ms) is the battle-tested
                # arbiter for exactly that "few but agreeing" situation.
                disk_save = self._finalize_cluster(cfg)
        else:
            disk_save = self._finalize_cluster(cfg)

        return FinalDecision(
            best_offset=self.best_offset,
            best_quality=self.best_quality,
            best_difficulty=self.best_difficulty,
            n_measurements=self.n_measurements,
            disk_save=disk_save,
            is_drifting=is_drifting,
            baseline_anti_corr=self.baseline_anti_corr,
        )
