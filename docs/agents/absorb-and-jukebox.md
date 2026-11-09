# Absorb Music and the Jukebox

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## ABSORB MUSIC — unattended capture of a linked playlist (phases 1-5)

Plan: `/home/javi/fleet-spotfx/data/absorb-music-plan/report.md` (his six
asks, his five answers in §0, phases in §12). **`services/absorb.py`'s
module docstring is the binding statement** for the runner and
**`services/absorb_silence.py`'s for the house guard** and
**`services/absorb_schedule.py`'s for the schedule**;
`services/absorb_bar.py` owns "already captured", `services/capture_watch.py`
the mid-song detectors, `models/absorb.py` the four stores. Phase 1:

- **NOTHING STARTS ON ITS OWN UNLESS HE SCHEDULED IT.** `AbsorbConfig.
  enabled` (the schedule's switch) ships False and `windows` ships empty; a
  window opens on its own only when BOTH are set (phase 3, below), otherwise
  only on a press, and a refusal is a RECORDED run answered 200. Do not add
  an "allow audible" switch.
- **ABSORB'S QUEUE, NOT SPOTIFY'S.** It sends a window of URIs (never a
  playlist context, never the queue API) and re-sends only as a song STARTS,
  so a correction cuts the head of a song that will be replayed, never the
  tail of a capture. "Requeue after the next song" is `_requeue` after the
  attempt's `follower`.
- **TWO SEAMS ON `audio_shape_service`, owned by the runner**: `force_uris`
  (per-song force-recapture, consumed at capture start; the global
  `recapture_active` counter is untouched) and `preroll_uris` (a VOUCHED
  head-start: on_track_change only learns of a track boundary from a running
  capture, so the first song after anything that did not capture — the
  warm-up, a cold open — lost its head; the report's D14 warm-up does nothing
  without it). The runner empties only what it put there.
- **ONE `CaptureOutcome` PER CAPTURE** (`outcome_listeners`), published at
  every terminal point of `_finalize_capture` — for a first-time capture only
  after its WAV + librosa — and carrying `capture_started_at`, which is how a
  late outcome from an abandoned capture is never read as the current one.
  A new terminal path in finalize must publish too. "ok" is not "has its
  head": the runner applies the bar to the file again (§8.4, `head_missed`).
- **THE SIDECAR HAS NO HEAD FIELD.** The plan expected phase 0 to add
  `first_timestamp_ms`; it did not. `absorb_bar.read_facts` reads the field
  when present and the npz's own first timestamp otherwise.
- **HIS PAUSE IS NOT AN ATTEMPT.** It stops the capture
  (`on_target_device` needs `is_playing`), so that outcome is an
  interruption, never an attempt.

Phase 2 — silence, the Order 27 gate, stand-down, restore (2026-10-20):

- **SILENCE IS `snap_volume` → 0, NEVER THE CAPTURE CLIENT.** The capture
  taps a null sink only `Effects Host` writes into, so that client stays
  untouched; Spotify volume 0 would record silence. The write goes through
  SPECTRA's narrow `/spectra/api/house-audio` (`spectra/api/house_audio.py`
  → `ha_volume_ease.set_absolute(ease_s=0)`, which also stops a Light Show
  ramp) because SpotFX's own `HOME_ASSISTANT_TOKEN` is the `.env.template`
  placeholder (verified 401, 2026-10-20); `settings.absorb_ha_via="direct"`
  exists for a real one (`api/ha_client.py`).
- **PROVEN, NOT BELIEVED, AND RE-PROVEN.** After the write, HA's own number
  must read back 0 and Snapcast's own status (`services/snapcast_status.py`,
  a FRESH connection per request — snapserver mishandles keep-alive) must
  show every other connected room at 0 %/muted and `Effects Host` exactly as
  it was; a room the volume misses is muted directly (remembered first), a
  room on the TTS stream is an announcement and left alone, and the proof
  re-runs every `silence_recheck_s`. Every failure — the capture client
  moved, an unreadable snapserver, River's hard block (her `allow=` label
  rule, label "absorb"), sleeping with `run_while_sleeping` off — STOPS the
  window; a Guest/AirPlay stream playing YIELDS it.
- **THE YIELD RESTORES FIRST** (`_yield`): volume, then lights, then the
  queue; never a playback call. Resume needs `resume_after_quiet_min` of
  CONFIRMED quiet — `state.poll_ok` (new) tells a failed poll, which holds
  the clock, from "nothing playing" — and is a full re-open, at most
  `max_resumes_per_window` times. Spotify polls at
  `absorb_poll_interval_ms` while the house is silent.
- **RESTORE ON EVERY EXIT, NEVER OVER ABSORB'S OWN SONG.** The contract is
  `storage/absorb_silence.json`, written before the first write; a restore
  is read back before the file goes, a failure is CRITICAL and retried by the
  supervisor (`absorb.run_supervised`, the FIRST lifespan task — its first
  tick restores a crashed window), and a close pauses absorb's song first and
  keeps the house silent if it can't confirm the song stopped.
- **THE LIGHTS STAND DOWN, PROVEN FROM THE SHOW SIDE.** `run.lights_held`
  rides the websocket `absorb` key; `spectra/services/absorb_hold.py` is the
  binding statement for every SPECTRA choke point it gates (house fires,
  `origin="house"`, pass) — `tests/test_absorb_stand_down.py` is the bar.

Phase 3 — scheduling and the clean close (2026-10-20):

- **HOUSE TIME, ONE OPEN PER OCCURRENCE.** Windows are `{days, start, end}`
  in America/New_York via `zoneinfo` (days name the START day; Mon
  21:30-00:30 runs into Tuesday). `storage/absorb_schedule.json` remembers
  which occurrence STARTS it acted on, written BEFORE the open, so a restart
  never opens one twice and his Stop is never undone. The schedule's tick
  runs inside the absorb supervisor AFTER the runner's (`absorb.
  supervise_once`), and waits while a dead process's silence is unrestored.
  A refusal is final for that occurrence and recorded (run + schedule log);
  `GET /api/absorb/schedule` joins each outcome to how its run ended.
- **HIS MUSIC AT THE START IS A WAIT, NOT A REFUSAL** (his Q4 at second
  zero): the run is `paused`/`waiting` with the house untouched; its first
  `_resume` is its first open (`_first_open`) and is not counted as a resume.
  A window cut by a restart is NOT reopened if it had opened (a crash loop
  must not flap the volume); one still waiting is tried again.
- **THE CLOSE ORDER IS THE SEMANTICS** (`absorb._window_end` →
  `_close_stop` → `_advance_close` → `_end`): stop the queue → pause →
  WAIT for in-flight captures' outcomes (bounded, `CLOSE_FINALIZE_WAIT_S`) →
  restore + read back → lift the stand-down → the record, whose "ended" is
  written only after the restore. A song ending within `overrun_grace_min`
  is finished first; otherwise abandoned (not an attempt). Every "move on"
  goes through `_next()`, which turns into the close while one is under way.
  A safety stop and his Stop still end at once. A test that asserts write
  ORDER needs the fake's I/O to yield (`asyncio.sleep(0)`) or a queued write
  can never interleave.

Tests: `tests/absorb_world.py` (fake Spotify / capture / disk / clock — reuse
it), `tests/test_absorb_schedule.py` (house time, the shipped-off week, the
three phase-3 acceptances, the close's edges), `tests/test_absorb_runner.py`,
`tests/test_absorb_capture_hooks.py` (the real ingest loop; a gap at 0:30
skips within one frame), `tests/test_absorb_bar.py`, `tests/
test_absorb_silence.py` (the fake house: snapserver + HA + the volume
automation, which can reach the capture client, drop a room in mid-window
or play an announcement), `tests/test_absorb_house_audio.py` (the
transports underneath — `ha_client`, `snapcast_status`, `house_audio` —
against mocked HTTP only, never a live house), `tests/
test_absorb_stand_down.py` (the lights, from the show side); his real
library, read-only: `scripts/check_absorb_classify.py`. A test that drives
`audio_shape_service.on_track_change` with analysis on must stub
`pcm_ring_buffer.ensure_alive` or it opens a real audio stream.

Phase 4 — the interface (2026-10-21): SPECTRA's `/absorb` (Engine ▾ Absorb,
`spectra/web/src/absorb/`) reaches SpotFX's `/api/absorb/*` same-origin
(`spotfxGet/Post/Put`); SPECTRA's backend is not involved. Three things:

- **EVERY SENTENCE IS `absorb/absorbSummary.ts`**, pure, so
  `scripts/check_absorb_page.mjs` (run by `tests/test_absorb_page.py`)
  drives it directly AND mounts the real page under jsdom against a
  recording fake of the routes. It never claims what the run did not
  record: no committed capture is a head rate of "none", not 0 %; a silence
  never read back earns no green dot.
- **`GET /api/absorb/parked` IS THE LEDGER, not a run** — a park outlives
  its run, so Needs attention and Retry read every parked song across
  runs (the live runner's in-memory ledger while it holds one).
- **Screenshots come from `spectra/web/harness/absorb.html`** (real chrome
  + page, mocked fetch, `?state=running|idle|paused`) served from the
  BUILT `harness-dist` by `scripts/render_absorb_page.py`, which also fails
  on a sideways scroll or a page error — never the vite dev server, whose
  proxy would forward an unmocked request to the live :8000. Help section
  `absorb-music` and its six topics.

Phase 5 — Sonic (2026-10-21): domain `absorb`, `spectra/services/
absorb_console.py` (its docstring is the binding statement; the
`absorb-music` skill is the cold-start map), in `lock_console.py`'s shape —
every op reaches SpotFX's own routes over HTTP, so a start through Sonic is
`POST /api/absorb/start` with every refusal the page meets, in its words.
Three things:

- **ASKING FIRST IS A TWO-CALL PROTOCOL**: a write that newly lets Absorb act
  on the house or his playlists without a press (start, force recapture ON,
  the schedule newly opening windows, the playlist changing while it is on,
  running-while-asleep back ON, `use_capture_lane` ON (phase 4, PR 4.4 — the
  hidden player learns songs with nobody pressing anything), Recently
  Captured's cap lowered) answers `needs_confirmation` + a single-use
  `confirm_id` bound to the op, its arguments and his config as they were;
  only the second call acts.
- **ONE VALIDATOR, DRY-RUN FIRST**: `PUT /api/absorb/config?dry_run=true`
  validates exactly as an edit and writes nothing, so he is never asked
  about a change that would be refused. `GET /api/absorb/playlists` (his
  library, with `editable`) is what a playlist is linked from, by EXACT name
  only — a close name is refused naming the candidate.
- **A NEW AbsorbConfig FIELD owes Sonic** a place in `SETTING_KEYS` (or its
  own op) or a named line on the module docstring's off-limits list.
  Spec: `tests/test_absorb_console.py` (the real router over the fake world),
  `scripts/check_absorb_page.mjs` §5; help topic `sonic-absorb`.

## THE JUKEBOX — the host's set list with jukebox slots (phase 1: the program engine)

Plan: `/home/javi/fleet-spotfx/data/jukebox-plan/report.md` (approved
2026-10-27; built one PR per phase item in its §9 order). Phase 1 PR 1.1 is
the engine only — no page, no guests. `services/jukebox/night.py`'s and
`program.py`'s module docstrings are the binding statements. Five things:

- **THE SET PLAYS AS SPOTIFY'S OWN CONTEXT; SPOTIFY NEVER SEES A SLOT.**
  About `commit_lead_s` (45 s) before the song in front of a slot ends, the
  engine sends the ONE song that fills it into Spotify's queue and reads
  `/me/player/queue` back. Only that song is locked in place (`move` refuses
  it, nothing passes it); a committed song he removes is SKIPPED as it
  starts (`next_track`), with the next waiting song committed behind it.
- **`program.project()` IS THE ONE DEFINITION** of what plays next — the
  engine's commit decision is `project(...)[0]`, and the preview, the
  status and `scripts/jukebox_dry_run.py` (read-only by construction:
  `ReadOnlyGateway`) call the same function. The cursor moves only through
  `on_set_start`/`on_jukebox_start`, fed by what the player is OBSERVED to
  start, so a missed commit re-syncs by itself: an empty slot passes, a
  missed one is OWED to the next gap (capped at one gap), a late commit is
  carried, never sent twice.
- **EVERY SPOTIFY CALL IS `services/jukebox/gateway.py`, off the loop,
  spaced ≥ 0.5 s — reads included.** `main.py`'s poll calls
  `on_track_state` synchronously and it only wakes the engine's own task;
  never await Spotify there.
- **HOUSE RULES**: never starts while `sleeping` is on or unreadable; a
  confirmed "on" mid-night ends it (pausing only music the engine started),
  "unreadable" twice in a row does. Absorb and a night exclude each other
  in BOTH directions (`absorb_busy` here, Absorb's `jukebox_night` gate).
- **THE SPOTIFY SIGN-IN HAS AN AGE (PR 1.2)**: Spotify's refresh tokens die six
  months after sign-in and, when one lapses, polling, Absorb and the Jukebox
  all stop at once. `services/spotify_auth_age.py` (its docstring is the
  binding statement) records the moment at the ONE writer, the OAuth
  callback, and reads it back as `GET /api/spotify/auth-age` and on the
  jukebox status's `spotify_auth`/`warnings` — a line from 14 days before the
  end. A sign-in older than the record reads `unknown`, never a guess.
- **THE CAPTURE ACCOUNT HAS ITS OWN SIGN-IN (G2, 2026-10-30)**:
  `api/spotify_capture.py` is the binding statement. Account B (phase 4's
  hidden "Serenity Capture" player) signs in at `/api/spotify/capture/login`
  with its own redirect URI (`settings.spotipy_capture_redirect_uri`), its
  own token file (`storage/.spotify_token_cache_capture`) and record — NEVER
  `/api/spotify/login`, whose ONE token everything SpotFX polls follows. The
  code is exchanged into memory and the account read back first; the main
  account is refused with nothing written (show_dialog, so Spotify always
  asks who), and the main token file is only ever read. `/capture/status`
  reads two files, never Spotify.
- **THE CAPTURE LANE (phase 4, PR 4.1)** is `capture_lane/` — its own
  process (`python -m capture_lane`, 127.0.0.1:8030, reference unit
  `deploy/spotfx-capture-lane.service`, not installed by any build);
  `capture_lane/lane.py`'s docstring is the binding statement. It plays ONE
  song from 0:00 on the hidden player under account B
  (`spotify_capture.capture_client()`, the token's only player) and reads
  that player's own FIFO (`settings.capture_lane_fifo`, which snapserver
  never mounts — nothing reaches a speaker), writing the same shape files a
  normal capture does (`synthesize_frames_from_pcm`, `AudioShapeRecorder`,
  the shared `audio_shape_service.detect_anchors` and
  `_save_wav_and_analyze`), sidecar `captured_by: "capture_lane"`. Four
  things: (1) NOTHING PLAYS until account B is confirmed from fresh reads
  and is NOT the main account, exactly one device carries
  `capture_lane_device_name` — Spotify Connect's `serenity-capture` (the
  desktop client takes its container's hostname; the container's
  DEVICE_NAME is unused), matched exactly because account B also sees
  "Serenity Guest", the house speakers — the song isn't already learned, and the FIFO
  is flowing steadily — every play/pause names the device id and the
  gateway refuses without one; (2) a sample's song-time is the reader's
  steady origin (`pcm.origin_from`, a low percentile past the opening
  backlog burst) minus the governor's own `offset_ms` and
  `capture_lane_extra_latency_ms` (0, unmeasured live) minus the song's
  start from Spotify's progress — proven on a real FIFO in
  `tests/test_capture_lane_timing.py` (a click at 2.0 s lands at 2008 ms,
  and moves by the hold when the hold is left out); (3) it pauses the hidden
  player on every way out — at a song's natural end a pause Spotify refuses
  because the track already stopped by itself (403 "Restriction violated",
  the first live G5 trial's failure) is a let-go (`ended`, the capture is
  saved), checked by fresh reads over ~2 s (Spotify's player state lags
  its 403 by ~0.5 s, the second trial's failure); still playing, the job
  fails and the finally pauses it — and a moved governor `seq`, a stalled
  progress (`STALL_TOLERANCE_MS`) or missing samples (`pcm.drift_from`) fail the
  song with nothing written; (4) it decides nothing: SpotFX tells it what
  to learn (`POST /learn` with `storage/capture_lane_key`) and does the
  main-account follow-ups itself. Its first live run (G5, 2026-11-02)
  played a song on the real hidden player inaudibly and lost it to (3)'s
  end-of-song race; real-device timing is still unproven.
- **ABSORB-THEN-QUEUE (phase 4, PR 4.2)** is `services/jukebox/learning.py`
  (its docstring is the binding statement), its own supervised task in
  main.py, talking to the lane through `services/jukebox/lane_client.py`
  (every way of not reaching it is ONE `LaneUnavailable`). A song the
  lights don't know gets `LineEntry.learn` and `ready=False`, so
  `night._fills` passes it — it keeps its place, a slot slides to the next
  ready song — until the lane learns it (one song at a time, line order).
  Four things: (1) NOTHING WAITS without a usable hidden player (lane down,
  account B signed out, a lane outcome in `LANE_DOWN` → left alone for
  `DOWN_BACKOFF_S`) or with `ShowConfig.learn_first` off — the plan's own
  fallback, play un-analysed; (2) the host can let a song through
  (`play_unanalysed`, `why: "host"`) and the program does it alone only
  when `_project(1)` is empty (`why: "dry"`); (3) `MAX_ATTEMPTS` song
  failures PARK it: `refund_due` makes guests.py's settling refund a paid
  song once ("you get it back if it can't be learned", §1 rule 5), and it
  waits for the host (`relearn` gives fresh tries); (4) the night's
  `add`/`add_entry` ask `deps.ready_at_add` (no I/O) and judge last call on
  the song's PLACE (as if ready) — the projection skips an unready song, so
  asking otherwise would refuse every new song as too late. Every lane call
  and file read happens outside the night's lock (`runner.edit_line` is the
  one way in). Routes: `GET /api/jukebox/learning`,
  `POST /api/jukebox/line/{id}/unanalysed|relearn`; Sonic sets
  `learn_first` and reads a learning summary in `jukebox_status`; the two
  buttons are named exclusions. Spec: `tests/test_jukebox_learning.py`.
  The screens (PR 4.3): the master page's Absorbing tab
  (`spectra/web/src/jukebox/AbsorbingTab.tsx`, words in `jukeboxLearning.ts`;
  every time is the server's own `eta_s`, never guessed), a learning badge on
  both line views, and on the guest page `learningLine`/`learningWhen`
  (`guest/logic.ts`) — the strip carries the SHORT form, because the full
  sentence wraps and pushes the vote buttons under the tab bar on iPhone
  15/Pro Max (the renders' "23-learning" shot is the guard). Spec:
  `scripts/check_jukebox_absorbing.mjs` (`tests/test_jukebox_absorbing_page.py`),
  the Absorbing tab in `scripts/render_jukebox_page.py` and the learning scene
  in `scripts/render_jukebox_guest.py`.
- **ABSORB'S BACKLOG ON THE HIDDEN PLAYER (phase 4, PR 4.4)** is
  `services/absorb_lane.py` (its docstring is the binding statement; the
  `absorb-music` skill carries the cold-start map), its own supervised task,
  switched by `AbsorbConfig.use_capture_lane` (ships OFF; Sonic asks first to
  turn it on). It learns only Absorb's FRESH songs, one at a time, and RESTS —
  cancelling its song — during a Jukebox night (the learning queue's), an
  Absorb window, sleeping or unreadable sleep (conservative: Order 27's only
  exception is his grant for Absorb's proven-silent windows), account B signed
  out, or a lane that says the hidden player is unusable. It never writes his
  playlists. Spec: `tests/test_absorb_lane.py`.
- **THE SECOND ACCOUNT'S SWITCH (2026-11-01, the Admiral: "a solid barrier so
  that the second user doesn't get their music taken from them by the
  system")** — `fx/second_account.py` is the binding statement. SPECTRA's
  Settings card (`SecondAccountCard.tsx`, `GET/PUT /api/second-account`)
  writes ONE record, ships OFF; off or unreadable, nothing may write to
  account B. Four things: (1) THE GATE IS IN THE CLIENT —
  `api/spotify_capture.SecondAccountSpotify` wraps its own HTTP session and
  asks `second_account.check()` (fresh from disk) before every non-GET, so a
  new write path cannot bypass it; reads always pass. Never build an
  account-B spotipy client any other way — `tests/test_second_account_lock.py`'s
  guard scans the repo and fails. (2) The ONE write allowed while off is
  LETTING GO (`release_system_playback`): it pauses only after a fresh read
  shows the system's own recorded play (`second_account.note_started`) on
  its own device; the second user's playback is never touched. The capture
  lane has no bare `pause` any more — every stop is a release, ON or OFF.
  (3) The lane re-reads the switch every poll (`_check_cancel`), so off
  mid-song ends the job as `account_locked` within ~2 s; the learning queue
  and the Absorb backlog treat it as "hidden player unusable" (songs play
  un-analysed), never a song's failure (`NOT_A_TRY`). (4) Sonic has NO
  operation for it, read or write, deliberately (named in
  `spectra/api/second_account.py`). Tests run with it ON via conftest's
  `_isolated_second_account`; help topic `second-account-lock`.
- **THE MASTER PAGE (PR 1.3)** is SPECTRA's `/jukebox` (Engine ▾ Jukebox,
  `spectra/web/src/jukebox/`): a Set list editor and a READ-ONLY Live tab,
  plus the sign-in line — a third tab, Credits, was added by PR 3.3
  (below). It never re-derives where slots go — it draws the
  server's `lap_items` (`GET /api/jukebox/preview`, the set cached 60 s) and
  copies `manual_equivalent` on Auto → Manual; the click rules are
  `jukeboxEditor.ts`, pure. Dragging a set song REORDERS HIS PLAYLIST IN
  SPOTIFY (`POST /api/jukebox/set/move`), refused during a night within two
  of the playing song. Proof: `node scripts/check_jukebox_editor.mjs`
  (its mounted half needs a dev-only `jsdom`, absent by default — install
  it with `npm install --no-save jsdom` in `spectra/web` to run it) and
  `scripts/render_jukebox_page.py` (1400×876, 876×1400, 412×891 →
  `docs/evidence/jukebox-page/`).
- **THE CREDITS ECONOMY (PR 3.1) IS THE SIMULATOR'S, LINE FOR LINE.**
  `services/jukebox/economy.py` is every price and earning rule of the
  plan's §1 (D4 re-tune: two songs in line, 8 starting credits, the add
  price doubling every 15 min), pure, with the planning simulator's own
  rounding; the shipped values are `models.jukebox.EconomyConfig`'s
  defaults. `services/jukebox/simulator.py` is the plan's simulator with its
  prices replaced by those functions, and `tests/test_jukebox_economy.py`
  holds it to the plan's §3.2 numbers at 4/8/15/30 guests (it reproduces
  them exactly; a drifted setting moves them — the red control). Change a
  price or a default and that test tells you whether it is still the tuned
  night. `services/jukebox/ledger.py` is the per-night APPEND-ONLY credits
  file (`storage/jukebox_ledger/<night>.jsonl`): balances are derived, a
  refund is a new entry, a tip is one three-entry group, and `verify()`
  re-checks every rule from the entries alone.
- **THE SHOW SETTINGS (PR 3.3, settings half)**: `services/jukebox/show.py`
  is the ONE validator for every economy setting (`PUT /api/jukebox/show`,
  partial, `?dry_run`); its `FIELDS` table gives each setting a card,
  label and unit, and the RANGES are read off `EconomyConfig`'s own field
  bounds — a new economy field must get a `FIELDS` row (a test refuses one
  without). Presets (Small/Medium/Large) set the PROGRAM and Large's
  approval, never a price (§3.5: one set of prices fits 4-30 guests). The
  Credits tab's harness mocks a SNAPSHOT of those answers
  (`spectra/web/harness/jukeboxShowSnapshot.json`) — regenerate it when they
  change.
- **SAVED SHOWS AND "PLAY NEXT MAY JUMP THE SET"** (§4's last two
  settings). A SHOW is everything §4 lists — the ShowConfig (now with its
  `name`), the ProgramConfig and whether the guest link is on — saved under
  a name (`services/jukebox/shows.py`, `storage/jukebox_shows.json`, its
  own store: an unreadable file RAISES and is never written over; 30 kept;
  a name is unique without regard to case and saving under it replaces).
  LOADING goes through the page's own steps (`POST /api/jukebox/shows/load`):
  the program through `runner.apply_config` (a running night refuses
  another set playlist, nothing changed), the jail conversion a mode switch
  needs, then the guest link — unless the body says `guest_link: false`,
  which Sonic's `load_jukebox_show` always does (switching the link is his
  act on the page). Saving/deleting a show are named Sonic exclusions. A new
  ShowConfig or ProgramConfig field rides in a saved show for free, so a
  setting that must NOT travel with a show needs to be kept out of both.
  JUMP (`ProgramConfig.next_jumps_set`, off): a play next — the guest's
  paid one or the host's (`move(..., play_next=True)`) — marks the entry
  `jump`, and `program.project()` plays a jump fill as soon as the slot
  cursor has no slot open (`gap_left <= 0`), ahead of the next set song and
  using NO slot; a drag drops the mark. It is priced by how far it really
  jumps (`guests.jump_front_ms`). Spec: `tests/test_jukebox_shows.py`,
  `tests/test_jukebox_play_next_jump.py`; help `jukebox-shows`,
  `jukebox-slots`.
- **THE VOTE-FARMING FLAG** (§12's abuse table: "the master flags phones
  that always vote identically within a second"). Every vote now keeps its
  moment (`GuestBook.vote_ms`, play -> phone -> ms; taken back with the
  vote, folded on a merge, evicted with the play), and the pure
  `guests.lockstep(book)` flags a PAIR that, over the span both were voting
  (the later one's first vote to the earlier one's last), voted on every
  song the same way within `LOCKSTEP_WINDOW_MS` (1000) — at least
  `LOCKSTEP_MIN_PLAYS` (5) songs; a song one of them added is left out, and
  a vote with no time (cast before times were kept) is never compared.
  Candidate pairs come from each play's votes sorted by time, so the cost
  is the night's votes, not every pair of phones. It is ONLY a flag
  (`phones()`' `lockstep` per row, the Guests tab's ⚑ beside Merge…, which
  starts with the partner picked): it refuses nothing, because two friends
  tapping together look the same. Merged and blocked phones are never
  flagged. Spec: `tests/test_jukebox_lockstep.py`; help `jukebox-lockstep`.
- **THE PARTY SIMULATOR AND SONIC (PR 3.4)**: the simulator moved from
  tests into `services/jukebox/simulator.py` — ONE copy is both the
  economy's executable spec and the master view's Simulate tab
  (`POST /api/jukebox/simulate`: one model night under the SAVED economy,
  recorded for playback, plus N nights beside the tuned defaults on the
  same seeds; reads only, off the loop, one at a time). Recording
  (`Party(record=True)`) only appends — it draws nothing from the random
  stream (asserted), so never add a recording hook that calls `rng`. The
  night is the model's FOUR hours (its arrivals are timed for that length;
  not a setting). The tab's harness mock is a snapshot
  (`spectra/web/harness/jukeboxSimSnapshot.json`, held to the route by
  `tests/test_jukebox_simulator.py`) — regenerate it when the model or a
  default changes. Sonic's `jukebox` domain is
  `spectra/services/jukebox_console.py` (its docstring is the binding
  statement and names what stays off-limits): HTTP to these routes only,
  and EVERY change asks first (absorb's two-call `confirm_id`, bound to the
  op, its arguments and the state asked about — a stop's yes covers only
  THAT night). Starting and stopping a night always ask; never test either
  anywhere but `tests/jukebox_world.py`'s fake world. A new jukebox
  setting or action owes this domain an op or a named exclusion.
- **THE GUEST LINK (N1) SHIPS OFF AND NEVER RUNS `tailscale` IN A TEST**:
  `services/jukebox/guest_link.py` (its docstring is the binding
  statement) publishes ONE Funnel port (`:8443` → `127.0.0.1:8020`, the
  guest app) only while a night runs — the night's start/end hooks
  (`JukeboxDeps.guest_link_start/_end`, no-ops unless production_deps()
  wires them) and a supervised reconcile that closes a Funnel left open
  with no night. The model refuses a guest port of `:8000`/`:8010`; a
  public port his `tailscale serve` already uses is refused; a read-back
  showing anything else published closes it again; the self-test checks
  only the plan while closed. `GuestLinkConfig.enabled` is False until G4
  (his) — the commands have never met his Tailscale. conftest replaces
  `guest_link.run_command` with one that fails loudly; drive a fake
  (`tests/test_jukebox_guest_link.py::FakeTailscale`, his own Serve on
  :443 included). The party token lives through a night (it is on the
  printed cards) and is replaced when a night that used the link ends.
- **THE POST-PARTY REPORT**: `services/jukebox/night_report.py` (`GET
  /api/jukebox/report`, the Live tab's last card, Sonic's
  `jukebox_night_report`; its module docstring is the binding statement)
  measures the latest night from its record, its credits ledger and its
  GUEST BOOK — every `simulator.ROWS` row, the model's way, so it sits
  beside the model's nights at the party size (the ledger's phones, a
  free-play night's joined phones, or `?guests=`). The book's REPORT
  RECORDS (`guests.py`: one `NightSample` per song start, taken on the
  first poll after the engine's `plays` moves; each guest's first look at
  an add price — their first search since their last add, since the page
  disables an Add they can't afford; adds turned away as too late) are what
  the ledger can't hold; a NEW model row needs its record added there, not
  guessed in the report. The book holds only the latest night
  (`load_book`). A measure the night can't take is None WITH its reason
  (`why`), never a 0; the ledger's own `verify()` rides along. It reads
  only. A test fixture that builds a `Ledger` must pass `persist=False` (or
  run under conftest's isolation) — the default persists to
  `storage/jukebox_ledger/` and replays on the next open. The Live tab's
  harness renders `jukeboxReportSnapshot.json`, held to the report by
  `tests/test_jukebox_report.py` — regenerate it when the report changes.
- **THE GUEST PAGE (PR 2.1) IS ITS OWN PROCESS, and `jukebox_guest/
  __init__.py` is the binding statement.** `python -m jukebox_guest`
  (:8020, reference unit `deploy/spotfx-jukebox-guest.service`,
  not installed by any build) serves the page built from
  `spectra/web/src/guest/` (`npx vite build --config vite.guest.config.ts`
  → `guest-dist/`) and answers EXACTLY `app.ROUTES` — no docs, no OpenAPI,
  nothing of the master's; each `/g/` call becomes one of `app.FORWARDS` on
  SpotFX's loopback address with the guest app's key (`jukebox_guest/key.py`,
  `storage/jukebox_guest_key`) and the phone's code from its cookie. Never
  give a guest route a body field that names a phone or a SpotFX path. What
  a call does is `services/jukebox/guests.py` behind
  `routers/jukebox_guest_router.py` (401 without the key): a NEW phone needs
  tonight's party token (a night now always has one — `guest_link.
  on_night_start` makes it, link on or off), a phone's view names other
  phones only by name, a vote is keyed by the PLAY (`<uri>@<started_ms>`),
  never on your own song, and the engine is read through its lean
  `night.JukeboxRunner.guest_state` (no Spotify call — every phone polls it).
  The page: four phones' renders with their safe areas, 44 px targets and the
  votes above the fold (`scripts/render_jukebox_guest.py`, which plants a
  problem to prove its own checks), the pure rules
  (`scripts/check_jukebox_guest_logic.mjs`), both run by
  `tests/test_jukebox_guest_page.py`. Web push (iPhone alerts from a Home
  Screen icon, Android lock-screen alerts) is NOT built: it needs the HTTPS
  link (G4) to test.
  **REACHABLE ON THE HOME LAN SINCE 2026-11-01 (the Admiral: "do wifi
  option")**: the shipped unit listens on `0.0.0.0`, so a phone on
  Serenity's own Wi-Fi opens `http://<serenity LAN IP>:8020/?t=<party
  token>` directly — the token is still checked exactly as before, and
  Tailscale Funnel (the alternative, public-internet option,
  `services/jukebox/guest_link.py`) stays a SEPARATE, still-off setting
  nothing here arms. Nothing about the per-address rate limits
  (`jukebox_guest/app.py`'s `_client()`) changes for this: a direct
  connection's own peer address already IS its identity (never collapsed
  to one bucket), and the loopback+`X-Forwarded-For` trust branch stays
  scoped to the Funnel case, where every connection genuinely does arrive
  from tailscaled on loopback. `guest_link.status()`'s own `lan_link`
  field (`GuestLinkDeps.lan_ip`, a routing-table read with no network
  traffic) is this address with tonight's token already on it, served on
  `GET /api/jukebox/guest-link` and `GET /api/jukebox/card` (the
  "Print the cards" page shows it) whether or not a token or Funnel
  address exists otherwise.
- **SEARCH AND ADD, AND THE HOST'S CONTROLS (PR 2.2)** are
  `services/jukebox/guests.py` too (its docstring is the binding statement):
  a guest's song goes in by FAIR ORDER — `LineEntry.round` is its adder's
  Nth song tonight (played + waiting + 1; the host's own adds are 1st songs)
  and `night.JukeboxRunner.add_entry` places it ahead of the first WAITING
  song with a higher round, never ahead of one sent to Spotify — and is
  refused, and taken back out, if the projection starts it after the night
  ends. Requests close `last_call_min` before `night_ends`; both, explicit
  songs, max phones, renames and the word filter are `ShowConfig` top-level
  keys behind `show.apply_patch` (`show.GUEST_FIELDS`, and Sonic sets them,
  asking first). A HELD song (`LineEntry.held`) keeps its place and is left
  out of `_fills`, so slots pass it. Search is his profile library first
  (`services/jukebox/library.py`, `known` = the audio-shape index) then
  Spotify, 10 a page, cached, on `gateway.search_gateway()` — a gateway of
  its own so a party searching never queues ahead of the engine's commit —
  and every disk read or Spotify call goes through `to_thread`
  (`tests/test_jukebox_guest_add.py` proves the loop keeps ticking, with a
  red control). The host's controls are the master's routes
  (`GET/POST /api/jukebox/guests`, `POST /api/jukebox/line/{id}/hold`) and
  the Jukebox page's Guests tab; approving, blocking and renaming a phone
  are a named Sonic exclusion.
- **FREE PLAY'S RULES (PR 2.3)**: the room's skip, bumps by count, the jail
  as a time-out, the host's pardon — `services/jukebox/guests.py`'s FREE
  PLAY section decides when, `night.py`'s FREE PLAY section acts. Four
  things: (1) THE JAIL'S TERM IS THE ENGINE'S, THE COUNT IS THE BOOK'S —
  `JukeboxNight.jail` (phone -> the `plays` count it ends at; `plays`
  counts every song that starts, never a repair skip) is what `_fills`
  reads, so a jailed guest's songs keep their places but are never sent;
  `GuestBook.play_by` + `GuestPhone.jail_base` are the net ▼ count, reset
  where the term ends (`_count_release`, run before any vote moves the
  count). (2) THE ROOM'S SKIP WAITS OUT `skip_grace_s` on a timer task and
  re-checks the tally then; `skip_by_vote` acts only on the SAME play and
  sends a waiting jukebox song first, so the skip lands on the slot, and
  records it (`_played("skipped", ...)`) so the night report's own
  `played.skipped` count sees a real vote-skip, not just the line's. (3) A
  BUMP MOVES AMONG THE SONGS THAT CAN BE SENT (`_movable`): a held or jailed
  song stays put, nothing passes the committed one, and `pushed_back` caps
  the song that ends up a place further back — a PER-SONG total, not a
  per-direction one: an up-bump steps past the song ahead of it and pushes
  THAT song back exactly as a down-bump would, refused the same way at the
  cap, so a guest cycling fresh phones can't push one song past the limit
  by bumping other songs up around it. (4) "guests" for the jail's crowd-scaled bar is phones seen
  in the last 15 minutes (`Guests._seen`, memory only). Settings:
  `ShowConfig.free_*`, the Guests tab's Free play card; Sonic sets them
  asking first; Pardon is the phone's button (a named exclusion, like
  approve/block/rename). THE BOT PARTY: `scripts/jukebox_bot_party.py` runs
  a SpotFX stand-in (the real Jukebox routers, engine and guests; only
  Spotify faked), the real guest app and N bot phones over loopback, with a
  10 ms probe in the stand-in's loop — `--minutes 20` is the acceptance
  run, `tests/test_jukebox_bot_party.py` a 25 s party. It measures the
  Jukebox's own share of SpotFX's loop, not SpotFX whole. Specs:
  `tests/test_jukebox_free_play.py`, the guest render's skip/move/time-out
  shots, `check_jukebox_editor.mjs` §1e/§2d; help `jukebox-free-play`.
- **CREDITS MODE (PR 3.2)** is `ShowConfig.play_mode` ("credits" by
  default — the plan's §4 tuned default; "free" is phase 2's free play —
  the Credits tab's Mode card, Sonic asking first). A test or script about
  FREE PLAY must say `play_mode="free"` (the bot party and the guest render
  do). `services/jukebox/guests.py`'s CREDITS MODE section is the binding
  statement; `services/jukebox/wallet.py` is the wallet (earning, prices
  from the night as it stands, the Shop's words). Four things: (1) THE
  LEDGER IS THE TRUTH — no balance is stored anywhere; every write is a
  ledger entry, on `to_thread` (it fsyncs), and the `Wallet` is rebuilt
  from it on open. Earning is checked on the phone's OWN polls
  (`_credits_tick`, no timer), and the lock is taken only when something
  is due. (2) THE SERVER PRICES, THE PAGE ONLY SHOWS: every spend carries
  the price the page showed and is refused with the new one if it moved
  (`_afford`); quotes come from `JukeboxRunner.quote_wait` (a sync probe
  insert/remove — the only way the projection says when a song WOULD
  start). (3) REFUNDS ARE WRITTEN: a paid song the host removed
  (`LineEntry.removed` + `paid_seq`), a skip pot whose song ended first,
  and paid songs still waiting when the night ends (`_close_night`). THE
  PUSH-BACK CAP IS PER SONG WHATEVER MOVED IT (firstmate's ruling on PR
  2.3): every song a play next jumps past is `pushed_back` one place — a
  guest's play next is refused at the cap (`next_pushed_max`, and the
  view's quote says so first); the host's Play next (`night.move`) counts
  the same way but is never refused. (4) THE SKIP
  LOCK (`JukeboxNight.no_skip`, by URI, `POST /api/jukebox/skip-lock`, the
  Guests tab's "Keep from skips") is checked in `skip_by_vote` itself, so
  the room's vote, a paid skip and a filling pot all refuse it in either
  mode; it is a named Sonic exclusion (a line action). Credits mode's jail
  is `JAIL_UNTIL_FREED` — it ends on a break-out (`jail_fee`) or Pardon.
  **(5) A JAIL'S KIND IS STORED WITH ITS TERM** (`JukeboxNight.jail_kind`,
  "timeout"/"breakout"), set by `night.jail()` and read everywhere a jail
  is shown or acted on (`guests.py`'s `jail_kind_of`: `build_view`'s
  `jail`/strip, `Guests.phones()`, `_jailed_refusal`, `break_out`) —
  **never reinterpreted by the CURRENT `play_mode`**, which can change
  mid-night. `night.convert_jail_mode` (called from `PUT /api/jukebox/show`
  — the one validator path, so Sonic's `set_jukebox_setting` gets it too —
  the instant `play_mode` actually changes) converts what is RUNNING:
  switching credits off turns a "breakout" jail into an ordinary "timeout"
  of `free_jail_songs` songs counted from that moment (or ends it at once
  with none, at 0); switching credits on leaves a "timeout" jail exactly as
  it was, with no break-out ever offered for it. Found live by review:
  before this, both the guest page and the Guests tab reinterpreted every
  jail by whichever mode was CURRENT, so a credits jail surviving a switch
  to free play read its `JAIL_UNTIL_FREED` term as "a billion songs to go"
  and a free-play time-out switched to credits could be paid away with
  `break_out()` though it was meant to end for free.
  The guest app forwards `/g/tip`, `/g/skip`, `/g/next`, `/g/breakout`,
  `GET /g/wallet`. Specs: `tests/test_jukebox_credits_play.py`, the guest
  render's credits shots (14-21), `check_jukebox_guest_logic.mjs`'s credits
  section, `check_jukebox_editor.mjs` §1e/§2b/§2d; help
  `jukebox-credits-mode`, `jukebox-skip-lock`.
- **THE BOARD** (phase 3; `services/jukebox/board.py` is the binding
  statement): "Tonight's top songs" RANKS SONGS, NOT PEOPLE — the plan's
  §2.2 flag (Spotify's "Do not create a game") at D1's default (a). A song
  that played twice is one row; who added it is attribution, never a rank.
  The people boards (top pickers, top voters, most generous — the last
  credits mode only) ship OFF (`ShowConfig.board_*`, the Guests tab's Board
  card, Sonic asking first). No prizes, and nothing the board says uses a
  word in `board.BANNED_WORDS` — a test holds every string to it; keep it
  that way in any new board wording. A phone is named only by its name
  (`build_board(viewer=)` marks `mine` without the id ever leaving).
  Guests read `/g/board` (the guest app's allowlist) on their Board tab;
  the host's card and the TV page read `GET /api/jukebox/board`, which
  carries every people board marked `shown`. THE TV PAGE is SPECTRA's
  `/jukebox/tv` — rendered outside the app chrome (App.tsx, like `/live`),
  LAN-only, showing only what guests see, and nothing until "On the TV"
  (`board_on_tv`) is on. Specs: `tests/test_jukebox_board.py`,
  `check_jukebox_editor.mjs` §1f/§2d/§2e, the guest render's
  `22-board`; help `jukebox-board`.
- **GIFTS AND BONUS CARDS** (phase 3; the plan's §1 rule 1, §4's Free
  credits card, §9's N2). The host's gift (`guests.gift`, `POST
  /api/jukebox/gift`): "Everyone +2" reaches every phone JOINED, APPROVED
  and not blocked; "Give…" one of them, 1-`GIFT_MAX` (20); credits mode
  only; a "host_gift" ledger grant per phone. Sonic's
  `give_jukebox_credits` asks first and takes a guest only by their exact
  name (a near miss is refused naming the closest — never guessed). THE
  BONUS CODES are `services/jukebox/bonus_codes.py` (its docstring is the
  binding statement): their OWN store (`storage/jukebox_bonus_codes.json`,
  `store.BONUS_FILE`, conftest-isolated) because cards are printed before a
  night exists; good for `qr_bonus` ONCE, EVER; one per phone a night (the
  wallet's `got` set); `BONUS_TRIES` (5) wrong codes a phone a night; a
  file that is there but unreadable RAISES rather than reading empty
  (`store.load_bonus`), so printed codes are never written over. A guest
  uses one from the join link (`?b=` — the guest page keeps it in session
  storage, strips it from the address, and uses it once they join in
  credits mode) or by typing it in the Shop (`/g/bonus`). Minting and
  voiding are the Credits tab's Bonus cards card; a named Sonic exclusion.
  Specs: `tests/test_jukebox_gifts_bonus.py`, `test_jukebox_console.py`'s
  gift test, `check_jukebox_editor.mjs` §2b/§2d, the guest logic check's
  bonus section, the render's credits pass (it arrives by a card's link);
  help `jukebox-gifts`, `jukebox-bonus-cards`.
- **THE PRINTED CARD (N2)** is SPECTRA's `/jukebox/cards` (chrome-less, like
  `/jukebox/tv`; "Print the cards" on the Credits tab's Bonus cards card):
  two cards across, four down on Letter, each with the guest Wi-Fi's QR, the
  party link's QR carrying that card's bonus code (`?b=`) and the code as
  text. **THE WI-FI PASSWORD IS TYPED THERE AND NEVER LEAVES THE PAGE** —
  React state only, QRs drawn in the browser (`jukebox/cardQr.ts`); never
  add it to a request, a store or the URL (the check asserts all three).
  `GET /api/jukebox/card` hands the page the link, the home-Wi-Fi address
  (`lan_link` — the 2026-11-01 "wifi option," no Funnel needed), the unused
  codes and the QR bonus, MAKING the party token if there is none (the cards
  carry it) but never switching the link on. The Jukebox QR uses the public
  link when one is saved, else falls back to `lan_link` — the card still
  prints and scans, just for a phone already on Serenity's own Wi-Fi. The
  QR encoder is `qrcode-generator` (MIT,
  pinned; told to encode UTF-8 — its default keeps a character's low 8
  bits); `jsqr` is dev-only, for decoding every code back — a deploy needs
  `npm ci` in spectra/web. Sonic: a named exclusion (`jukebox_console`).
  Specs: `scripts/check_jukebox_cards.mjs` (every QR decoded, the password
  never leaving), `scripts/render_jukebox_cards.py` (printed to a Letter
  PDF: one page, QRs ≥ 1 in, the longest Wi-Fi still fitting; `--out`),
  both run by `tests/test_jukebox_cards.py`; help `jukebox-cards`.
- **ZERO AND MERGE A PHONE** (§4's host buttons, §12's cookie-reset and
  second-phone guards; `guests.py`'s ZERO AND MERGE docstring section is the
  binding statement). Zero is one `host_zero` ledger entry (balance to
  exactly 0) and forgoes any welcome credits not yet had. Merge makes two
  phones ONE GUEST: a `merge_out`/`merge_in` ledger group, after which the
  ledger forwards every write naming the retired phone to the kept one
  (`Ledger.owner`) and counts per-guest things (votes paid, tips a song, the
  double-first allowance) as one — `verify()` re-checks all of it, replay
  included. Songs, votes, time-out, jail count and bumps join the kept phone;
  the guest keeps the FIRST phone's name. The retired code keeps working:
  every guest call is resolved through `Guests.alias` (the `@_as_guest`
  decorator — a new guest call naming a phone needs it), and hello hands
  that page the kept code. A new per-phone record (book or engine) must be
  folded in `Guests.merge`/`JukeboxRunner.merge_phone` too. Sonic: a named
  exclusion. Spec: `tests/test_jukebox_zero_merge.py`; help
  `jukebox-merge-phones`.
- **THE LIVE ECONOMY PANEL** (§9 3.3; `services/jukebox/economy_live.py` is
  the binding statement): `GET /api/jukebox/economy`, the Live tab's "The
  economy right now" card. Its credits ARE `night_report.credits_section`
  read while the night runs (one vocabulary with the post-party report),
  its prices are the guest Shop's own functions, and its recent events are
  the ledger's GROUPS in words — votes, welcomes and top-ups counted, never
  listed; one "Everyone +N" (one gift per DIFFERENT phone, moments apart)
  is one event. Names only: no event or line row may carry a phone's code
  (the Live line now names who added each song — `jukeboxEconomy.ts`'s
  `liveLineWords`). Reads only, on the loop, so it never replays the ledger
  (`verify()` is the report's). §7's "draggable line" is on BOTH host views,
  as §7.2 itself specs it — the Live tab's own line is draggable too, not
  just the Guests tab's (row 1.3's "read-only Live" was the phase-1
  starting point before host controls existed, not a standing rule): a
  waiting song drags by its ⠿ handle through `night.move`, the same move
  Play next makes, and the song already sent to Spotify has no handle and
  nothing passes it. ONE shared component, `JukeboxLine.tsx`, draws both
  tabs' line (never two copies) — nothing else on the Live tab writes.
  Spec: `tests/test_jukebox_economy_live.py`,
  `check_jukebox_editor.mjs`; help `jukebox-economy`, `jukebox-live`,
  `jukebox-guests`.
- **NAMES**: the code says `program`, never `setlist` — SpotFX's existing
  Set Lists (`services/setlist_store.py`) is a different feature. Stores:
  `storage/jukebox.json` (his program settings, one validator:
  `routers/jukebox_router.apply_config_patch`), `storage/jukebox_night.json`,
  `storage/jukebox_show.json` (the show settings — presets, approval,
  the economy; one validator: `services/jukebox/show.apply_patch`), and
  `storage/jukebox_guest_link.json` (the guest link's settings and state;
  one validator: `services/jukebox/guest_link.apply_patch`), and
  `storage/jukebox_guests.json` (tonight's phones and votes,
  `services/jukebox/guests.py`), all
  isolated per test by conftest's `_isolated_jukebox`. Tests:
  `tests/jukebox_world.py` models Spotify's
  queue rule and a crossfade lock — reuse it; a script run OUTSIDE pytest
  writes the real `storage/` unless it repoints `store.*_FILE` first.

