---
name: sung-labels
description: >
  Sung labels, Claude's colour meanings and a song's word matches (lyrics
  plan step 3, PR #499), AND word colours and imprints (lyrics plan step
  4, PR #504), and THE ROLL (word chance per play, 2026-11-12):
  spectra/services/sung_labels.py, lyric_matches.py,
  lyric_reading.py, color_meanings.py, colour_words.py, claude_text.py and
  lyric_events.py; the /sung-labels correction page; the Test Bed's Sung
  words lane, Word matches row and Word actions row; and Sonic's lyrics
  domain (spectra/services/lyric_console.py). Load before touching any of
  these files, before adding a sung-label/reading/word-colour setting or
  route, or before a report shaped like "a word isn't matching / a
  re-draft wiped his edits / Sonic can't read or change the sung labels or
  word colours / a word never (or always) plays / every play does the same
  thing / the kept roll or a pin didn't stick."
---

# Sung labels, colour meanings and word matches

`docs/agents/testbed-and-drops.md`'s own lyrics-step-3 sections ("Sung words
on the test bed", "Sung labels and word matches") and each module's own
docstring are the binding statements — read those before this file for the
mechanism. This skill is the cold-start map plus the Sonic-coverage
follow-up (the Admiral's standing protocol, 2026-10-06: every feature
change owes Sonic a follow-up, filed when it ships rather than gating the
feature's own deploy).

**THIS REACHES THE ROOM ONLY THROUGH WORD COLOURS, ON A SHOW HE HAS SWITCHED
ON** (`spectra/services/lyric_events.py`, off for every show; its own docs are
`docs/agents/testbed-and-drops.md`'s "Word colours and imprints"). Nothing here
writes to the show; the only reader is that module, lazily, off the event loop,
so starting the show still pulls in none of these (`tests/test_lyric_reading.py`'s
fresh-interpreter test, mirrored for the Sonic domain in
`tests/test_lyric_console.py`). Sonic's own reach over the switch, its tuning
and a preview of what each word would do is the "Sonic reach" section below.

## The shape, cold

1. **ONE LIST PER CARD, FOUR SOURCES, ONE COMPUTED.** `sung_labels.py`'s
   `page()`/`catalogue()` build each colour set's and effect's sung labels
   from its seed (`colour_words.seed_labels`, pure — colour + name), Claude's
   drafted meanings (`color_meanings.draft`, things/moods/places, colour
   sets only) and his own edits (`LabelEdits`: added/removed deltas, never a
   second copy of the computed list). A re-seed or re-draft can never undo
   one of his edits, because his edits are stored APART from what they
   change.
2. **CLAUDE READS TEXT ONLY, AGAINST ONE LIST, CHECKED.** `lyric_reading.
   read_song(uri)` hands Claude the song's words (via `lyric_matches.
   word_keys`/`lyrics_timeline.timeline_for_uri`) and the current label
   list, once (`build_system_prompt`/`build_user_prompt`); `parse_reply`
   throws away and counts any row naming a line/phrase/label that isn't
   really there. `claude_text.py` is the one Claude client (same account/
   model switch as Sonic, `config.lyric_agent_model()`), shared by
   `color_meanings.draft` too.
3. **THERE IS NO WEAK-MATCH THRESHOLD ANY MORE** (2026-11-12, the Admiral:
   "no cutoff anymore"). Every guess is kept with its confidence, and the
   confidence is the share of plays the word acts on (`lyric_events.
   chance_for`, below). The reading prompt asks for doubtful guesses with an
   honest low number instead of leaving them out; `parse_reply` drops only
   rows that are not really there. `SungLabelSettings.weak_match_threshold`,
   its getter/setter, its API field and Sonic's `weak_match_threshold`
   argument are all gone; a stored value is ignored on load
   (`extra="ignore"`) and dropped on the next save. Do not bring a cut-off
   back as a setting: a "too weak" word is a word with a small chance.
4. **A MATCH SITS ON WORDS, NEVER ON TIMES OR AN OPAQUE NAME TO SPEAK.**
   `lyric_matches.py`: `his` (his own matches) and `deleted` (guesses he
   took out) are the only writable parts; `reading` is replaced whole by
   each read. `anchor()` re-finds a span by its words after a recapture
   moves everything. A Claude guess's id (`guess_id`, a hash) and his own
   match's id (`h_<uuid>`) are never something anyone would say aloud —
   Sonic (below) reaches a match by its PHRASE text, not its id.
5. **OFF BY DEFAULT.** `SungLabelSettings.auto_read` gates
   `lyric_reading.run_supervised()`'s sweep entirely; a press (`POST
   /api/testbed/lyric-matches/read`) always works regardless.

## The highlight: where a word's effect shows before and at fire time (2026-11-12)

Option A plus E's live pulse of `/home/javi/fleet-spotfx/data/word-effect-
highlight-options/report.md`, the Admiral's pick verbatim: "I like A, with
E's live pulse and showing it in the countdown box ... Instead of the red dot
swatch next to 'smoke', just highlight the blue square, like you do in the
strip ... just put the word under the swatch ... A fire-alone word is a
marker and can be 'next' in the box and replace the 'his scene change/his
flares' rows". No engine timing or behaviour change; three surfaces read the
ONE plan.

- **The join is by TRIGGER ID, never by time.** `GET /api/upcoming` rows
  now carry `id` (a stored trigger's own, `analysed_plan._plan`'s synthetic
  `analysed-scene:`/`analysed-flare:` + generator key, or `drop-seq:<key>:
  <class>`), and `upcoming.with_words` joins `lyric_events.word_marks(plan)`
  onto them: an imprinted event gains `word`/`word_ms`/`swatch`, a fire-alone
  word becomes its own `kind: "word"` row (id `lyric:<word key>`). A flare's
  landing moment carries its lead and its mark does not, so a time join would
  miss. Only when `lyric_events.enabled(uri)`; an unreadable plan leaves the
  list untouched (`tests/test_upcoming_api.py`).
- **The colour before fire time is the FIRST candidate set's swatch**
  (`WordHit.swatches`, from `sung_labels.Target.swatch` through `reach()` —
  the same swatch the Word matches row draws). Which set lands, and whether
  the event can carry it, is fire time's: `lyric_events.fired_payload` →
  `TriggerEngine._lyric_fired` → `engine._push_word_colour` → `{"type":
  "word_colour", ...}` on SPECTRA's websocket, `swatch` = the landed set's
  (`swatch_for`). The browser (`lib/wordColourPush.ts`) flashes the marker by
  `event_id` and the next-event box in that colour. The show log stays the
  record; this is only the flash.
- **One drawing rule, three places** (`songStrip.ts`: `HALO_GAP`, `HALO_
  STROKE`, `diamondPath`, `wordColour`, `kindGlyphSvg(kind, num, halo)`):
  the strip and Home's shape (`trackPainter.ts`, `drawShapeMarkers`), the
  next-event box (ring on the kind's own glyph, the word printed under it —
  NO second swatch, NO "→ scene"), and the Test Bed's **Word events row**
  (`TestbedLaneBar.tsx` `WordEventsRow`, `lyricEvents.ts` `wordEvents`),
  which REPLACED the "His scene changes"/"His flares" rows and now also
  feeds the Sung words lane's guide lines (`LyricsLane` takes `guides`).
  Words that do nothing draw nowhere outside the Test Bed.
- **Proofs:** `scripts/check_song_strip.mjs` §SIX, `scripts/check_testbed_
  lyrics_lane.mjs`, `scripts/render_testbed_lyrics_lane.py` (the harness
  `spectra/web/harness/testbedlyrics.tsx` now mocks `/testbed/lyric-events`),
  `tests/test_lyric_events.py`'s "the highlight" section.

## The roll: which words act this play (2026-11-12)

`/home/javi/fleet-spotfx/data/word-chance-plan/` (report + explainer), and
`lyric_events.py`'s "THE ROLL" docstring, which is binding. The Admiral:
"Instead of always using a "word" effect, it should randomly be used, based
on it's confidence ... The choice is calculated when the song is loaded",
and "if the confidence leve is .97, it runs 97% of the time".

- **`plan_play` = `roll_hits` then `plan_words`, everywhere.** The trigger
  clock (`_refresh_lyric_plan`), the Test Bed (`preview_lyric_events`) and
  the strip/Home join (`upcoming.with_words` → `preview_lyric_events`) all
  roll the same play, so only this play's winners get halos and diamonds.
  `plan_words`' own rules are untouched. Rolling BEFORE it is the point: a
  word sitting out (`WHY_SAT_OUT`) frees its line, event and gap.
- **`chance_for` is the one mapping** (confidence exactly; `his` → 1.0; pin
  Always/Never → 1.0/0.0). "We might add more math to that later" — add it
  there and nowhere else.
- **`draw_for(seed, uri, hit)`** hashes the seed with the word's own span
  and label: independent per word, monotone in chance, same seed = same
  winners. Never draw from a shared RNG stream: a new match would reshuffle
  every other word.
- **The play** is begun lazily for a switched-on show only (an off show
  writes nothing — the switch-off proof asserts `LYRIC_PLAYS_FILE` absent),
  kept through pause/seek/rewind/restart, ended by a different song, by the
  same song after `PLAY_GAP_S` away, or by a repeat wrap (needs the
  bridge's `track_duration_ms`, wired in `engine.py`). Logged once per play
  as `lyric:roll`.
- **Kept roll** = `LyricShowState.kept_seed` (`keep_roll`); `set_show` must
  keep preserving it. **Sample** = `GET ?sample=N`, page-only, never stored.
  **Pins** = `SongMatches.pins` (`lyric_matches.set_pin`), on words + label
  like `deleted`.
- **UI:** the roll line, chance on each Word actions chip, dotted sat-out
  chips and the `PinControl` live ONLY on the Test Bed's Sung words slot —
  his rule: nothing on Home, "keep it subtle and clean". Help topic
  `testbed-word-chance`.
- **Proofs:** `tests/test_lyric_events.py` §7, `tests/test_lyric_reading.py`
  (pins through a re-read, the prompt), `scripts/check_testbed_lyrics_lane.
  mjs` §5, `scripts/render_testbed_lyrics_lane.py` (roll-1440/390 shots).

## Sonic reach (`spectra/services/lyric_console.py`, domain `lyrics`)

Built as the coverage follow-up this skill exists to record. Load
`.claude/skills/sonic-ops/SKILL.md` before changing anything here.

- **Reads**: `get_lyric_reading_settings` (auto_read and Claude
  availability), `list_sung_label_targets` (every colour set's/
  effect's name + label count, kind-filterable — call this first to get
  the exact name the other ops expect), `get_sung_labels` (one named
  target's labels, plus meanings for a colour set), `get_lyric_matches`
  (one song's matches — `song` omitted means whatever is playing now),
  `get_lyric_event_settings` (whether word colours are on for a song, the
  energy cut-off/minimum gap/imprint window, and how many shows have it
  on), `preview_lyric_events` (what each matched word would do — fire,
  imprint on a nearby drop/scene change/flare, or nothing and why; the
  exact plan the Test Bed's Word actions row shows, including THE ROLL:
  `roll`, and each action's `chance`/`won`/`pin`).
- **Writes, no confirmation needed**: `edit_sung_label` (add/remove one
  word on a target's labels or, colour-set-only, things/moods/places),
  `add_lyric_match`/`delete_lyric_match`/`restore_lyric_matches` (a match
  is named by its PHRASE TEXT, disambiguated by `label` or `occurrence`
  when the same phrase repeats — never by its internal id), turning
  `auto_read` OFF, turning a show's
  word colours OFF, and changing the energy cut-off/minimum gap/imprint
  window (`set_lyric_event_settings` — shared by every show, so it is
  never the per-show "newly lets it act" write).
- **Writes that ASK FIRST, every single call** (not just the first — the
  absorb_console/drop_console in-process confirm/redeem shape, no HTTP hop
  since these modules live in SPECTRA's own process): `draft_colour_
  meanings` (Claude spend, up to `color_meanings.DRAFT_BATCH_SIZE` named
  colour sets — sized to fit inside the spotfx reverse proxy's 60s read
  timeout, `services/spectra_proxy.py`; do not hand-copy its current
  number, it has already moved once) and `read_song_
  lyrics` (Claude spend, one song). Turning `auto_read` ON also asks first
  — it is the one write here that newly spends his Claude allowance
  continuously with nobody pressing anything, the same test
  `absorb_console.py`'s own settings asks apply. `set_lyric_event_show`
  turning a show's word colours ON asks first the same way (NOT the
  "every single call" shape — once he's said yes for a show, it's done;
  turning it off again needs no confirmation either): it is what lets a
  matched word start changing his room's colours while that song plays.
- **`preview_lyric_events` GOES OVER HTTP, DELIBERATELY, UNLIKE EVERY OTHER
  OP HERE.** It needs the exact same answer the Test Bed's Word actions
  row shows — including which drop/scene change/flare a word imprints on
  — which needs `TriggerEngine.song_event_moments`'s own event
  candidates. Reaching that by import would pull `lyric_console.py` into
  the whole live engine stack (`engine.py`/`scene_response.py`/
  `drift_conductor.py`/`fx_executor.py`) this module's own "NO LIGHT
  OUTPUT, NO TRIGGER WIRING" boundary exists to keep it out of — so
  instead it calls the real route (`GET /api/testbed/lyric-events`)
  through `lyric_console.http`, SPECTRA's own HTTP layer calling itself
  (`root.mount("/spectra", create_app())` in `spectra/app.py` means even
  SPECTRA's own port answers under `/spectra/...`; `settings_agent.
  dispatch_url()` is the existing precedent for this same self-loopback,
  as opposed to `lock_console.py`'s call to the separate ROOT spotfx
  process). Tests replace `http` with a fake backed by a real `TestClient`
  over the real router (`lock_console.py`'s own test precedent, see
  `lyric_events_route` in `tests/test_lyric_console.py`) — never a socket,
  live or otherwise.
- **`song_event_moments` IGNORES HIS OLD `source=="authored"` TRIGGERS,
  2026-11** (the Admiral: "we should only focus on the analysed
  triggers... [old triggers] shouldn't be part of any future work"): it
  builds its candidates and resolves its per-song mode from the song's
  non-authored triggers only, so word colours land the same whether or
  not a song also carries his old hand-placed rows. Scoped to this
  preview path alone — ordinary flare/drop firing (`tick()`,
  `plan_analysed_flares`, live drop-sequence detection via `_drop_view`)
  still reads the real triggers and can legitimately disagree with the
  preview for a song that has them; see the function's own docstring
  before changing either side.
- **A SONG IS A SEARCH, NOT A `resolve_name` CANDIDATE DUMP.** His library
  can hold hundreds of analysed songs, so `_resolve_song` caps a clean
  miss's `known_names` fallback (`SONG_CANDIDATES_SHOWN`) rather than
  listing every song — the same reason the Jukebox's own song search is a
  bounded search, not a flat name list (AGENTS.md). A colour set or effect
  name still uses `name_resolve.resolve_name` verbatim (its library is
  small enough).
- **What stays off-limits, deliberately**: the automatic reader's own
  pacing constants (`SWEEP_POLL_S`/`READ_GAP_S`/`LABELS_QUIET_S`/
  `FAILURE_BACKOFF_S`) are a hand-picked pace, not a setting — nothing
  exposes them to him either. Deleting a colour set or an effect's own
  registration stays the Colours page / the effect registry's job.
- **A COMMON BUG WHEN EXTENDING THIS**: `lyric_matches.payload()`'s own
  `status` field is the SONG'S WORD-TIMELINE status (ok/none/invalid/
  stale), never an operation outcome — splatting that dict into a write
  result AFTER setting `"status": "applied"` silently overwrites it.
  `lyric_console._applied(data, **extra)` is the one helper that renames
  the timeline's status out of the way; use it for any new write that
  returns a `lyric_matches.payload()`-shaped dict.

## Files

- `spectra/models/lyric_labels.py` — every stored shape (`SungLabelStore`,
  `SongMatches`, `Reading`, `ClaudeGuess`, `HisMatch`, `LyricEventStore`,
  `LyricEventSettings`, `LyricShowState`).
- `spectra/services/{sung_labels,lyric_matches,lyric_reading,color_meanings,
  colour_words,claude_text,lyric_events}.py` — the mechanism (see each
  module's own docstring).
- `spectra/api/{sung_labels,lyric_matches,lyric_events}.py` — the page's
  own routes (the last one is the Test Bed's Word actions row, and the
  route `preview_lyric_events` below calls over HTTP).
- `spectra/web/src/sunglabels/{SungLabelsPage.tsx,sungLabels.ts}` — the
  correction page.
- `spectra/web/src/testbed/` — the Sung words lane, Word events row, Word
  matches row and Word actions row (`TestbedLaneBar.tsx`/`TestbedPage.tsx`/
  `lyricEvents.ts`).
- `spectra/api/upcoming.py` (`with_words`), `spectra/web/src/components/
  {songStrip.ts,trackPainter.ts,SongNextBox.tsx,SongStrip.tsx}`,
  `spectra/web/src/lib/wordColourPush.ts` — the highlight on the strip,
  Home and the next-event box, and the fire-time flash.
- `spectra/services/lyric_console.py` — Sonic's `lyrics` domain, wired into
  `spectra/services/settings_agent.py`'s `_DOMAIN_OP_DICTS`/
  `ALL_OPERATIONS`, with its MCP wrappers in `settings_mcp_server.py`.

## Specs

`tests/test_sung_labels.py`, `tests/test_lyric_reading.py`,
`tests/test_lyric_events.py`, `tests/test_lyric_console.py` (the Sonic
domain — round trips, the ask-first flow for both Claude-spending ops and
the auto_read/word-colours-show on/off asymmetry, the import boundary
proof, and `lyric_events_route` — the real-`TestClient`-backed fixture
`preview_lyric_events`'s own tests use instead of a live socket),
`tests/test_scene_console.py::
test_dispatch_recognizes_exactly_the_declared_operation_set` (the
exhaustive merged-dispatch proof — update its hand-imported domain list
when a domain is ADDED, not just when an op is added to an existing one),
`tests/test_settings_agent_cli.py::
test_the_lyrics_domain_widening_parses_from_its_structured_tool_result`
(the CLI/MCP manifest widening — every "current manifest" synthetic
fixture's `tools` array needed the new tool names added, per the
sonic-ops skill's own step 7, each time this domain widens). Help:
`sung-labels-reading` (no cut-off any more, and Sonic reach),
`testbed-word-chance` (the roll, keep, sample, pins) and
`testbed-word-colours` (the switch/tuning/preview Sonic reach) in
`spectra/web/src/help/helpContent.ts`.
