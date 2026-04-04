"""
SpotFX NN -- Export / inspect training data.

Run: python -m nn.export_training_data
     or via VS Code task "NN: Export Training Data"

Prints dataset statistics so you can verify the data pipeline is correct
before training any model.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path so SpotFX modules resolve
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn.dataset import SpotFXDataset, ROLE_NAMES, NUM_CLASSES
from nn.genre_map import GENRE_NAMES


def main():
    base = PROJECT_ROOT
    ds = SpotFXDataset(
        profiles_dir=base / "storage" / "profiles",
        audio_shapes_dir=base / "storage" / "audio_shapes",
        training_profiles_file=base / "storage" / "training_profiles.json",
        training_profile_name="Trap/Reggaeton",
        verified_only=True,
    )

    print(f"\n{'='*60}")
    print(f" SpotFX NN -- Training Data Summary")
    print(f"{'='*60}")
    print(f"\n  Songs loaded:  {len(ds)}")
    total_beats = sum(s["num_beats"] for s in ds.songs)
    total_triggers = sum(s["num_triggers"] for s in ds.songs)
    print(f"  Total beats:   {total_beats:,}")
    print(f"  Total triggers: {total_triggers:,}")
    print(f"  Trigger rate:  {total_triggers/max(total_beats,1)*100:.1f}%")

    # Per-song breakdown
    print(f"\n{'-'*60}")
    print(f" Per-Song Breakdown")
    print(f"{'-'*60}")
    print(f"  {'Artist':<20} {'Title':<25} {'Beats':>6} {'Trigs':>6} {'Genre'}")
    print(f"  {'-'*20} {'-'*25} {'-'*6} {'-'*6} {'-'*10}")
    for s in ds.songs:
        genre_name = GENRE_NAMES[s["genre_id"]]
        print(
            f"  {s['artist'][:20]:<20} {s['title'][:25]:<25} "
            f"{s['num_beats']:>6} {s['num_triggers']:>6} {genre_name}"
        )

    # Label distribution
    print(f"\n{'-'*60}")
    print(f" Label Distribution (all songs)")
    print(f"{'-'*60}")
    counts = ds.label_counts()
    for name in ROLE_NAMES:
        c = counts[name]
        pct = c / max(total_beats, 1) * 100
        bar = "#" * int(pct * 2)  # 2 chars per percent
        print(f"  {name:<12} {c:>6}  ({pct:>5.1f}%)  {bar}")

    # Feature statistics
    print(f"\n{'-'*60}")
    print(f" Feature Statistics (min / mean / max)")
    print(f"{'-'*60}")
    import torch
    all_feats = torch.cat([s["features"] for s in ds.songs], dim=0)
    feat_names = [
        "rms_total", "rms_bass", "rms_mid", "rms_high",
        "onset_score", "bass_onset_score", "harmonic_score",
        "is_downbeat", "beat_pos_bar", "rel_pos_song",
        "sec:intro", "sec:verse", "sec:chorus", "sec:bridge", "sec:drop", "sec:outro",
        "sec_energy", "sec_onset_density",
    ]
    for j, name in enumerate(feat_names):
        col = all_feats[:, j]
        print(f"  {name:<18} {col.min():>6.3f} / {col.mean():>6.3f} / {col.max():>6.3f}")

    # Train/val split
    print(f"\n{'-'*60}")
    print(f" Train / Validation Split (80/20 by song)")
    print(f"{'-'*60}")
    train_ds, val_ds = ds.train_val_split(val_fraction=0.2, seed=42)
    print(f"  Train songs: {len(train_ds)}")
    print(f"  Val songs:   {len(val_ds)}")
    train_counts = train_ds.label_counts()
    val_counts = val_ds.label_counts()
    print(f"\n  {'Label':<12} {'Train':>8} {'Val':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8}")
    for name in ROLE_NAMES:
        print(f"  {name:<12} {train_counts[name]:>8} {val_counts[name]:>8}")

    # Event-to-role mapping
    print(f"\n{'-'*60}")
    print(f" Event -> Role Mapping (from training profile)")
    print(f"{'-'*60}")
    for eid, role_idx in ds.event_to_role.items():
        print(f"  {eid[:36]}  ->  {ROLE_NAMES[role_idx]}")

    print(f"\n{'='*60}")
    print(f" Data pipeline OK -- ready for training!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
