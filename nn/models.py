"""
SpotFX NN -- Model architectures.

Phase 2: MLPBaseline -- processes each beat independently (no context).
Phase 3: TriggerTransformer -- self-attention gives each beat full song context.

Both models follow the same interface:
    forward(features, genre_ids) -> logits (batch, seq_len, num_classes)
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn

from nn.dataset import FEATURES_PER_BEAT, NUM_CLASSES as DEFAULT_NUM_CLASSES
from nn.genre_map import NUM_GENRES


class MLPBaseline(nn.Module):
    """
    Simple feed-forward network that classifies each beat independently.

    No context window -- each beat's prediction is based solely on its own
    18 features + 8-dim genre embedding = 26 input dims.

    This serves as a baseline to measure how much context (transformer)
    improves predictions.
    """

    def __init__(
        self,
        hidden_dim: int = 64,
        genre_embed_dim: int = 8,
        dropout: float = 0.3,
        num_classes: int = DEFAULT_NUM_CLASSES,
    ):
        super().__init__()
        self.genre_embed = nn.Embedding(NUM_GENRES, genre_embed_dim)
        input_dim = FEATURES_PER_BEAT + genre_embed_dim  # 18 + 8 = 26

        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(
        self,
        features: torch.Tensor,     # (batch, seq_len, 18)
        genre_ids: torch.Tensor,     # (batch,)
    ) -> torch.Tensor:               # (batch, seq_len, num_classes)
        batch, seq_len, _ = features.shape

        # Expand genre embedding to every beat: (batch, 8) -> (batch, seq_len, 8)
        genre_emb = self.genre_embed(genre_ids)
        genre_emb = genre_emb.unsqueeze(1).expand(-1, seq_len, -1)

        # Concatenate: (batch, seq_len, 26)
        x = torch.cat([features, genre_emb], dim=-1)

        # MLP processes each beat independently
        logits = self.net(x)
        return logits


# ---------------------------------------------------------------------------
# Sinusoidal Positional Encoding
# ---------------------------------------------------------------------------
# This tells the transformer WHERE each beat is in the sequence.
# Without it, self-attention is permutation-invariant (beat order wouldn't matter).
# The encoding uses sin/cos waves at different frequencies so each position
# gets a unique signature.  The transformer can then learn patterns like
# "triggers tend to appear near section boundaries" or "after 8 quiet beats".

class SinusoidalPositionalEncoding(nn.Module):
    """
    Adds a fixed sinusoidal position signal to the input embeddings.

    For each position p and dimension i:
      PE(p, 2i)   = sin(p / 10000^(2i/d_model))
      PE(p, 2i+1) = cos(p / 10000^(2i/d_model))

    This is the same encoding used in "Attention Is All You Need" (Vaswani 2017).
    """

    def __init__(self, d_model: int, max_len: int = 800):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float)
            * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        # Register as buffer (not a parameter -- no gradients, moves with .to(device))
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, d_model)
        return x + self.pe[:, :x.size(1), :]


# ---------------------------------------------------------------------------
# Transformer Trigger Model
# ---------------------------------------------------------------------------

class TriggerTransformer(nn.Module):
    """
    Small transformer encoder for beat-level trigger classification.

    How it works:
      1. Each beat's 18 features + 8-dim genre embedding = 26 dims
      2. A linear layer projects 26 -> d_model (64)
      3. Sinusoidal positional encoding is added (so the model knows beat order)
      4. N transformer encoder layers process the sequence with self-attention
         - Each beat can "look at" every other beat in the song
         - This lets the model learn contrast patterns (quiet->loud = drop)
         - Multi-head attention (4 heads) lets it attend to different patterns
      5. A final linear layer maps d_model -> num_classes per beat

    ~120K parameters -- tiny enough to run on a Raspberry Pi 5 in <150ms.
    """

    def __init__(
        self,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 4,
        dim_feedforward: int = 128,
        dropout: float = 0.2,
        genre_embed_dim: int = 8,
        num_classes: int = DEFAULT_NUM_CLASSES,
    ):
        super().__init__()
        self.d_model = d_model

        # Genre embedding (same as MLP)
        self.genre_embed = nn.Embedding(NUM_GENRES, genre_embed_dim)

        # Project input features to transformer dimension
        input_dim = FEATURES_PER_BEAT + genre_embed_dim  # 18 + 8 = 26
        self.input_proj = nn.Linear(input_dim, d_model)

        # Positional encoding (fixed sinusoidal)
        self.pos_enc = SinusoidalPositionalEncoding(d_model, max_len=1200)

        # Transformer encoder layers
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,     # (batch, seq, feature) format
            activation="gelu",    # smoother than ReLU, often better for transformers
        )
        self.encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=num_layers,
        )

        # Classification head: one prediction per beat
        self.classifier = nn.Linear(d_model, num_classes)

        # Dropout before classifier
        self.pre_cls_dropout = nn.Dropout(dropout)

    def forward(
        self,
        features: torch.Tensor,     # (batch, seq_len, 18)
        genre_ids: torch.Tensor,     # (batch,)
        padding_mask: torch.Tensor | None = None,  # (batch, seq_len) True=real, False=pad
    ) -> torch.Tensor:               # (batch, seq_len, num_classes)
        batch, seq_len, _ = features.shape

        # Genre embedding -> expand to every beat
        genre_emb = self.genre_embed(genre_ids)
        genre_emb = genre_emb.unsqueeze(1).expand(-1, seq_len, -1)

        # Concatenate features + genre: (batch, seq_len, 26)
        x = torch.cat([features, genre_emb], dim=-1)

        # Project to d_model: (batch, seq_len, 64)
        x = self.input_proj(x)

        # Add positional encoding
        x = self.pos_enc(x)

        # Build key_padding_mask for transformer
        # PyTorch transformer expects True=IGNORE, False=attend (opposite of our mask)
        src_key_padding_mask = None
        if padding_mask is not None:
            src_key_padding_mask = ~padding_mask  # invert: True=pad=ignore

        # Transformer encoder: self-attention across all beats
        x = self.encoder(x, src_key_padding_mask=src_key_padding_mask)

        # Classify each beat
        x = self.pre_cls_dropout(x)
        logits = self.classifier(x)  # (batch, seq_len, num_classes)

        return logits
