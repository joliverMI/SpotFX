"""
SpotFX — Librosa analysis data model.

Stores per-song musical events extracted by librosa:
  - beats and downbeats
  - onsets (note/transient attacks) — full-spectrum and bass-specific
  - structural section boundaries (with energy/density/label)
  - harmonic change points
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class LibrosaBeat(BaseModel):
    ms: int
    is_downbeat: bool = False
    rms_total: float = 0.0   # normalised 0–1 RMS energy for this beat interval
    rms_bass:  float = 0.0   # low-frequency band  (<250 Hz)
    rms_mid:   float = 0.0   # mid-frequency band  (250–4000 Hz)
    rms_high:  float = 0.0   # high-frequency band (>4000 Hz)
    onset_score:      float = 0.0  # sum of onset strengths in this interval, normalised 0–1 across song
    bass_onset_score: float = 0.0  # sum of bass onset strengths, normalised 0–1
    harmonic_score:   float = 0.0  # sum of harmonic novelty values, normalised 0–1
    mfcc: list[float] = Field(default_factory=list)        # 13 MFCC coefficients (z-score normalised per song)
    mfcc_delta: list[float] = Field(default_factory=list)  # 13 delta-MFCC coefficients


class LibrosaOnset(BaseModel):
    ms: int
    strength: float = 1.0   # onset envelope value at this point (normalized 0–1)


class LibrosaSection(BaseModel):
    start_ms: int
    end_ms: int
    label: str = ""                  # inferred type: intro/verse/chorus/bridge/drop/outro
    energy_rms: float = 0.0          # mean RMS energy, normalised 0–1 across all sections
    onset_density_per_s: float = 0.0 # onsets per second within this section


class LibrosaHarmonicChange(BaseModel):
    ms: int
    novelty: float = 1.0    # chroma novelty value (normalized 0–1)


class LibrosaAnalysis(BaseModel):
    spotify_uri: str
    title: str
    artist: str
    analyzed_at: str
    tempo_bpm: float
    beats_per_bar: int = 4
    downbeat_phase: int = 0      # phase used for is_downbeat labeling (0–beats_per_bar-1)
    librosa_offset_ms: int = 0   # reserved: future sync-slider adjustment
    beats: list[LibrosaBeat]
    onsets: list[LibrosaOnset]
    bass_onsets: list[LibrosaOnset] = Field(default_factory=list)  # low-freq (<250 Hz) onset pass
    sections: list[LibrosaSection]
    harmonic_changes: list[LibrosaHarmonicChange]
