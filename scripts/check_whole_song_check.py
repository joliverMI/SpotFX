#!/usr/bin/env python3
"""Executable spec: the end-of-play WHOLE-SONG CHECK (services/whole_song_check.py)
and the re-save withholding (xcorr_sweep.SweepEvaluator.stronger_elsewhere).

data/lock-investigation/report.md §5.4/§8 recs 1 and 4; the Admiral's call,
2026-10-13, option A (correct automatically).

Run:  .venv/bin/python scripts/check_whole_song_check.py [--live-shapes DIR]

  §1  His two failing songs (their REAL stored shapes, tests/fixtures/
      whole_song/, with a live capture synthesised at the report's true
      offset) — the vote picks +11,750 for El Efecto and +6,250 for Ponle
      Dembow, and the twin each was stuck on scores like the report measured.
  §2  A song already right is never moved (saved at the truth, and within
      ±500 ms of it, across seeds).
  §3  A twin-ambiguous song (one phrase looped) splits its vote — nothing
      changes. RED CONTROL: with the gates collapsed the same vote WOULD move.
  §4  A play skipped early is too short to judge; a user-verified offset is
      reported and never saved.
  §5  Rec. 4 on the Ponle Dembow 18:42 window pattern: the capped +1,225 is
      not re-saved over seven +6,225 finds; RED CONTROL with withholding off.
  §6  (--live-shapes DIR, read-only) the report's 20 songs that locked on
      2026-10-12, at their locked offsets, from the live shape library: the
      vote agrees with every one of them and corrects none.

Exits non-zero on the first failed assertion. Writes nothing anywhere.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from services import whole_song_check as wsc            # noqa: E402
from services.xcorr_sweep import SweepConfig, SweepEvaluator   # noqa: E402
from tests import whole_song_world as W                  # noqa: E402

CFG = wsc.WholeSongConfig()
FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        FAILS.append(what)


def vote_for(name, truth, saved, *, seed=0, **kw):
    ts, sq, raw = W.load_fixture(name)
    frames = W.live_frames(ts, raw, truth, seed=seed, **kw)
    t0 = time.process_time()
    v = wsc.whole_song_vote(ts, sq, frames, saved_offset_ms=saved)
    return v, time.process_time() - t0


def section1() -> None:
    print("§1 the two songs the engine could not correct")
    for name, title, true_ms, twin_ms in (W.EL_EFECTO, W.PONLE_DEMBOW):
        v, cpu = vote_for(name, true_ms, twin_ms)
        d = wsc.decide(v, CFG)
        print(f"     {title}: vote {v.winner_offset_ms:+d} ms, {v.wins}/{v.n_windows} windows, "
              f"median r {v.median_r_winner:.2f}; saved {twin_ms:+d} ms r {v.median_r_saved:.2f}; "
              f"{cpu:.2f} s CPU -> {d.action}")
        check(d.action == wsc.CORRECTED and d.offset_ms == true_ms,
              f"{title} corrected {twin_ms:+d} -> {true_ms:+d} ms")
        check(v.median_r_saved < 0.65,
              f"{title}: the twin scores like the report measured (r {v.median_r_saved:.2f} < 0.65)")


def section2() -> None:
    print("§2 a song already right is never moved")
    moved = 0
    runs = 0
    for name, title, true_ms, _twin in (W.EL_EFECTO, W.PONLE_DEMBOW):
        for jitter in (0, -300, 200, 500):
            for seed in (1, 2, 3):
                v, _ = vote_for(name, true_ms, true_ms + jitter, seed=seed)
                d = wsc.decide(v, CFG)
                runs += 1
                if d.action == wsc.CORRECTED:
                    moved += 1
                    print(f"     MOVED {title} saved {true_ms + jitter:+d}: {d.reason}")
    check(moved == 0, f"0 of {runs} right-or-nearly-right saves moved")


def section3() -> None:
    print("§3 a twin-ambiguous song changes nothing")
    ts, sq, raw = W.periodic_shape()
    loose = wsc.WholeSongConfig(min_vote_fraction=0.0, min_median_r=0.0, min_r_margin=-1.0)
    for seed in (0, 1, 2):
        v = wsc.whole_song_vote(ts, sq, W.live_frames(ts, raw, 1000, seed=seed),
                                saved_offset_ms=-3000)
        d = wsc.decide(v, CFG)
        print(f"     seed {seed}: top bins {v.top_bins} of {v.n_windows} -> {d.action}")
        check(d.action == wsc.NO_CLEAR_MAJORITY, f"looped phrase seed {seed}: no clear majority")
        check(wsc.decide(v, loose).action == wsc.CORRECTED,
              f"RED CONTROL seed {seed}: with the gates collapsed it WOULD move")


def section4() -> None:
    print("§4 too short, and user-verified")
    v, _ = vote_for("el_efecto", 11750, 325, until_ms=50_000)
    check(wsc.decide(v, CFG).action == wsc.TOO_FEW_WINDOWS,
          f"a play skipped at 50 s ({v.n_windows} windows) is too short to judge")
    v, _ = vote_for("el_efecto", 11750, 325)
    d = wsc.decide(v, CFG, verification="user_verified")
    check(d.action == wsc.USER_VERIFIED and d.offset_ms is None,
          "a user-verified offset is reported, never saved")


def _ponle(min_repeats: int):
    cfg = SweepConfig(
        global_threshold=0.50, old_correlating_floor=0.50, old_correlating_margin=0.20,
        save_confirm_tol_ms=300, save_min_confirm=2.0, save_min_confirm_anti=1.5,
        save_min_quality=0.50, single_save_r=0.78, single_save_q=0.70,
        single_save_far_r=0.90, single_save_far_q=0.85, far_jump_ms=1000,
        engine_snap_far_jump_ms=1000, engine_snap_far_jump_q=0.85, lock_q=0.70,
        lock_agree_windows=3, withhold_resave_min_repeats=min_repeats)
    ev = SweepEvaluator(cfg, uri="ponle", verification="auto_verified",
                        play_type="natural", seed_offset_ms=1525)
    for i, (old_r, new_r) in enumerate([(0.70, 0.78), (0.62, 0.80), (0.66, 0.81),
                                        (0.60, 0.77), (0.65, 0.84), (0.68, 0.82),
                                        (0.64, 0.79)]):
        ev.process_window(40_000 + i * 6000, 45_000 + i * 6000, difficulty=0.9,
                          new_result=(6225, new_r), old_r=old_r, stored_offset_ms=1225,
                          stored_quality=0.6, engine_current_offset_ms=1225,
                          engine_play_best_quality=0.6, envelope_exempt=True)
    return ev, ev.finalize()


def section5() -> None:
    print("§5 rec. 4: the capped value is not re-saved over a stronger repeated find")
    _ev, off = _ponle(0)
    check(off.disk_save is not None and off.disk_save[0] == 1225,
          "RED CONTROL: with withholding off the sweep re-saves +1225 ms (the 18:42 log)")
    ev, on = _ponle(3)
    check(on.disk_save is None, "withholding on: nothing re-saved")
    check(ev.withheld_save is not None and ev.withheld_save["offset_ms"] == 6225,
          f"…and it names the stronger find: {ev.withheld_save}")


def section6(shapes_dir: Path) -> None:
    print(f"§6 the report's 20 locks, live shapes read-only from {shapes_dir}")
    found = 0
    for title, lock_ms in W.REPORT_LOCKS:
        p = W.find_live_shape(title, shapes_dir)
        if p is None:
            print(f"     (no shape for {title!r} — skipped)")
            continue
        found += 1
        ts, sq, raw = W.shape_from_npz(p)
        v = wsc.whole_song_vote(ts, sq, W.live_frames(ts, raw, lock_ms),
                                saved_offset_ms=lock_ms)
        d = wsc.decide(v, CFG)
        print(f"     {title}: lock {lock_ms:+d} vote {v.winner_offset_ms:+d} "
              f"{v.wins}/{v.n_windows} r {v.median_r_winner:.2f} -> {d.action}")
        check(d.action in (wsc.AGREES, wsc.SMALL_MOVE), f"{title}: not moved")
    check(found >= 18, f"{found} of {len(W.REPORT_LOCKS)} shapes found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-shapes", type=Path, default=None,
                    help="read-only audio_shapes dir for §6 (e.g. /home/javi/SpotFX/storage/audio_shapes)")
    args = ap.parse_args()
    section1()
    section2()
    section3()
    section4()
    section5()
    if args.live_shapes is not None:
        section6(args.live_shapes)
    else:
        print("§6 skipped (pass --live-shapes DIR to run the report's 20 locks)")
    print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} CHECK(S) FAILED"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
