"""The shapes of the sung-label store and of one song's word matches (lyrics
plan step 3). spectra/services/sung_labels.py and lyric_matches.py are the
binding statements for what they mean."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MeaningKind = Literal["things", "moods", "places"]
MEANING_KINDS: tuple[MeaningKind, ...] = ("things", "moods", "places")
TargetKind = Literal["color_set", "effect"]
MatchSource = Literal["claude", "his"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LabelEdits(_Model):
    """His changes to a list that is otherwise computed: what he added, and
    which of the computed words he took out. Stored as deltas so a re-seed or
    a palette change can never undo them."""
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class MeaningList(LabelEdits):
    """One kind of meaning: Claude's latest draft, with his edits kept beside
    it so a re-draft replaces only `draft`."""
    draft: list[str] = Field(default_factory=list)


class Meanings(_Model):
    things: MeaningList = Field(default_factory=MeaningList)
    moods: MeaningList = Field(default_factory=MeaningList)
    places: MeaningList = Field(default_factory=MeaningList)


class ColorSetLabels(_Model):
    labels: LabelEdits = Field(default_factory=LabelEdits)
    meanings: Meanings = Field(default_factory=Meanings)
    drafted_ms: Optional[int] = None
    draft_model: Optional[str] = None


class EffectLabels(_Model):
    labels: LabelEdits = Field(default_factory=LabelEdits)


class SungLabelSettings(_Model):
    # OFF by default: nothing is sent to Claude until he turns this on or
    # presses a read button himself.
    auto_read: bool = False
    # Below this confidence a guess is no match at all (lyric_matches.py's
    # own docstring). A first guess, his to tune — 0.6 to match that
    # module's own default; the two are never cross-imported (models stay
    # pure), so keep them in sync by hand if either changes.
    weak_match_threshold: float = Field(0.6, ge=0.0, le=1.0)


class SungLabelStore(_Model):
    schema_version: int = 1
    settings: SungLabelSettings = Field(default_factory=SungLabelSettings)
    # When the label list last changed by his hand or a draft; the automatic
    # reader waits for this to be quiet.
    labels_changed_ms: int = 0
    color_sets: dict[str, ColorSetLabels] = Field(default_factory=dict)
    effects: dict[str, EffectLabels] = Field(default_factory=dict)


class WordSpan(_Model):
    """Which words a match sits on. The times are never stored: they belong
    to the capture and come from the word timeline at read time, so a
    recapture cannot leave a stale one behind. `norm` is what lets the span be
    found again if the word positions ever shift."""
    first_word: int = Field(ge=0)
    last_word: int = Field(ge=0)
    norm: list[str]
    phrase: str


class ClaudeGuess(WordSpan):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    why: str = ""


class TargetRef(_Model):
    kind: TargetKind
    id: str


class HisMatch(WordSpan):
    id: str
    targets: list[TargetRef] = Field(default_factory=list)
    label: str = ""
    added_ms: int = 0


class DeletedGuess(_Model):
    first_word: int
    last_word: int
    norm: list[str]
    label: str


class Reading(_Model):
    """One reading by Claude. Replaced whole by the next one."""
    at_ms: int
    model: str
    backend: str
    labels_hash: str
    words_hash: str
    matches: list[ClaudeGuess] = Field(default_factory=list)
    # What was thrown away, by reason: below the weak-match line, or naming a
    # line, phrase or label that is not there.
    n_weak: int = 0
    refused: dict[str, int] = Field(default_factory=dict)


class SongMatches(_Model):
    schema_version: int = 1
    uri: str
    reading: Optional[Reading] = None
    his: list[HisMatch] = Field(default_factory=list)
    deleted: list[DeletedGuess] = Field(default_factory=list)
