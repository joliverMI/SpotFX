"""list_room_map — Sonic coverage audit build item D16: a READ ONLY view
of the Live view's room map (which camera poses have anything drawn, and
for one pose, which pieces are placed vs. still in the tray). Hand
placement itself stays a drag on a camera picture — no write op here.

Storage (ROOM_MAPS_FILE/ROOM_VIEW_FILE) is isolated per test by
conftest.py's autouse fixture."""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.run(coro)


def test_list_room_map_with_no_data_reports_no_poses():
    from spectra.services import room_effect_console as rec

    result = rec.OPERATIONS["list_room_map"].handler()
    assert result == {"poses": []}


def test_list_room_map_unknown_pose_is_rejected():
    from spectra.services import room_effect_console as rec

    result = rec.OPERATIONS["list_room_map"].handler(pose="nonexistent-pose")
    assert result["status"] == "rejected"
    assert result["known_poses"] == []


def test_list_room_map_reports_placed_pieces_and_the_tray(monkeypatch):
    from spectra.services import room_effect_console as rec
    from spectra.services import room_view

    monkeypatch.setattr(room_view, "current_poses",
                        lambda: [{"pose_id": "kitchen", "label": "Kitchen", "rooms": ["Kitchen"]}])

    def fake_view(pose_id):
        assert pose_id == "kitchen"
        return {
            "label": "Kitchen",
            "pieces": [
                {"key": "p1", "label": "Sconce left", "virtual_id": "v1", "device_id": "d1",
                 "source": "footprint", "at": {"x": 0.3, "y": 0.4, "r": 0.05}, "xy": None},
                {"key": "p2", "label": "Sconce right", "virtual_id": "v2", "device_id": "d2",
                 "source": "unmapped", "at": None, "xy": None},
            ],
            "hand": {},
            "notes": ["one note"],
        }
    monkeypatch.setattr(room_view, "current_view", fake_view)

    result = rec.OPERATIONS["list_room_map"].handler(pose="kitchen")
    assert result["pose_id"] == "kitchen"
    placed = {p["key"]: p["placed"] for p in result["pieces"]}
    assert placed == {"p1": True, "p2": False}
    assert result["tray"] == ["Sconce right"]
    assert result["notes"] == ["one note"]


def test_list_room_map_counts_a_hand_placement_as_placed(monkeypatch):
    from spectra.services import room_effect_console as rec
    from spectra.services import room_view

    monkeypatch.setattr(room_view, "current_poses",
                        lambda: [{"pose_id": "kitchen", "label": "Kitchen", "rooms": []}])
    monkeypatch.setattr(room_view, "current_view", lambda pose_id: {
        "label": "Kitchen",
        "pieces": [{"key": "p1", "label": "Sconce", "virtual_id": "v1", "device_id": "d1",
                   "source": "unmapped", "at": None, "xy": None}],
        "hand": {"p1": {"x": 0.5, "y": 0.5, "size": 0.1}},
        "notes": [],
    })

    result = rec.OPERATIONS["list_room_map"].handler(pose="kitchen")
    assert result["pieces"][0]["placed"] is True
    assert result["tray"] == []


def test_list_room_map_is_declared_as_a_room_domain_read_op():
    from spectra.services import settings_agent as sa

    assert "list_room_map" in sa.ALL_OPERATIONS
    op = sa.ALL_OPERATIONS["list_room_map"]
    assert op.domain == "room" and op.kind == "read"


def test_list_room_map_discoverable_via_list_operations():
    from spectra.services import settings_agent as sa

    idx = _run(sa._dispatch("list_operations", {"domain": "room"}))
    names = {o["name"] for o in idx["operations"]}
    assert "list_room_map" in names
