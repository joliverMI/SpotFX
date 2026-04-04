# SpotFX NN — Status Summary

## What Was Built (Phases 1–4)

### Phase 1: Data Pipeline (`nn/dataset.py`)
- `SpotFXDataset` loads verified song profiles + librosa audio features, builds per-beat feature vectors (28 features: audio scores, is_downbeat, beat position, section one-hot, section aggregates)
- URI-based matching between profiles and librosa files (not filename-based, due to Windows truncation)
- `SpotFXSubset` for train/val splits, `collate_songs` for variable-length padding
- `train_val_split()` with configurable seed and val fraction
- 9 trigger classes: no_trigger, beat_start, song_end, drop, lull, charge, quiet, scene_fill, flare

### Phase 2: MLP Baseline (`nn/models.py`)
- `MLPBaseline` — per-beat MLP with genre embedding. Proof of concept only; no sequence context.

### Phase 3: Transformer (`nn/models.py`)
- `TriggerTransformer` — 4-layer, 4-head, d_model=64, 136K params
- Sinusoidal positional encoding (max_len=1200)
- Genre embedding concatenated to features
- Padding mask support for variable-length songs

### Phase 4: Augmentation + Training Improvements
- **Sliding-window chunking** (`ChunkedSpotFXDataset`): window=128 beats, stride=64, optional Gaussian jitter on audio features
- **LR scheduling**: 5-epoch linear warmup (10%→100%) then cosine annealing to 1e-6
- **Focal loss** with gamma=2.0 and inverse-frequency class weights
- **Binary mode** (`--binary`): collapses all trigger types to trigger vs no_trigger
- **All-genres mode** (`--all-genres`): uses EDM, Rock, etc. alongside Latin, each with its own training profile event mapping
- **K-fold CV** (`--kfold N`): cross-validation for more reliable metrics

## Experiment Results (as of 2026-03-22)

| Experiment | Songs | Best Val F1 |
|---|---|---|
| Multi-class, 15 Latin, no aug | 15 | 0.046 |
| Multi-class, 15 Latin, chunking+jitter+LR | 15 | 0.052 |
| Binary, 15 Latin, no chunking | 15 | 0.120 |
| Binary, 20 Latin, no chunking | 20 | 0.151 |
| Binary, 20 Latin, no-flare | 20 | 0.064 |
| Binary, 30 all-genres, 5-fold CV | 30 | **0.179 avg** (0.150–0.214) |

## Key Findings

1. **More data is the #1 lever.** Every batch of new songs improved F1 significantly. Model architecture and augmentation made marginal differences.
2. **Binary mode >> multi-class** with small data. 9-class F1 was near zero; binary (trigger vs no_trigger) is learnable.
3. **All genres help.** Despite different musical styles and trigger mappings, adding EDM/Rock songs improved results over Latin-only.
4. **Don't remove flares.** Flares are ~60-70% of all trigger beats. Excluding them (--no-flare) collapsed F1 to 0.064.
5. **Class imbalance is extreme.** ~94% of beats are no_trigger. Focal loss + class weights help but don't solve the fundamental data scarcity.
6. **K-fold gives reliable estimates.** Single train/val split variance is high with <30 songs.

## What To Do Next (When More Songs Are Verified)

### Immediate: Retrain and Compare
```bash
# Run 5-fold CV with all genres, binary mode
python -m nn.train --model transformer --epochs 100 --lr 0.001 --no-chunking --binary --all-genres --kfold 5
```
Compare average F1 to 0.179 (the current best with 30 songs).

### When F1 Reaches ~0.3–0.4: Try Multi-Class Again
Binary mode was a workaround for insufficient data. Once binary F1 is solid, switch back:
```bash
python -m nn.train --model transformer --epochs 100 --lr 0.001 --no-chunking --all-genres --kfold 5
```

### Other Angles to Explore (Roughly Prioritized)
1. **Feature engineering** — delta features (beat-to-beat change in audio scores), distance to nearest section boundary, rolling window stats. Could help detect musical transitions.
2. **Re-enable chunking** — with more data, chunking (5x multiplier) may actually help rather than just amplifying noise.
3. **Simpler model** — 2-layer transformer or binary MLP might generalize better until dataset is larger.
4. **Threshold tuning** — instead of argmax, tune the trigger probability threshold to trade precision for recall.

## File Map

| File | Purpose |
|---|---|
| `nn/dataset.py` | Dataset classes, feature extraction, collation |
| `nn/models.py` | MLPBaseline, TriggerTransformer |
| `nn/train.py` | Training loop, binary/multi-class, k-fold, augmentation |
| `nn/evaluate.py` | Per-class metrics, confusion matrix |
| `nn/losses.py` | FocalLoss, class weight computation |
| `nn/genre_map.py` | Genre string → macro genre ID (EDM=0, Latin=1, Rock=2, Pop=3, HipHop=4, Other=5) |
| `nn/list_songs.py` | Lists songs and their training readiness |
| `.vscode/tasks.json` | VS Code tasks for training, evaluation, listing |

## VS Code Tasks
- **NN: Train Transformer** — Phase 4 args (150 epochs, chunking, jitter)
- **NN: Train Transformer (no aug)** — No chunking/jitter for comparison
- **NN: Evaluate Transformer** — Per-class breakdown + confusion matrix
- **NN: List Latin Songs** — Shows song readiness status

## Training Profile Setup
Each genre uses a different training profile (in `storage/training_profiles.json`) that maps LedFX event IDs to structural roles (drop, lull, charge, etc.). When adding a new genre, a training profile must exist for it or those songs will be skipped in all-genres mode.

Current profiles: **Trap/Reggaeton** (Latin), **EDM/House** (EDM).
