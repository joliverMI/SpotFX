"""
SpotFX — the Jukebox's data model (data/jukebox-plan/report.md, phase 1:
the program engine). services/jukebox/ is the code that runs it.

Two stores, each with one job (services/jukebox/store.py):

  ProgramConfig  storage/jukebox.json        HIS program settings: which
                                             playlist is the set, where the
                                             jukebox slots go, what happens
                                             when the set runs out. Only an
                                             edit writes it; a night never
                                             does.
  JukeboxNights  storage/jukebox_night.json  the current (or last) night —
                                             the set as read, the jukebox
                                             line, where the program is, the
                                             song committed to Spotify's
                                             queue, a bounded log — plus a
                                             short history of earlier nights.
                                             Churns on every song.

The code says `program`, never `setlist`: SpotFX already has a feature
called Set Lists (services/setlist_store.py, setlist_runtime.py: per-playlist
behaviour and timing overrides) and this must not clobber it. The UI says
"Set list" because that is his word.

Every model is `extra="ignore"` and every field is defaulted, so an older or
newer file always loads.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Where the jukebox slots go (report §5):
#   auto           a slot after every `every` set songs, `run` slots in a row
#   jukebox_first  the set only plays when nobody has a song waiting
#   manual         slots after the set songs he picked (`manual`)
SlotMode = Literal["auto", "jukebox_first", "manual"]
# When the set runs out (report §4, Program card):
#   again          play the set again (Spotify's repeat-context does the loop)
#   jukebox_only   only jukebox songs from then on, until the line is empty
#   end            the night ends with the last set song
RunOut = Literal["again", "jukebox_only", "end"]

LineState = Literal["queued", "committed", "playing", "played", "removed", "skipped"]
# What the read-back of Spotify's queue said about a commit:
#   next     it is the next thing Spotify will play
#   later    something else (his own "Add to queue") is ahead of it
#   missing  the queue read did not show it (re-read once, then re-queued)
#   unread   the queue could not be read; the POST itself was accepted
CommitCheck = Literal["", "next", "later", "missing", "unread"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ManualSlot(_Model):
    """A run of jukebox slots after one set song, keyed by the song's URI so
    it follows the song when the set is reordered (report §5: "click a set
    song to put a Jukebox slot after it; click a Jukebox slot to put another
    one right after it")."""
    after_uri: str
    count: int = Field(1, ge=1, le=3)

    @field_validator("after_uri")
    @classmethod
    def _uri(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.startswith("spotify:track:"):
            raise ValueError("a manual slot follows a set song: a spotify:track: URI")
        return v


class ProgramConfig(_Model):
    """His program settings (report §4, the Program card; §5, the editor).
    Defaults are the plan's: a jukebox slot after every set song, one at a
    time, and the set plays again when it runs out."""
    playlist: str = ""                         # a playlist link, URI or bare id
    mode: SlotMode = "auto"
    every: int = Field(1, ge=1, le=5)          # auto: a slot after every N set songs
    run: int = Field(1, ge=1, le=3)            # auto: K jukebox slots in a row
    manual: list[ManualSlot] = Field(default_factory=list)
    run_out: RunOut = "again"
    # How long before the song in front of a slot ends the next jukebox song
    # is sent into Spotify's queue (the study's option D: "~45 s before the
    # current song ends"). Earlier keeps fewer songs locked in place; later
    # risks the player having already picked its next track (crossfade).
    commit_lead_s: float = Field(45.0, ge=15.0, le=90.0)

    @field_validator("manual")
    @classmethod
    def _unique(cls, v: list[ManualSlot]) -> list[ManualSlot]:
        seen: set[str] = set()
        for slot in v:
            if slot.after_uri in seen:
                raise ValueError(f"two manual slot runs after {slot.after_uri}")
            seen.add(slot.after_uri)
        return v


class SetItem(_Model):
    """One song of the set, in playlist order (duplicates kept: the playlist's
    position is what Spotify plays by)."""
    uri: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0


class LineEntry(_Model):
    """A song in the jukebox line. `ready` is phase 4's absorb-then-queue
    hook; until then every song is ready (an un-learned song plays
    un-analysed and is learned as it plays)."""
    id: str
    uri: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    added_ms: int = 0
    added_by: str = "host"
    ready: bool = True
    state: LineState = "queued"
    # A committed song he removed: it is already in Spotify's queue and can't
    # be taken out, so it is SKIPPED the moment it starts (the repair path).
    doomed: bool = False
    committed_ms: Optional[int] = None
    commit_check: CommitCheck = ""
    played_ms: Optional[int] = None


class Cursor(_Model):
    """Where the program is. Owned by services/jukebox/program.py's pure
    transitions — the runner never edits a field of it by hand.

    `gap_left` is the number of jukebox slots still to come between the item
    playing now and the next set song; `owed` is slots a missed commit still
    owes the jukebox (served in the next gap, never lost)."""
    set_pos: int = -1          # index of the set song most recently started
    set_uri: str = ""          # its URI (re-anchors set_pos after a reorder)
    since_slot: int = 0        # set songs since the last slot boundary (auto)
    gap_left: int = 0
    owed: int = 0
    loops: int = 0             # times the set has wrapped around
    started: bool = False      # a set song has played tonight


class NowItem(_Model):
    """What is playing, as the program sees it."""
    kind: Literal["", "set", "jukebox", "skipping", "foreign"] = ""
    uri: str = ""
    title: str = ""
    set_index: Optional[int] = None
    entry_id: str = ""
    started_ms: Optional[int] = None


class PlayedItem(_Model):
    kind: Literal["set", "jukebox", "skipped", "foreign"]
    uri: str
    title: str = ""
    at_ms: int = 0
    set_index: Optional[int] = None
    entry_id: str = ""


class JukeboxNight(_Model):
    id: str = ""
    state: Literal["running", "ended", "refused"] = "running"
    started_ms: int = 0
    started_by: str = "press"
    ended_ms: Optional[int] = None
    end_reason: str = ""
    end_detail: str = ""
    # The engine started playback (a "Start" with play), so the night's own
    # ending may pause it; a night that only followed his playback never does.
    owns_playback: bool = False
    # The set index playback was told to start from (play nights only) — the
    # playing position until the cursor confirms it (`cursor.started`), used
    # by the "two or more ahead" reorder floor during the settle window after
    # start. None on a follow-mode night (it never chose a start song).
    start_index: Optional[int] = None
    device_name: str = ""
    playlist_id: str = ""
    playlist_uri: str = ""
    playlist_name: str = ""
    snapshot_id: str = ""
    set_items: list[SetItem] = Field(default_factory=list)
    line: list[LineEntry] = Field(default_factory=list)
    cursor: Cursor = Field(default_factory=Cursor)
    now: NowItem = Field(default_factory=NowItem)
    played: list[PlayedItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)


class JukeboxNights(_Model):
    night: Optional[JukeboxNight] = None
    history: list[dict] = Field(default_factory=list)   # briefs of earlier nights
