"""THE PRE-DROP RULES (predrop plan step 3; spectra/services/
predrop_detector.py is the binding statement): the spike and the vocal
intro on synthetic envelopes — every test of both rules, passing and
failing alone — the tiers, one pre-drop per drop, and the re-anchor. Then
his own songs, through the cut windows scripts/check_predrop_detector.py
--write-fixtures committed (each proven there to agree with its whole
song), and Eyes Cut Deeper whole through drop_detector.detect. Never his
storage."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from spectra import config
from spectra.services import drop_detector
from spectra.services import predrop_detector as P

FIXTURES = Path(__file__).parent / "fixtures" / "predrop"
FRAME = 12
BEAT = 500.0          # 120 bpm
D = 20_000            # the drop
UNIT = {"low": 1.0, "mid": 1.0, "high": 1.0}   # ceilings: the bands read as given


def _song(n_ms: int = 30_000) -> tuple[np.ndarray, dict]:
    """Music to 4 s before the drop, a hushed break, the drop's music after."""
    t = np.arange(0, n_ms, FRAME, dtype=np.int64)
    bands = {"low": np.full(len(t), 0.6), "mid": np.full(len(t), 0.3),
             "high": np.full(len(t), 0.3)}
    _set(t, bands["low"], D - 4000, D, 0.02)
    _set(t, bands["mid"], D - 4000, D, 0.02)
    _set(t, bands["high"], D - 4000, D, 0.05)
    _set(t, bands["low"], D, n_ms, 0.8)
    _set(t, bands["mid"], D, n_ms, 0.5)
    _set(t, bands["high"], D, n_ms, 0.5)
    return t, bands


def _set(t, x, a_ms, b_ms, v) -> None:
    x[(t >= a_ms) & (t < b_ms)] = v


def _hit(t, x, at_ms, peak=0.9, hold_ms=48) -> None:
    """One short hit: `hold_ms` at `peak`, back to the floor over 100 ms."""
    floor = float(x[int(np.searchsorted(t, at_ms)) - 1])
    _set(t, x, at_ms, at_ms + hold_ms, peak)
    for k, ms in enumerate(range(int(at_ms + hold_ms), int(at_ms + hold_ms + 100), FRAME)):
        _set(t, x, ms, ms + FRAME, peak - (peak - floor) * (k + 1) / 9)


def _shape(t, bands):
    return P.make_shape(t, bands, BEAT, ceilings=UNIT)


# ── kind 1: the spike ───────────────────────────────────────────────────────

H = D - 800


def _spike_song():
    t, b = _song()
    _hit(t, b["high"], H)
    return t, b


def test_a_lone_loud_hit_in_the_hush_is_a_confident_spike_on_its_attack():
    r = P.spike(_shape(*_spike_song()), D)
    assert r["status"] == "found"
    assert abs(r["ms"] - H) <= 3 * FRAME          # on the hit's attack
    assert r["lead"] == D - r["ms"]
    assert set(r["margins"]) == {"peak", "ratio", "local_iso", "global_iso", "later",
                                 "after", "sustain"}
    assert r["score"] == pytest.approx(min(r["margins"].values()))
    assert r["margins"]["peak"] == pytest.approx(0.9 / P.SPIKE_PEAK_MIN, rel=1e-6)
    assert P.tier_for(P.KIND_SPIKE, r["score"], r["lead"]) == P.TIER_CONFIDENT


def _spike_fails(mutate, weakest, th=None):
    t, b = _spike_song()
    mutate(t, b)
    r = P.spike(_shape(t, b), D, th=th)
    assert r["status"] == "weak", r
    assert r["weakest"] == weakest, r["margins"]
    assert r["score"] < P.FOUND_SCORE
    return r


def test_spike_test_loud_a_hit_under_the_ceiling_bar_is_not_one():
    r = _spike_fails(lambda t, b: _hit(t, b["high"], H, peak=0.6), "peak")
    assert r["margins"]["peak"] == pytest.approx(0.6 / P.SPIKE_PEAK_MIN, rel=1e-6)


def test_spike_test_stands_out_a_hit_on_a_busy_bed_is_not_one():
    def busy(t, b):
        _set(t, b["high"], D - 4000, H, 0.3)       # no hush before it
        _hit(t, b["high"], H)
    r = _spike_fails(busy, "ratio")
    assert r["margins"]["ratio"] == pytest.approx(((0.9 + 0.03) / (0.3 + 0.03)) / P.SPIKE_RATIO_MIN,
                                                  rel=1e-3)


def test_spike_test_not_a_beat_a_hit_with_another_just_before_it_is_not_one():
    # another as loud within the 1.25 beats before it: a beat, not a moment
    _spike_fails(lambda t, b: _hit(t, b["high"], H - 400), "local_iso")


def test_spike_test_the_loudest_of_the_last_3_s_an_equal_hit_earlier_is_not_one():
    # outside the 1.25 beats, inside the 3 s before the drop
    _spike_fails(lambda t, b: _hit(t, b["high"], H - 1500), "global_iso")


def test_spike_test_the_last_word_a_comparable_hit_after_it_is_not_one():
    _spike_fails(lambda t, b: _hit(t, b["high"], H + 400, peak=0.6), "later")


def test_spike_test_the_last_word_the_high_band_must_fall_away_after_it():
    # the mean after can only fail where the max after passes on a tighter
    # bar: the high band settling at 6% of the hit fails a 4% bar alone
    r = _spike_fails(lambda t, b: None, "after", th={"AFTER_MAX": 0.04})
    assert r["margins"]["later"] > 1.0


def test_spike_test_not_the_drop_the_bass_staying_up_after_it_is_not_one():
    def bass_in(t, b):
        _set(t, b["low"], H, D, 0.6)              # the bass is already back
    _spike_fails(bass_in, "sustain")


def test_spike_searches_its_own_window_only():
    for lead in (200, 3200):                     # under 250 ms, over 3 s
        t, b = _song()
        _hit(t, b["high"], D - lead)
        assert P.spike(_shape(t, b), D)["status"] == "none"
    t, b = _song()
    _hit(t, b["high"], D - 300)                  # inside the search, outside the study's
    s = _shape(t, b)
    assert P.spike(s, D)["status"] == "found"
    assert P.spike(s, D, *P.SPIKE_STUDY_MS)["status"] == "none"


def test_no_capture_before_the_drop_is_said_so():
    t, b = _spike_song()
    keep = t >= D - 3000                          # the capture starts 3 s out
    s = P.make_shape(t[keep], {k: v[keep] for k, v in b.items()}, BEAT, ceilings=UNIT)
    assert P.spike(s, D)["status"] == "no_capture"
    assert P.intro(s, D)["status"] == "no_capture"
    assert P.detect(s, D) is None


# ── kind 2: the vocal intro ─────────────────────────────────────────────────

O = D - 2500


def _intro_song(level=0.5):
    t, b = _song()
    _set(t, b["mid"], O, D, level)
    return t, b


def test_a_line_entering_out_of_a_hush_and_holding_is_a_confident_vocal_intro():
    r = P.intro(_shape(*_intro_song()), D)
    assert r["status"] == "found"
    assert abs(r["ms"] - O) <= 3 * FRAME          # on the entry's onset
    assert set(r["margins"]) == {"entry", "quiet", "sharp", "hold", "no_bass", "not_build"}
    assert r["score"] == pytest.approx(min(r["margins"].values()))
    assert r["margins"]["entry"] == pytest.approx(0.5 / P.INTRO_ENTRY_MIN, rel=1e-3)
    assert P.tier_for(P.KIND_INTRO, r["score"], r["lead"]) == P.TIER_CONFIDENT


def _intro_fails(mutate, weakest, th=None, level=0.5):
    t, b = _intro_song(level)
    mutate(t, b)
    r = P.intro(_shape(t, b), D, th=th)
    assert r["status"] == "weak", r
    assert r["weakest"] == weakest, r["margins"]
    return r


def test_intro_test_enters_a_line_too_quiet_is_not_one():
    _intro_fails(lambda t, b: None, "entry", level=0.2)


def test_intro_test_out_of_a_hush_a_line_over_a_busy_mid_is_not_one():
    _intro_fails(lambda t, b: _set(t, b["mid"], D - 4000, O, 0.25), "quiet")


def test_intro_test_sharp_the_entry_must_arrive_quickly():
    r = _intro_fails(lambda t, b: None, "sharp", th={"SHARP_MS": 20})
    assert r["rise_ms"] > 20


def test_intro_test_holds_a_line_that_falls_away_is_not_one():
    _intro_fails(lambda t, b: _set(t, b["mid"], O + 700, D, 0.02), "hold")


def test_intro_test_no_bass_yet_the_bass_already_in_is_not_one():
    _intro_fails(lambda t, b: _set(t, b["low"], O, D, 0.4), "no_bass")


def test_intro_test_not_a_build_a_line_that_keeps_climbing_is_not_one():
    def climb(t, b):
        _set(t, b["mid"], O, D, 0.3)
        m = (t >= O + 800) & (t < D)
        b["mid"][m] = np.linspace(0.3, 1.5, int(m.sum()))   # too gradual to be an entry
    _intro_fails(climb, "not_build")


def test_the_earliest_passing_entry_wins_the_phrases_own_start():
    # two entries that both pass (the out-of-a-hush bar relaxed so the
    # second, out of a shorter hush, does too) — the later one scores
    # higher, and the earlier one still names the moment
    t, b = _intro_song()
    _set(t, b["mid"], O + 600, O + 1500, 0.02)
    th = {"RATIO_MIN": 1.0}
    s = _shape(t, b)
    r = P.intro(s, D, th=th)
    assert r["status"] == "found" and abs(r["ms"] - O) <= 3 * FRAME
    later = P.intro(s, D, wmax=D - (O + 1400), th=th)   # the second entry alone
    assert later["status"] == "found" and later["score"] > r["score"]


# ── tiers and one pre-drop per drop ─────────────────────────────────────────

def test_the_tiers():
    assert P.tier_for(P.KIND_SPIKE, 0.99, 800) is None
    assert P.tier_for(P.KIND_SPIKE, 1.0, 800) == P.TIER_SUGGESTED
    assert P.tier_for(P.KIND_SPIKE, 1.07, 800) == P.TIER_CONFIDENT
    assert P.tier_for(P.KIND_INTRO, 1.17, 1000) == P.TIER_SUGGESTED
    assert P.tier_for(P.KIND_INTRO, 1.18, 3500) == P.TIER_CONFIDENT
    assert P.tier_for(P.KIND_INTRO, 1.5, 3501) == P.TIER_SUGGESTED   # enters too early


def test_one_pre_drop_per_drop_the_higher_score_names_the_kind():
    t, b = _intro_song()
    _hit(t, b["high"], H)
    s = _shape(t, b)
    sp, it = P.spike(s, D), P.intro(s, D)
    assert sp["status"] == it["status"] == "found"
    pre = P.detect(s, D)
    winner = P.KIND_SPIKE if sp["score"] >= it["score"] else P.KIND_INTRO
    assert pre.kind == winner
    assert pre.stored() == {"ms": pre.ms, "kind": winner, "lead_ms": D - pre.ms,
                            "score": round(max(sp["score"], it["score"]), 3), "tier": pre.tier}


def test_an_exact_tie_is_a_spike(monkeypatch):
    found = {"status": "found", "score": 1.2, "ms": 19000, "lead": 1000, "margins": {"x": 1.2}}
    monkeypatch.setattr(P, "spike", lambda s, d: dict(found))
    monkeypatch.setattr(P, "intro", lambda s, d: dict(found, ms=18000, lead=2000))
    assert P.detect(object(), D).kind == P.KIND_SPIKE


def test_no_shape_no_pre_drop():
    assert P.detect(None, D) is None
    assert P.reanchor(None, np.array([]), np.array([]), D) is None


# ── the re-anchor ───────────────────────────────────────────────────────────

D0, D1 = 20_000, 20_800


def _clap_then_return(clap=True, gap=0.02, ret=0.8):
    """A drop found on a clap that carries bass (D0), the bass back at D1."""
    t, b = _song()
    for band, v in (("low", gap), ("mid", 0.02), ("high", 0.05)):
        _set(t, b[band], D0, D1, v)
    _set(t, b["low"], D1, 30_000, ret)
    _set(t, b["low"], D0, D0 + 60, 0.7)            # the clap's own bass
    if clap:
        _hit(t, b["high"], D0)
    s = _shape(t, b)
    att_ms, att_rise = drop_detector.find_attacks(s.t, s.n["low"], drop_detector.ATTACK_MIN_RISE)
    return s, att_ms, att_rise


def test_a_drop_found_on_its_own_pre_drop_moves_to_the_bass_return():
    s, att_ms, att_rise = _clap_then_return()
    d1 = P.reanchor(s, att_ms, att_rise, D0)
    assert d1 is not None and abs(d1 - D1) <= 3 * FRAME
    pre = P.detect(s, d1)                          # the clap becomes its pre-drop
    assert pre.kind == P.KIND_SPIKE and abs(pre.ms - D0) <= P.SAME_HIT_MS


def test_the_blanket_case_a_bass_hit_with_no_spike_does_not_move():
    s, att_ms, att_rise = _clap_then_return(clap=False)
    assert P.bass_return(s, att_ms, att_rise, D0) is not None      # the return is there
    assert P.reanchor(s, att_ms, att_rise, D0) is None             # but no pre-drop hit


def test_no_sustained_return_does_not_move():
    s, att_ms, att_rise = _clap_then_return(ret=0.04)
    assert P.reanchor(s, att_ms, att_rise, D0) is None
    s, att_ms, att_rise = _clap_then_return(gap=0.5)                # the gap is not a gap
    assert P.reanchor(s, att_ms, att_rise, D0) is None


def test_a_spike_on_another_hit_does_not_move_the_drop():
    t, b = _song()
    for band, v in (("low", 0.02), ("mid", 0.02), ("high", 0.05)):
        _set(t, b[band], D0, D1, v)
    _set(t, b["low"], D1, 30_000, 0.8)
    _set(t, b["low"], D0, D0 + 60, 0.7)
    _hit(t, b["high"], D0 - 600)                   # the spike is a different hit
    s = _shape(t, b)
    att_ms, att_rise = drop_detector.find_attacks(s.t, s.n["low"], drop_detector.ATTACK_MIN_RISE)
    assert P.spike(s, D1)["status"] == "found"
    assert P.reanchor(s, att_ms, att_rise, D0) is None


# ── his songs, through the committed cut windows ────────────────────────────

def _cases():
    meta = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    z = np.load(FIXTURES / "cases.npz")
    for c in meta["cases"]:
        raw = {b: z[f"{c['id']}_{b}"] for b in ("low", "mid", "high")}
        yield c, P.make_shape(z[f"{c['id']}_t"], raw, c["beat_len"], c["ceilings"])


def _judge(s, d):
    pre = P.detect(s, d)
    return ({k: dict(fn(s, d, *w)) for k, fn, w in (("spike", P.spike, P.SPIKE_STUDY_MS),
                                                     ("intro", P.intro, P.INTRO_STUDY_MS))},
            pre.stored() if pre else None)


def test_every_committed_case_judges_as_its_whole_song_did():
    n = 0
    for c, s in _cases():
        rules, pre = _judge(s, c["drop_ms"])
        assert pre == c["expect"]["pre_drop"], c["title"]
        for k in ("spike", "intro"):
            want, got = c["expect"][k], rules[k]
            assert got["status"] == want["status"], (c["title"], c["drop_ms"], k)
            if want["status"] == "found":
                assert got["ms"] == want["ms"] and got["lead"] == want["lead"]
                assert got["score"] == pytest.approx(want["score"], abs=1e-12)
        n += 1
    assert n >= 50


def test_the_reports_finds_are_all_in_the_committed_cases():
    """Every moment a rule finds in the study is committed, so their count
    per set IS the report's (the full count, misses included, is
    scripts/check_predrop_detector.py's, over his stored shapes)."""
    found = {}
    for c, s in _cases():
        rules, _ = _judge(s, c["drop_ms"])
        for k in ("spike", "intro"):
            if rules[k]["status"] == "found" and c["set"] != "named":
                found[(k, c["set"])] = found.get((k, c["set"]), 0) + 1
    assert found == {("spike", "approved"): 11, ("spike", "detected"): 7,
                     ("spike", "random"): 15, ("intro", "approved"): 8,
                     ("intro", "detected"): 18, ("intro", "random"): 2}


def _case(title, drop_ms):
    for c, s in _cases():
        if c["title"] == title and c["drop_ms"] == drop_ms:
            return c, s
    raise AssertionError(f"no committed case {title} {drop_ms}")


def test_dopamine_drop_1_is_a_confident_vocal_intro_at_1_50():
    _, s = _case("Dopamine", 47850)
    pre = P.detect(s, 47850)
    assert (pre.kind, pre.tier, round(pre.score, 2), pre.lead_ms) == (
        P.KIND_INTRO, P.TIER_CONFIDENT, 1.50, 3295)
    assert P.spike(s, 47850)["status"] == "weak"        # ambiguous as a spike (0.56)


def test_fina_158208_is_a_spike_over_its_vocal_intro():
    _, s = _case("FINA", 158208)
    sp, it = P.spike(s, 158208), P.intro(s, 158208)
    assert (round(sp["score"], 2), round(it["score"], 2)) == (1.11, 1.01)
    assert P.detect(s, 158208).kind == P.KIND_SPIKE


# ── Eyes Cut Deeper, whole, through the drop detector ───────────────────────

ECD = "spotify:track:3E8WZzcp6nscGt9YvBX9MW"


@pytest.fixture()
def ecd(tmp_path, monkeypatch):
    shapes = tmp_path / "audio_shapes"
    shutil.copytree(FIXTURES / "ecd", shapes)
    monkeypatch.setattr(config, "AUDIO_SHAPES_DIR", shapes)
    from spectra.services import analysis_reader
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    drop_detector.reset_memo()
    yield
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    drop_detector.reset_memo()


def _ecd_detect():
    # his room's own thresholds when his store was detected
    return drop_detector.detect_uri(ECD, confident_score=1.0, suggested_score=0.7,
                                    drop_floor=0.1)


def test_eyes_cut_deeper_drop_1_moves_to_where_he_moved_it(ecd):
    det = _ecd_detect()
    one = next(q for q in det.sequences if q.reanchored_from is not None)
    assert (one.reanchored_from, one.drop_ms, one.key) == (69584, 70350, "drop:70350")
    assert (one.lull_ms, one.charge_ms) == (64440, 58484)     # still leading into the hit
    assert one.pre_drop["kind"] == P.KIND_SPIKE
    assert abs(one.pre_drop["ms"] - 69584) <= P.SAME_HIT_MS
    assert any("70350" in n and "pre-drop" in n for n in one.notes)
    assert [q.drop_ms for q in det.sequences if q.reanchored_from is None] == [150865]


def test_without_the_re_anchor_it_stays_on_the_clap(ecd, monkeypatch):
    monkeypatch.setattr(P, "reanchor", lambda *a, **k: None)
    det = _ecd_detect()
    assert [q.drop_ms for q in det.sequences] == [69584, 150865]
    assert all(q.reanchored_from is None for q in det.sequences)
