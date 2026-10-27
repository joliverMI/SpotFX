"""The Jukebox program's rules (services/jukebox/program.py) — pure, no I/O.

`project()` is the one definition of "what plays next": these tests pin the
slot patterns the plan names (every other, every 3rd, two in a row, jukebox
first, manual), the empty slot that passes, the owed slot a miss leaves, and
the three run-out policies.
"""
from __future__ import annotations

from models.jukebox import Cursor, ManualSlot, ProgramConfig, SetItem
from services.jukebox import program
from services.jukebox.program import Fill, UNBOUNDED


def _set(n: int, s: int = 200) -> list[SetItem]:
    return [SetItem(uri=f"spotify:track:set{i:03d}aaaaaaaaaaaaaa", title=f"S{i}",
                    duration_ms=s * 1000) for i in range(n)]


def _fills(n: int) -> list[Fill]:
    return [Fill(entry_id=f"e{i}", uri=f"spotify:track:jbx{i:03d}bbbbbbbbbbbbbb",
                 title=f"J{i}", duration_ms=180_000) for i in range(n)]


def _cfg(**kw) -> ProgramConfig:
    return ProgramConfig(playlist="spotify:playlist:x", **kw)


def _labels(items) -> list[str]:
    return [i.title if i.kind != "open" else "_" for i in items]


def test_defaults_are_the_plans():
    cfg = ProgramConfig()
    assert (cfg.mode, cfg.every, cfg.run, cfg.run_out) == ("auto", 1, 1, "again")
    assert cfg.commit_lead_s == 45.0


def test_every_other():
    out = program.project(_cfg(), _set(4), Cursor(), _fills(3), 8)
    assert _labels(out) == ["S0", "J0", "S1", "J1", "S2", "J2", "S3", "_"]


def test_every_third():
    out = program.project(_cfg(every=3), _set(7), Cursor(), _fills(2), 9)
    assert _labels(out) == ["S0", "S1", "S2", "J0", "S3", "S4", "S5", "J1", "S6"]


def test_two_in_a_row():
    out = program.project(_cfg(run=2), _set(3), Cursor(), _fills(5), 9)
    assert _labels(out) == ["S0", "J0", "J1", "S1", "J2", "J3", "S2", "J4", "_"]


def test_jukebox_first_plays_the_whole_line_then_the_set():
    out = program.project(_cfg(mode="jukebox_first"), _set(4), Cursor(), _fills(3), 7)
    assert _labels(out) == ["S0", "J0", "J1", "J2", "S1", "S2", "S3"]


def test_jukebox_first_shows_no_open_slots():
    out = program.project(_cfg(mode="jukebox_first"), _set(3), Cursor(), [], 3)
    assert [i.kind for i in out] == ["set", "set", "set"]


def test_manual_slots_follow_the_song():
    items = _set(5)
    cfg = _cfg(mode="manual", manual=[ManualSlot(after_uri=items[1].uri, count=2),
                                      ManualSlot(after_uri=items[3].uri, count=1)])
    out = program.project(cfg, items, Cursor(), _fills(4), 9)
    assert _labels(out) == ["S0", "S1", "J0", "J1", "S2", "S3", "J2", "S4", "S0"]
    # reordered set: the slots still follow S1 and S3
    moved = [items[3], items[0], items[1], items[2], items[4]]
    out = program.project(cfg, moved, Cursor(), _fills(4), 6)
    assert _labels(out) == ["S3", "J0", "S0", "S1", "J1", "J2"]


def test_an_empty_line_shows_open_slots_and_the_set_continues():
    out = program.project(_cfg(every=2, run=2), _set(4), Cursor(), [], 8)
    assert _labels(out) == ["S0", "S1", "_", "_", "S2", "S3", "_", "_"]


def test_a_line_that_runs_dry_mid_gap_closes_the_gap():
    out = program.project(_cfg(run=3), _set(3), Cursor(), _fills(1), 6)
    assert _labels(out) == ["S0", "J0", "_", "_", "S1", "_"]


def test_committed_fill_comes_first():
    fills = [Fill("c", "spotify:track:c", "C", committed=True)] + _fills(1)
    out = program.project(_cfg(), _set(3), Cursor(), fills, 4)
    assert _labels(out) == ["S0", "C", "S1", "J0"]
    assert out[1].committed and not out[3].committed


def test_projection_from_the_middle_of_a_gap():
    items = _set(4)
    cur = program.on_set_start(_cfg(run=2), items, Cursor(), 0)
    cur = program.on_jukebox_start(cur)          # J0 playing, one slot left
    out = program.project(_cfg(run=2), items, cur, _fills(2), 3)
    assert _labels(out) == ["J0", "S1", "J1"]


# ── the cursor ──────────────────────────────────────────────────────────────

def test_a_miss_is_owed_to_the_next_gap_without_shifting_the_rhythm():
    cfg, items = _cfg(every=3), _set(9)
    c = Cursor()
    for i in range(3):
        c = program.on_set_start(cfg, items, c, i)
    assert c.gap_left == 1
    c = program.on_set_start(cfg, items, c, 3, owe=True)    # S2's slot was missed
    assert c.gap_left == 1 and c.since_slot == 1           # owed slot after S3
    out = program.project(cfg, items, c, _fills(2), 6)
    assert _labels(out) == ["J0", "S4", "S5", "J1", "S6", "S7"]


def test_owed_slots_are_capped_at_one_gap():
    cfg, items = _cfg(), _set(9)
    c = program.on_set_start(cfg, items, Cursor(), 0)
    for i in range(1, 5):
        c = program.on_set_start(cfg, items, c, i, owe=True)
    assert c.gap_left == 2       # the rule's 1 + at most 1 owed


def test_an_empty_gap_is_not_owed():
    cfg, items = _cfg(), _set(4)
    c = program.on_set_start(cfg, items, Cursor(), 0)
    c = program.on_set_start(cfg, items, c, 1, owe=False)
    assert c.gap_left == 1 and c.owed == 0


def test_run_out_again_wraps_and_counts_loops():
    cfg, items = _cfg(), _set(2)
    out = program.project(cfg, items, Cursor(), [], 6)
    assert _labels(out) == ["S0", "_", "S1", "_", "S0", "_"]
    c = program.on_set_start(cfg, items, Cursor(), 0)
    c = program.on_set_start(cfg, items, c, 1)
    c = program.on_set_start(cfg, items, c, 0)
    assert c.loops == 1


def test_run_out_jukebox_only_plays_the_line_then_ends():
    cfg, items = _cfg(run_out="jukebox_only"), _set(2)
    out = program.project(cfg, items, Cursor(), _fills(4), 20)
    assert _labels(out) == ["S0", "J0", "S1", "J1", "J2", "J3"]
    out = program.project(cfg, items, Cursor(), [], 20)
    assert _labels(out) == ["S0", "_", "S1"]


def test_run_out_end_ends_with_the_last_set_song():
    cfg, items = _cfg(run_out="end"), _set(2)
    out = program.project(cfg, items, Cursor(), _fills(5), 20)
    assert _labels(out) == ["S0", "J0", "S1"]
    c = program.on_set_start(cfg, items, Cursor(), 1)
    assert c.gap_left == 0 and program.next_set_index(cfg, items, c) is None


def test_resolve_set_index_prefers_the_expected_occurrence():
    items = _set(4)
    items[3] = items[1].model_copy()          # S1 is in the set twice
    cfg = _cfg()
    c = program.on_set_start(cfg, items, Cursor(), 2)
    assert program.resolve_set_index(cfg, items, c, items[1].uri) == 3
    c = program.on_set_start(cfg, items, Cursor(), 0)
    assert program.resolve_set_index(cfg, items, c, items[1].uri) == 1
    assert program.resolve_set_index(cfg, items, c, "spotify:track:nope") is None


def test_reanchor_follows_the_song_through_a_reorder():
    items = _set(5)
    c = program.on_set_start(_cfg(), items, Cursor(), 2)
    reordered = [items[2], items[0], items[1], items[3], items[4]]
    assert program.reanchor(reordered, c).set_pos == 0


def test_start_times_count_from_the_end_of_the_current_song():
    out = program.with_start_times(program.project(_cfg(), _set(3, 100), Cursor(),
                                                   _fills(1), 4), 30_000)
    assert [i.starts_in_ms for i in out] == [30_000, 130_000, 310_000, 410_000]


def test_lap_counts_one_pass():
    assert program.lap(_cfg(), _set(10)).slots == 10
    assert program.lap(_cfg(every=3, run=2), _set(10)).slots == 6
    assert program.lap(_cfg(mode="jukebox_first"), _set(4)).unbounded
    lap = program.lap(_cfg(mode="manual", manual=[ManualSlot(after_uri="spotify:track:gone")]),
                      _set(3))
    assert lap.slots == 0 and lap.notes
    assert program.lap(_cfg(run_out="jukebox_only"), _set(3)).unbounded


def test_unbounded_gap_is_never_decremented():
    c = Cursor(gap_left=UNBOUNDED, started=True)
    assert program.on_jukebox_start(c).gap_left == UNBOUNDED


def test_as_manual_copies_the_auto_pattern():
    items = _set(6)
    m = program.as_manual(_cfg(every=2, run=2), items)
    assert [(x.after_uri, x.count) for x in m] == [(items[1].uri, 2), (items[3].uri, 2),
                                                    (items[5].uri, 2)]
    # copied as manual, the program is the same
    manual = _cfg(mode="manual", manual=m)
    auto = _cfg(every=2, run=2)
    assert _labels(program.project(manual, items, Cursor(), _fills(9), 12)) == \
        _labels(program.project(auto, items, Cursor(), _fills(9), 12))


def test_as_manual_for_jukebox_first_is_a_slot_after_every_song():
    m = program.as_manual(_cfg(mode="jukebox_first"), _set(3))
    assert [x.count for x in m] == [1, 1, 1]
