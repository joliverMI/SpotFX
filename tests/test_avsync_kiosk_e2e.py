"""THE NUMBER, from the kiosk's own reductions — the load-bearing proof.

`scripts/check_avsync_kiosk.py` is the simulator and the spec; this file
runs it, so the two share ONE idea of the room (the established pattern
`tests/test_av_sync_session.py` uses with `scripts/check_av_sync.py`). What
it asserts is the only thing that matters about this client: that raw
microphone bytes and raw camera frames, reduced by
`spectra/capture_client/avsync_reduce.py` and timestamped by its
`SampleClock`, drive the REAL server correlation to the KNOWN offset, with
the right SIGN, in both directions — and that the harness goes RED when
either of those is corrupted.

No hardware, no network, no live storage."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_avsync_kiosk.py"
_spec = importlib.util.spec_from_file_location("check_avsync_kiosk", _SCRIPT)
kiosk = importlib.util.module_from_spec(_spec)
sys.modules["check_avsync_kiosk"] = kiosk
_spec.loader.exec_module(kiosk)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import av_sync_session as sessions
    from spectra.services import preview_pause
    monkeypatch.setattr(scfg, "AV_SYNC_MEASUREMENTS_FILE",
                        tmp_path / "av_sync_measurements.json")
    monkeypatch.setattr(scfg, "AV_SYNC_PATTERN_FILE",
                        tmp_path / "av_sync_pattern.json")
    sessions.current = None
    preview_pause.clear()
    yield tmp_path
    preview_pause.clear()
    sessions.current = None


def test_the_kiosks_own_reductions_recover_a_known_offset(tmp_path):
    """Raw PCM and raw grey8 frames in, `av_offset_ms` out — through the
    client's real framing, its real sample clock, the real wire messages and
    the real correlator."""
    room = kiosk.KioskRoom()
    result = asyncio.run(kiosk.run_kiosk_room(room, storage_dir=tmp_path,
                                              verbose=False))
    kiosk.check(result, room)
    est = result["estimate"]
    assert est["ok"] and est["av_offset_ms"] < 0
    assert "AHEAD" in est["statement"]
    # the client really did produce both streams, not a stub of one
    assert result["audio_messages"] > 100 and result["video_samples"] > 200
    assert result["audio_stats"]["anchor_frozen"]


def test_lights_genuinely_behind_read_positive_and_say_behind(tmp_path):
    """The sign, in the other direction. A wrong-SIGN answer is the one
    outcome worse than no answer at all, so it is asserted both ways."""
    room = kiosk.KioskRoom(light_latency_s=0.420, audio_path_s=0.040, fps=60,
                           seed=11)
    result = asyncio.run(kiosk.run_kiosk_room(room, storage_dir=tmp_path,
                                              verbose=False))
    kiosk.check(result, room)
    assert result["estimate"]["av_offset_ms"] > 0
    assert "BEHIND" in result["estimate"]["statement"]


def test_a_wildly_offset_client_clock_cancels_in_the_difference(tmp_path):
    """The kiosk's monotonic clock has no relationship to the server's —
    `time.monotonic()` is an uptime, so the two differ by days. It is
    common to both lags and must cancel."""
    room = kiosk.KioskRoom(phone_clock_offset_s=-86400.5, rtt_s=0.040,
                           read_jitter_s=0.020, mic_noise_db=6, seed=9)
    result = asyncio.run(kiosk.run_kiosk_room(room, storage_dir=tmp_path,
                                              verbose=False))
    kiosk.check(result, room)
    assert result["estimate"]["clock"]["ready"]


def test_the_harness_goes_red_on_a_flipped_sign_and_a_naive_audio_stamp(tmp_path):
    """A PROOF THAT CANNOT FAIL ON THE DEFECT IT WAS WRITTEN FOR IS
    DECORATION. Both corruptions are the exact shape of a silent wrong
    answer: a plausible number in the wrong direction, and a plausible
    number shifted by a batch length because the envelope was stamped when
    the read returned rather than when its samples existed."""
    room = kiosk.KioskRoom()
    result = asyncio.run(kiosk.run_kiosk_room(room, storage_dir=tmp_path,
                                              verbose=False))
    controls = kiosk.red_controls(room, result, storage_dir=tmp_path)
    assert [name for name, red, _ in controls if not red] == [], controls
    assert len(controls) == 2


def test_the_record_names_the_kiosk_that_measured_it(tmp_path):
    """A stored measurement months later has to say which camera stood
    where — otherwise a kiosk run and a phone run are the same row."""
    room = kiosk.KioskRoom()
    result = asyncio.run(kiosk.run_kiosk_room(room, storage_dir=tmp_path,
                                              verbose=False))
    phone = result["record"]["phone"]
    assert phone["source"] == "kiosk"
    assert phone["host"] == "sim-kiosk"
    assert phone["pose_name"] == "the sim shelf"
    assert phone["client"] == "spectra-capture-client"
    assert phone["video"]["capture_time_available"] is False
    assert phone["audio"]["latency_s"] is None
    # ...and the server names both kiosk-side systematics, in OPPOSITE
    # directions, because the client declined to claim either
    terms = {t["term"]: t["direction"]
             for t in result["estimate"]["systematics"]}
    camera = [d for t, d in terms.items() if "camera pipeline" in t]
    mic = [d for t, d in terms.items() if "microphone pipeline" in t]
    assert camera == ["lights_look_later"], terms
    assert mic == ["lights_look_earlier"], terms


def test_nothing_but_the_measurement_record_is_written(tmp_path):
    """The privacy property, re-proven for a client that has raw media in
    its hands: no audio, no frames, no number streams reach the disk."""
    from spectra.services.av_sync_session import load_measurements
    room = kiosk.KioskRoom()
    asyncio.run(kiosk.run_kiosk_room(room, storage_dir=tmp_path,
                                     verbose=False))
    recs = load_measurements(tmp_path / "av_sync_measurements.json")
    assert len(recs) == 1
    blob = repr(recs)
    for forbidden in ("data", "pcm", "audio_samples", "frame_bytes"):
        assert f"'{forbidden}'" not in blob
    assert not (tmp_path / "av_sync_pattern.json").exists()
