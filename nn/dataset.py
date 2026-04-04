"""
SpotFX NN — Dataset.

Converts existing SpotFX song profiles + librosa analysis into PyTorch tensors
for training the trigger prediction model.

Each sample is one song: a feature matrix (num_beats, 18) and a label vector (num_beats,).
The genre ID is stored separately and fed to the model's embedding layer.

Feature dimensions (18, before genre embedding):
  0: rms_total        7: is_downbeat
  1: rms_bass         8: beat_position_in_bar  (0-1)
  2: rms_mid          9: relative_position_in_song (0-1)
  3: rms_high        10-15: section_type one-hot (intro/verse/chorus/bridge/drop/outro)
  4: onset_score      16: section_energy_rms
  5: bass_onset_score 17: section_onset_density (normalised)
  6: harmonic_score

Label classes (10):
  0: no_trigger   5: lull
  1: song_start   6: charge
  2: beat_start   7: quiet
  3: song_end     8: scene_fill
  4: drop         9: flare
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset
from torch.nn.utils.rnn import pad_sequence

logger = logging.getLogger(__name__)

# ── Structural role labels ──────────────────────────────────────────────────
ROLE_NAMES = [
    "no_trigger",   # 0
    "beat_start",   # 1
    "song_end",     # 2
    "drop",         # 3
    "lull",         # 4
    "charge",       # 5
    "quiet",        # 6
    "scene_fill",   # 7
    "flare",        # 8
]
NUM_CLASSES = len(ROLE_NAMES)

# TrainingProfile field name -> label index
# NOTE: song_start is excluded -- it's always at ms=0 and added programmatically
_ROLE_FIELD_TO_LABEL = {
    "beat_start_event_id": 1,
    "song_end_event_id":   2,
    "drop_event_id":       3,
    "lull_event_id":       4,
    "charge_event_id":     5,
    "quiet_event_id":      6,
    "scene_fill_event_id": 7,
    "flare_event_id":      8,
}

# Section label → one-hot index (6 slots)
SECTION_LABELS = ["intro", "verse", "chorus", "bridge", "drop", "outro"]
_SECTION_TO_IDX = {s: i for i, s in enumerate(SECTION_LABELS)}
NUM_SECTION_TYPES = len(SECTION_LABELS)

# Feature count (before genre embedding is added by model)
FEATURES_PER_BEAT = 7 + 1 + 2 + NUM_SECTION_TYPES + 2  # = 18

# Match window: max ms distance between a trigger timestamp and its nearest beat
MATCH_WINDOW_MS = 500


def _build_event_to_role(training_profile: dict) -> dict[str, int]:
    """Build event_id → role_label mapping from a training profile dict."""
    mapping = {}
    for field, label_idx in _ROLE_FIELD_TO_LABEL.items():
        eid = training_profile.get(field, "")
        if eid:
            mapping[eid] = label_idx
    return mapping


def _find_section(sections: list[dict], beat_ms: int) -> Optional[dict]:
    """Find the section containing a beat timestamp."""
    for sec in sections:
        if sec["start_ms"] <= beat_ms < sec["end_ms"]:
            return sec
    # If past the last section, use the last one
    if sections:
        return sections[-1]
    return None


def _extract_features(
    analysis: dict,
    genre_id: int,
) -> tuple[torch.Tensor, torch.Tensor, int]:
    """
    Extract feature matrix and beat timestamps from a librosa analysis dict.

    Returns:
        features: (num_beats, 18) float tensor
        beat_ms: (num_beats,) int tensor of beat timestamps
        genre_id: int macro genre ID
    """
    beats = analysis["beats"]
    sections = analysis.get("sections", [])
    beats_per_bar = analysis.get("beats_per_bar", 4)
    duration_ms = beats[-1]["ms"] if beats else 1  # approximate

    # Normalise section onset density across this song
    max_onset_density = max(
        (s.get("onset_density_per_s", 0) for s in sections), default=1.0
    )
    if max_onset_density == 0:
        max_onset_density = 1.0

    num_beats = len(beats)
    features = torch.zeros(num_beats, FEATURES_PER_BEAT)
    beat_ms = torch.zeros(num_beats, dtype=torch.long)

    for i, beat in enumerate(beats):
        ms = beat["ms"]
        beat_ms[i] = ms

        # 7 librosa features (0-6)
        features[i, 0] = beat.get("rms_total", 0.0)
        features[i, 1] = beat.get("rms_bass", 0.0)
        features[i, 2] = beat.get("rms_mid", 0.0)
        features[i, 3] = beat.get("rms_high", 0.0)
        features[i, 4] = beat.get("onset_score", 0.0)
        features[i, 5] = beat.get("bass_onset_score", 0.0)
        features[i, 6] = beat.get("harmonic_score", 0.0)

        # is_downbeat (7)
        features[i, 7] = 1.0 if beat.get("is_downbeat", False) else 0.0

        # beat_position_in_bar (8): 0.0 to ~1.0
        features[i, 8] = (i % beats_per_bar) / max(beats_per_bar - 1, 1)

        # relative_position_in_song (9): 0.0 to 1.0
        features[i, 9] = ms / max(duration_ms, 1)

        # section one-hot (10-15) + section features (16-17)
        sec = _find_section(sections, ms)
        if sec:
            sec_label = sec.get("label", "").lower()
            sec_idx = _SECTION_TO_IDX.get(sec_label)
            if sec_idx is not None:
                features[i, 10 + sec_idx] = 1.0
            features[i, 16] = sec.get("energy_rms", 0.0)
            features[i, 17] = sec.get("onset_density_per_s", 0.0) / max_onset_density

    return features, beat_ms, genre_id


def _assign_labels(
    beat_ms: torch.Tensor,
    triggers: list[dict],
    event_to_role: dict[str, int],
) -> torch.Tensor:
    """
    Assign a structural role label to each beat based on trigger timestamps.

    Each trigger is matched to its nearest beat within MATCH_WINDOW_MS.
    If multiple triggers map to the same beat, the rarer role wins (higher label index).
    """
    num_beats = len(beat_ms)
    labels = torch.zeros(num_beats, dtype=torch.long)  # 0 = no_trigger
    beat_ms_np = beat_ms.numpy()

    for trig in triggers:
        if not trig.get("enabled", True):
            continue
        eid = trig.get("event_id", "")
        role = event_to_role.get(eid)
        if role is None:
            continue  # trigger uses an event not in the training profile's role mapping

        trig_ms = trig["timestamp_ms"]
        # Find nearest beat
        dists = abs(beat_ms_np - trig_ms)
        nearest_idx = dists.argmin()
        if dists[nearest_idx] > MATCH_WINDOW_MS:
            continue  # no beat close enough

        # Higher label index = rarer role, wins ties
        if role > labels[nearest_idx].item():
            labels[nearest_idx] = role

    return labels


class SpotFXDataset(Dataset):
    """
    PyTorch Dataset for SpotFX trigger prediction.

    Each item is a full song: (features, labels, genre_id, song_info).
    - features: (num_beats, 18) float tensor
    - labels: (num_beats,) long tensor (0-9)
    - genre_id: int (0-5)
    - song_info: dict with title, artist, num_beats, etc.
    """

    def __init__(
        self,
        profiles_dir: str | Path,
        audio_shapes_dir: str | Path,
        training_profiles_file: str | Path,
        training_profile_name: str = "Trap/Reggaeton",
        verified_only: bool = True,
        genre_filter: Optional[list[int]] = None,
        all_genres: bool = False,
    ):
        super().__init__()
        self.profiles_dir = Path(profiles_dir)
        self.audio_shapes_dir = Path(audio_shapes_dir)
        self.training_profile_name = training_profile_name
        self.verified_only = verified_only
        self.genre_filter = genre_filter

        # Load training profiles for event→role mapping
        tp_data = json.loads(Path(training_profiles_file).read_text(encoding="utf-8"))

        if all_genres:
            # Load ALL training profiles that have event mappings + genres
            self._genre_to_event_role: dict[int, dict[str, int]] = {}
            from nn.genre_map import map_genre
            for prof in tp_data.values():
                etr = _build_event_to_role(prof)
                if not etr:
                    continue
                tp_genres = prof.get("genres", [])
                for g in tp_genres:
                    gid = map_genre([g])
                    if gid not in self._genre_to_event_role:
                        self._genre_to_event_role[gid] = etr
            self.event_to_role = {}  # not used directly in all_genres mode
            self.training_profile = None
            self.genre_filter = None  # no filtering
            logger.info("All-genres mode: loaded mappings for genre IDs %s",
                        list(self._genre_to_event_role.keys()))
        else:
            self._genre_to_event_role = {}
            self.training_profile = None
            for prof in tp_data.values():
                if prof.get("name") == training_profile_name:
                    self.training_profile = prof
                    break
            if self.training_profile is None:
                raise ValueError(
                    f"Training profile '{training_profile_name}' not found. "
                    f"Available: {[p.get('name') for p in tp_data.values()]}"
                )

            self.event_to_role = _build_event_to_role(self.training_profile)
            if not self.event_to_role:
                raise ValueError(
                    f"Training profile '{training_profile_name}' has no event->role mappings. "
                    "Fill in the *_event_id fields in the UI first."
                )

            # Auto-detect genre filter from training profile if not explicitly set
            if self.genre_filter is None:
                tp_genres = self.training_profile.get("genres", [])
                if tp_genres:
                    from nn.genre_map import map_genre
                    detected = set()
                    for g in tp_genres:
                        detected.add(map_genre([g]))
                    self.genre_filter = list(detected)

        # Load and filter songs
        self.songs: list[dict] = []
        self._load_songs()

    def _load_songs(self):
        """Scan profiles + librosa files and build the dataset."""
        from nn.genre_map import map_genre

        # Build URI -> librosa path index (filenames may not match profiles)
        librosa_by_uri: dict[str, Path] = {}
        for lp in sorted(self.audio_shapes_dir.glob("*.librosa.json")):
            try:
                data = json.loads(lp.read_text(encoding="utf-8"))
                uri = data.get("spotify_uri", "")
                if uri:
                    librosa_by_uri[uri] = lp
            except Exception:
                continue

        for profile_path in sorted(self.profiles_dir.glob("*.json")):
            try:
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            # Must have triggers
            if not profile.get("triggers"):
                continue

            # Verified-only filter
            if self.verified_only:
                if not profile.get("verified", False):
                    continue

            # Must have librosa analysis (match by spotify_uri)
            spotify_uri = profile.get("spotify_uri", "")
            librosa_path = librosa_by_uri.get(spotify_uri)
            if librosa_path is None:
                continue

            try:
                analysis = json.loads(librosa_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if not analysis.get("beats"):
                continue

            # Genre mapping
            genres = profile.get("artist_genre", [])
            genre_id = map_genre(genres)

            # Genre filter
            if self.genre_filter is not None and genre_id not in self.genre_filter:
                continue

            # Pick the right event→role mapping for this song's genre
            if self._genre_to_event_role:
                event_to_role = self._genre_to_event_role.get(genre_id)
                if event_to_role is None:
                    continue  # no training profile for this genre
            else:
                event_to_role = self.event_to_role

            # Extract features and labels
            features, beat_ms, genre_id = _extract_features(analysis, genre_id)
            labels = _assign_labels(beat_ms, profile["triggers"], event_to_role)

            num_triggers = int((labels > 0).sum())
            # Skip songs where no triggers matched the training profile's event mapping
            # (e.g. EDM songs when using the Trap/Reggaeton profile)
            if num_triggers == 0:
                continue

            self.songs.append({
                "features": features,
                "labels": labels,
                "beat_ms": beat_ms,
                "genre_id": genre_id,
                "title": profile.get("title", "?"),
                "artist": profile.get("artist", "?"),
                "spotify_uri": profile.get("spotify_uri", ""),
                "num_beats": len(features),
                "num_triggers": num_triggers,
                "genres_raw": genres,
            })

        logger.info(
            "Loaded %d songs (%d total beats, %d total triggers)",
            len(self.songs),
            sum(s["num_beats"] for s in self.songs),
            sum(s["num_triggers"] for s in self.songs),
        )

    def __len__(self):
        return len(self.songs)

    def __getitem__(self, idx):
        s = self.songs[idx]
        return s["features"], s["labels"], s["genre_id"], {
            "title": s["title"],
            "artist": s["artist"],
            "num_beats": s["num_beats"],
            "num_triggers": s["num_triggers"],
        }

    def get_song_info(self, idx) -> dict:
        return self.songs[idx]

    def label_counts(self) -> dict[str, int]:
        """Count labels across all songs."""
        counts = {name: 0 for name in ROLE_NAMES}
        for s in self.songs:
            for label_idx in range(NUM_CLASSES):
                counts[ROLE_NAMES[label_idx]] += int((s["labels"] == label_idx).sum())
        return counts

    def train_val_split(
        self, val_fraction: float = 0.2, seed: int = 42
    ) -> tuple["SpotFXSubset", "SpotFXSubset"]:
        """
        Split by song (not by beat) to avoid data leakage.
        Returns (train_subset, val_subset).
        """
        indices = list(range(len(self.songs)))
        rng = random.Random(seed)
        rng.shuffle(indices)
        split = max(1, int(len(indices) * val_fraction))
        val_indices = indices[:split]
        train_indices = indices[split:]
        return SpotFXSubset(self, train_indices), SpotFXSubset(self, val_indices)


class SpotFXSubset(Dataset):
    """A subset of SpotFXDataset (train or val split)."""

    def __init__(self, parent: SpotFXDataset, indices: list[int]):
        self.parent = parent
        self.indices = indices

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, idx):
        return self.parent[self.indices[idx]]

    def get_song_info(self, idx) -> dict:
        return self.parent.get_song_info(self.indices[idx])

    def label_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in ROLE_NAMES}
        for i in self.indices:
            s = self.parent.songs[i]
            for label_idx in range(NUM_CLASSES):
                counts[ROLE_NAMES[label_idx]] += int((s["labels"] == label_idx).sum())
        return counts


class ChunkedSpotFXDataset(Dataset):
    """
    Sliding-window augmentation for training.

    Wraps a SpotFXSubset and returns fixed-size chunks instead of full songs.
    Used ONLY for training -- validation always uses full songs.

    With window_size=128 and stride=64 (50% overlap), a 300-beat song produces
    ~4 chunks, giving roughly 4-5x data multiplication across the training set.
    """

    def __init__(
        self,
        subset: SpotFXSubset,
        window_size: int = 128,
        stride: int = 64,
        jitter_std: float = 0.0,
    ):
        super().__init__()
        self.subset = subset
        self.window_size = window_size
        self.stride = stride
        self.jitter_std = jitter_std

        self.chunks: list[tuple[int, int, int]] = []  # (song_idx, start, end)
        self._build_chunks()

    def _build_chunks(self):
        """Pre-compute all (song_idx, start, end) tuples."""
        for song_idx in range(len(self.subset)):
            features, labels, genre_id, info = self.subset[song_idx]
            num_beats = len(features)
            for start in range(0, num_beats, self.stride):
                end = min(start + self.window_size, num_beats)
                # Skip very short tail chunks (less than 16 beats)
                if end - start < 16:
                    continue
                self.chunks.append((song_idx, start, end))

    def __len__(self):
        return len(self.chunks)

    def __getitem__(self, idx):
        song_idx, start, end = self.chunks[idx]
        features, labels, genre_id, info = self.subset[song_idx]
        chunk_feat = features[start:end].clone()
        chunk_labels = labels[start:end].clone()

        # Feature jittering: add Gaussian noise to the 7 continuous audio features
        if self.jitter_std > 0:
            noise = torch.randn_like(chunk_feat[:, :7]) * self.jitter_std
            chunk_feat[:, :7] = (chunk_feat[:, :7] + noise).clamp(0.0, 1.0)

        return chunk_feat, chunk_labels, genre_id, {
            "title": info.get("title", "?") if isinstance(info, dict) else "?",
            "artist": info.get("artist", "?") if isinstance(info, dict) else "?",
            "num_beats": end - start,
            "num_triggers": int((chunk_labels > 0).sum()),
        }

    def label_counts(self) -> dict[str, int]:
        """Count labels across all chunks."""
        counts = {name: 0 for name in ROLE_NAMES}
        for song_idx, start, end in self.chunks:
            features, labels, genre_id, info = self.subset[song_idx]
            chunk_labels = labels[start:end]
            for label_idx in range(NUM_CLASSES):
                counts[ROLE_NAMES[label_idx]] += int((chunk_labels == label_idx).sum())
        return counts


def collate_songs(batch):
    """
    Collate variable-length songs into a padded batch.

    Returns:
        features: (batch, max_beats, 18) padded
        labels: (batch, max_beats) padded with -1 (ignored in loss)
        genre_ids: (batch,) long tensor
        masks: (batch, max_beats) bool — True for real beats, False for padding
        infos: list of info dicts
    """
    features_list, labels_list, genre_ids, infos = [], [], [], []
    for feat, lab, gid, info in batch:
        features_list.append(feat)
        labels_list.append(lab)
        genre_ids.append(gid)
        infos.append(info)

    # Pad features
    features = pad_sequence(features_list, batch_first=True, padding_value=0.0)
    # Pad labels with -1 (will be masked in loss)
    labels = pad_sequence(labels_list, batch_first=True, padding_value=-1)
    # Build mask
    masks = torch.zeros(features.shape[0], features.shape[1], dtype=torch.bool)
    for i, feat in enumerate(features_list):
        masks[i, :len(feat)] = True

    genre_ids = torch.tensor(genre_ids, dtype=torch.long)

    return features, labels, genre_ids, masks, infos
