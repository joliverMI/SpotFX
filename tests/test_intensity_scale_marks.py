"""Unit + API proof for the 2026-08-15 per-track manual mark: the one way
past the AUTO ceiling (intensity_scale.HEADROOM_RESERVE * SCALE_MAX = 0.75)
— "he marks the track; automatic never does." conftest.py's autouse
_isolated_intensity_scale fixture repoints every storage path this touches;
nothing here reaches real repo storage.
"""
from __future__ import annotations

from spectra.services import intensity_scale as isc
from spectra.services import intensity_scale_marks as marks


# ── the store itself ───────────────────────────────────────────────────────

def test_get_mark_is_none_when_unset():
    assert marks.get_mark("spotify:track:unmarked") is None


def test_set_and_get_round_trips():
    saved = marks.set_mark("spotify:track:x", 1.4)
    assert saved == 1.4
    assert marks.get_mark("spotify:track:x") == 1.4


def test_set_mark_clamps_to_manual_range():
    assert marks.set_mark("spotify:track:hi", 5.0) == marks.MANUAL_MAX
    assert marks.set_mark("spotify:track:lo", -1.0) == marks.MANUAL_MIN
    assert marks.MANUAL_MAX == 2.0, "matches SpotFX's own manual slider ceiling"


def test_clear_mark_reports_whether_one_existed():
    assert marks.clear_mark("spotify:track:never-set") is False
    marks.set_mark("spotify:track:y", 1.1)
    assert marks.clear_mark("spotify:track:y") is True
    assert marks.get_mark("spotify:track:y") is None


def test_marks_persist_across_a_fresh_read():
    marks.set_mark("spotify:track:z", 1.8)
    # A second, independent read from disk (not relying on any in-process cache).
    assert marks.load_all()["spotify:track:z"]["factor"] == 1.8


# ── song_scaling_factor()'s mark check ──────────────────────────────────────

def test_song_scaling_factor_prefers_a_mark_over_auto():
    marks.set_mark("spotify:track:marked", 1.9)
    # No library/genre data at all -> auto would fall to the bare genre
    # default (0.7); the mark must win outright, unrelated to that.
    assert isc.song_scaling_factor("spotify:track:marked", []) == 1.9


def test_song_scaling_factor_falls_through_to_auto_when_unmarked():
    assert isc.song_scaling_factor("spotify:track:unmarked-2", []) == \
        isc.auto_scaling_factor("spotify:track:unmarked-2", [])


def test_mark_is_never_reclamped_into_the_auto_range():
    """The whole point: a mark above SCALE_MAX must survive untouched —
    re-clamping it down to the auto range would silently restore the cap
    he explicitly asked to have a release valve for."""
    marks.set_mark("spotify:track:hype", 2.0)
    assert isc.song_scaling_factor("spotify:track:hype", []) == 2.0
    assert 2.0 > isc.SCALE_MAX, "sanity: this mark is genuinely outside the auto range"


def test_auto_scaling_factor_ignores_marks_entirely():
    """auto_scaling_factor() is the AUTO-only half of the 0.75 ceiling —
    a mark must never leak into it, or the ceiling stops meaning anything
    for the many callers that specifically want the un-marked number."""
    marks.set_mark("spotify:track:marked-2", 1.9)
    assert isc.auto_scaling_factor("spotify:track:marked-2", []) <= isc.SCALE_MAX


def test_no_uri_never_touches_the_marks_store():
    # No uri -> song_scaling_factor must not even attempt a mark lookup.
    assert isc.song_scaling_factor(None, ["rock"]) == isc.resolve_genre_scale(["rock"])
    assert isc.song_scaling_factor("", ["rock"]) == isc.resolve_genre_scale(["rock"])


# ── the 0.75 ceiling, with and without a mark ────────────────────────────────

def test_a_marked_track_can_clear_the_075_auto_ceiling():
    marks.set_mark("spotify:track:hype-2", 2.0)
    factor = isc.song_scaling_factor("spotify:track:hype-2", [])
    final = isc.combine_measured_and_scale(1.0, factor)
    assert final > 0.75, "a marked track must be able to exceed the automatic ceiling"
    assert final == 1.0, "matches the Admiral's own worked example: 0.6 * 2.0 = 1.2, clamped to 1.0"


def test_an_unmarked_track_never_exceeds_075_at_the_auto_ceiling():
    factor = isc.song_scaling_factor("spotify:track:no-mark-ever", [])
    final = isc.combine_measured_and_scale(1.0, factor)
    assert final <= isc.HEADROOM_RESERVE * isc.SCALE_MAX + 1e-9


# ── API surface ─────────────────────────────────────────────────────────────

def test_api_mark_lifecycle():
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    client = TestClient(create_app())
    uri = "spotify:track:api-mark-test"

    r = client.get("/api/intensity-scale/mark", params={"uri": uri})
    assert r.status_code == 200
    body = r.json()
    assert body["mark"] is None
    assert body["effective_factor"] == body["auto_factor"], \
        "unmarked: effective == auto"
    assert body["manual_min"] == 0.0 and body["manual_max"] == 2.0

    r = client.put("/api/intensity-scale/mark", params={"uri": uri}, json={"factor": 1.6})
    assert r.status_code == 200
    assert r.json() == {"uri": uri, "mark": 1.6}

    r = client.get("/api/intensity-scale/mark", params={"uri": uri})
    body = r.json()
    assert body["mark"] == 1.6
    assert body["effective_factor"] == 1.6
    assert body["auto_factor"] != 1.6, "auto_factor must stay the UNMARKED number"

    r = client.delete("/api/intensity-scale/mark", params={"uri": uri})
    assert r.status_code == 200
    assert r.json() == {"uri": uri, "cleared": True}

    r = client.get("/api/intensity-scale/mark", params={"uri": uri})
    body = r.json()
    assert body["mark"] is None
    assert body["effective_factor"] == body["auto_factor"]


def test_api_rejects_a_factor_outside_the_manual_range():
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    client = TestClient(create_app())
    r = client.put("/api/intensity-scale/mark",
                   params={"uri": "spotify:track:reject-me"}, json={"factor": 2.5})
    assert r.status_code == 422
    assert marks.get_mark("spotify:track:reject-me") is None, \
        "a rejected PUT must never partially apply"
