"""
SpotFX NN — Visualize a song's features and triggers.

Run: python -m nn.visualize
     or via VS Code task "NN: Visualize Song"

Opens a matplotlib window showing:
  - Beat energy features (rms_total, rms_bass) as a waveform-like timeline
  - Section boundaries as colored bands
  - Trigger placements as colored markers (one color per structural role)

Use --song N to pick a specific song index (default: 0).
Use --list to see available songs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Visualize SpotFX NN training data")
    parser.add_argument("--song", type=int, default=0, help="Song index to visualize")
    parser.add_argument("--list", action="store_true", help="List available songs")
    args = parser.parse_args()

    from nn.dataset import SpotFXDataset, ROLE_NAMES, SECTION_LABELS
    from nn.genre_map import GENRE_NAMES

    base = PROJECT_ROOT
    ds = SpotFXDataset(
        profiles_dir=base / "storage" / "profiles",
        audio_shapes_dir=base / "storage" / "audio_shapes",
        training_profiles_file=base / "storage" / "training_profiles.json",
        training_profile_name="Trap/Reggaeton",
        verified_only=True,
    )

    if args.list or len(ds) == 0:
        print(f"\nAvailable songs ({len(ds)}):")
        for i, s in enumerate(ds.songs):
            genre = GENRE_NAMES[s["genre_id"]]
            print(f"  [{i}] {s['artist']} - {s['title']} ({s['num_beats']} beats, {s['num_triggers']} triggers, {genre})")
        if len(ds) == 0:
            print("  (none — check verified_only filter and training profile)")
        return

    if args.song >= len(ds):
        print(f"Song index {args.song} out of range (0-{len(ds)-1})")
        return

    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    song = ds.get_song_info(args.song)
    features = song["features"].numpy()
    labels = song["labels"].numpy()
    beat_ms = song["beat_ms"].numpy()
    beat_s = beat_ms / 1000.0  # convert to seconds for x-axis

    title = f"{song['artist']} - {song['title']}"
    print(f"\nVisualizing: {title} ({song['num_beats']} beats, {song['num_triggers']} triggers)")

    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
    fig.suptitle(f"SpotFX NN Features — {title}", fontsize=14, fontweight="bold")

    # ── Panel 1: Energy features ─────────────────────────────────────────────
    ax1 = axes[0]
    ax1.fill_between(beat_s, features[:, 0], alpha=0.3, color="#4fc3f7", label="rms_total")
    ax1.fill_between(beat_s, features[:, 1], alpha=0.4, color="#e53935", label="rms_bass")
    ax1.plot(beat_s, features[:, 2], alpha=0.5, color="#66bb6a", linewidth=0.8, label="rms_mid")
    ax1.plot(beat_s, features[:, 3], alpha=0.5, color="#ab47bc", linewidth=0.8, label="rms_high")
    ax1.set_ylabel("Energy (0-1)")
    ax1.set_ylim(0, 1.05)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.set_title("Energy Features", fontsize=10)

    # Add section bands to all panels
    section_colors = {
        "intro": "#2196F320",
        "verse": "#4CAF5020",
        "chorus": "#FF980020",
        "bridge": "#9C27B020",
        "drop": "#F4433620",
        "outro": "#60738020",
    }
    # Reconstruct sections from one-hot features
    sections = []
    current_sec = None
    for i in range(len(beat_s)):
        sec_onehot = features[i, 10:16]
        sec_idx = sec_onehot.argmax() if sec_onehot.max() > 0 else -1
        sec_label = SECTION_LABELS[sec_idx] if sec_idx >= 0 else None
        if sec_label != current_sec:
            if current_sec is not None:
                sections[-1]["end"] = beat_s[i]
            if sec_label is not None:
                sections.append({"label": sec_label, "start": beat_s[i], "end": beat_s[-1]})
            current_sec = sec_label
    if sections:
        sections[-1]["end"] = beat_s[-1]

    for ax in axes:
        for sec in sections:
            color = section_colors.get(sec["label"], "#00000010")
            ax.axvspan(sec["start"], sec["end"], color=color)
        # Add section labels to top panel only
    for sec in sections:
        mid = (sec["start"] + sec["end"]) / 2
        ax1.text(mid, 1.02, sec["label"], ha="center", va="bottom", fontsize=7, alpha=0.7)

    # ── Panel 2: Onset + harmonic features ───────────────────────────────────
    ax2 = axes[1]
    ax2.bar(beat_s, features[:, 4], width=beat_s[1]-beat_s[0] if len(beat_s)>1 else 0.5,
            alpha=0.5, color="#ff9800", label="onset_score")
    ax2.bar(beat_s, features[:, 5], width=beat_s[1]-beat_s[0] if len(beat_s)>1 else 0.5,
            alpha=0.5, color="#e53935", label="bass_onset_score")
    ax2.plot(beat_s, features[:, 6], color="#7c4dff", linewidth=1.2, alpha=0.8, label="harmonic_score")
    # Mark downbeats
    downbeats = features[:, 7] > 0.5
    if downbeats.any():
        ax2.scatter(beat_s[downbeats], np.full(downbeats.sum(), -0.03),
                   marker="|", s=30, color="#888888", alpha=0.5, label="downbeats")
    ax2.set_ylabel("Score (0-1)")
    ax2.set_ylim(-0.08, 1.05)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.set_title("Onset & Harmonic Features", fontsize=10)

    # ── Panel 3: Trigger labels ──────────────────────────────────────────────
    ax3 = axes[2]
    role_colors = {
        1: "#2196F3",   # song_start — blue
        2: "#4CAF50",   # beat_start — green
        3: "#607380",   # song_end — gray
        4: "#F44336",   # drop — red
        5: "#9C27B0",   # lull — purple
        6: "#FF9800",   # charge — orange
        7: "#00BCD4",   # quiet — cyan
        8: "#FFEB3B",   # scene_fill — yellow
        9: "#E91E63",   # flare — pink
    }

    # Plot rms_total as background reference
    ax3.fill_between(beat_s, features[:, 0], alpha=0.15, color="#888888")
    ax3.set_ylabel("Triggers")
    ax3.set_ylim(-0.1, 1.4)

    # Plot triggers as vertical lines + markers
    for role_idx in range(1, 10):
        mask = labels == role_idx
        if not mask.any():
            continue
        color = role_colors.get(role_idx, "#888888")
        name = ROLE_NAMES[role_idx]
        trig_s = beat_s[mask]
        ax3.vlines(trig_s, 0, 1.0, colors=color, alpha=0.7, linewidth=1.5)
        ax3.scatter(trig_s, np.full(len(trig_s), 1.1), color=color, s=40,
                   zorder=5, label=f"{name} ({len(trig_s)})")

    ax3.set_xlabel("Time (seconds)")
    ax3.legend(loc="upper right", fontsize=7, ncol=3)
    ax3.set_title("Trigger Labels (ground truth)", fontsize=10)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
