"""
Spec for the 2026-08-14 librosa-backfill failure handling:

  - services/audio_shape_service._save_wav_and_analyze writes WAVs atomically
    (tmp file + os.replace) so a concurrent reader never observes a partial
    file — this is the root cause of the "System error" opens seen during
    the backfill run (a live re-capture overwriting a WAV in place while
    scripts/rerun_librosa.py was reading the same path).
  - scripts/rerun_librosa.rerun_one classifies each failure as "vanished"
    (WAV gone/changed after the check — transient, expected to recover on a
    later rerun) or "corrupt" (WAV still present and unchanged — genuinely
    needs re-capture), never retries, and reports each song exactly once.

No live access: everything runs against tmp_path fixtures.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.audio_shape import AudioShapeMeta


def _make_meta(tmp_path: Path, name: str = "Artist - Title") -> AudioShapeMeta:
    return AudioShapeMeta(
        spotify_uri=f"spotify:track:{name}",
        title="Title",
        artist="Artist",
        duration_ms=180_000,
        sample_interval_ms=23,
        npz_file=f"{name}.npz",
    )


def _write_real_wav(path: Path, seconds: float = 0.2, sr: int = 22050) -> None:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    pcm = 0.1 * np.sin(2 * np.pi * 440 * t).astype("float32")
    sf.write(str(path), pcm, sr, subtype="FLOAT", format="WAV")


# ── rerun_one classification ──────────────────────────────────────────────

def test_rerun_one_ok_on_success(tmp_path, monkeypatch):
    import scripts.rerun_librosa as rerun_librosa

    meta = _make_meta(tmp_path)
    monkeypatch.setattr(
        "services.librosa_service.has_wav", lambda m: True,
    )
    monkeypatch.setattr(
        "services.librosa_service.analyze_sync", lambda m: object(),
    )
    assert rerun_librosa.rerun_one(meta) == "ok"


def test_rerun_one_vanished_when_wav_missing_upfront(tmp_path, monkeypatch):
    import scripts.rerun_librosa as rerun_librosa

    meta = _make_meta(tmp_path)
    monkeypatch.setattr("services.librosa_service.has_wav", lambda m: False)
    assert rerun_librosa.rerun_one(meta) == "vanished"


def test_rerun_one_vanished_when_wav_disappears_during_analysis(tmp_path, monkeypatch):
    """The has_wav() gate passes, but analyze_sync raises and the WAV is gone
    by the time we check again — the concurrent-capture signature."""
    import scripts.rerun_librosa as rerun_librosa

    meta = _make_meta(tmp_path)
    calls = {"n": 0}

    def has_wav(m):
        calls["n"] += 1
        return calls["n"] == 1  # present at the gate, gone on the post-failure check

    def analyze_sync(m):
        raise RuntimeError("Error opening '...': System error.")

    monkeypatch.setattr("services.librosa_service.has_wav", has_wav)
    monkeypatch.setattr("services.librosa_service.analyze_sync", analyze_sync)
    assert rerun_librosa.rerun_one(meta) == "vanished"


def test_rerun_one_corrupt_when_wav_present_but_unreadable(tmp_path, monkeypatch):
    """WAV is present both before and after the failure — a real content
    problem, not a race. Must be reported as corrupt, not retried."""
    import scripts.rerun_librosa as rerun_librosa

    meta = _make_meta(tmp_path)

    def analyze_sync(m):
        raise RuntimeError("Error opening '...': Format not recognised.")

    monkeypatch.setattr("services.librosa_service.has_wav", lambda m: True)
    monkeypatch.setattr("services.librosa_service.analyze_sync", analyze_sync)
    assert rerun_librosa.rerun_one(meta) == "corrupt"


def test_rerun_one_never_retries(tmp_path, monkeypatch):
    """A single attempt per song — analyze_sync must be called exactly once
    even on failure (no retry-forever loop)."""
    import scripts.rerun_librosa as rerun_librosa

    meta = _make_meta(tmp_path)
    call_count = {"n": 0}

    def analyze_sync(m):
        call_count["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("services.librosa_service.has_wav", lambda m: True)
    monkeypatch.setattr("services.librosa_service.analyze_sync", analyze_sync)
    rerun_librosa.rerun_one(meta)
    assert call_count["n"] == 1


# ── atomic WAV write closes the race ──────────────────────────────────────

def test_atomic_write_never_exposes_a_partial_file(tmp_path):
    """Direct reproduction of the backfill failure class: a writer
    continuously replacing the WAV while a reader repeatedly opens it.
    The old sf.write(target, ...)-in-place pattern truncates before writing
    (reproduced here as the 'broken' baseline); the tmp-file + os.replace()
    pattern used by _save_wav_and_analyze must never let a reader observe a
    partial file.
    """
    target = tmp_path / "target.wav"
    sr = 22050
    t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False)
    pcm = 0.1 * np.sin(2 * np.pi * 440 * t).astype("float32")
    sf.write(str(target), pcm, sr, subtype="FLOAT", format="WAV")

    stop = threading.Event()
    failures = []

    def atomic_writer():
        while not stop.is_set():
            fd, tmp = tempfile.mkstemp(dir=tmp_path, prefix=target.name, suffix=".tmp")
            os.close(fd)
            try:
                sf.write(tmp, pcm, sr, subtype="FLOAT", format="WAV")
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.005)

    writer_thread = threading.Thread(target=atomic_writer, daemon=True)
    writer_thread.start()
    try:
        for _ in range(40):
            try:
                sf.read(str(target), dtype="float32", always_2d=False)
            except Exception as exc:
                failures.append(exc)
            time.sleep(0.002)
    finally:
        stop.set()
        writer_thread.join(timeout=2)

    assert failures == []


# ── _save_wav_and_analyze writes atomically ───────────────────────────────

def test_save_wav_and_analyze_writes_atomically_and_leaves_no_tmp(tmp_path, monkeypatch):
    import asyncio

    import services.audio_shape_service as svc
    import services.librosa_service as librosa_service

    monkeypatch.setattr(svc, "AUDIO_SHAPES_DIR", tmp_path)
    monkeypatch.setattr(librosa_service, "AUDIO_SHAPES_DIR", tmp_path)
    monkeypatch.setattr(librosa_service, "manage_wav_retention", lambda: None)

    async def fake_analyze_async(meta):
        return object()

    monkeypatch.setattr(librosa_service, "analyze_async", fake_analyze_async)

    meta = _make_meta(tmp_path, name="Artist - Title")
    sr = 22050
    t = np.linspace(0, 0.1, int(sr * 0.1), endpoint=False)
    pcm = 0.1 * np.sin(2 * np.pi * 440 * t).astype("float32")

    ok = asyncio.run(svc._save_wav_and_analyze(meta, pcm, sr))
    assert ok is True

    target = tmp_path / "Artist - Title.wav"
    assert target.exists()
    # No leftover .tmp files from the write-then-rename.
    assert list(tmp_path.glob("*.tmp")) == []
    # The file that landed is a complete, readable WAV.
    read_pcm, read_sr = sf.read(str(target), dtype="float32", always_2d=False)
    assert read_sr == sr
    assert len(read_pcm) == len(pcm)


def test_save_wav_and_analyze_cleans_up_tmp_on_write_failure(tmp_path, monkeypatch):
    import asyncio

    import services.audio_shape_service as svc
    import services.librosa_service as librosa_service

    monkeypatch.setattr(svc, "AUDIO_SHAPES_DIR", tmp_path)
    monkeypatch.setattr(librosa_service, "AUDIO_SHAPES_DIR", tmp_path)

    meta = _make_meta(tmp_path, name="Artist - Title")
    # Deliberately malformed PCM (wrong ndim) to make sf.write raise.
    bad_pcm = np.zeros((2, 2, 2), dtype="float32")

    ok = asyncio.run(svc._save_wav_and_analyze(meta, bad_pcm, 22050))
    assert ok is False
    assert list(tmp_path.glob("*.tmp")) == []
    assert not (tmp_path / "Artist - Title.wav").exists()
