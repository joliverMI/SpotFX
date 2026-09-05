"""THE IDENTITY BOOTSTRAP — the one case learning-on-contact cannot cover.

A device learns its own MAC the first time it is reached. A device whose
address ALREADY moved is never reached, so it never learns, so it can never
be looked up — the exact state his config was in on 2026-09-04. This script
is that bootstrap, and it is DRY-RUN BY DEFAULT because its second source
(matching a peer by device NAME) is a proposal for a human to confirm, not
a measurement.

Everything here runs against a temp config and real loopback HTTP. It never
reads or writes his fx-live config and never touches his network.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_device_identity import DEAD_ADDRESS, FakeWled

LEFT_BARE = "e08cfe5c3a78"
CRYSTAL_BARE = "6825dd488b80"


def _seeder():
    path = Path(__file__).resolve().parent.parent / "scripts" / \
        "seed_wled_hardware_ids.py"
    spec = importlib.util.spec_from_file_location("seed_wled_hardware_ids",
                                                  path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(tmp_path, devices):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"devices": devices, "virtuals": []}))
    return path


def _run(monkeypatch, path, *args):
    module = _seeder()
    monkeypatch.setattr(sys, "argv",
                        ["seed", "--config", str(path), *args])
    assert module.main() == 0
    return json.loads(path.read_text())


def test_an_identity_is_learned_off_the_wire_for_every_device_that_answers(
        monkeypatch, tmp_path):
    with FakeWled(mac=LEFT_BARE, name="Sconce, Kitchen, Left") as sconce:
        path = _write(tmp_path, [
            {"id": "sconce-kitchen-left", "type": "wled",
             "config": {"ip_address": sconce.address,
                        "name": "Sconce, Kitchen, Left", "sync_mode": "DDP"}},
            {"id": "hue-lights", "type": "hue",
             "config": {"ip_address": "203.0.113.215", "name": "Hue"}},
        ])
        before = json.loads(path.read_text())

        # dry run writes nothing
        assert _run(monkeypatch, path) == before

        after = _run(monkeypatch, path, "--apply")

    assert after["devices"][0]["config"]["hardware_id"] == LEFT_BARE
    assert after["devices"][0]["config"]["sync_mode"] == "DDP"
    assert after["devices"][1] == before["devices"][1], \
        "a non-WLED device must be byte-identical"


def test_a_relocated_device_is_bootstrapped_from_a_siblings_peer_list(
        monkeypatch, tmp_path):
    """His sconce, exactly: its pinned address is dead, and the crystal —
    which still answers — knows where it went."""
    with FakeWled(mac=LEFT_BARE, name="Sconce, Kitchen, Left") as moved:
        with FakeWled(mac=CRYSTAL_BARE, name="Crystal",
                      nodes=[moved.address]) as crystal:
            path = _write(tmp_path, [
                {"id": "sconce-kitchen-left", "type": "wled",
                 "config": {"ip_address": DEAD_ADDRESS,
                            "name": "Sconce, Kitchen, Left"}},
                {"id": "crystal", "type": "wled",
                 "config": {"ip_address": crystal.address,
                            "name": "Crystal"}},
            ])
            after = _run(monkeypatch, path, "--apply")

    configs = {e["id"]: e["config"] for e in after["devices"]}
    assert configs["sconce-kitchen-left"]["hardware_id"] == LEFT_BARE
    assert configs["crystal"]["hardware_id"] == CRYSTAL_BARE
    # the bootstrap gives it an identity; it never rewrites the stale
    # address, because finding the device is the reconcile path's job
    assert configs["sconce-kitchen-left"]["ip_address"] == DEAD_ADDRESS


def test_an_explicit_mac_always_wins_and_a_bad_one_is_refused(
        monkeypatch, tmp_path):
    path = _write(tmp_path, [
        {"id": "sconce-kitchen-left", "type": "wled",
         "config": {"ip_address": DEAD_ADDRESS, "name": "Left"}}])

    after = _run(monkeypatch, path, "--no-discover", "--apply",
                 "--mac", "sconce-kitchen-left=e0:8c:fe:5c:3a:78")
    assert after["devices"][0]["config"]["hardware_id"] == LEFT_BARE

    module = _seeder()
    monkeypatch.setattr(sys, "argv", ["seed", "--config", str(path),
                                      "--mac", "sconce-kitchen-left=nope"])
    with pytest.raises(SystemExit):
        module.main()


def test_a_device_that_already_has_an_identity_is_left_alone(
        monkeypatch, tmp_path):
    with FakeWled(mac=CRYSTAL_BARE, name="Crystal") as server:
        path = _write(tmp_path, [
            {"id": "crystal", "type": "wled",
             "config": {"ip_address": server.address, "name": "Crystal",
                        "hardware_id": LEFT_BARE}}])
        before = json.loads(path.read_text())
        after = _run(monkeypatch, path, "--apply")
    assert after == before, \
        "a stored identity is never silently replaced by a probe"
