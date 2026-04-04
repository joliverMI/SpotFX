"""
SpotFX NN -- Training loop.

Run: python -m nn.train --model transformer --epochs 100 --lr 0.001 --no-chunking --binary
     python -m nn.train --model transformer --epochs 100 --lr 0.001 --no-chunking --binary --all-genres
     python -m nn.train --model transformer --epochs 100 --lr 0.001 --no-chunking --binary --all-genres --kfold 5
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR, LinearLR, SequentialLR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn.dataset import (
    SpotFXDataset, SpotFXSubset, ChunkedSpotFXDataset, collate_songs,
    NUM_CLASSES, ROLE_NAMES,
)
from nn.losses import FocalLoss, compute_class_weights
from nn.models import MLPBaseline, TriggerTransformer
from nn.evaluate import compute_metrics, print_metrics

BINARY_NAMES = ["no_trigger", "trigger"]


def _collapse_binary(labels: torch.Tensor, exclude_classes: set[int] | None = None) -> torch.Tensor:
    """Collapse multi-class labels to binary: 0=no_trigger, 1=trigger. Preserves -1 padding."""
    out = labels.clone()
    if exclude_classes:
        for cls in exclude_classes:
            out[out == cls] = 0
    out[out > 0] = 1
    return out


def _build_model(model_type: str, num_classes: int, device: torch.device):
    """Build a fresh model instance."""
    if model_type == "mlp":
        model = MLPBaseline(hidden_dim=64, genre_embed_dim=8, dropout=0.3, num_classes=num_classes)
    elif model_type == "transformer":
        model = TriggerTransformer(
            d_model=64, nhead=4, num_layers=4, dim_feedforward=128,
            dropout=0.2, genre_embed_dim=8, num_classes=num_classes,
        )
    return model.to(device)


def _eval_binary(all_preds: torch.Tensor, all_labels: torch.Tensor) -> dict:
    """Compute binary trigger F1."""
    tp = ((all_preds == 1) & (all_labels == 1)).sum().item()
    fp = ((all_preds == 1) & (all_labels == 0)).sum().item()
    fn = ((all_preds == 0) & (all_labels == 1)).sum().item()
    tn = ((all_preds == 0) & (all_labels == 0)).sum().item()
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}


def train_fold(
    train_ds: SpotFXSubset,
    val_ds: SpotFXSubset,
    *,
    model_type: str,
    epochs: int,
    lr: float,
    batch_size: int,
    binary: bool,
    exclude_classes: set[int],
    no_chunking: bool,
    chunk_size: int,
    jitter: float,
    checkpoint_path: Path | None,
    verbose: bool = True,
) -> float:
    """Train one fold. Returns best val F1."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    num_classes = 2 if binary else NUM_CLASSES

    # Chunking
    if no_chunking or model_type == "mlp":
        train_data = train_ds
    else:
        stride = chunk_size // 2
        train_data = ChunkedSpotFXDataset(train_ds, window_size=chunk_size,
                                           stride=stride, jitter_std=jitter)
        if verbose:
            print(f"  Chunked: {len(train_data)} windows from {len(train_ds)} songs")

    train_loader = DataLoader(train_data, batch_size=batch_size, shuffle=True, collate_fn=collate_songs)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, collate_fn=collate_songs)

    # Class weights
    train_counts = train_data.label_counts()
    if binary:
        no_trig_count = train_counts["no_trigger"]
        trig_count = sum(v for k, v in train_counts.items() if k != "no_trigger")
        total = no_trig_count + trig_count
        w_no = total / (2 * max(no_trig_count, 1))
        w_trig = total / (2 * max(trig_count, 1))
        class_weights = torch.tensor([w_no, w_trig], dtype=torch.float32).to(device)
    else:
        class_weights = compute_class_weights(train_counts).to(device)

    # Model + optimizer + scheduler
    model = _build_model(model_type, num_classes, device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = FocalLoss(alpha=class_weights, gamma=2.0, ignore_index=-1)

    warmup_epochs = min(5, epochs // 5)
    warmup_sched = LinearLR(optimizer, start_factor=0.1, total_iters=warmup_epochs)
    cosine_sched = CosineAnnealingLR(optimizer, T_max=max(epochs - warmup_epochs, 1), eta_min=1e-6)
    scheduler = SequentialLR(optimizer, [warmup_sched, cosine_sched], milestones=[warmup_epochs])

    best_val_f1 = 0.0

    for epoch in range(1, epochs + 1):
        # Train
        model.train()
        train_loss = 0.0
        train_batches = 0

        for features, labels, genre_ids, masks, infos in train_loader:
            features, labels = features.to(device), labels.to(device)
            genre_ids, masks = genre_ids.to(device), masks.to(device)

            if binary:
                labels = _collapse_binary(labels, exclude_classes)

            if model_type == "transformer":
                logits = model(features, genre_ids, padding_mask=masks)
            else:
                logits = model(features, genre_ids)

            B, T, C = logits.shape
            flat_logits = logits.reshape(B * T, C)
            flat_labels = labels.reshape(B * T)
            flat_labels[~masks.reshape(B * T)] = -1

            loss = criterion(flat_logits, flat_labels)
            optimizer.zero_grad()
            loss.backward()
            if model_type == "transformer":
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            train_loss += loss.item()
            train_batches += 1

        avg_loss = train_loss / max(train_batches, 1)
        scheduler.step()
        current_lr = optimizer.param_groups[0]["lr"]

        # Validate
        model.eval()
        all_preds, all_labels_list = [], []
        with torch.no_grad():
            for features, labels, genre_ids, masks, infos in val_loader:
                features = features.to(device)
                genre_ids, masks = genre_ids.to(device), masks.to(device)

                if model_type == "transformer":
                    logits = model(features, genre_ids, padding_mask=masks)
                else:
                    logits = model(features, genre_ids)
                preds = logits.argmax(dim=-1)

                if binary:
                    labels = _collapse_binary(labels, exclude_classes)

                for b in range(features.shape[0]):
                    length = masks[b].sum().item()
                    all_preds.append(preds[b, :length].cpu())
                    all_labels_list.append(labels[b, :length])

        all_preds_t = torch.cat(all_preds)
        all_labels_t = torch.cat(all_labels_list)

        if binary:
            bm = _eval_binary(all_preds_t, all_labels_t)
            macro_f1 = bm["f1"]
        else:
            metrics = compute_metrics(all_preds_t, all_labels_t)
            trigger_f1s = [metrics["per_class"][n]["f1"] for n in ROLE_NAMES[1:]
                           if metrics["per_class"][n]["support"] > 0]
            macro_f1 = sum(trigger_f1s) / max(len(trigger_f1s), 1)

        star = ""
        if macro_f1 > best_val_f1:
            best_val_f1 = macro_f1
            if checkpoint_path:
                torch.save({
                    "epoch": epoch, "model_state_dict": model.state_dict(),
                    "macro_f1": macro_f1, "model_type": model_type, "binary": binary,
                }, checkpoint_path)
            star = " *"

        if verbose:
            print(f"  Epoch {epoch:>3}/{epochs}  loss={avg_loss:.4f}  val_F1={macro_f1:.3f}  lr={current_lr:.2e}{star}")

            if epoch % 25 == 0 or epoch == epochs:
                if binary:
                    bm = _eval_binary(all_preds_t, all_labels_t)
                    print(f"\n    P={bm['precision']:.3f} R={bm['recall']:.3f} F1={bm['f1']:.3f} "
                          f"TP={bm['tp']} FP={bm['fp']} FN={bm['fn']} TN={bm['tn']}\n")
                else:
                    print()
                    print_metrics(metrics)
                    print()

    return best_val_f1


def main():
    parser = argparse.ArgumentParser(description="Train SpotFX NN trigger model")
    parser.add_argument("--model", default="mlp", choices=["mlp", "transformer"])
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--chunk-size", type=int, default=128)
    parser.add_argument("--no-chunking", action="store_true")
    parser.add_argument("--jitter", type=float, default=0.0)
    parser.add_argument("--binary", action="store_true", help="Binary: trigger vs no_trigger")
    parser.add_argument("--no-flare", action="store_true", help="Exclude flare triggers")
    parser.add_argument("--all-genres", action="store_true", help="Use all genres (not just Latin)")
    parser.add_argument("--kfold", type=int, default=0, help="K-fold cross-validation (0=disabled)")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nDevice: {device}")

    exclude_classes: set[int] = set()
    if args.no_flare:
        exclude_classes.add(ROLE_NAMES.index("flare"))
        print("Excluding flare triggers")
    if args.binary:
        print("Binary mode: trigger vs no_trigger")

    # Load dataset
    base = PROJECT_ROOT
    ds = SpotFXDataset(
        profiles_dir=base / "storage" / "profiles",
        audio_shapes_dir=base / "storage" / "audio_shapes",
        training_profiles_file=base / "storage" / "training_profiles.json",
        training_profile_name="Trap/Reggaeton",
        verified_only=True,
        all_genres=args.all_genres,
    )

    print(f"\nLoaded {len(ds)} songs" + (" (all genres)" if args.all_genres else " (Latin only)"))

    if len(ds) < 2:
        print("Need at least 2 songs. Verify more songs.")
        return

    checkpoint_dir = base / "storage" / "nn_models"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    if args.kfold > 1:
        # -- K-fold cross-validation --
        indices = list(range(len(ds)))
        rng = random.Random(args.seed)
        rng.shuffle(indices)

        fold_size = len(indices) // args.kfold
        fold_f1s = []

        print(f"\n{'='*70}")
        print(f" {args.kfold}-Fold Cross-Validation -- {args.epochs} epochs, lr={args.lr}")
        print(f" {len(ds)} songs, ~{fold_size} per fold")
        print(f"{'='*70}")

        for fold in range(args.kfold):
            start = fold * fold_size
            end = start + fold_size if fold < args.kfold - 1 else len(indices)
            val_idx = indices[start:end]
            train_idx = indices[:start] + indices[end:]

            train_sub = SpotFXSubset(ds, train_idx)
            val_sub = SpotFXSubset(ds, val_idx)

            print(f"\n--- Fold {fold+1}/{args.kfold}: train={len(train_sub)}, val={len(val_sub)} ---")

            best_f1 = train_fold(
                train_sub, val_sub,
                model_type=args.model, epochs=args.epochs, lr=args.lr,
                batch_size=args.batch_size, binary=args.binary,
                exclude_classes=exclude_classes, no_chunking=args.no_chunking,
                chunk_size=args.chunk_size, jitter=args.jitter,
                checkpoint_path=None,  # don't save per-fold
                verbose=True,
            )
            fold_f1s.append(best_f1)
            print(f"  Fold {fold+1} best F1: {best_f1:.3f}")

        avg_f1 = sum(fold_f1s) / len(fold_f1s)
        print(f"\n{'='*70}")
        print(f" K-Fold Results:")
        for i, f1 in enumerate(fold_f1s):
            print(f"  Fold {i+1}: {f1:.3f}")
        print(f"  Average: {avg_f1:.3f}")
        print(f"  Min:     {min(fold_f1s):.3f}")
        print(f"  Max:     {max(fold_f1s):.3f}")
        print(f"{'='*70}\n")

    else:
        # -- Single train/val split --
        train_ds, val_ds = ds.train_val_split(val_fraction=0.2, seed=args.seed)
        print(f"Train: {len(train_ds)} songs, Val: {len(val_ds)} songs")

        suffix = f"{'binary_' if args.binary else ''}{args.model}"
        checkpoint_path = checkpoint_dir / f"best_{suffix}.pt"

        print(f"\n{'='*70}")
        print(f" Training -- {args.epochs} epochs, lr={args.lr}, batch_size={args.batch_size}")
        if args.binary:
            print(f" Mode: BINARY")
        print(f"{'='*70}")

        best_f1 = train_fold(
            train_ds, val_ds,
            model_type=args.model, epochs=args.epochs, lr=args.lr,
            batch_size=args.batch_size, binary=args.binary,
            exclude_classes=exclude_classes, no_chunking=args.no_chunking,
            chunk_size=args.chunk_size, jitter=args.jitter,
            checkpoint_path=checkpoint_path,
        )

        print(f"\n{'='*70}")
        print(f" Training complete! Best val F1: {best_f1:.3f}")
        print(f" Checkpoint: {checkpoint_path}")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
