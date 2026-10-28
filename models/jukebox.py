"""
SpotFX — the Jukebox's data model (data/jukebox-plan/report.md, phase 1:
the program engine). services/jukebox/ is the code that runs it.

Five stores, each with one job (services/jukebox/store.py):

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
  ShowConfig     storage/jukebox_show.json   the show settings (phase 3.3):
                                             the last party-size preset, the
                                             new-phone approval switch, and
                                             every economy setting. Only an
                                             edit writes it
                                             (services/jukebox/show.py is
                                             the one validator).
  GuestLinkConfig/   storage/                the guest link's settings (N1:
  GuestLinkState     jukebox_guest_link.json  off until G4) and durable state
                                               (whether a Funnel this process
                                               opened is still open). One
                                               validator, services/jukebox/
                                               guest_link.apply_patch.
  GuestBook      storage/jukebox_guests.json  tonight's phones (a random id,
                                             the name each picked) and their
                                             votes (phase 2.1, services/
                                             jukebox/guests.py). One night's
                                             worth; a new night starts empty.

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
    # §4's "Play next may jump the set" (off): a song played next (a guest's
    # paid play next, the host's Play next) plays straight after the song
    # playing — ahead of the next set song — instead of at the next slot.
    next_jumps_set: bool = False

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
    position is what Spotify plays by). `image`/`thumb` are the album art's
    URLs on Spotify's own image servers (the guest page shows them unaltered
    — Spotify's attribution rule, report §2.3); empty when Spotify gave none."""
    uri: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    image: str = ""
    thumb: str = ""


class LineEntry(_Model):
    """A song in the jukebox line. `ready` is phase 4's absorb-then-queue
    hook; until then every song is ready (an un-learned song plays
    un-analysed and is learned as it plays)."""
    id: str
    uri: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    image: str = ""
    thumb: str = ""
    added_ms: int = 0
    added_by: str = "host"          # "host", or the phone id of the guest who added it
    # Fair order (phase 2.2): this was its adder's 1st, 2nd, ... song tonight;
    # a guest's new song goes ahead of every waiting song with a HIGHER
    # round. The host's own adds count as 1st songs.
    round: int = 1
    # The host held it: it keeps its place in the line but isn't sent to
    # Spotify (slots pass it) until he lets it go.
    held: bool = False
    explicit: bool = False
    # The lights already know it (its audio shape is captured): the guest
    # page's "Ready" badge. Not `ready`, which is phase 4's commit gate.
    known: bool = False
    # Places it has been pushed back tonight (free play's bumps, PR 2.3;
    # also a play next it was jumped past, PR 3.2) — whether by a down-bump
    # of its own, or as the song an up-bump or a play next stepped past:
    # never more than the show's `bump_down_max_places`.
    pushed_back: int = 0
    # Played next while "Play next may jump the set" was on: it plays ahead
    # of the next set song (services/jukebox/program.py's `project`) — what
    # was bought stands even if the setting is switched off afterwards.
    jump: bool = False
    # CREDITS MODE (PR 3.2): what its adder paid for it (locked when added)
    # and the ledger entry that paid it — a refund points at it; and
    # whether it has used its one "play next".
    paid: int = 0
    paid_seq: Optional[int] = None
    nexted: bool = False
    # the HOST took it out (Remove): a paid song is refunded (§1 rule 5)
    removed: bool = False
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
    """What is playing, as the program sees it. `skip_reason` says why a
    "skipping" item is being skipped: "removed" (a committed song he took
    out, the repair path), "votes" (the room voted it off, PR 2.3) or "paid"
    (a guest paid for the skip, or a chip-in pot filled — credits, PR 3.2)."""
    kind: Literal["", "set", "jukebox", "skipping", "foreign"] = ""
    uri: str = ""
    title: str = ""
    set_index: Optional[int] = None
    entry_id: str = ""
    started_ms: Optional[int] = None
    skip_reason: Literal["", "removed", "votes", "paid"] = ""


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
    # Songs that have started tonight (set, jukebox or off the set; never a
    # repair skip) — the clock a jail term runs on.
    plays: int = 0
    # THE JAIL (free play, PR 2.3): phone id -> the `plays` count at which
    # its time-out ends. While `plays` is below it, that guest's waiting
    # songs keep their places but are never sent (slots pass them). The
    # host's pardon removes the term.
    jail: dict[str, int] = Field(default_factory=dict)
    # The KIND each entry in `jail` is — "timeout" (free play, ends on its
    # own) or "breakout" (credits, ends only by paying `jail_fee` or a
    # pardon) — stored WITH the term so a later mode switch
    # (services/jukebox/night.py's `convert_jail_mode`, run from
    # services/jukebox/show.py's one validator path) can convert it
    # instead of every reader reinterpreting it by the CURRENT play_mode.
    # Reset (popped) whenever the matching `jail` entry ends or is pardoned.
    jail_kind: dict[str, str] = Field(default_factory=dict)
    # Songs the host has kept from skips tonight (their URIs): neither the
    # room's vote nor a paid skip touches them (report §12, "Skip griefing").
    no_skip: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)


class JukeboxNights(_Model):
    night: Optional[JukeboxNight] = None
    history: list[dict] = Field(default_factory=list)   # briefs of earlier nights


# ── the credits economy (phase 3) ────────────────────────────────────────────

class EconomyConfig(_Model):
    """Every credits-economy setting of the plan's §4, with the tuned
    starting values (report §0 and §3, re-tuned for two songs in line, D4)
    as defaults and §4's ranges as bounds. services/jukebox/economy.py is
    the only reader; the rulebook (§1) is what each one means.

    "Per 4 songs" / "per 4 minutes" prices are stored per ONE song / minute
    (0.25), the simulator's own shape, and rounded UP — so a single song
    behind already costs the +1."""
    # free credits
    start_credits: int = Field(8, ge=0, le=20)            # half at once, half later
    start_rest_after_min: float = Field(20.0, ge=0, le=60)
    topup_every_min: float = Field(45.0, ge=0, le=90)     # 0 = off, else 15-90
    topup_cap: int = Field(10, ge=6, le=40)               # top-ups pause at this many held
    qr_bonus: int = Field(5, ge=1, le=10)
    # earning
    vote_reward: int = Field(1, ge=0, le=3)
    adder_up_reward: int = Field(1, ge=0, le=3)
    tips: bool = True
    tip_unit: int = Field(1, ge=1, le=3)
    tip_max_per_song: int = Field(3, ge=1, le=10)
    gift_double_first: int = Field(5, ge=0, le=20)        # 0 = off
    # adding a song
    add_base: int = Field(4, ge=1, le=20)
    add_free_min: float = Field(15.0, ge=0, le=30)
    add_double_min: float = Field(15.0, ge=0, le=60)      # 0 = flat, else 10-60
    add_cap: int = Field(60, ge=10, le=99)
    long_over_min: float = Field(5.0, ge=4, le=8)
    long_extra_per_min: int = Field(1, ge=0, le=5)
    learn_first_extra: int = Field(1, ge=0, le=5)
    max_waiting: int = Field(2, ge=1, le=3)               # songs in line per guest (D4)
    fair_order: bool = True                               # 1st songs before 2nd songs
    # bumps
    bump_up_base: int = Field(2, ge=1, le=10)
    bump_up_per_behind: float = Field(0.25, ge=0, le=2)
    bump_down_base: int = Field(3, ge=1, le=10)
    bump_down_per_ahead: float = Field(0.25, ge=0, le=2)
    bump_down_max_places: int = Field(3, ge=0, le=10)
    # play next
    next_base: int = Field(8, ge=1, le=50)
    next_per_min: float = Field(0.25, ge=0, le=2)
    next_min_away_min: float = Field(10.0, ge=0, le=30)
    # skip
    skip_max: int = Field(40, ge=10, le=99)
    skip_half_min: float = Field(20.0, ge=10, le=60)
    skip_floor: int = Field(16, ge=4, le=40)
    skip_crowd: bool = True
    skip_down_pct: float = Field(15.0, ge=0, le=30)       # each net ▼ takes this % off
    skip_min: int = Field(4, ge=1, le=20)
    chip_in: bool = True
    skip_grace_s: float = Field(20.0, ge=0, le=60)
    # jail
    jail_net_downs: int = Field(5, ge=3, le=15)
    jail_scale: bool = True
    jail_fee: int = Field(10, ge=1, le=40)

    @field_validator("topup_every_min")
    @classmethod
    def _topup(cls, v: float) -> float:
        if v != 0 and not 15 <= v <= 90:
            raise ValueError("a top-up runs every 15-90 minutes, or 0 for off")
        return v

    @field_validator("add_double_min")
    @classmethod
    def _double(cls, v: float) -> float:
        if v != 0 and not 10 <= v <= 60:
            raise ValueError("the add price doubles every 10-60 minutes of wait, or 0 for flat")
        return v


# ── the show: presets and the economy's saved settings (phase 3.3) ───────────

Preset = Literal["small", "medium", "large"]


# Free play's "play next" (report §4's Free play card): the host's own button
# on the Guests tab's line, or nobody's.
FreePlayNext = Literal["host", "off"]
# The guest page's mode (report §6: "One switch on the Show settings page
# (Mode: Credits · Free play) hides every price, the credits chip and the
# Shop"). Credits ships as the default (the plan's §4 tuned values):
# nothing about a night changes to free play until he switches.
PlayMode = Literal["free", "credits"]

# Explicit songs (report §4, "Add a song"): not allowed (the default), allowed
# for +2 credits ("extra" — in free play simply allowed), or only after a set
# time of the night.
ExplicitRule = Literal["no", "extra", "after"]
_HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class ShowConfig(_Model):
    """The saved show settings: which party-size preset was last applied,
    whether new phones need his approval (the Large preset turns it on,
    report §3.5 and §12), every economy setting, and the guests' own rules
    (report §4's Show, Add a song and Guests cards: when the night ends and
    requests close, explicit songs, how many phones, renames, the word
    filter). Only an edit writes it (services/jukebox/show.py is the one
    validator). Times are house time (America/New_York), "HH:MM".
    `name` is §4's Show card "Name": what this set of settings is called —
    a show is SAVED under it (services/jukebox/shows.py)."""
    name: str = Field("Saturday party", min_length=1, max_length=60)
    preset: Optional[Preset] = None
    approve_new_phones: bool = False
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    night_ends: str = Field("00:00", pattern=_HHMM)          # the night window's end
    last_call_min: int = Field(20, ge=0, le=60)               # requests close this long before
    explicit: ExplicitRule = "no"
    explicit_after: str = Field("22:00", pattern=_HHMM)       # with explicit = "after"
    max_phones: int = Field(40, ge=5, le=100)
    renames_per_night: int = Field(3, ge=0, le=10)
    word_filter: bool = True
    # FREE PLAY (report §6 and §4's Free play card, PR 2.3): nothing costs
    # anything, and counts keep it fair. A song is skipped once it has
    # `free_skip_downs` ▼ AND that share (a whole percent, rounded) of its
    # votes; a guest may bump `free_bumps_per_hour` times in any hour; a
    # guest whose songs reach the jail's net ▼ (the economy's jail_net_downs,
    # rising with the crowd) sits out `free_jail_songs` songs (0 = no jail).
    free_skip_downs: int = Field(3, ge=2, le=10)
    free_skip_share: int = Field(67, ge=50, le=90)
    free_bumps_per_hour: int = Field(2, ge=0, le=10)
    free_play_next: FreePlayNext = "host"
    free_jail_songs: int = Field(5, ge=0, le=15)
    # credits or free play (the whole guest economy on or off, PR 3.2). The
    # plan's §4 default is Credits ("defaults are the tuned values"); free play
    # hides every price, the credits chip and the Shop (§6)
    play_mode: PlayMode = "credits"
    # the board (report §1 rule 11, §2.2, §4's Board card; D1 (a)): the
    # guests' Board tab shows "Tonight's top songs"; the PEOPLE boards are his
    # call and ship off (the "a game" flag); "On the TV" is the master's own
    # full-screen board page (services/jukebox/board.py)
    board_on: bool = True
    board_top_pickers: bool = False
    board_top_voters: bool = False
    board_most_generous: bool = False
    board_on_tv: bool = False


# ── the guest link (N1: services/jukebox/guest_link.py) ──────────────────────

# The ports Tailscale Funnel can publish (its docs; report §8.3) and the two
# the guest link must never reach: SpotFX's master (:8000) and SPECTRA (:8010).
FUNNEL_PORTS: tuple[int, ...] = (443, 8443, 10000)
MASTER_PORTS: tuple[int, ...] = (8000, 8010)
PublicPort = Literal[443, 8443, 10000]


class GuestLinkConfig(_Model):
    """How the guests' public HTTPS link is published (report §8.3, N1).
    `enabled` SHIPS OFF: until he turns it on (after G4 lets Funnel run on
    Serenity), a night never touches Tailscale."""
    enabled: bool = False
    # his tailnet name for Serenity ("serenity.<tailnet>.ts.net"); empty =
    # read from `tailscale status --json` when a night opens the link
    public_host: str = ""
    public_port: PublicPort = 8443
    guest_port: int = Field(8020, ge=1024, le=65535)    # the guest app (phase 2)

    @field_validator("guest_port")
    @classmethod
    def _not_master(cls, v: int) -> int:
        if v in MASTER_PORTS:
            raise ValueError(f"the guest link can never point at :{v} (the master and "
                             "SPECTRA are never published)")
        return v

    @field_validator("public_host")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip().rstrip(".").lower()
        if v and ("/" in v or ":" in v or " " in v):
            raise ValueError("public_host is a host name only, like serenity.<tailnet>.ts.net")
        return v


class GuestLinkAction(_Model):
    what: str                        # open | close | status | host
    ok: bool
    detail: str = ""
    at_ms: int = 0


class GuestLinkState(_Model):
    """What the link is doing, durable so a restart knows whether a Funnel
    it opened is still open. The party token is in every printed card, so
    it lives through a night and is replaced when the night ends."""
    token: str = ""
    token_created_ms: Optional[int] = None
    funnel_open: bool = False
    opened_ms: Optional[int] = None
    opened_for_night: str = ""
    host: str = ""                   # the host the open link was published on
    last_action: Optional[GuestLinkAction] = None
    self_test: Optional[dict] = None


# ── tonight's guests (phase 2.1: services/jukebox/guests.py) ─────────────────

class GuestPhone(_Model):
    """One phone at tonight's party. `id` is a random code the guest page
    keeps in a cookie and the phone's own storage — no account, no sign-in.
    `joined` turns true on "Let's go"; renames before that are free (the
    welcome screen's shuffle), after it they count against the night's
    limit."""
    id: str
    name: str = ""
    joined: bool = False
    created_ms: int = 0
    joined_ms: Optional[int] = None
    renames: int = 0
    # The host's controls (phase 2.2): a phone that joined while approval
    # was on waits for his yes; a blocked phone is out for the night; a
    # locked name can't be changed by the phone.
    approved: bool = True
    blocked: bool = False
    name_locked: bool = False
    # THE JAIL (PR 2.3). The term itself is the engine's (JukeboxNight.jail);
    # the book keeps the count. `jail_base` is the net ▼ on this phone's
    # songs when its last term ended — "your count starts again at 0" — and
    # `jail_open` says a term was begun and its end not yet counted.
    jail_open: bool = False
    jail_base: int = 0
    jails: int = 0
    jailed_ms: Optional[int] = None
    # when this phone bumped a song, for "N bumps an hour" (the last hour's only)
    bumps_ms: list[int] = Field(default_factory=list)
    # The host merged this phone into another (§4 "merge two phones": one
    # guest, two codes): it is that guest now — a request carrying this code
    # acts as them, and its page is handed their code on its next visit.
    merged_into: str = ""
    # THE REPORT'S "WANTS" (§3's "can afford it right away"): a guest's first
    # search after their last add is their first look at an add price; this
    # stays True until they add (services/jukebox/guests.py's `search`).
    want_open: bool = False


class NightSample(_Model):
    """One moment of the night as the post-party report measures it — the
    simulator's own series (services/jukebox/simulator.py), one per song
    start: credits held by the phones here, how long a song added at the
    back would wait, its add price there (a known 3.6-minute song), and how
    many are in a time-out and here. `held`/`price_back` are None in free
    play (nothing costs anything)."""
    t_ms: int
    held: Optional[int] = None
    back_wait_ms: Optional[int] = None
    price_back: Optional[int] = None
    jailed: int = 0
    present: int = 0


class WantCounts(_Model):
    """§3's "can afford it right away": each first look at an add price, and
    whether the balance then covered it — and the same for a guest who
    already had a song waiting (a 2nd song)."""
    wants: int = 0
    afford_now: int = 0
    wish_more: int = 0
    afford_more: int = 0


class SavedShow(_Model):
    """One saved show (§4: "a 'show' is a saved set of these"): the show
    settings, the program settings and whether the guest link is on — all of
    §4's cards — as they were when he saved it."""
    saved_ms: int = 0
    show: ShowConfig = Field(default_factory=ShowConfig)
    program: ProgramConfig = Field(default_factory=ProgramConfig)
    guest_link: bool = False


class SavedShows(_Model):
    shows: dict[str, SavedShow] = Field(default_factory=dict)


class BonusCode(_Model):
    """One printed bonus card's code (services/jukebox/bonus_codes.py): good
    for `qr_bonus` credits once, ever. `used_*` say when, on which night and
    by which guest's name it was used (never the phone's id)."""
    batch: str = ""
    created_ms: int = 0
    used_ms: Optional[int] = None
    used_night: str = ""
    used_name: str = ""


class BonusCodes(_Model):
    codes: dict[str, BonusCode] = Field(default_factory=dict)


class GuestBook(_Model):
    """One night's phones and votes. `votes` is keyed by the PLAY — the song
    and the moment it started (`<uri>@<started_ms>`) — so a song that plays
    twice is voted on twice; each play holds {phone id: +1 or -1}."""
    night_id: str = ""
    phones: dict[str, GuestPhone] = Field(default_factory=dict)
    votes: dict[str, dict[str, int]] = Field(default_factory=dict)
    # which guest added each voted play (play key -> phone id): the jail
    # counts the net ▼ on a guest's songs from it. Host and set songs are
    # never here (they never go to jail).
    play_by: dict[str, str] = Field(default_factory=dict)
    # CREDITS MODE (PR 3.2): the ledger is the truth for every credit
    # (services/jukebox/ledger.py); the book keeps only what decides WHEN to
    # write — the last top-up tick per phone, the plays whose Adder credits
    # are settled, and how each skip pot ended ("filled" or "refunded").
    credit_tick: dict[str, int] = Field(default_factory=dict)
    settled: list[str] = Field(default_factory=list)
    pots: dict[str, str] = Field(default_factory=dict)
    # the host's merges (§4): a retired phone's code -> the phone it joined
    merged: dict[str, str] = Field(default_factory=dict)
    # THE POST-PARTY REPORT'S RECORDS (§9 3.3, §12 risk 3): one sample per
    # song start (`sampled_plays` is the engine's `plays` count last sampled),
    # the guests' first looks at an add price, and adds turned away by code
    # ("too_late": it would start after the night ends).
    series: list[NightSample] = Field(default_factory=list)
    sampled_plays: int = -1
    wants: WantCounts = Field(default_factory=WantCounts)
    refused: dict[str, int] = Field(default_factory=dict)
