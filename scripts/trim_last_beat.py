"""
trim_last_beat.py
-----------------
One-time cleanup: drop the last beat from every existing .librosa.json file and
re-normalise onset_score, bass_onset_score, and harmonic_score across the
remaining beats so the per-song max is still 1.0.

Run from the repo root:
    py scripts/trim_last_beat.py
"""
import json
import glob
import os

AUDIO_SHAPES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "storage", "audio_shapes"
)

SCORE_KEYS = ["onset_score", "bass_onset_score", "harmonic_score"]


def renorm(beats: list[dict]) -> None:
    """Re-normalise each score key in-place so the max across all beats = 1.0."""
    for key in SCORE_KEYS:
        values = [b[key] for b in beats]
        mx = max(values)
        if mx > 0:
            for b in beats:
                b[key] = round(b[key] / mx, 3)


def process(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    beats = data.get("beats", [])
    if len(beats) < 2:
        return "SKIP (too few beats)"

    data["beats"] = beats[:-1]
    renorm(data["beats"])

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return f"OK  ({len(beats)} → {len(beats) - 1} beats)"


def main():
    pattern = os.path.join(AUDIO_SHAPES_DIR, "*.librosa.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print("No .librosa.json files found — check AUDIO_SHAPES_DIR path.")
        return

    print(f"Processing {len(files)} files...\n")
    for path in files:
        name = os.path.basename(path)[:60]
        result = process(path)
        print(f"  {result:<35} {name}")

    print(f"\nDone. {len(files)} files updated.")


if __name__ == "__main__":
    main()
