"""
SpotFX NN — Loss functions.

Focal Loss for handling the extreme class imbalance in trigger prediction.
Most beats are no_trigger (~90%), so standard cross-entropy would learn to
always predict no_trigger. Focal loss down-weights easy (confident) examples
and focuses learning on hard cases.

Reference: Lin et al., "Focal Loss for Dense Object Detection" (2017)
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from nn.dataset import ROLE_NAMES, NUM_CLASSES


class FocalLoss(nn.Module):
    """
    Focal Loss with per-class weighting.

    loss(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)

    Args:
        alpha: per-class weights tensor of shape (num_classes,).
               Higher weight = more importance for that class.
        gamma: focusing parameter. 0 = standard CE, 2 = strong focus on hard examples.
        ignore_index: label value to ignore (used for padded beats).
    """

    def __init__(
        self,
        alpha: torch.Tensor | None = None,
        gamma: float = 2.0,
        ignore_index: int = -1,
    ):
        super().__init__()
        self.gamma = gamma
        self.ignore_index = ignore_index
        if alpha is not None:
            self.register_buffer("alpha", alpha.float())
        else:
            self.alpha = None

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        Args:
            logits: (N, C) raw model outputs
            targets: (N,) class indices (may contain ignore_index)

        Returns:
            Scalar loss.
        """
        # Mask out ignored indices
        mask = targets != self.ignore_index
        if not mask.any():
            return torch.tensor(0.0, device=logits.device, requires_grad=True)

        logits = logits[mask]
        targets = targets[mask]

        # Standard cross-entropy (per-sample, unreduced)
        log_probs = F.log_softmax(logits, dim=-1)
        probs = log_probs.exp()

        # Gather the probability of the correct class
        targets_onehot = F.one_hot(targets, num_classes=logits.shape[-1]).float()
        p_t = (probs * targets_onehot).sum(dim=-1)       # (N,)
        log_p_t = (log_probs * targets_onehot).sum(dim=-1)  # (N,)

        # Focal modulation
        focal_weight = (1.0 - p_t) ** self.gamma  # (N,)

        # Per-class alpha weighting
        if self.alpha is not None:
            alpha_t = self.alpha[targets]  # (N,)
            focal_weight = focal_weight * alpha_t

        loss = -focal_weight * log_p_t
        return loss.mean()


def compute_class_weights(label_counts: dict[str, int]) -> torch.Tensor:
    """
    Compute class weights that balance trigger vs no_trigger.

    Strategy:
      - no_trigger gets weight 0.1 (still contributes, but doesn't dominate)
      - trigger classes get inverse-frequency weights relative to each other
      - zero-count classes get weight 0
    """
    counts = torch.tensor(
        [label_counts.get(name, 0) for name in ROLE_NAMES],
        dtype=torch.float,
    )

    weights = torch.zeros(NUM_CLASSES)

    # no_trigger: low fixed weight (still contributes to learning "not a trigger")
    weights[0] = 0.1

    # Trigger classes: inverse frequency relative to the most common trigger class
    trigger_counts = counts[1:]
    max_trigger_count = trigger_counts[trigger_counts > 0].max() if (trigger_counts > 0).any() else 1.0

    for i in range(1, NUM_CLASSES):
        if counts[i] > 0:
            # Most common trigger class gets weight 1.0, rarer ones get higher
            weights[i] = max_trigger_count / counts[i]

    return weights
