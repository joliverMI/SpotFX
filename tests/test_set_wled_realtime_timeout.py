"""scripts/set_wled_realtime_timeout.py — dry run by default, read-back
confirmed on --apply, an unreadable or unconfirmed fixture is a failure.
No network: the script's two transport calls are replaced."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "set_wled_realtime_timeout.py"


@pytest.fixture
def mod(monkeypatch):
    spec = importlib.util.spec_from_file_location("set_wled_rt", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    cfg = {"10.0.0.110": 25, "10.0.0.113": 25}
    writes = []
    monkeypatch.setattr(m, "stored_addresses", lambda: {
        "sconce-kitchen-left": "10.0.0.110", "sconce-kitchen-right": "10.0.0.113"})
    monkeypatch.setattr(m, "read_timeout", lambda host: cfg[host])

    def write(host, tenths):
        writes.append((host, tenths))
        cfg[host] = tenths
    monkeypatch.setattr(m, "write_timeout", write)
    m._cfg, m._writes = cfg, writes
    return m


def test_dry_run_writes_nothing(mod, capsys):
    assert mod.main([]) == 0
    assert mod._writes == []
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_writes_and_reads_back(mod, capsys):
    assert mod.main(["--apply"]) == 0
    assert mod._writes == [("10.0.0.110", 500), ("10.0.0.113", 500)]
    assert capsys.readouterr().out.count("written and read back") == 2
    assert mod.main(["--apply"]) == 0
    assert len(mod._writes) == 2, "already set: no second write"


def test_an_unconfirmed_write_and_an_unknown_device_fail(mod, monkeypatch):
    monkeypatch.setattr(mod, "write_timeout", lambda host, t: None)   # ignored
    assert mod.main(["--apply", "sconce-kitchen-left"]) == 1
    assert mod.main(["nope"]) == 1
