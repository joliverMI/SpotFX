"""Colour Set / Colour Group likelihood curves (owner ask, 2026-08-17:
"Give color sets a likelihood curve. Reuse the same kind of structure as
for scenes. Groups can also have likelihood curves, default is flat one,
but these don't overwrite they multiply with the child likelihood curve").

Colour SETS already had a likelihood curve before this change —
SequencerConfig.color_set_entries (spectra/models/sequencer.py) is keyed by
ColorSetCard id and was already read by the colour-set selector
(curve × genre × wheel-travel). This file is the GROUP half: a Group's
curve lives in the SAME dict (no new storage shape), never becomes its own
candidate, and instead multiplies onto every member Set's own score —
services/selection_kernel.py's Candidate.group_points / group_curve_mult,
resolved by services/color_set_groups.group_ids_by_set's reverse "which
groups contain this set" lookup.

Three things this file proves at exact equality, per the task:
  1. Flat (no entry / default entry) is a genuine ×1.0 identity — not
     "close enough".
  2. A set under more than one group CHAINS every enclosing group's curve
     (his real data: 4 sets sit under both "First Group" and "Blues").
  3. Multiplication compounds toward zero, but a group-only veto is NOT
     ladder-proof the way a set's own curve veto is — RUNG_NO_GROUP
     recovers it — and the resolved group factor is always visible in
     Pick.factors, never hidden.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.models.sequencer import CurvePoint, SelectorEntry
from spectra.services import color_set_groups
from spectra.services.color_sets import ColorSetCard, GroupMember
from spectra.services.selection_kernel import (Candidate, RUNG_FULL,
                                               RUNG_NO_GENRE, RUNG_NO_GROUP,
                                               RUNG_NO_WHEEL,
                                               build_color_set_candidates,
                                               group_curve_mult,
                                               select_color_set)

FLAT: list[CurvePoint] = [CurvePoint(x=0.0, y=1.0)]


def pts(*xy: tuple[float, float]) -> list[CurvePoint]:
    return [CurvePoint(x=x, y=y) for x, y in xy]


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    yield


def _write_cards(*cards: ColorSetCard) -> None:
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {c.id: json.loads(c.model_dump_json()) for c in cards}))


def _set(id_: str, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="set", **kw)


def _group(id_: str, members: list[str], **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="group",
                        members=[GroupMember(color_set_id=m) for m in members], **kw)


# ── 1. group_curve_mult: the pure multiplicand ──────────────────────────────

def test_no_groups_is_the_exact_identity():
    """Empty group_points (ungrouped, or every enclosing group defaulted to
    flat) must leave the set's own score EXACTLY unchanged — not
    approximately. This is what stops every ungrouped/default-group set
    from silently drifting the day this ships."""
    assert group_curve_mult([], 0.0) == 1.0
    assert group_curve_mult([], 0.37) == 1.0
    assert group_curve_mult([], 1.0) == 1.0


def test_flat_group_curve_is_the_exact_identity():
    """A group with no authored curve (or an explicit flat one) multiplies
    by exactly 1.0 — float 1.0 multiplication is exact under IEEE 754, so
    this isn't a tolerance check, it's ==."""
    for x in (0.0, 0.13, 0.5, 0.91, 1.0):
        assert group_curve_mult([FLAT], x) == 1.0
        assert group_curve_mult([FLAT, FLAT, FLAT], x) == 1.0


def test_multiple_groups_chain_by_multiplication():
    """THE MULTI-GROUP RULE (his real data: 4 sets sit under both "First
    Group" and "Blues"): curves CHAIN — every enclosing group's height
    multiplies in, not "one wins". Exact round numbers so the check is
    == rather than a tolerance."""
    half = pts((0.0, 0.5))
    quarter = pts((0.0, 0.25))
    assert group_curve_mult([half, quarter], 0.0) == 0.125
    # order must not matter — multiplication commutes
    assert group_curve_mult([quarter, half], 0.0) == 0.125


def test_a_zero_group_curve_zeroes_the_chain():
    veto = pts((0.0, 0.0))
    half = pts((0.0, 0.5))
    assert group_curve_mult([veto, half], 0.0) == 0.0


# ── 2. build_color_set_candidates: resolving group_points per candidate ────

def test_candidate_group_points_resolved_from_the_same_entries_dict():
    """A group's curve lives in the SAME color_set_entries dict as a set's
    own curve — reuse, no parallel storage. A group with no entry defaults
    to flat, same as any other missing entry."""
    entries = {
        "warm": SelectorEntry(),
        "group-a": SelectorEntry(inline_points=pts((0.0, 0.6))),
        # "group-b" has no entry at all -> defaults to flat.
    }
    cands = {c.id: c for c in build_color_set_candidates(
        entries, {}, genre_bucket=None, room_deg=None,
        set_positions={"warm": None},
        wheel_points=FLAT,
        group_ids_by_set={"warm": ["group-a", "group-b"]})}
    warm = cands["warm"]
    assert len(warm.group_points) == 2
    assert group_curve_mult(warm.group_points, 0.0) == 0.6   # group-a × flat group-b


def test_ungrouped_set_carries_no_group_points():
    entries = {"solo": SelectorEntry()}
    cands = {c.id: c for c in build_color_set_candidates(
        entries, {}, genre_bucket=None, room_deg=None,
        set_positions={"solo": None}, wheel_points=FLAT)}
    assert cands["solo"].group_points == []


# ── 3. select_color_set: the fourth multiplicand + its own ladder rung ─────

def test_full_rung_score_includes_the_group_factor():
    cand = Candidate(id="a", points=pts((0.5, 1.0)), genre_mult=2.0,
                     wheel_mult=0.5, group_points=[pts((0.5, 0.4))])
    p = select_color_set([cand], intensity=0.5, rng=Random(1))
    f = p.factors["a"]
    assert f["group"] == 0.4
    assert abs(f["score"] - (1.0 * 2.0 * 0.5 * 0.4)) < 1e-12
    assert p.rung == RUNG_FULL


def test_group_only_veto_is_rescued_by_its_own_ladder_rung():
    """A candidate zeroed ONLY by an enclosing group's curve at this
    intensity is not permanently vetoed — the same recoverability
    wheel-travel and genre already have. Only the SET'S OWN curve hitting
    zero is a true, ladder-proof veto (proven separately below)."""
    cand = Candidate(id="a", points=FLAT, group_points=[pts((0.5, 0.0))])
    p = select_color_set([cand], intensity=0.5, rng=Random(1))
    assert p.picked_id == "a"
    assert p.rung == RUNG_NO_GROUP


def test_ladder_drops_group_before_wheel_before_genre():
    """Cumulative relaxation, same shape as the existing wheel->genre chain:
    each rung drops one more factor than the last."""
    cand = Candidate(id="a", points=FLAT, wheel_mult=0.0,
                     group_points=[pts((0.5, 0.0))])
    p = select_color_set([cand], intensity=0.5, rng=Random(1))
    assert p.picked_id == "a" and p.rung == RUNG_NO_WHEEL

    cand2 = Candidate(id="a", points=FLAT, genre_mult=0.0, wheel_mult=0.0,
                      group_points=[pts((0.5, 0.0))])
    p2 = select_color_set([cand2], intensity=0.5, rng=Random(1))
    assert p2.picked_id == "a" and p2.rung == RUNG_NO_GENRE


def test_own_curve_zero_is_never_rescued_by_dropping_group():
    """The set's OWN curve hitting zero stays a hard veto through every
    rung, group or no group — unchanged from before groups existed."""
    cand = Candidate(id="a", points=pts((0.5, 0.0)), group_points=[pts((0.5, 0.9))])
    other = Candidate(id="b", points=FLAT)
    seen = {select_color_set([cand, other], intensity=0.5, rng=Random(i)).picked_id
           for i in range(50)}
    assert seen == {"b"}


def test_compounding_is_visible_not_silent():
    """Two modest group curves compound toward a small-but-nonzero score —
    never blocked outright (only an exact 0 is a hard veto), but the
    resolved magnitude is always in Pick.factors so a starved set is
    explainable by looking, never a silent mystery."""
    cand = Candidate(id="a", points=FLAT,
                     group_points=[pts((0.5, 0.2)), pts((0.5, 0.3))])
    other = Candidate(id="b", points=FLAT)
    p = select_color_set([cand, other], intensity=0.5, rng=Random(1))
    assert p.factors["a"]["group"] == pytest.approx(0.06)
    assert p.factors["a"]["score"] == pytest.approx(0.06)
    # "a" is still drawable (score > 0), just heavily disfavoured against "b".
    counts = {"a": 0, "b": 0}
    for i in range(400):
        counts[select_color_set([cand, other], intensity=0.5, rng=Random(i)).picked_id] += 1
    assert counts["a"] > 0
    assert counts["a"] < counts["b"]


# ── 4. the reverse lookup: which groups contain a set ───────────────────────

def test_group_ids_by_set_reverse_lookup():
    _write_cards(
        _set("s1"), _set("s2"), _set("s3"),
        _group("first-group", ["s1", "s2"]),
        _group("blues", ["s1", "s3"]))
    reverse = color_set_groups.group_ids_by_set()
    assert set(reverse["s1"]) == {"first-group", "blues"}   # in BOTH groups
    assert reverse["s2"] == ["first-group"]
    assert reverse["s3"] == ["blues"]


def test_group_ids_by_set_omits_ungrouped_sets():
    _write_cards(_set("lonely"), _group("g", ["other"]))
    reverse = color_set_groups.group_ids_by_set()
    assert "lonely" not in reverse


# ── 5. end-to-end: the wired choke point picks up group curves ─────────────

def test_scene_sequencer_roll_applies_the_group_curve():
    """Same shape as scene_sequencer's own wheel-travel wiring test — a set
    that is only disfavoured through its enclosing group's curve is still
    reachable through the real _roll_color_set path, not just the pure
    kernel."""
    from spectra.models.sequencer import SequencerConfig
    from spectra.services import sequencer_store
    from spectra.services.scene_sequencer import SceneSequencer

    _write_cards(
        _set("grouped"), _set("plain"),
        _group("muted", ["grouped"]))

    config = SequencerConfig(color_set_entries={
        "grouped": SelectorEntry(),
        "plain": SelectorEntry(),
        "muted": SelectorEntry(inline_points=[{"x": 0.0, "y": 0.0}]),
    })
    sequencer_store.save_config(config)

    seq = SceneSequencer(
        eligible_sets=lambda scene_id: {"grouped": None, "plain": None},
    )
    color = seq._roll_color_set(config, {}, "scene-1", intensity=0.5, genre_bucket=None)
    assert color is not None
    assert color["picked_id"] == "plain"
    assert color["record"]["factors"]["grouped"]["group"] == 0.0
