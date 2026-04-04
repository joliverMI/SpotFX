"""
SpotFX NN -- Evaluation metrics.

Run: python -m nn.evaluate
     or via VS Code task "NN: Evaluate Model"

Loads the best checkpoint, runs on the validation set, and prints:
  - Per-class precision, recall, F1
  - Confusion matrix
  - Overall accuracy and macro-F1 (trigger classes only)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn.dataset import SpotFXDataset, collate_songs, NUM_CLASSES, ROLE_NAMES


def compute_metrics(
    preds: torch.Tensor,    # (N,) predicted class indices
    labels: torch.Tensor,   # (N,) ground truth class indices
) -> dict:
    """
    Compute per-class precision, recall, F1, and a confusion matrix.

    Returns dict with:
        per_class: {role_name: {precision, recall, f1, support}}
        confusion: (NUM_CLASSES, NUM_CLASSES) tensor  [true, pred]
        accuracy: float
    """
    confusion = torch.zeros(NUM_CLASSES, NUM_CLASSES, dtype=torch.long)
    for t, p in zip(labels, preds):
        confusion[t.item(), p.item()] += 1

    per_class = {}
    for i, name in enumerate(ROLE_NAMES):
        tp = confusion[i, i].item()
        fp = confusion[:, i].sum().item() - tp   # others predicted as i
        fn = confusion[i, :].sum().item() - tp    # i predicted as others
        support = confusion[i, :].sum().item()

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-8)

        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    total = labels.shape[0]
    correct = (preds == labels).sum().item()
    accuracy = correct / max(total, 1)

    return {
        "per_class": per_class,
        "confusion": confusion,
        "accuracy": accuracy,
    }


def print_metrics(metrics: dict):
    """Pretty-print evaluation metrics."""
    print(f"  {'Class':<12} {'Prec':>6} {'Rec':>6} {'F1':>6} {'Support':>8}")
    print(f"  {'-'*12} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")
    for name in ROLE_NAMES:
        m = metrics["per_class"][name]
        print(
            f"  {name:<12} {m['precision']:>6.3f} {m['recall']:>6.3f} "
            f"{m['f1']:>6.3f} {m['support']:>8}"
        )

    # Macro F1 over trigger classes only
    trigger_f1s = [
        metrics["per_class"][name]["f1"]
        for name in ROLE_NAMES[1:]
        if metrics["per_class"][name]["support"] > 0
    ]
    macro_f1 = sum(trigger_f1s) / max(len(trigger_f1s), 1)
    print(f"\n  Accuracy: {metrics['accuracy']:.3f}")
    print(f"  Macro F1 (trigger classes): {macro_f1:.3f}")


def print_confusion_matrix(confusion: torch.Tensor):
    """Print a confusion matrix with row/column labels."""
    # Abbreviate names for display
    abbr = ["noTrg", "bStar", "sEnd", "drop", "lull", "chrge", "quiet", "sFill", "flare"]

    print(f"\n  Confusion Matrix (rows=true, cols=predicted):")
    print(f"  {'':>7}", end="")
    for a in abbr:
        print(f" {a:>5}", end="")
    print()

    for i, name in enumerate(abbr):
        print(f"  {name:>7}", end="")
        for j in range(NUM_CLASSES):
            val = confusion[i, j].item()
            if val == 0:
                print(f"   {'.':>3}", end="")
            else:
                print(f" {val:>5}", end="")
        print()


def main():
    parser = argparse.ArgumentParser(description="Evaluate SpotFX NN trigger model")
    parser.add_argument("--model", default="mlp", choices=["mlp", "transformer"], help="Model type")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (must match training)")
    args = parser.parse_args()

    from nn.models import MLPBaseline, TriggerTransformer
    from torch.utils.data import DataLoader

    base = PROJECT_ROOT
    checkpoint_path = base / "storage" / "nn_models" / f"best_{args.model}.pt"

    if not checkpoint_path.exists():
        print(f"\nNo checkpoint found at {checkpoint_path}")
        print("Run training first: python -m nn.train --model mlp --epochs 50")
        return

    # Load dataset with same split
    ds = SpotFXDataset(
        profiles_dir=base / "storage" / "profiles",
        audio_shapes_dir=base / "storage" / "audio_shapes",
        training_profiles_file=base / "storage" / "training_profiles.json",
        training_profile_name="Trap/Reggaeton",
        verified_only=True,
    )
    _, val_ds = ds.train_val_split(val_fraction=0.2, seed=args.seed)
    val_loader = DataLoader(val_ds, batch_size=4, shuffle=False, collate_fn=collate_songs)

    # Load model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
    print(f"\nLoaded checkpoint: epoch {checkpoint['epoch']}, macro_f1={checkpoint['macro_f1']:.3f}")

    if args.model == "mlp":
        model = MLPBaseline()
    elif args.model == "transformer":
        model = TriggerTransformer()
    model.load_state_dict(checkpoint["model_state_dict"])
    model = model.to(device)
    model.eval()

    # Run evaluation
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for features, labels, genre_ids, masks, infos in val_loader:
            features = features.to(device)
            genre_ids = genre_ids.to(device)
            masks = masks.to(device)

            if args.model == "transformer":
                logits = model(features, genre_ids, padding_mask=masks)
            else:
                logits = model(features, genre_ids)
            preds = logits.argmax(dim=-1)

            for b in range(features.shape[0]):
                length = masks[b].sum().item()
                all_preds.append(preds[b, :length].cpu())
                all_labels.append(labels[b, :length])

    all_preds = torch.cat(all_preds)
    all_labels = torch.cat(all_labels)
    metrics = compute_metrics(all_preds, all_labels)

    print(f"\n{'='*60}")
    print(f" Evaluation Results -- {args.model} model")
    print(f" Val songs: {len(val_ds)}")
    print(f"{'='*60}\n")

    print_metrics(metrics)
    print_confusion_matrix(metrics["confusion"])

    # Per-song breakdown
    print(f"\n{'-'*60}")
    print(f" Per-Song Trigger Accuracy")
    print(f"{'-'*60}")

    song_idx = 0
    with torch.no_grad():
        for features, labels, genre_ids, masks, infos in val_loader:
            features = features.to(device)
            genre_ids = genre_ids.to(device)
            masks = masks.to(device)
            if args.model == "transformer":
                logits = model(features, genre_ids, padding_mask=masks)
            else:
                logits = model(features, genre_ids)
            preds = logits.argmax(dim=-1)

            for b in range(features.shape[0]):
                length = masks[b].sum().item()
                p = preds[b, :length].cpu()
                l = labels[b, :length]
                info = infos[b]

                # Count trigger predictions vs ground truth
                pred_triggers = (p > 0).sum().item()
                true_triggers = (l > 0).sum().item()
                correct_triggers = ((p > 0) & (p == l)).sum().item()

                print(
                    f"  {info['artist'][:20]:<20} {info['title'][:25]:<25} "
                    f"true={true_triggers:>3} pred={pred_triggers:>3} correct={correct_triggers:>3}"
                )
                song_idx += 1

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
