"""scripts/approve_half_edited_drops.py (the Drops panel proposal's Q8:
"approve them once under the new rule; I list them first and you say yes"):
the dry run lists every half-edited drop under its group and writes
nothing; --apply backs the store up and approves exactly those, each the
way an edit approves now (a drop switched off stays off); --only narrows to
the groups he said yes to; a removed drop and an added one are never
touched; a second run finds nothing."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
URI = "spotify:track:halfedited"


def _script():
    spec = importlib.util.spec_from_file_location(
        "approve_half_edited_drops", REPO / "scripts" / "approve_half_edited_drops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _det(drop, lull, charge, pre=None):
    out = {"key": f"drop:{drop}", "drop_ms": drop, "lull_ms": lull, "charge_ms": charge,
           "score": 1.2, "tier": "suggested", "notes": []}
    if pre is not None:
        out["pre_drop"] = {"ms": pre, "kind": "spike", "score": 1.1, "tier": "suggested"}
    return out


@pytest.fixture
def store(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import drop_sequences as ds
    path = tmp_path / "drop_sequences.json"
    monkeypatch.setattr(scfg, "DROP_SEQUENCES_FILE", path)
    data = {URI: {
        "detected": {"uri": URI, "beat_ms": 500.0, "stamp": "t", "excluded": [],
                     "sequences": [_det(44_000, 40_000, 35_000), _det(60_000, 56_000, 50_000),
                                   _det(80_000, 76_000, 70_000), _det(100_000, 96_000, 90_000, 99_200),
                                   _det(120_000, 116_000, 110_000, 119_300),
                                   _det(140_000, 136_000, 130_000)]},
        "overrides": {
            # a part approved, the drop still waiting (his Q8 words)
            "drop:44000": {"detected": None, "parts": {"lull": "on"}},
            # the drop approved alone, its build waiting
            "drop:60000": {"detected": None, "state": "confirmed", "parts": {"drop": "on"}},
            # the drop switched off, the rest waiting
            "drop:80000": {"detected": None, "parts": {"drop": "off"}},
            # a legacy confirm before pre-drops existed: one found since
            "drop:100000": {"detected": None, "state": "confirmed"},
            # removed: never touched
            "drop:140000": {"detected": None, "state": "dismissed"},
            # one of his own drops' pre-drops, relabelled, never approved
            "mine:his1": {"pre_drop_kind": "intro"},
        },
        "added": [{"id": "added:x", "drop_ms": 150_000, "lull_ms": None, "charge_ms": None}],
    }}
    path.write_text(json.dumps(data), encoding="utf-8")
    ds.reset()
    yield path
    ds.reset()


def test_the_dry_run_lists_each_group_and_writes_nothing(store, capsys):
    mod = _script()
    before = store.read_bytes()
    assert mod.main(["--file", str(store)]) == 0
    out = capsys.readouterr().out
    assert store.read_bytes() == before
    for group, key in [("drop_waiting", "drop:44000"), ("build_waiting", "drop:60000"),
                       ("drop_off", "drop:80000"), ("pre_drop_found_later", "drop:100000"),
                       ("his_pre_drop", "mine:his1")]:
        assert f"[{group}]" in out and key in out
    assert "drop:140000" not in out and "added:x" not in out and "drop:120000" not in out


def test_apply_approves_exactly_those_after_a_backup(store, capsys):
    from spectra.services import drop_sequences as ds
    mod = _script()
    assert mod.main(["--file", str(store), "--apply"]) == 0
    assert list(store.parent.glob("drop_sequences.json.bak-half-edited-*"))
    ds.reset()
    seqs = {s["key"]: s for s in ds.view(URI, triggers=[])["sequences"]}
    assert seqs["drop:44000"]["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent",
                                           "drop": "on"}
    assert seqs["drop:60000"]["parts"]["lull"] == "on"
    # Q6: a drop switched off stays off, the rest approved
    assert seqs["drop:80000"]["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent",
                                           "drop": "off"}
    assert seqs["drop:100000"]["parts"]["pre_drop"] == "on"
    assert seqs["drop:120000"]["state"] == "suggested"           # never touched
    assert seqs["drop:140000"]["state"] == "dismissed"
    assert ds.stored(URI)["overrides"]["mine:his1"]["parts"] == {"pre_drop": "on"}
    capsys.readouterr()
    assert mod.main(["--file", str(store)]) == 0
    assert "0 half-edited drops" in capsys.readouterr().out


def test_only_narrows_to_the_groups_he_said_yes_to(store, capsys):
    from spectra.services import drop_sequences as ds
    mod = _script()
    assert mod.main(["--file", str(store), "--only", "drop_waiting", "--apply"]) == 0
    ds.reset()
    seqs = {s["key"]: s for s in ds.view(URI, triggers=[])["sequences"]}
    assert seqs["drop:44000"]["parts"]["drop"] == "on"
    assert seqs["drop:60000"]["parts"]["lull"] == "waiting"
    assert mod.main(["--file", str(store), "--only", "nonsense"]) == 2
