"""
SpotFX — Training Profile manager.

CRUD for AI-trigger training profiles stored in storage/training_profiles.json.
Each profile bundles a name, description/prompt, training song URIs, and target song URIs.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
import uuid

from config import PROFILES_DIR

logger = logging.getLogger(__name__)

TRAINING_PROFILES_FILE = PROFILES_DIR.parent / "training_profiles.json"


class TrainingProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Profile"
    description: str = ""
    training_uris: list[str] = []
    embedded_only_uris: list[str] = []  # additional songs used for KNN training only (not sent to Claude)
    target_uris: list[str] = []
    genres: list[str] = []      # genre tags this profile handles (e.g. ["edm", "dubstep"])
    is_default: bool = False    # fallback when no profile's genres match the song
    # ── Embedded trigger tuning ───────────────────────────────────────────────
    min_trigger_spacing_beats: int = 4        # min beats between any two triggers (overrides ms fallback)
    min_scene_change_spacing_beats: int = 16  # min beats between standard scene fill triggers

    # ── Explicit event IDs per structural role ────────────────────────────────
    song_start_event_id: str = ""    # Stage 0 — always at ms=0 (empty = skip)
    beat_start_event_id: str = ""    # Stage 1 — first bass entry (empty = use scene_fill_event_id)
    song_end_event_id: str = ""      # Stage 2 — fade-out detection (empty = skip)
    drop_event_id: str = ""          # Stage 3 — bass re-entry after gap (empty = skip)
    lull_event_id: str = ""          # Stage 3 — quiet before drop / gap entry (empty = skip)
    charge_event_id: str = ""        # Stage 4 — buildup peak before lull (empty = skip)
    quiet_event_id: str = ""         # Stage 5 — extended quiet section entry (empty = skip)
    scene_fill_event_id: str = ""    # Stage 6 — standard fill / energy re-entry (empty = skip)
    flare_event_id: str = ""         # Stage 7 — flare triggers (empty = skip flare stage)
    flare_max_gap_beats: int = 32    # maximum beats between flares (at low energy sections)

    # ── Profile notes (running explainer, shown in UI) ────────────────────────
    notes: str = ""

    # ── Hidden tuning parameters (per-profile, not in main UI) ───────────────
    # Beat Start (Stage 1)
    beat_start_lookback_beats: int = 4
    beat_start_lookahead_beats: int = 4
    beat_start_near_zero_thresh: float = 0.05
    beat_start_factor: float = 3.0
    beat_start_abs_thresh: float = 0.15

    # Gap Detection — Lull + Drop (Stage 3)
    gap_energy_thresh: float = 0.15
    gap_min_beats: int = 1
    gap_max_beats: int = 20
    gap_before_thresh: float = 0.35
    gap_before_window: int = 4
    gap_after_thresh: float = 0.45
    gap_after_window: int = 4
    gap_bass_onset_gate: bool = True
    gap_bass_onset_gate_window: int = 4
    gap_bass_onset_gate_thresh: float = 0.20

    # Charge (Stage 4)
    charge_lookback_beats: int = 12
    charge_min_score: float = 0.40

    # Quiet Section (Stage 5)
    quiet_thresh: float = 0.40       # rms_total below this = quiet beat
    quiet_min_beats: int = 8         # min beats for a run to count as a quiet section
    quiet_ramp_beats: int = 8        # look-back window to detect gradual ramp
    quiet_ramp_max_step: float = 0.08  # max per-beat rms drop to count as "gradual"

    # Standard Fill (Stage 6)
    fill_uptick_thresh: float = 0.10
    fill_harmonic_thresh: float = 0.35
    fill_min_spacing_beats: int = 48     # minimum beats between any two fill scene triggers

    # Song End (Stage 2)
    song_end_fade_thresh: float = 0.20
    song_end_sustain_beats: int = 8


def _load_raw() -> dict:
    if TRAINING_PROFILES_FILE.exists():
        try:
            return json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_raw(data: dict) -> None:
    TRAINING_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRAINING_PROFILES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_training_profiles() -> list[dict]:
    return list(_load_raw().values())


def save_training_profile(profile: TrainingProfile) -> None:
    raw = _load_raw()
    # Enforce single default: clear is_default on all other profiles first
    if profile.is_default:
        for pid, pdata in raw.items():
            if pid != profile.id and pdata.get("is_default"):
                pdata["is_default"] = False
    raw[profile.id] = json.loads(profile.model_dump_json())
    _save_raw(raw)
    logger.debug("Saved training profile: %s", profile.name)


def delete_training_profile(profile_id: str) -> bool:
    raw = _load_raw()
    if profile_id not in raw:
        return False
    del raw[profile_id]
    _save_raw(raw)
    return True
