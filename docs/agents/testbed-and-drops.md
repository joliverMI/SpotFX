# The music-analysis test bed and drop detection

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## The music-analysis test bed (`/testbed`)

Capability state and honest deployment status: `docs/SPECTRA_SPEC.md` §109.
Admiral-approved phased build, 2026-09-09, grounded in
`data/spotfx-music-analysis-plan/report.md` (read that report before
touching any of this — it has the real measurements: today's librosa
section-boundary detector recalls only 7-10% of his hand-placed marks at
±500ms, and beat_this (CPJKU 2024) roughly doubles downbeat F1 over the
current pipeline at the same tolerance). A read-only comparison surface
with exactly one write exception (push-to-real), extending the ported
timeline surface family (`ReviewLaneBar`'s read-only multi-lane pattern,
above) rather than inventing a parallel one.

**Backend**, all in `spectra/services/testbed_*.py` +
`spectra/api/testbed.py` (`/api/testbed/*`, mounted in `spectra/app.py`):
`testbed_marks.py` reads his real marks from the FIRED trigger copy
(`trigger_store`, not the legacy editor copy — same "TWO trigger copies"
choice the plan report itself makes, with the editor copy's own trigger
COUNT + `ai_generated`/`verified` provenance surfaced as a caveat, not a
second definition of "his marks"), split transitions
(`fire_scene`/`fire_scene_update`) vs flares (`fire_response`/
`select_color_set`). **ONLY `source=="authored"` rows are reference marks**
— `midsong_generator` seeds a generated `fire_scene` at every librosa
section boundary, the librosa engine's own `section_boundary` times, and
63% of his stored songs hold nothing else, so admitting them would grade
librosa against itself; the excluded rows are counted (`n_generated` on
`/songs` and `/marks`) and a generated-only song stays listed with an
honest "no authored marks yet" lane/metrics state instead of an empty
comparison. **A TEST-BED-PROMOTED ROW IS NOT SCORED EITHER** — the same
circularity through the authored door: push-to-real lands a suggestion
`source="authored"` at the suggesting engine's OWN exact `time_ms`, so
every promotion would lift that engine's own P/R/F1 on the next look.

**The song LIST (`all_song_marks()`) has a second exception on top of the
above, 2026-11**: a song with cached analyzed triggers
(`services/analyzed_trigger_store.py`, top-level SpotFX —
`storage/analyzed_triggers/<track_id>.json`, read there as a plain dict,
never through that module's own pydantic models or
`services.training_profile_manager`, per the S3 import-discipline rule)
is listed FROM THOSE instead of `trigger_store`, even if it also has old
rows there. A song with only old `trigger_store` rows and at least one
`source=="authored"` row, and NO analyzed cache, is still listed but with
NO reference marks at all in the LIST specifically (the Admiral: his old
hand placements "shouldn't be part of any future work") —
`marks_for_song()`/`reference_marks_for_song()` (the per-song detail and
`/compare` routes) are deliberately left reading the old rows exactly as
before; only the list's own "does this song have work to review" read
changed. **Mind the naming collision**: `services/analyzed_trigger_store.py`
("analyzed", SpotFX's embedded-engine cache keyed by bare `track_id`) and
`spectra/services/analysed_flares.py` ("analysed", SPECTRA's own
midsong_generator-derived plan, keyed into `trigger_store`'s `source==
"generated"` rows) are two UNRELATED systems that happen to share a name
root — do not conflate them when touching either.

Nothing on the trigger can tell it from a hand-placed one (that is
deliberate — see below), so `testbed_promote` keeps its OWN provenance
store: `promoted_ids.json` (`{uri: [trigger_id, ...]}`, **never
truncated**) → `promoted_trigger_ids()`/`promoted_ids_by_uri()` →
`ReferenceMark.promoted`. **That is a SECOND store beside the bounded
`promotions.json`, and the split is the point** — the display log caps at
`_LOG_MAX_ENTRIES` and refusals share that budget, so sourcing the
exclusion from it meant an evicted promotion silently read as
hand-authored again and re-entered `scoring_marks()`, with the lane tint,
the `n_promoted` count and the metrics note all quietly stopping saying
so. The reads UNION the durable index with whatever the log window still
shows, so an install that promoted before the index existed keeps its
provenance with no migration; the union can only ADD ids. The exclusion is VISIBLE, never silent — the
mark stays in `transitions`/`flares` flagged, is drawn in its own dashed
tint with an "excluded from scoring" label, is counted (`n_promoted`), and
is dropped only by `testbed_marks.scoring_marks()`, the ONE definition
both `reference_marks_for_song()` (the `/compare` route) and the page's
own local matcher apply. `testbed_metrics.py` is the greedy nearest-neighbor
precision/recall/F1 matcher — the report's own methodology, made
executable — with a deliberate byte-for-byte TypeScript port
(`spectra/web/src/testbed/metrics.ts`) so the frontend's tolerance slider
recomputes instantly with no round-trip; `scripts/check_testbed_metrics.mjs`
cross-checks both sides against the same fixed vectors. `testbed_engines.py`
is the engine registry: `librosa` derives marks LIVE from the
already-computed `.librosa.json` (via `analysis_reader.py`, which gained
`beats_for_uri()` alongside its existing `sections_for_uri()`); `beat_this`
reads from an OFFLINE precompute cache (`testbed_cache.py`,
`storage/spectra/testbed/analysis/<engine>/<uri>.json`) — never re-run in
the request path (some engines take 80-560s/song per the report's own
timings). `testbed_beatthis.py` is the actual `beat_this` call
(`File2Beats(checkpoint_path="final0", dbn=False)` — `dbn=False` is
load-bearing, it's what keeps madmom out), invoked only by
`scripts/testbed_precompute.py`; `beat_this` is an OPTIONAL dependency
(`requirements-testbed.txt`, mirroring `requirements-capture-client.txt`'s
precedent) — code and published checkpoints are both MIT-licensed (checked
before shipping; unlike madmom's CC-BY-NC-SA models), and an uninstalled
host reports the engine "unavailable" rather than crashing anything.
**`GET /api/testbed/songs` is ONE read per store, off the event loop, and
it never PARSES an engine's output at all** (`trigger_store.list_all` +
`testbed_marks.all_song_marks` + `analysis_reader.stem_index` +
`testbed_promote.promoted_ids_by_uri`, composed in `spectra/api/testbed.py`'s
`_song_list` under `asyncio.to_thread`, the `sync-from-profile` precedent) —
never loop `marks_for_song`/`stem_for_uri` over the corpus in a handler: the
former is a full ~9.5MB `triggers.json` parse PER SONG, and the latter
rebuilds the whole audio-shape sidecar index on every MISS, i.e. once per
stored song with no captured audio. The listing passes
`availability_for(..., count_marks=False)`, which answers each engine's
availability with a STAT (`analysis_reader.has_librosa_analysis` /
`testbed_cache.has_cache`) and reports `mark_count: None` rather than a
fabricated 0 — parsing every song's `.librosa.json` to build marks the
payload discards is 965 files / 417MB of his real storage per request, and
this listing is re-fetched on every pin, unpin and promotion. The full
parse stays on `/engines` and `/engine-marks`, one song each. The song list also carries each song's
`title`/`artist` from the same one-pass profile scan its provenance comes
from, so the page never fans out one `/api/profiles/by-uri` per song. A pin
(a full WAV copy + decode) runs under `asyncio.to_thread` too, which is why
`testbed_audio` locks its registry read-modify-write — and because that
worker thread rebuilds `analysis_reader`'s uri→stem index while the loop
thread reads it every tick, `_build_index` REBINDS a fresh dict and never
clears in place (`tests/test_analysis_reader_index.py`). The page's
per-lane fetch is `GET /api/testbed/engine-marks` (one engine's marks,
nothing else — the slider matches locally); `/compare` is the
server-computed number at a fixed tolerance and reads the fired copy only,
never the profile directory.

**Test-bed audio retention is its OWN policy** (`testbed_audio.py`,
Admiral-approved test-bed pinning), deliberately independent of
production's `settings.audio_wav_max_songs`/`librosa_service.
manage_wav_retention()`: pinning COPIES a song's current WAV into
`storage/spectra/testbed/audio/` (never moves/symlinks) — a directory
`manage_wav_retention()`'s own glob (scoped to `AUDIO_SHAPES_DIR` only)
never reaches, so a pin structurally cannot be evicted by production's LRU
cap, and unpinning never touches production's own copy. Peaks (a
downsampled min/max waveform-lane render) are computed once at pin time.
The waveform lane falls back to production's `.npz` RMS-envelope shape
(retained for every played song, unlike the WAV) when nothing is pinned,
labeled honestly as coarse rather than silently rendering nothing.

**A PINNED WAV'S SAMPLE 0 IS NOT SONG-TIME 0** — a capture starts mid-song,
so a waveform drawn from the left edge sits EARLIER than every mark lane by
the capture lag (5-10s, the code's own figure). `testbed_audio.
capture_offset_ms(uri)` is the one resolver and `/waveform` carries it on
the `wav_peaks` payload, resolved at READ time so a pin taken before this
existed gets it too. It reads the `.npz` sidecar's own first
`timestamps_ms` — the song-relative stamp `AudioCaptureStream` gave the
first PCM it held — and **deliberately NOT `LibrosaAnalysis.
librosa_offset_ms`**, which this file already records as unreliable. `None`
means genuinely UNKNOWN: the lane then relabels itself "start time
unknown", greys its trace and captions that it is not aligned, rather than
drawing at a position it cannot justify. The page's own timebase counts a
WAV as ending at `capture_offset_ms + duration_ms`, since `duration_ms` is
the recording's LENGTH and not the song's end.

**Push-to-real is gated, structurally, not by UI convention**
(`testbed_promote.py`): `promote()` refuses (`PromotionNotConfirmed`,
writes nothing, logs the refusal) unless `confirmed=True` arrives on the
call itself — there's no way to "confirm once and it stays confirmed."
`PromotionReviewDialog.tsx` is the ONLY component wired to the promote
mutation, and only from its own explicit "Confirm & push" button, never the
mark-click that opens it. **It also DISCLOSES the consequence**: under
`scene_change_mode == "triggers_only"` (his live setting) a song holding
≥1 authored trigger fires ONLY authored triggers, so on a song with none
yet this push does not ADD a mark — it REPLACES that song's whole
automatic show with it. The dialog reads `useRoomControls()` +
`useTestbedMarks()` and says so plainly when both conditions hold.
Disclosure, NOT a gate: Confirm stays enabled and nothing about
`room_controls` or the firing rules is touched. The write lands in the
FIRED copy only
(`trigger_store.upsert`, `source="authored"`, `generator_key=None` — never
"generated," so front 3's regeneration/ownership-transfer rule can never
silently claim a promoted trigger back), through
`trigger_store.validate_action()` — the SAME reference-integrity check
`spectra/api/triggers.py`'s human-authoring POST uses (lifted out of that
module's own `_validate_action`, which is now a thin 422-mapping wrapper
over it, specifically so both write surfaces share one choke point and
can't diverge). Every attempt, accepted or refused, is appended to a
durable, bounded audit log
(`storage/spectra/testbed/promotions.json`, `GET /api/testbed/promotions`)
— the visible proof the button cannot write silently. That log is HISTORY
for a human; the scoring exclusion reads the unbounded
`promoted_ids.json` beside it (above), and a new store here needs its own
`tests/conftest`-style repoint in every testbed test fixture or it writes
into the real `storage/spectra/testbed/`. **A repeat confirm
is refused, never stacked**: an authored trigger of the same action kind
within `testbed_promote.DUPLICATE_WINDOW_MS` of the moment refuses by name
(`PromotionDuplicate`, HTTP 409, logged `reason="duplicate"` with the
existing id) — every call mints a fresh id, so without it the second
confirm of one click would land a double-fire on one tick. **The fired
copy's writers are serialised by `trigger_store.write_lock`, AND NONE OF
THEM RUNS ON THE EVENT LOOP** (re-entrant; held inside `upsert`/`delete`/
`apply_batch` across each load+save, and by `promote()` across its
duplicate check AND the write): an unserialised read-modify-write of the
whole file loses whichever write landed first. Serialising is only half of
it — a WAITER must not be the loop. `POST`/`DELETE`/`generate`
`/api/triggers` therefore hand their store calls to `asyncio.to_thread`
alongside `sync-from-profile`, the generator and the promotion: the
promotion's critical section is two whole-file parses plus a rewrite, so a
route awaiting that lock inline would park the 200ms trigger tick, the
bridge poll and every WS broadcast behind one Timeline save. A new
check-then-act on this store holds that lock itself; plain reads never
take it; a new MUTATING caller goes on a worker thread. Proof:
`tests/test_trigger_store_write_lock.py` (both the lost-update shape and
the real routes' own thread, verified RED against an inline call).

**Frontend**: `spectra/web/src/testbed/TestbedPage.tsx` (`/testbed`, "Test
Bed" nav link, route-mapped in `routeTopics.ts`) — song picker, an A/B
engine picker, `TestbedLaneBar.tsx` (waveform/energy lane + his marks +
up to two engine lanes, green/amber/red tinting by match tightness — the
`ReviewLaneBar` pattern generalized to N lanes), `TestbedMetricsPanel.tsx`
(live P/R/F1 table + tolerance slider), and `PromotionReviewDialog.tsx`
(the review gate's UI half). **A TINT MEANS WHAT THE LEGEND SAYS**: the
dim/grey `extra` swatch is documented as an ENGINE mark with no match to
any of his, so his OWN marks under a no-metrics condition (the selected
engine has nothing precomputed for this song — every song today for
`beat_this`) render `unscored`, never `extra`; nothing was compared, so
neither "matched" nor "over-segmented" is true of them.
**EVERY LANE IS THE SAME `ms / durationMs`
SCALE** — the waveform used to position its buckets by INDEX across the
full lane width, so it drifted against every mark lane beside it by
whatever the timebase exceeded the WAV's own duration; `durationMs` is
also a REAL duration wherever the song has one (no `×1.05`/`×1.02` padding
putting a length on the axis label the song does not have). **The engine
picker is driven by the `/songs` payload's own `engines` map**, not a
hardcoded frontend copy of the registry — a third engine registered in
`testbed_engines.ENGINES` appears with no frontend edit; only pretty
mark-kind labels are local, with a raw-key fallback. Help:
`analysis-testbed` section + `testbed-promotion` entry in
`helpContent.ts`, both linked (not orphaned) — `testbed-promotion` from
`PromotionReviewDialog`'s own header as well as the promotion-history
card, since that card only renders once a promotion exists.

Executable specs: `tests/test_testbed_*.py` (marks split/provenance,
metrics matcher, audio pinning + production-eviction independence, engine
registry, the guarded beat_this call, the promotion gate, and a full
`TestClient(create_app())` route-shape pass) + `scripts/
check_testbed_metrics.mjs` (TS/Python parity).

**Every engine mark is stored in WAV time; his reference marks are song
time — shifted at `spectra/api/testbed.py::_estimate_for`, the one choke
point both `/compare` and `/engine-marks` (and therefore the page's
`metrics.ts` port) go through** (`data/music-analysis-octave-scout/
report.md`, "Work that should ship" #1). A production capture starts
mid-song (URI detection lags 5-10s), so `librosa_marks_for_stem`'s raw
`beats[].ms` and `testbed_beatthis.compute_marks_ms`'s raw
`s * 1000` are both WAV-relative, not song-relative — on a song whose
capture started ~4s in, every engine mark was scored ~4s early before this
fix, which happened to read as a coincidental win on the one song (Soy
Peor) whose bar length made the phase land close anyway. The shift is
`testbed_audio.capture_offset_ms(uri)`, applied once here (never inside
`testbed_metrics.match_marks`/`metrics.ts` — the inputs move, not the
matcher); `None` (unknown offset) is treated as 0, the pre-fix behaviour.

**Tolerance has a PER-LANE default, not one flat number** (same report,
"Work that should ship" #2): at a flat 500ms a beat lane cannot lose on
any song above 120 BPM and a downbeat lane cannot tell a downbeat from the
beat next to it (El Apagón: librosa downbeat F1 0.46 at 500ms vs 0.07 at
150ms, median signed offset +470ms on a 499ms beat). `TestbedPage.tsx`'s
`laneDefaultToleranceMs`/`effectiveDefaultToleranceMs` compute
`min(200ms, 0.4 × the song's beat length)` for a beat/downbeat lane and
500ms for section boundaries, using the TIGHTEST default across whichever
lane(s) are active (the page has one shared slider, not one per lane); the
slider still moves freely to any value, including 500ms, and a "Reset to
default" control appears once he has moved it. The song's beat length
comes from `analysis_reader.tempo_bpm_for_uri` (librosa's own `tempo_bpm`
field), carried on `GET /api/testbed/marks`'s `tempo_bpm` key — the one
extra `.librosa.json` read the page already pays for via `/engine-marks`.
Help: `analysis-testbed` §`testbed-lanes-and-tolerance` and
§`testbed-engines`, updated in the same change (both already linked).

## Sung words on the test bed (lyrics plan, step 2 — no effect on the room)

`spectra/services/lyrics_timeline.py` is the binding statement for the clock
and what gets flagged, `lyrics_emphasis.py` for the pure score, `lyrics_sidecar.py`
for the file and its freshness; `scripts/import_lyrics_sidecars.py` is the
only way a timeline gets in (dry run by default). Four things:

- **ONE CLOCK: THE CAPTURE'S LABELS.** A word's `ms` and a trigger's
  `timestamp_ms` are both on it, so a word and a flare at the same number
  coincide in the room; nothing converts either. `wav_ms` is only for
  comparing a word with librosa's beats. Not `wav_ms + capture_offset_ms`:
  that naive sum is where his marks were placed (the Timeline's beat grid) and
  parts from the labels on about a third of the library, so a song slipping by
  more than `SLIP_FLAG_MS` is flagged, keeps its words, and loses its guide
  lines and scores. Timing row: `docs/SPECTRA_TIMING_CONVENTIONS.md`.
- **A `.lyrics.json` IS IN THE CAPTURE-SIDECAR DIRECTORY.** Every `*.json` scan
  of `storage/audio_shapes` must skip it by name, or it parses each timeline
  (~100 KB) — `analysis_reader._build_index` does that on the event-loop thread
  on any miss. A new scan of that directory owes the same skip.
- **A RECAPTURE MAKES EVERY WORD TIME WRONG**, so reads compare the stamped
  `.npz` hash and WAV stat and a mismatch reports `stale` and draws nothing. A
  missing WAV alone is not stale (the retention cap deletes them; the labels
  are in the `.npz`).
- **NOTHING IN THE SHOW READS THIS.** Held by `tests/test_testbed_lyrics_lane.py`
  (who may import these modules) and by `testbed_promote.READ_ONLY_ENGINES`, so
  the lane cannot reach his real triggers. The score, slider and word lists are
  recomputed on every read and stored nowhere. **Labels and matching are built
  (step 3, "Sung labels and word matches" below) — `matched_label` on a mark is
  now read from `lyric_matches.labels_by_word`, not unset.** Colour and imprints
  are still step 4.

## Word colours and imprints (lyrics plan, step 4 — off for every show)

`spectra/services/lyric_events.py`'s docstring is the binding statement; this
section is what is not obvious from it. His rulings are in
`/home/javi/fleet-spotfx/data/lyrics-timing-plan/grilling-notes.md`.

- **One show = one song, by URI.** `LyricEventStore.shows` in
  `storage/spectra/lyric_events.json`; absent means off, and an unreadable file
  reads as off. The switch and the three settings are on the Test Bed; the Word
  actions row is that same `plan_words`, built for any song by
  `TriggerEngine.preview_lyric_events`.
- **Off means off, and is proven.** `tests/test_lyric_events.py::
  test_with_the_switch_off_the_output_is_exactly_an_engine_without_the_feature`
  drives a real engine with a word beside every event against a control engine
  built without the feature, and proves the words are never even read.
- **An imprint is NOT a second colour path.** It rides `lyric_events.ACTIVE`
  through the event's own fire and the existing paths read it where they would
  otherwise pick a colour: `drop_color_change`, a scene fire's explicit colour
  set, a flare's or update's colour jump. A staggered colour jump carries it on
  `PendingKindBatch.lyric`, the way it carries the drop-colour-done flag.
- **The chooser is the shipped one** (`ResponseEngine.lyric_pick`, the colour
  ladder over `automatic_pool_cards`), so a set with no selector entry is not a
  candidate unless the selector has no entries at all, exactly like every other
  colour pick.
- **What a word cannot know ahead of the song** (which scene will show, so whether
  it allows the colour or its band can carry it) is decided at fire time and
  named on the show log (`triggers` bucket, keys `lyric:fire` / `lyric:imprint`,
  drawn by `describeEvent.ts`). The Word actions row says so rather than guessing.
- **Conservative calls beyond the rulings, flagged for his tuning:** a scene
  change naming its own colour and a `select_color_set` trigger both count as
  events that cannot carry colour (his authored colour stands, and no word fires
  on top of it). The gap is applied strongest-first, like everything else here.
- **Held colour** pauses the journey only (`DriftConductor.hold_for_lyric`,
  `held_for: "lyric_word"`), and ends on the next scene fire, the next word that
  lands, a song change, or the switch going off. Flares and drops still change
  colour during it, as they would without one.
- **The highlight (2026-11-12, the Admiral: "Add a visual highlight to scene
  changes and flares and drops that are getting a word related effect"; his
  pick, option A + E's live pulse, in `/home/javi/fleet-spotfx/data/word-
  effect-highlight-options/report.md`).** Every `/api/upcoming` row carries
  the trigger id tick() fires, and `upcoming.with_words` joins the same
  `plan_words` output onto it by that id (`lyric_events.word_marks`): an
  imprinted event gains `word`/`swatch` (the FIRST candidate set's swatch,
  `WordHit.swatches`, as the Word matches row draws it) and a fire-alone word
  is its own `kind: "word"` row, counted down to like any event. The strip
  and Home draw a halo ring / a diamond in that colour (`songStrip.ts`,
  `trackPainter.ts`), the next-event box rings the kind's own glyph with the
  word under it, and the Test Bed's **Word events row** (which REPLACED the
  "His scene changes"/"His flares" rows — they drew a different mark set from
  the events a word can reach) draws the same events and feeds the lane's
  guide lines. At fire time `lyric_events.fired_payload` is pushed as
  `{"type": "word_colour"}` (`TriggerEngine._lyric_fired` → `engine._push_
  word_colour`) so the marker and the box flash in the set that really
  landed. Words that do nothing draw nowhere outside the Test Bed. No engine
  timing change; see `.claude/skills/sung-labels/SKILL.md`'s "The highlight".
- **Sonic coverage, built.** `lyric_console.py` reads and changes the per-show
  switch and the three tuning settings (`get_lyric_event_settings`/
  `set_lyric_event_show`/`set_lyric_event_settings`), and answers "what would
  this word do" (`preview_lyric_events`) — the exact `plan_words` output this
  section describes, including imprints. Turning a show's switch ON asks first,
  the same "newly lets it act" shape as `sung_labels.auto_read`; the tuning
  settings are shared by every show, so changing them applies at once.
  `preview_lyric_events` is the one op in this domain that goes over HTTP
  (`GET /api/testbed/lyric-events`, SPECTRA calling its own `/spectra`-mounted
  app) rather than an import: reaching `TriggerEngine.preview_lyric_events`'s
  own event candidates by import would pull `lyric_console.py` into the whole
  engine stack (`engine.py`/`scene_response.py`/`drift_conductor.py`/
  `fx_executor.py`) its own "NO LIGHT OUTPUT, NO TRIGGER WIRING" boundary keeps
  it out of. See `.claude/skills/sung-labels/SKILL.md`'s "Sonic reach" section.

## Sung labels and word matches (lyrics plan, step 3 — off the room unless word colours are on)

`spectra/services/sung_labels.py` is the binding statement for the list,
`lyric_reading.py` for how Claude reads a song against it, `lyric_matches.py`
for what a match is, `colour_words.py` for the seed and `claude_text.py` for
the one Claude call (Sonic's account and switch, `SPECTRA_LYRIC_AGENT_MODEL`
to point it elsewhere). `/sung-labels` is the one correction page; the matches
are the Word matches row under the Sung words lane. Five things:

- **THE ONLY THING IN THE SHOW THAT READS THIS IS WORD COLOURS, ON A SHOW HE
  HAS SWITCHED ON** (the section above), lazily and off the event loop.
  `tests/test_lyric_reading.py` holds that starting the show pulls none of it
  in, and automatic reading (`SungLabelSettings.auto_read`) ships off: until he
  switches it on, only a press reaches Claude.
- **HIS EDITS ARE STORED APART FROM WHAT IS COMPUTED.** A label edit is a delta
  over the seed (`LabelEdits`), a meaning edit a delta over Claude's `draft`,
  and a match's reading is separate from his `his` and `deleted` lists. Only
  the computed half is ever replaced, which is the whole of why a re-draft, a
  re-read or a recapture cannot touch them. A new thing he can edit needs the
  same split.
- **A MATCH SITS ON WORDS, NOT TIMES.** It stores word positions and what they
  said; its `ms`/`end_ms` come from the current word timeline at read time, so
  a recapture cannot leave a stale time behind.
- **CLAUDE READS ONE LIST OF DISTINCT LABELS, AND WHO CARRIES A LABEL IS ANSWERED
  AT READ TIME.** So `labels_hash` covers only the words: moving a word from one
  card to another needs no re-read. Both stores raise rather than read a torn
  file as "no edits" (`StoreUnreadable`).
- **THE SEED IS COMPUTED ON READ, NOT WRITTEN.** Nothing is migrated to deploy
  this, and `storage/color_sets.json` is never written by it (SPECTRA does not
  write that file).

**SONIC'S FOLLOW-UP, BUILT** (the Admiral's standing Sonic coverage
protocol, 2026-10-06): `spectra/services/lyric_console.py` (domain
`lyrics`) reads and changes sung labels/meanings, shows and edits a
song's word matches (a match is named by its PHRASE, never its opaque
id), and reads/changes the auto-read switch and the weak-match
threshold — `WEAK_MATCH_THRESHOLD` is no longer a bare module constant:
`SungLabelSettings.weak_match_threshold` (default 0.6) is a real,
persisted setting `read_song()` reads live, so he (or Sonic) can actually
tune the "first guess, his to tune" the module docstring always promised.
Turning `auto_read` ON, drafting colour meanings and reading a song's
lyrics all ask first — the last two on EVERY call, since each one spends
his Claude allowance regardless of whether it's the first. A song is
resolved by a bounded search, not `name_resolve`'s own `known_names`
fallback verbatim — his library can hold hundreds of analysed songs.
See `.claude/skills/sung-labels/SKILL.md` for the cold-start map.

## Phase 2 of the music-analysis plan — snapping generated cues to a beat

2026-09-22, the Admiral's decision on `data/music-analysis-octave-scout/
report.md`'s open questions: "we are still using the old transition
detection, but we are pinning it to a beat for better precision... go for
it." `spectra/services/beat_snap.py` is the binding statement. Section
detection (`midsong_generator.py`) is UNCHANGED — it still decides which
moments get a generated cue and roughly when. This module only nudges
WHERE, within one beat, a generated cue's stored `timestamp_ms` actually
lands: onto the nearest downbeat of a per-song grid.

**Grid choice is the scout's own measured discriminator (Q1), not a
preference**: beat_this's downbeats only win when its precompute exists
for the song AND its tempo reads at roughly HALF of librosa's own
(`beat_snap.HALF_TIME_RATIO=0.6`) — the phrase-length grid his Soy Peor
marks actually sit on (his own separate ruling, "every 8 is good").
Otherwise librosa's own downbeat grid is used; NO LIVE beat_this
execution is ever attempted from this path. A section boundary and both
downbeat grids are all computed by analyzing the SAME captured WAV (the
same librosa `y` array for librosa's own beats, beat_this's own offline
precompute over that same file for the other), so they already share one
coordinate frame — this module compares them RAW and applies NO
capture-offset shift (a same-frame comparison;
`testbed_audio.capture_offset_ms_or_zero(uri)`'s WAV-time -> song-time
shift belongs only to `spectra/api/testbed.py::_estimate_for`'s own
CROSS-frame comparison against genuinely song-time authored marks, and
shifting a same-frame grid by it would have introduced a constant bias
into every snap decision). A nearest downbeat farther than one beat
length (`60000/tempo_bpm`) away is left UNSNAPPED — the section's own raw
time survives untouched rather than being dragged that far.

**Provenance, not a second trigger schema**: `SpectraTrigger.snap_grid`/
`snap_moved_ms` (`spectra/models/trigger.py`) record which grid a
generated cue snapped to and how far, both `None` for a hand-placed
trigger or an unsnapped cue. Editing a generated, snapped trigger clears
both fields too: `spectra/api/triggers.py`'s `upsert_trigger` already
stamps every human-facing write `source="authored"` (front 3's
ownership-transfer rule, above) and now resets `snap_grid`/
`snap_moved_ms` to `None` in that same stamp, so a hand edit never
carries forward a stale snap that no longer describes where he placed it.
`midsong_generator.candidate_moments`'s `generator_key` stays keyed on
the section's own RAW (unsnapped) start_ms — the analysis moment, never
the snapped position — so toggling the setting between runs UPDATES the
same generated trigger in place rather than deleting and re-adding it
under a new key.

**`RoomControlState.midsong_snap_to_beat`** (default `True`, his own "go
for it") gates the whole thing, read live by `candidate_moments` on every
generation pass — no restart needed. UI: a power-button toggle in the
Scenes panel (`RoomControlsBar.tsx`), next to the scene-change tier, help
topic `midsong-snap-to-beat`. Surfaced two more places, additively: the
Review page (`trigger_engine.py`'s `fire_history.record_fire` call for a
trigger fire carries `snap_grid`/`snap_moved_ms` in its `detail` when set,
rendered by `describeEvent.ts`'s `triggers` case) and the test bed
(`testbed_marks.SongMarks.n_snapped`/`snap_grid_counts`, a per-song
GENERATED-cue summary — never a scored reference mark, since only
`source=="authored"` rows are ever scoring marks).

Acceptance measurement (offline, read-only against the live checkout,
never against this worktree's own `storage/`):
`scripts/check_midsong_beat_snap.py` — runs `generate_for_song` twice per
reference song (snap off, snap on) against fresh throwaway trigger stores,
then scores the generated cue timestamps against his REAL authored marks
(read separately, never copied into the temp store) with the test bed's
own `testbed_metrics.match_marks`, at 150ms/500ms, against both
transitions and flares. El Apagón is reported but never weighted in a
verdict (his own word).

### The frame fix — a generated cue was placed in the WRONG TIME FRAME

2026-09-23 (`data/transition-alignment-plan/report.md` §2.1, his own
report: "the song transitions are not well aligned... a few beats off").
A section boundary's `start_ms` is in the CAPTURED-WAV's own frame
(`services/librosa_service.py` places every boundary on a beat of the
WAV, not the song), but the room's fire clock and his own authored
triggers both run in SONG time — and most captures start several seconds
into the song (URI-detection lag). So every generated cue used to fire
that many ms EARLY, together, on every song whose capture didn't happen
to start at song time 0 (17,226 of 19,490 real generated cues sat on a
song with a 2s-or-more gap). `midsong_generator.candidate_moments` now
shifts a section's raw boundary by
`testbed_audio.capture_offset_ms_or_zero(uri)` (the WAV's own sample 0,
expressed in song time) before placing OR snapping it — `_shift_song_grid`
shifts `beat_snap`'s own downbeat grid by the identical amount first, so
`beat_snap.py`'s own "ONE FRAME, NO SHIFT" comparison stays true of the
frame this caller chose (WAV time for its raw grid, song time once
shifted) rather than beat_snap.py itself needing to know about capture
offsets. `generator_key` is unaffected — still keyed on the section's own
unshifted, WAV-time `start_ms` — so a recapture that changes the offset
UPDATES the same stored trigger in place. Zero measured offset (no npz
sidecar yet, or a capture that genuinely started at song time 0) shifts
by exactly 0 — byte-identical to before this fix.

The same frame mismatch existed one line over: `analysis_reader.
section_energy_at` (the intensity `bridge.intensity()` reads for every
automatic, non-authored fire — the drift conductor, the sequencer's
default pick, automatic transition fires) compared a caller's song-time
position against sections' own WAV-time bounds. Fixed the same way,
inside `section_energy_at` itself (shifts each section's bounds by the
same `capture_offset_ms_or_zero`), with the offset CACHED per URI
(`analysis_reader._capture_offset_for`, a lazy import of `testbed_audio`
to avoid the circular import — `testbed_audio` already imports
`analysis_reader` for `stem_for_uri`) — this function is read on the
event-loop thread every ~200ms trigger-engine tick, and the offset's own
source (an `.npz` file read) has no caching of its own, so an uncached
call would put synchronous file I/O on that hot path. **The cache entry
is keyed on the sidecar `.npz`'s own `(mtime_ns, size)`, not just the
URI** — a cheap `stat()`, not the file parse itself — so it SELF-HEALS on
a live recapture: a plain per-URI-forever cache was tried first and shipped
briefly, then caught by review before it went further (a recapture mid-
session would have kept reading the old offset for the rest of the
process life). Missing stem or missing `.npz` both key on signature
`None`, so a song with no audio yet caches its 0 offset the same way
until a capture actually lands.

Acceptance: `scripts/check_transition_alignment.py` extends
`check_midsong_beat_snap.py` with a "Today" vs "Frame fixed" vs "+ Snap"
three-way comparison (offline, read-only against the live checkout, on
copies) — reproduces the report's own one-beat recall numbers exactly
(Soy Peor 7%→14%, Contra/Dopamine/El Apagón unaffected since their real
capture offset is 0). Unit tests: `tests/test_midsong_generator.py` (a
synthetic nonzero offset moves a cue later by exactly that amount, and
shifts the snap grid identically so a snap still lands; zero offset is a
no-op), `tests/test_analysis_reader_section_energy.py` (the same shift on
`section_energy_at`, plus the per-URI cache actually caching).

## Transition-alignment tuning loop — `rhythmic_edges.py` + the test bed's Generator/Rhythmic-edges lanes

`data/transition-alignment-plan/report.md` (firstmate home) is the plan;
ship task 2 of its section 5 built the TUNING side only (the `edges`
lane, the two knobs). The rule that turns edges into placement (report
R3) is task 3, built — see the PLACEMENT RULE R3 section below. Task 4
(the "Use as room default" button + the four-song reference-set row) is
also built — see its own subsection at the end of this section.

`spectra/services/rhythmic_edges.py` computes bass-energy edges from the
per-beat `rms_bass` already stored in `.librosa.json` — never a WAV
re-analysis (the plan's own §2.3 finding: a kick-band re-analysis of the
raw audio was tried and was not better). Four kinds: `bass_up`/`bass_down`
(a beat's `rms_bass` jumping past `sensitivity` × a local median) and
`gap_stop`/`gap_resume` (a run of `window_beats`+ consecutive quiet beats,
and its end). **The three knobs are NOT interchangeable and window_beats is
NOT what it sounds like**: `sensitivity` (default 0.5) is the ONLY thing
governing `bass_up`/`bass_down` — the local-median lookback they compare
against is FIXED at 16 beats (`MEDIAN_LOOKBACK_BEATS`, matching the plan
evidence script's own `rolling_median` default), so the plan's own §2.3
"Bass energy jumps up/down" reproduction holds at the default knobs
regardless of `window_beats`. `window_beats` (default 8) is the gap
run-length threshold (`gap_beats` in the plan's evidence script, there
fixed at 2 — the different default here is deliberate: the plan's own
reproduction acceptance is scoped to the up/down rows only, never the gap
rows). `direction` (`both`/`up`/`down`, default `both`, the plan's own
"third, coarser knob") filters which half of the four kinds is returned —
`up` keeps `bass_up`/`gap_resume`, `down` keeps `bass_down`/`gap_stop`,
matching the plan's own "gaps are a special case of down then up" framing
(§2.3) rather than being gap-exempt. Read the module's own "THREE KNOBS"
docstring section before touching any default or before assuming
`window_beats`/`direction` move a bass_up/bass_down mark on their own —
only `sensitivity` moves the up/down threshold, and `direction` only ever
removes marks the other two already produced, never adds any.

Registered as a THIRD and FOURTH `testbed_engines.py` engine:
**`edges`** (the four kinds above, `window_beats`/`sensitivity`/`direction`
as new query params on `GET /api/testbed/engine-marks` and `/compare`,
ignored by every other engine) and **`generator`** ("what the room will do"
— kind `stored` is `trigger_store.list_for_song`'s own `source != "authored"`
rows exactly as written, never recomputed, so a generator frame defect
shows up on this lane before it's fixed; kind `preview` is
`midsong_generator.candidate_moments(uri)` run fresh, read-only, no
trigger-store write — the CURRENT placement rule, which since the
PLACEMENT RULE R3 section below is R3-then-R1, not just Phase 2's plain
downbeat snap). **`generator`'s marks are the ONE exception to
`_estimate_for`'s capture-offset shift** (`spectra/api/testbed.py`) —
every other engine's marks are a raw WAV-time analysis pass and get
shifted into song time for comparison; the generator engine's marks are
already in whatever frame the room's own engine currently fires from
(bug included), so shifting them again would hide, not show, exactly the
kind of generator frame defect this lane exists to surface. Push-to-real
(`testbed_promote.py`) needed no changes — it's already generic over
`source_engine`/`source_mark_kind` strings, so a `generator:preview` mark
reviews and pushes exactly like any other engine's.

Frontend: two sliders plus a three-way Direction toggle
(`spectra/web/src/testbed/edgeKnobs.ts`, the pure clamp/relevance module —
`knobsRelevant()` shows all three while an `edges` lane, OR the
`generator` engine's own `preview` kind, is selected in either A/B slot —
see the R3 section immediately below, `stored` still ignores them) on
`TestbedMetricsPanel.tsx`, next to the tolerance slider, re-scoring the
way it does. `useTestbedEngineMarks` always sends all three knobs
regardless of which engine is active — harmless, and means switching a
slot INTO `edges` needs no extra plumbing. Proof:
`scripts/check_testbed_edge_knobs.mjs` (this repo's no-DOM/no-jsdom
convention for this page, same as `scripts/check_testbed_song_search.mjs`).

**Ship task 4 — the "strongest N" slider, "Use as room default", and the
four-song reference-set row (2026-09-23).** A fourth slider, "Transitions
per song" (`edgeKnobs.ts`'s `DEFAULT_MAX_PER_SONG`/`MIN_MAX_PER_SONG`/
`MAX_MAX_PER_SONG` = 12/6/40, matching `RoomControlState.
transition_max_per_song`'s own `Field(ge=6, le=40)`), shown only for the
generator's own `preview` kind (`edgeKnobs.maxPerSongRelevant` — narrower
than `knobsRelevant`, since `edges` never ranks or trims candidates).
Threaded the same "explicit overrides, `None` falls back to the live room
setting" way `midsong_generator.candidate_moments` already resolves it,
all the way through `testbed_engines.marks_for`/`_generator_marks`/
`_generator_preview_marks`, `spectra/api/testbed.py`'s `_estimate_for` and
the `/engine-marks`/`/compare` query params (bound read live via
`room_controls.field_bounds("transition_max_per_song")`, never a
hand-copied range).

**"Use as room default" makes exactly ONE write, through the EXISTING
`PUT /api/room-controls` partial merge — there is no new write route.**
The three sliders SYNC ONCE from the room's own live values the first
time they resolve (`TestbedPage.tsx`'s `knobsSyncedFromRoomRef`, never
re-synced after — a later room-controls change, e.g. a Sonic voice edit
or this same button's own write, must not silently overwrite a slider
mid-drag). Starting them at the hardcoded module defaults instead was the
original shape and read every knob as "differs" the instant the page
opened on a room already tuned away from 8/0.5/12 — fixed in review.
`edgeKnobs.ts`'s `roomControlsPatchForUseAsDefault`/
`useAsRoomDefaultConfirmMessage`/`transitionDefaultsDiffer` all key off one
shared `changedTransitionFields(current, room)` so they can never disagree
about which knob moved: the PUT patch and the confirm text each carry
ONLY the knob(s) that actually diverge from the room's current values,
never all three unconditionally — a slider never touched must not be
re-asserted, let alone claimed as "changing," back at the room's own
value. Kept pure so `scripts/check_testbed_edge_knobs.mjs` §9 can prove
both the sync-from-non-default-room shape and the partial payload without
a DOM. `direction` is deliberately excluded from the payload — it has no
room-level setting (see `RoomControlState.transition_window_beats`'s own
docstring). Nothing is written until the button is pressed and confirmed,
and an unchanged set of knobs reports "nothing to change" rather than
confirming or writing a no-op. `TestbedPage.tsx` shows the room's own
current three values next to the sliders (`useRoomControls`) and
highlights them when they diverge.

**The reference-set row (`GET /api/testbed/reference-set`,
`spectra/services/testbed_reference_set.py`) is the report's own four-song
acceptance table, live**: Soy Peor / Contra / Dopamine / El Apagón (the
SAME hardcoded URIs `scripts/check_transition_alignment.py` uses — a
deliberate duplication, not a shared import, since that script repoints
storage under a throwaway temp root and must never be imported by a live
request handler) scored on the `generator:preview` lane at ONE-BEAT
tolerance (60000 / that song's own `tempo_bpm`) — never the page's own
tolerance slider, which scores a different lane at a possibly non-beat
tolerance. Recomputed on every drag of Window/Sensitivity/Direction/
Transitions-per-song, so the whole set moves together rather than judging
one song at a time — exactly the acceptance shape ("dragging Window 8→2
on Contra moves recall 73%→55%").

## PLACEMENT RULE R3 — the edge-then-downbeat rule is now the generator's own placement rule

2026-09-23, `data/transition-alignment-plan/report.md` §3/§5 task 3, the
Admiral's rollout approval (`decision-rollout.md`, verbatim: "make the
edge-then-downbeat rule the generator's placement rule with Window and
Sensitivity as room settings you set from the test bed, then regenerate
the whole library in one pass"). `beat_snap.place_cue`/
`place_with_resolved` supersede Phase 2's plain downbeat-only snap above —
Phase 2's own module (grid choice, "ONE FRAME, NO SHIFT", the one-beat
snap cap) is UNCHANGED and IS stage 2 of this rule, not replaced.

**The rule, exactly**: stage 1 — move a candidate to the nearest
`bass_up`/`bass_down` rhythmic edge (`rhythmic_edges.py`, above) within
`window_beats * beat_length_ms`, PROVIDED the move is NONZERO (an edge
sitting exactly at the candidate's own raw time does not count as a
stage-1 match — this replicates the report's own reference measurement
script's `x if x != t else <R1 fallback>` shape exactly, which is what
the acceptance numbers below were measured against; read
`place_with_resolved`'s own comment before "simplifying" this away).
Stage 2 — Phase 2's downbeat snap, gated on `RoomControlState.
midsong_snap_to_beat` exactly as before (that switch "becomes stage 2 of
place_cue" — nothing else about it changed). Neither stage — the
boundary's own raw time survives. **Stage 1 runs UNCONDITIONALLY**,
regardless of `midsong_snap_to_beat` — only stage 2 is gated by that
switch. `gap_stop`/`gap_resume` are deliberately EXCLUDED from stage 1's
edge candidates (only `bass_up`/`bass_down`), matching the report's own
reference implementation precisely — its own methodology never folds gap
events into R3, even though the SAME two kinds join `bass_up`/`bass_down`
under `rhythmic_edges.py`'s own `direction` knob for the `edges` test-bed
lane's DIFFERENT purpose (exploration, not placement) — don't conflate
the two.

**Three new `RoomControlState` fields** (`transition_window_beats`
default 8, `transition_edge_sensitivity` default 0.5,
`transition_max_per_song` default 12 — bounds mirror
`rhythmic_edges.py`'s own MIN/MAX for the first two;
`transition_max_per_song` is 6-40), all Sonic-editable
(`settings_console.SETTINGS_REGISTRY`) and exposed on the Scenes panel
(`RoomControlsBar.tsx`, next to "Snap generated cues to beat"; help topic
`transition-placement-rule`). `direction` has NO room setting — production
generation always uses `rhythmic_edges.DEFAULT_DIRECTION` ("both"); it
stays a test-bed-only exploration knob.

**DENSITY** (the same rollout decision, item 1: "emit about as many
transitions as you mark by hand ... instead of 2-3x that"): before
placement, `midsong_generator.candidate_moments` keeps only each song's
strongest `transition_max_per_song` candidates by ABSOLUTE bass-energy
step size (`rhythmic_edges.bass_step_at`, a raw `|Δrms_bass|` at a
candidate's own raw beat — comparable whether or not that step actually
crosses the sensitivity threshold as a named edge), ranked BEFORE
placement moves anything, ties broken by chronological order (stable
sort). A song with fewer raw candidates than the cap is unaffected.
**Density is a separate concern from the placement rule and is NOT part
of `scripts/check_transition_alignment.py`'s four-song acceptance
table** — that script measures the placement rule alone (uncapped), same
as the report's own reference measurement; density's own effect is
proven by `tests/test_midsong_generator.py`'s own density tests.

**Provenance**: `SpectraTrigger.snap_grid` gained two new values,
`"edge:up"`/`"edge:down"` (`rhythmic_edges.UP_KINDS`/`DOWN_KINDS`'s own
vocabulary), alongside Phase 2's `"librosa"`/`"beat_this"` — visible on
the Review page (`describeEvent.ts`, reworded from "snapped to X beat" to
"moved to X" since an edge match isn't a beat-grid snap) and the test
bed exactly as Phase 2's provenance already was.

**The test bed's `generator:preview` lane now reflects R3** (item (f)):
`testbed_engines.marks_for`/`_generator_preview_marks` thread the page's
own `window_beats`/`sensitivity`/`direction` knobs into
`candidate_moments` — the SAME three knobs the `edges` lane already
exposed (`knobsRelevant` in `edgeKnobs.ts` now shows them for
`generator:preview` too, not `stored`, which is exactly what's currently
written and ignores them). `snap_enabled`/the density cap stay at the
live room default — there is no test-bed-only copy of either; a "use
these as room defaults" button is the plan's own later task 4, not built
here.

**The opening scene change is untouched** — `trigger_engine._fire_
transition` still fires on song detection, not a stored cue; this build
never touches it (the report's own recommendation, ratified in the
rollout decision).

Acceptance: `scripts/check_transition_alignment.py`'s fourth column,
"+ Edge rule" (the shipped default knobs, `RoomControlState()`'s own
defaults, density uncapped to isolate the placement rule) — the one-beat
recall is 21/73/45% (Soy Peor/Contra/Dopamine), reproducing the report's
own §3 table exactly, floor-compared with whole-percent rounding (the
report's own "73%" is itself a rounded fraction — 8/11 = 72.7...% —
comparing the raw float against the rounded floor would fail a song that
landed EXACTLY on target). El Apagón is excluded from this floor and its
regression check (`EDGE_RULE_FLOOR_PCT`'s own comment, the
`no-mistakes(review)` fix 2026-09-23) — reported, never weighted, same
as task 1's own acceptance note. Unit tests: `tests/test_beat_snap.py`
(edge-within-window, no-edge fallback, window clamped to its one-beat
floor, the zero-move-still-falls-through quirk, `snap_enabled=False`
disabling only stage 2, direction filtering), `tests/test_midsong_generator.py`
(density keeps the strongest N and restores chronological order, knob
plumbing reads the room default when unset, an explicit override wins,
edge provenance on a real placed cue).

**His library is NOT regenerated by this build** — task 5
(`scripts/import_analysed_triggers.py --apply`) is a separate,
captain-gated step per the rollout decision, unchanged by this work.

## DENSITY is now a RATE, not a flat count (2026-09-25, supersedes the `transition_max_per_song` paragraphs above)

The Admiral: "instead of a fixed transition count per song, do per
minute. then calculate total per song and use that number instead...
and scale the value with the mark percentage for that song."
`RoomControlState.transition_max_per_song` (6-40, default 12) is
RETIRED — every mention of it above (ship task 4, the DENSITY section,
the test-bed slider) describes the mechanism it replaced; the field no
longer exists and a stored file carrying it drops the key on load
(`room_controls.load_room_controls`'s own migration, no value carried
over — the two are different units with no faithful conversion).
`RoomControlState.transitions_per_minute` (`Field(ge=1, le=30,
default=8)`) is the new knob, and `midsong_generator.
resolve_transition_count(uri, sections, transitions_per_minute)` is the
one place it resolves to a per-song total: `round(transitions_per_minute
* duration_minutes * effective_intensity_scale_factor(uri))`, clamped to
`[1, RESULT_CAP_PER_SONG]` (200 — a sanity ceiling only, never reached by
an ordinary song at the default rate).
`effective_intensity_scale_factor` (`midsong_generator.py`) is
`intensity_scale.song_scaling_factor(uri, genres)` — the SAME per-song
factor the show applies to render intensity (automatic up to 125%, or a
manual "Mark" up to 200%) — with genres read from the live bridge only
when `uri` is the currently-playing track (genres aren't stored per-song
anywhere offline), lazily imported to avoid the `engine` -> `trigger_
engine` -> `midsong_generator` import cycle. `candidate_moments` now
takes `transitions_per_minute` (not `max_per_song`) and every downstream
surface followed: `RoomControlsBar.tsx` ("Transitions per minute"),
the test bed's density slider/query param/`edgeKnobs.ts` constants
(`DEFAULT_TRANSITIONS_PER_MINUTE` etc.), `spectra/api/testbed.py`'s
`_RATE_GE/_LE`, `settings_console.py`'s registry entry, and `types.ts`.
`scripts/check_transition_alignment.py`'s columns all monkeypatch
`resolve_transition_count` to an unlimited constant, unchanged in intent
from the old script's `max_per_song=40` default — this script still
measures the PLACEMENT rule alone, never density. Spec:
`tests/test_midsong_generator.py`'s own rate-arithmetic tests
(`resolve_transition_count`'s formula, the factor scaling, the >=1 floor,
the sanity ceiling) alongside the pre-existing density-ranking tests
(now driven through a patched, count-returning `resolve_transition_count`
for exact control, matching the old flat-count semantics).

## ANALYSED FLARES — the transitions that did not make the cut fire as flares

2026-09-26, the Admiral: "all of the transitions that didn't get selected
because they didn't rank high enough to be treated like flares."
**`spectra/services/analysed_flares.py`'s docstring is the binding
statement.** `midsong_generator.plan_moments` returns the song's
`MomentPlan` (`kept` = the planner's scene changes, stored as generated
fire_scene triggers; `unselected` = every other action, placed by the
identical rule; `dropped` = no action). Since the SCENE-CHANGE PLANNER below,
`candidate_moments` is `kept + unselected` (every action — the placement
and density view), NOT what is stored. The unselected ones are DERIVED AT
PLAY TIME, never stored:
`TriggerEngine` plans them once per song in a worker thread
(`plan_analysed_flares`, cached for the current URI only) and feeds them to
`tick()` as synthetic `fire_response` triggers (ids `analysed-flare:…`), so
they get the same crossing logic, offsets and lead as a stored flare, then
fires them via `engine.fire_response_event(..., analysed=True)` — the one
extra tier the gate admits. Scope is `analysed_flares.analysed_flares_allowed`
(effective mode "analysed", or "full" on a song with no authored trigger),
applied in `tick()`. Spacing: `SCENE_CUE_CLEARANCE_MS`/`FLARE_MIN_SPACING_MS`
(2 s each, named in help topic `analysed-flares`). A settings change takes
effect from the next play of a song. Spec: `tests/test_analysed_flares.py`.

**THE PLAN'S KEPT SCENE CHANGES FIRE TOO WHEN NONE ARE STORED (2026-10-08,
`data/drop-scene-variety-plan/report.md` option A).** Auto-generation never
runs on a song carrying his triggers, so under "analysed" such a song had NO
scene change after the song-start pick (FINA: one scene through 13 drops)
while the markers drew the plan. `tick()` now fires the cached `_scene_cue_
plan` as synthetic generated `fire_scene` triggers (`analysed-scene:<key>`)
whenever `analysed_flares_allowed` holds and `analysed_flares.
has_stored_scene_cues` is False — the ONE test `scene_change_moments` uses,
so markers and fires agree; stored generated cues always win (never both).
Planned-cue dwell tolerance, protected-window holds, pins and lead as a
stored cue; show log detail `planned_scene_cue`. Spec: `tests/
test_analysed_scene_cues_on_authored_song.py` (FINA's real data);
`scripts/check_drop_firing.py` gains the "Scene changes fired" column.

**The debug page's shape canvas marks them** (and the scene cues):
`GET /api/analysed-plan?uri=` (`spectra/api/analysed_plan.py`) serves the
trigger engine's own cached plan when the song is playing (else the same
`plan_for_song`), stored generated scene cues (else the planned kept ones),
and `show_clock_shift_ms` (`engine.show_clock_shift_ms`, display only).
`spectra/web/src/debug/plannedEvents.ts` places each marker where the canvas
playhead will be when the trigger clock reaches it — proven by
`node scripts/check_planned_event_markers.mjs`; spec
`tests/test_analysed_plan_api.py`.

**The Timeline (Builder) page's own audio-shape canvas shows the same
markers too (2026-09-27, his ask: "i still don't see markers ... for the
Spectra analyzed actions")** — reused, not copied: the same `AnalysedPlan`
type, marker colours, and the debug-authored `CanvasLayer` (draw code only
ever reads pre-placed `f.data.plannedEvents`, so one layer serves both
pages) live in `spectra/web/src/debug/plannedEvents.ts`/`layers.ts`, folded
into `spectra/web/src/timeline/canvas/layers.ts`'s `BUILDER_LAYERS`. The
Timeline's own placement (`songPositionMarkers`, same module) is
deliberately simpler than debug's clock-shifted `plannedMarkers` — the
Timeline canvas already draws everything (RMS bands, triggers, librosa) at
raw song-time timestamps, and `analysed-plan`'s own `timestamp_ms` already
IS song time, so it needs no shift at all; `show_clock_shift_ms` only
matters to a canvas whose axis is the live playhead, which the Timeline's
isn't. Wired via `useAnalysedPlan(uri)` (`spectra/web/src/timeline/
queries.ts`) so it tracks whichever song is shown, not just the one
playing. Toggle + count/reason legend: `BuilderPage.tsx`'s "Analysed
events" chip and its legend row, help topic `builder-analysed-events`.
Proven by `node scripts/check_timeline_analysed_markers.mjs`.

**The SAME markers also draw on the full-song trigger strip (2026-10-06,
his ask: "I want to see the generated flares on the timeline. I see them
on the audio shape")** — `spectra/web/src/timeline/components/
AnalysedEventsStrip.tsx`, mounted in `SpectraTriggersCard`'s `below` slot
above the drop-sequence strip, fed the exact same `songPositionMarkers(
analysedPlan)` list the canvas layer draws (one source, so a drop
sequence's protected window holds a cue back on both surfaces alike).
Gated by the same "Analysed events" toggle.

**Light Show High/Low Trigger markers, same ask, same night** — his
`show_cues.py`/`ArmsStatus` data (already served on `AnalysedPlan.
show_cues` and `GET /api/light-show/arms`) is now ALSO drawn as a marker
on both the trigger strip and the audio-shape canvas, shown whether or
not anything is armed on it: `spectra/web/src/timeline/
lightShowMarkers.ts` (pure — `armAppliesToCue` mirrors `show_arms.py`'s
own `_applies_to_song`, `lightShowCueMarkers` produces solid-when-armed/
muted-when-not markers, `sceneChangeArms` picks out arms with no fixed
song position for the legend line instead of a marker) +
`canvas/lightShowLayer.ts` (the canvas layer, z=41, right above
`analysedEvents`) + `ShowCueBar.tsx`'s own armed ring/glow (the SAME
rule, since that strip already existed and only needed the armed/muted
distinction added). New "Light Show" toggle, on by default, legend under
the canvas. Proven by `node scripts/check_timeline_light_show_markers.mjs`.

## THE SCENE-CHANGE PLANNER — the strongest transitions are the scene changes

2026-10-04 (data/scene-change-ranking-plan/report.md, the Admiral's "use all
recommendations"). **`midsong_generator`'s SCENE-CHANGE PLANNER docstring
section is the binding statement.** Before it, rank had NO effect: the
dwell gate chose first-come-first-served at play time (top-10% of
transitions → scene change 38%, flat by rank). Now `plan_moments` ranks
every boundary by SECTION-ENERGY CHANGE (not the one-beat bass step), places
all of them (placement unchanged), dedupes moments placed on one instant,
keeps the strongest "total actions" (`transitions_per_minute`), and a
STRONGEST-FIRST FILL makes the ones that fit the hold in both directions the
scene changes (`planning_hold_s` = the longest enabled scene's dwell curve
at the cue's own ENERGY — `spectra/services/energy.py`, since the
2026-10-28 Energy build, see "ENERGY" above — + 0.5 s; `scene_changes_
per_minute`, 0 = off, is an optional ceiling); the rest are ordinary
analysed flares. At play time a
generated cue fires through `TriggerEngine._fire_planned_scene` with
`dwell.PLANNED_CUE_TOLERANCE_S` (1.5 s) of hold allowed, and every
trigger-engine kernel draw passes the showing scene as `current_id`.
Measured with the plan's validated simulator against the built code (763
un-authored songs): top-10% → 85%, top-3 → 87%, ~2.8 changes/min, 0.0% of
planned changes deferred. **A test about placement or storage with early
fixture boundaries must zero the holds** (`planning_hold_s` → 0, as
`tests/test_midsong_generator.py`'s `no_holds`, `scripts/check_triggers.py`
§6-7 and the two placement acceptance scripts do) — a boundary inside the
song-start pick's ~16 s hold is a flare, not a stored cue. Spec:
`tests/test_scene_change_planner.py`. Acceptance against his live analysis
(read-only, temp copy): `scripts/check_scene_change_ranking.py`.

**Rank on the markers (2026-10-04, report §4).** `GET /api/analysed-plan`
gives every event `rank`/`rank_of` (a stored cue is ranked by its
generator_key against the same plan; the engine's cached ranks while it
plays — `TriggerEngine.cached_plan_ranks`; a cue the current plan does not
contain is `rank: null`, never guessed). The shared `plannedEvents` layer
draws the tab/dot size by rank third and opacity by rank (pure helpers in
`spectra/web/src/debug/plannedEvents.ts`), and names the rank on hover via
`CanvasLayer.tooltipAt` — a hover-only hook in `TimelineCanvas`, so a marker
never steals a click from a trigger. Specs: `node scripts/
check_planned_event_markers.mjs` (FOUR), `tests/test_analysed_plan_api.py`.

## DROP DETECTION — the detector and its file (drop-detection plan, phase 2)

Plan: `/home/javi/fleet-spotfx/data/drop-detection-plan/report.md` (approved
2026-10-05, "Do all recs"; phase 1, the partner timing rule, is
`phase_partner.py` above). **`spectra/services/drop_detector.py` and
`drop_sequences.py` are the binding statements.** Five things:

- **THE DETECTOR IS THE PLAN'S METHOD B, PORTED LINE FOR LINE** — the
  arithmetic is the measured thing. `scripts/check_drop_detector.py`
  (read-only against live storage, on temp copies) holds its raw output
  identical to the testbed's on Contra / Dopamine / Pop Off / 100 Millones
  and the plan's numbers (11 of 13; 9 of 13 confident, 0 false on the EDM
  songs — that script now detects at `drop_floor=0.0` so the floor below
  doesn't move this acceptance). Change a rule and that script tells you
  what moved; bump `DETECTOR_VERSION` whenever an unchanged song would
  detect differently.
- **THE DROP FLOOR (2026-10-06, the Admiral's own setting, default 0.7):
  a candidate is only kept if the TOP BAR'S OWN "⚡ Energy" NUMBER,
  EXACTLY AS DISPLAYED, clears it at the drop's moment** — at the time,
  `drop_detector.final_energy_at` was plain `analysis_reader.
  section_energy_at`, the SAME value `LiveEnergyReadout.tsx` rendered
  verbatim via `bridge.intensity()`, with NO rescaling. His first ask was
  0.95 against this same raw section energy — told that removed every one
  of his 13 real drops on the four reference songs, his follow-up: "what
  about when we factor in the mark score? i want to match to the energy
  in the top bar shown. if that still needs 0.7 for my drops to land, do
  .7. otherwise, stay with .95 if that fixes the issue." **A MARK-
  FACTORED COMPOSITE WAS BUILT, MEASURED, AND REVERTED** —
  `intensity_scale.combine_measured_and_scale` over the section energy
  and the song's own `song_scaling_factor` (genres from the capture
  sidecar): it structurally capped every one of these four songs' own
  ceiling at 0.40-0.44 (their auto scale is 0.68-0.74, so
  `HEADROOM_RESERVE`(0.6, the value live that day) x scale never reaches
  0.7 even at energy=1.0), so NEITHER 0.95 NOR 0.7 ever let a real drop
  through on that measure — it would have switched generated drops off
  entirely. Checking `LiveEnergyReadout.tsx` directly settled it AT THE
  TIME: the "⚡ Energy" readout showed the raw number with no mark
  factored in anywhere — the adjacent "Mark" readout
  (`IntensityMarkControl.tsx`) was a SEPARATE, un-multiplied number. His
  final word, "match to the energy in the top bar shown", is the
  DISPLAYED number, so the floor reverted to it — and stayed reverted to
  it: **since the 2026-10-28 ONE ENERGY build (see "ENERGY" above), what
  the top bar displays IS the Mark-factored figure**
  (`drop_detector.final_energy_at` now reads `energy.energy_at(...,
  look_ahead=True)`, the exact same `spectra/services/energy.py` number
  `LiveEnergyReadout` draws), which is precisely what he had asked for —
  the floor still matches the displayed number, that number just stopped
  excluding the Mark. `scripts/energy_parity.py` re-set `drop_floor` so
  the same share of his drops still clears it under the new scale (the
  plan's D5). Room setting `drop_floor`, folded into `drop_sequences.
  stamp_for`'s own stamp so a change re-detects each song the next time it
  plays. Gated ONLY inside `detect()`, so a sequence he has confirmed,
  edited or added is never removed by it. A song with no stored section
  energy is UNKNOWN, never gated. **Measured, not assumed, at the time**:
  `scripts/check_drop_floor.py` scored the same four songs at 0.0/0.7/0.95
  on the then-plain measure — at 0.95, 0 of his 11 detector-found drops
  survived; at 0.7, 9 of 11 did. His own fallback rule decided the
  default: 0.7, since 0.95 kept none of them and 0.7 kept nearly all.
- **IT READS ONLY THE STORED AUDIO SHAPE AND THE BEATS, AND EVERY TIME IS
  SONG TIME** (the `.npz` is captured in song time; beats shift by its first
  timestamp). The test bed's `_estimate_for` must NOT shift the Drops lane
  (`testbed_engines.SONG_TIME_ENGINES`).
- **DETECTED ≠ HIS.** `storage/spectra/drop_sequences.json` holds the
  detection (a stamped cache, replaced wholesale when stale) plus ONLY his
  edits, keyed `drop:<detected ms>` and re-attached within two beats after a
  re-detection — never rows in triggers.json (an edit there would stamp
  `authored` and silence the song's analysed show under My triggers only).
- **HIS OWN TRIGGERS WIN IN THE VIEW, NOT IN THE TEST BED.** `view()` stands
  a detection down as `matches_yours` within two beats of his enabled
  charge/lull/drop; the Drops lane and `drop_scoring.score_song` score the
  detector's raw proposal, or every match would stand down and score zero.
- **WHAT FIRES IS `drop_firing.py`** (phase 5, below) — this store only says
  what each sequence IS.

**PHASE 3 — SEEN ON THE TIMELINE, READ-ONLY (2026-10-06).**
`spectra/web/src/timeline/dropSequences.ts` is the binding statement: ONE
`buildDisplay` decides each sequence's look, whether it fires, its number and
its words, and the canvas layer (`canvas/dropSeqLayer.ts`, three z-slots —
read its header for why), the strip (`DropSequenceStrip.tsx`) and the review
card (`DropSequencesCard.tsx`) all draw that list; the builds are
`phaseBlend.ts`'s engine mirror. His grouped charge/lull/drop is drawn in the
same shape (look `mine`) and the detection it matched is NOT drawn twice.
Snap rails: `GET /api/drop-sequences/rails` (the detector's own spikes and
the beats, song time, read-only) in their own band under the main area
(`frame.ts` `railH`; the beat strips start below it). Gold/sky/magenta
(`PHASE_COLOR`) belong to the phases ONLY — the analysed flare is lime, the
High/Low flags white/indigo (decision 5). Proof: `node
scripts/check_drop_sequence_view.mjs`.

**PHASE 4 — EDITING (2026-10-06).** Four things:

- **EVERY EDIT IS `drop_sequences.apply_edit`** (the write routes in
  `spectra/api/drop_sequences.py`, and Sonic's `drop_console.py` — no second
  write path), and answers HIS EDITS before and after (`{overrides, added}`,
  never the detection). That pair IS undo: `POST /restore` puts one side back
  and 409s when his edits are no longer the other side (another tab).
- **A DRAG MOVES A GHOST IN A REF** (`useDropSeqInteractions.live`, read by
  the layer every frame — no React render per pointer move) and saves ONCE on
  release with only the changed handles; keyboard steps coalesce the same
  way (`dropEdit.KEY_SAVE_IDLE_MS`). The saved ghost is dropped only once the
  saved view is drawn, so a handle never jumps back. `dropEdit.ts` is the
  pure arithmetic (snap, step, order clamp, undo stack, key map).
- **THE KEYBOARD IS GATED ON FOCUS**: a capture listener registered in
  BuilderPage BEFORE the palette/intensity hooks takes C/L/D, arrows, Enter,
  Delete, N/P, Ctrl+Z only while a sequence has the Timeline's attention
  (a press inside a `data-drop-focus` element); otherwise every key goes on
  to the page exactly as before.
- **A FILLED LULL/CHARGE NEVER REACHES BACK PAST THE PREVIOUS DROP** (a quick
  re-drop gets a bare drop, his to extend with ＋ Lull / ＋ Charge).
  "Make it my triggers" is still to come. Proof: `node
  scripts/check_drop_sequence_edit.mjs`, `tests/test_drop_sequence_edits.py`,
  `tests/test_drop_console.py`.

**PHASE 5 — FIRING (2026-10-06).** `spectra/services/drop_firing.py` is the
binding statement (what fires per mode, the stand-downs, the protected
window). Four things:

- **A MEMBER IS A SYNTHETIC TRIGGER IN `tick()`**, the analysed flares'
  shape: `drop-seq:<key>:<class>` beside the stored triggers, gated by
  `drop_firing.fires_here` (NOT `_trigger_allowed`), relocated and led like
  any `fire_response`, fired through `engine.fire_response_event(...,
  via_trigger=True, analysed=True)` with its gap from its OWN sequence
  (`FiringSequence.gap_ms`). The view is memoised on
  `drop_sequences.revision()` plus his phase triggers, so a tick costs a
  stat. A sequence of his never counts as an authored trigger for the
  "My triggers only" per-song fallback.
- **THE PROTECTED WINDOW IS APPLIED TWICE, ON PURPOSE**: `plan_moments`
  (`protected=`, read through `drop_firing.protected_windows`; the drop
  moment and lull leave the ranking, the window holds no scene change) with
  the windows in `song_inputs` so an edit marks stored cues stale
  (`GENERATOR_VERSION` "3"), and `tick()` holds a generated `fire_scene` /
  analysed flare at fire time (`_held_by_drop_window`, recorded as
  `deferred/drop_window`) for the play during which a plan predates an edit
  or a detection. His own grouped sequences are windows too. A new analysed
  write path near a drop needs the same check.
- **AN EDIT OR A DETECTION CALLS `drop_sequences._changed`**, which drops the
  trigger clock's cached analysed plan for the song. A planner test that
  puts phase triggers in the store now gets windows from them — pass
  `protected=[]` when that is not what it is about.
- **THE TIMELINE FOLLOWS THE SERVER'S `fires`** (`drop_firing.annotate`, on
  every drop-sequences view and the analysed plan): `FireStatus` is
  fires / muted / waits / stands_down / dismissed. Proof:
  `tests/test_drop_firing.py` (the four songs' real detections and phase
  triggers as `tests/fixtures/drop_sequences_four_songs.json`, every mode),
  `tests/test_preview_holds_the_show.py`, and the offline show run
  `scripts/check_drop_firing.py` (temp copies of live storage). Help topic
  `drop-sequence-firing`.

**EVERY DROP FIRES `drop_timing_offset_ms` OFF ITS MARK (2026-10-12, the
Admiral: "shifting the drops so they fire 400ms earlier").**
`spectra/services/drop_timing.py` is the binding statement. A room setting
(default -400, OFFSET family, Sonic-editable) with a per-scene override
slot (`SceneV2.drop_timing_offset_ms`, None = the room's — set by dragging
the drop's red line on a scene's drop-sequence preview, or Sonic's
`set_scene_setting`), applied in ONE place: `tick()` sums it into the target
of every `fire_response` drop (his and the sequences'); the cut, Shockwave
and strip drop ride that fire. A build ending on a drop gets the gap to the
SHIFTED mark (`drop_timing.build_gap_ms` — `_phase_partner_gap_ms`,
`FiringSequence.gap_ms`, the preview's `build_gaps`), so the breath-hold
ends on it. **Tests run with it at 0** (`tests/conftest.py`'s
`_drop_timing_on_the_mark`; `@pytest.mark.drop_timing_live` opts back in —
`tests/test_drop_timing.py`), and `scripts/check_triggers.py` holds it at 0
the same way. **The drag** (2026-10-12, "it should work on a touch screen"):
`PreviewRuler`'s `dragMark` (own handle lane, narrow line strip, per-pointer,
`touch-action: none`) + `scenes/tabs/dropMarkDrag.ts` (the arithmetic,
measured from the drop mark's `music_mark_s`); the preview request carries
the draft value (`SequenceRequest.drop_timing_offset_ms`) so an unsaved drag
plays at once. Spec: `node scripts/check_drop_marker_drag.mjs`,
`tests/test_drop_marker_drag.py`; help `drop-mark-drag`.

**PHASE 2 OF THE DROP-SCENE-VARIETY PLAN — A DROP CAN BE THE SCENE CHANGE
(2026-10-08, the Admiral: "just switch at the drop", early in the charge
only "if it doesn't fit well at the drop").** `spectra/services/
drop_switch.py` is the binding statement and the lull hand-off hook's
installed RESOLVER (never a second hook). Four things:

- **ONE DECISION PER SEQUENCE, at the first member the trigger clock
  fires** (`TriggerEngine._decide_switch`), cut in the SAME `_fire` call
  just before the planned member — the drop, or (early) the charge start /
  the first flare inside the charge — so that member's phase arm lands on
  the NEW scene. Never split the cut into its own trigger.
- **A HARD CUT IS A ONE-CALL OVERRIDE**: `fire_scene_by_id(origin="drop",
  cut=True)` → `scene_compiler.fire_scene(cut=)` → `fx_seam.apply_writes
  (cut=)` → the facade's `"cut": true` → `Virtual.set_effect(cut=True)`
  (`fx/VENDOR.md` #63). Without it every switch rides the virtual's stored
  0.5 s Add crossfade; the stored value must never be changed for this.
  `origin="drop"` is never deferred by dwell and is NAMED
  (`overrode_dwell_for_drop`).
- **An effect born with a `phase` key never edge-fires it** (every phase
  effect's creation baseline), so the drop arm is the response's own write
  right after the cut, not a key in the scene write.
- **Tunables are room settings** (`drop_switch_enabled`,
  `_after_previous_drop`, `_stale_margin_s`, `_drops_in_a_row`;
  Sonic-editable, room bar's Scenes panel); decisions are in
  `drop_switch.plans_for` (the Timeline strip's ⇄, Sonic's read-only
  `explain_drop_switch`) and the show log (`drop_sequence:switch`). A spec
  that builds a `TriggerEngine` with an injected `fire_scene` gets the cut
  through that fake. Fireworks pairs are the phase-3 melds (below). The
  planner's protected windows are UNCHANGED — the early switch is the
  resolver's act, not a planned cue (the revised plan's D).
  Specs: `tests/test_drop_switch.py` (FINA + 100 MILLONES real stores),
  `tests/test_drop_switch_cut.py`; help topic `drop-led-switch`.

**PHASE 3 — THE FIREWORKS MELDS (2026-10-08, option C).** Rows of the same
`drop_switch.HANDOFF` table and the same one-call cut — only the MOMENT
moves; `drop_switch.py`'s THE FIREWORKS MELDS docstring is the binding
statement. Four things:

- **INTO FIREWORKS (`keepers`)**: the lull is told `lull_keep =
  FIREWORKS_KEEP` (3); Orbits joined `LULL_HANDOFF_EFFECTS` to hold N
  spaced blobs (told 1/untold: byte-identical). A lull told another effect
  FLAGS its keepers in its snapshot (`"keepers"`), and Fireworks holds each
  as a rocket the drop arm explodes where it stands (`fx/VENDOR.md` #64).
  An unflagged snapshot adopts byte-identically to before.
- **OUT OF FIREWORKS, LATE MOMENTS**: Fireworks plays its OWN drop, then
  `after_drop` (into the Black Hole, `drop_switch_swallow_delay_s` after the
  mark — swallowed) or `next_hit` (into Fish/Orbits/Squiggles/STAR). A late
  plan is ARMED when the drop member fires (`TriggerEngine.
  _arm_late_switch`, its moment recomputed then) and cut by
  `_tick_late_switches` — or, for a hit, by the hit flare's own `_fire`
  (`_hit_ids`, the ride pattern), so that flare lands on the new scene.
- **THE NEXT BIG BASS HIT IS DEFINED ONCE** (`drop_switch.next_big_hit`):
  the first ANALYSED flare past the drop's own reach (MATCH_BEATS, where a
  flare is silenced anyway; >= HIT_MIN_AFTER_MS) at least
  `drop_switch_hit_threshold`; else `hit_deadline_ms` (tail + a bar), where
  the cut fires the incoming scene's flare itself. A switch still pending
  when the next sequence's first member fires is cut then
  (`before_next_sequence`) — on his dense FINA that is the common case.
- **The sequence preview** gives a late cut its own `"switch"` cue
  (`phase_preview.late_cut_after_s`; the next hit stood in by
  `PREVIEW_HIT_AFTER_S`). Squiggles skips its fade-in for a piece adopted
  on a cut (it went dark ~80 ms). Specs: `tests/test_fireworks_melds.py`;
  GIFs `scripts/render_fireworks_melds.py` -> `docs/evidence/
  fireworks-melds/`; help topic `fireworks-melds`.

**SONIC'S FULL EDIT SET (2026-10-06, Sonic coverage audit build).**
`spectra/services/drop_console.py` now covers every `apply_edit` op, AND
reads what fires: `list_drop_sequences` runs `drop_firing.
annotated_view` (not the plain `drop_sequences.view`), so every
sequence carries `fires`/`fires_reason` — the same phase-5 verdict the
Timeline shows — alongside state and times. Edit ops still resolve a
sequence off the plain view (`_pick`, key/times/state only). The edit
set itself: add/confirm/dismiss/move (pre-existing) plus switching a lull/charge off
or adding one that was never there (`set_drop_member` — distinguishing
"off, time remembered" from "never there, place it by the detector's own
rules" via the view's own `lull_off`/`charge_off` flags), back-to-detected
(`revert_drop_sequence`), answering a re-detection's "needs review"
(`resolve_drop_review`), Sonic's own one-step undo (`undo_drop_edit` — its
own last edit only, in-memory per uri, refused rather than clobbering if
the Timeline edited the same song since), re-detecting now
(`redetect_drop_sequences`), and the library-wide summary
(`drop_detection_summary`). The two detection thresholds
(`drop_confident_score`/`drop_suggested_score`) are ordinary
`settings_console.SETTINGS_REGISTRY` keys. See the `drop-detection` skill
for the cold-start detail and `tests/test_drop_console.py::
test_every_apply_edit_op_has_a_sonic_operation_or_is_acknowledged`.

**HOME'S DROPS PANEL (2026-10-26, predrop plan step 1 — `/home/javi/
fleet-spotfx/data/predrop-plan/report.md` 3.6).** A third Home card: per
drop, ONE bar of toggles — the double tick, one button per part (charge,
lull, pre-drop, drop), remove, edit-in-place — plus an icon-only Testing
toggle. `spectra/services/drop_panel.py` (writes), `drop_sequences.py`'s
PARTS section (the model) and `services/profile_trigger_edit.py` (his
own triggers) are the binding statements; the `drop-detection` skill has
the cold-start detail. Six things:

- **PARTS HAVE TWO MODES, AND ANY EDIT APPROVES (2026-10-28, his
  "any edit ... counts as confirmation and approval of the sequence").**
  An override with no `parts` dict reads the legacy way (confirmed/edited
  = every part his); the first edit seeds the dict and then
  `drop_sequences._approve_edited` approves every part not off, and the
  drop unless he switched it off (Q6: reviewed, plays nothing) — wired per
  op in `_apply_edit` (`_approving`), NOT inside the `_op_*` functions,
  because his own rows' `multi` steps write a standing detection's parts
  as bookkeeping and must keep its tier. Remove, Back to detected and
  restore never approve. Older half-approved data is brought level once by
  `scripts/approve_half_edited_drops.py` (dry run lists it by group;
  `--apply` only after his yes).
- **THE PANEL SHOWS WHAT FIRES, WHEN** (his Q1-Q12; dropsPanel.ts and
  HomeDrops.tsx are the binding statements): rows stay in time order, the
  drop that just played is highlighted in place (any mode), the next one
  that will play counts down to its FIRE moment — `fire_ms`, stamped by
  `drop_firing.annotate` from `drop_timing.fire_moment_ms` (mark + drop
  band offset + drop timing offset, read live through
  `trigger_engine.drop_fire_ms`) and carried on `/api/upcoming` drops so
  the top bar's next box counts to it too. **His own `yours` rows go
  through a SEPARATE callable** (`his_fire_ms=`/`drop_timing.
  his_fire_moment_ms`/`trigger_engine.his_drop_fire_ms`), because his
  drop's/lull's/charge's stored timestamp already has its own
  `trigger_offset_ms` folded in — the clamp has to run against the raw
  stored timestamp, never that offset-inclusive one, or a nonzero
  `trigger_offset_ms` double-counts inside the clamp floor. A waiting part
  on a confident tier draws approved with a detector dot and is not "to
  review"; a double-tap switches a part off and folds into the first
  tap's undo step (`dropEdit.mergeEdit`).
- **TESTING (`RoomControlState.drop_testing`) is a fire-time gate only**:
  `drop_firing.firing_sequences(view, testing)`, read once per tick and in
  the trigger clock's memo key. The PLANNER's `protected_windows` never
  includes it, so toggling it never re-plans stored cues — a cue planned
  into a suggestion Testing fires is held at fire time instead. Removed and
  switched-off never fire, Testing or not. A fired drop pushes
  `{"type": "drop_played", uri, key, at_ms}` (engine status
  `triggers.last_drop` is the backstop).
- **HIS OWN DROPS LIVE IN TWO STORES, and a write must reach both.** His
  charge/lull/drop triggers are in his song profile; the panel writes them
  through the root's narrow `POST /api/profiles/triggers/edit` (raw-dict
  patch, phase triggers only, refuses unknown ids; placed by hand →
  DELETE, imported → switch OFF, the rule living beside the profile), which
  runs the whole-song sync — so it also lands any older profile edit that
  never reached the fired copy, as a Timeline save would. Because under
  "analysed" the DETECTION standing in for his drop is what plays, removing
  or switching off his drop also dismisses it (`dismissed_for` + `prior`,
  put back when his drop comes back on). One undo restores both stores. A
  trigger the sync ledger never saw in a profile (and the profile does not
  hold) was BORN ON SPECTRA'S TRIGGER CARD: it is written in the fired copy
  directly (deleted — placed by hand), its undo record marked `store:
  "fired"`. A row's handles sit at the moment a trigger FIRES (stored time
  + its own `trigger_offset_ms`), so a drag stores the moment less that
  offset.
- **A STALE TIMELINE WOULD SAVE A REMOVED TRIGGER BACK** (every save posts
  the whole profile): the root broadcasts `profile_triggers_changed`; a
  clean tab reloads with a fresh undo history, one with an unsaved edit
  HOLDS the save until he chooses (`timeline/store.ts` `changedElsewhere`).
  The frozen `web/src/builder/` twin does not listen — a known limit.
- **Sonic** (`approve_drop_sequence`, `set_drop_part`,
  `remove_drop_sequence`) ASKS FIRST wherever a write could delete his
  hand-placed triggers. Proofs: `tests/test_drop_parts.py` (incl. the
  show-side sweep), `tests/test_drop_panel_his_rows.py` (copies of his real
  Pop Off/Dopamine), `scripts/check_home_drops_panel.mjs`,
  `scripts/check_timeline_changed_elsewhere.mjs`,
  `scripts/check_home_drops_layout.py`; help `drops-panel`, `drop-testing`.

**EVERY DROP ARRIVES IN A NEW COLOUR SET (2026-10-26, predrop plan step 2
— the Admiral: "It should be a big color change, but it can vary, just
close to 180 degrees").** `spectra/services/drop_colour.py` is the pick
(pure) and the binding statement; `ResponseEngine.drop_color_change` the
precedence; `engine.fire_drop_colour_event` the choke point. Four things:

- **IT FIRES INSIDE THE DROP'S OWN `_fire`, AFTER THE SWITCH IS DECIDED AND
  BEFORE IT CUTS** (`_ensure_switch_plan` then the change then
  `_switch_before_member`), so the set comes from the scene the drop will
  show and the cut compiles in it; his own stored drop triggers take it
  before `_fire_response`. A drop that would not fire (the drop's own
  `_response_gate`) changes no colour.
- **THE POOL IS THE AUTOMATIC ONE, ONE DEFINITION**:
  `scene_sequencer.automatic_pool_cards` (factored out of the sequencer's
  `_default_eligible_sets`, byte-identical) — so his rainbow limit means a
  drop louder than 0.9 lands a rainbow. Holds, each named: the room
  setting (`drop_colour_change`), a room hold, Force Colour (a set pin
  stays, a group pin rolls), a 2D gradient (its own drop kick), a house
  mode that keeps its look. Below those holds but ahead of this pick, a
  word imprinting on the drop (lyrics plan step 4, "Word colours and
  imprints" above) takes the drop instead — the full precedence order is
  `ResponseEngine.drop_color_change`'s own docstring.
- **ONE CHANGE PER DROP**: a landed change claims the drop; the drop band's
  own colour-jump kind then skips, named (`_DROP_COLOUR_DONE`, carried on a
  `PendingKindBatch`). `_color_jump` with a ramp of 0 now lands as a JUMP.
- **A PRE-DROP THAT PLAYS FADES IT** (live since step 5, below): the
  change starts one tick before the pre-drop and lands on the drop; a
  pre-drop that does not play leaves it instant. Spec:
  `tests/test_drop_colour.py` (his 46 single-hue sets, the precedence, the
  show-side sweep with a red control); help `drop-colour-change`.

**PRE-DROPS ARE DETECTED, TWO KINDS (2026-10-26, predrop plan step 3).** `spectra/services/predrop_detector.py` is
the binding statement; the `drop-detection` skill has the cold-start
detail. Four things:

- **THE RULES ARE THE STUDY'S, LINE FOR LINE** — a SPIKE (one loud short
  hit in the high band) and a VOCAL INTRO (a mid-band line entering out of
  a hush and holding). `scripts/check_predrop_detector.py` (read-only, on
  copies of his storage) holds the report's numbers over the moments
  frozen in `tests/fixtures/predrop/study_moments.json`; bump
  `PREDROP_VERSION` (in every detection's stamp) when an unchanged song
  would find differently. Every detected sequence carries `pre_drop`; the
  view names it (`pre_drop_ms/_kind/_auto/_tier/_score`) and, since step 4
  (below), its part.
- **THE RE-ANCHOR** moves a drop sitting ON its own pre-drop hit to the
  sustained bass return 0.5-2 s later, only when that hit passes the spike
  test against it — exactly Eyes Cut Deeper drop 1 in his store, to where
  he moved it by hand. Its lull and charge stay placed against the HIT;
  `reanchored_from` + `drop_sequences._det_distance` keep his overrides
  pairing with it (view AND `_resolve_detected_key`).
- **HIS OWN DROPS' PRE-DROPS ARE WORKED OUT ONLY OFF THE LOOP**
  (`view_with_detection` → `view(compute_pre_drops=True)`), memoised per
  song, stamp and drop time; a plain `view()` — the trigger clock's — never
  analyses, and leaves `authored[].pre_drop` OUT where nothing is
  memoised. Step 5 fills it on the song-change edge
  (`drop_sequences.work_out_his_pre_drops`, in `on_song_played`'s worker
  thread), and a newly memoised answer moves `revision()`.
- **A CAPTURE'S FRAME TIMES CAN STEP BACK**, so `np.searchsorted` over a
  cut window can land a frame from where it lands over the whole song: a
  weak verdict's score may differ in a cut (never a found one). The rules
  keep the study's raw search on purpose. Help: `testbed-predrops` (the
  test bed's Pre-drops lane, a glyph per kind). Specs:
  `tests/test_predrop_detector.py`, `tests/test_predrop_view.py`.

**PRE-DROPS ARE EDITABLE (2026-10-26, predrop plan step 4).** `drop_sequences.py`'s "EDITING A PRE-DROP" and "HIS OWN DROPS'
PRE-DROPS" sections are the binding statement; the `drop-detection` skill
has the cold-start detail. Four things:

- **`pre_drop` IS ONE MORE HANDLE on the existing ops** (`handles`,
  `member`, `fill`, `parts`, the double tick, Confirm) plus one new op,
  `pre_drop_kind`; the snap rails gain `hits`/`entries`. Every edit is the
  usual undo pair.
- **ITS LEAD must fit its kind's range** (`predrop_detector.lead_range`),
  checked on the pre-drop's own edits only — a drop drag never trips on
  it; a placed one holds a drop move back by the 200 ms order rule, and a
  move carrying the pre-drop is checked against where it is going.
- **HIS OWN DROPS' PRE-DROPS live in the drop store** (`overrides
  ["mine:<drop trigger id>"]`, `apply_edit("mine_pre_drop")`), never his
  profile: `drop_panel` maps his "his:" keys onto them, so no edit of a
  pre-drop ever touches one of his triggers (and none asks first).
- **THE UI**: the Timeline's orange handle (help topic `pre-drop`) and the
  Home panel's pre-drop button and editor handle; Sonic's `set_pre_drop` /
  `switch_pre_drop`. Spec: `tests/test_predrop_edits.py` plus the
  drop-sequence view/edit and Home panel check scripts.

**THE PRE-DROP ENGINE (2026-10-26, predrop plan step 5; the looks:
Fireworks and Pulse, step 6; Orbits and Black Hole, step 7; the Fish, Star
and Sauron, step 8; the strips, step 9).** `fx/effects/pre_drop.py` (the told keys, the looks,
`phase_clock`) and `spectra/services/pre_drop_play.py` (the one rule) are
the binding statements; times are in `docs/SPECTRA_TIMING_CONVENTIONS.md`.
Five things:

- **NOT A PHASE — FOUR KEYS ON THE LULL ARM**, told only to
  `fx.device_model.PRE_DROP_EFFECTS` members — Fireworks and Pulse since
  step 6, Orbits and Black Hole since step 7, the Fish, Star (radial) and
  Sauron since step 8, every strip phase member since step 9 (never
  Squiggles). Every
  non-member arm write over his 14 real scenes is
  byte-identical to the pre-engine golden, and a member's lull arm differs
  only by the told keys (`tests/test_pre_drop_arm_identity.py`,
  `tests/fixtures/pre_drop/` — recapture only with a deliberate reason).
  THE LOOKS: Fireworks' lull stays dark (no rockets), is black through
  the breath, and its rocket ring fires ON the pre-drop and bursts on the
  drop; Pulse bursts (spike) or swells to 30% (vocal intro), then holds a
  dark span (a quarter of the gap, 100-500 ms) black like the breath;
  Orbits dims its blob to its 25% floor by the breath and holds it there
  (one curve with the base render's breath, never black), then is back at
  full on the pre-drop, jittering harder and growing to the drop; Black
  Hole is dark from its dark point and black through the breath, then its
  infall ring falls from the hex edge to the centre over the gap, in the
  set's colours; the Fish's searching lull ends on the pre-drop (its keep
  mark is measured to it), then the lone searcher darts to the centre and
  coils there, its head quivering harder to the drop, never dark; Star is
  black from its dark point, then a thin, dim outline in its own shape grows
  out of the centre as it spins up, full size on the drop, and the drop's
  pieces wear the set as it is at the drop — WIDENED 2026-10-28 (the
  Admiral: "yes, the star should change color") to every drop that lands a
  colour change, not just one whose pre-drop played: `fx/effects/
  drop_colour_resample.py` tells Star so on every drop arm; Sauron
  is black through the breath, then its lids part to the iris's edge, the
  flames held down, a glare dimmer than the prototype (0.20 -> 0.36), and
  the drop opens it without its half-open slam; the strips keep their own
  lull up to the pre-drop, then Melt, Power and the Black Hole and Orbits
  strips TWINKLE — drawn once in the shared layer (`fx/effects/
  strip_phase.py`'s THE PRE-DROP): a few pixels in the set's colours, each
  at the effect's own brightness, never dimmed (his "use twinkle to dim"),
  thickening to the drop, painted brighter-wins after the lull's fade — and
  the Fireworks strip is the crystal's idea: dark, black through the breath,
  two rockets fired from the strip's ends on the pre-drop at full (the
  layer lifts its 12% ember for them, `_strip_phase_pre_drop_lift`), bursting
  on the drop. A strip the Radial reads skips its lull, so it gets neither.
  A strip's "today" pins the effect AND the layer
  (`pre_drop_look_harness.load_pinned_strip`). A longer gap adds light to
  Orbits (+1% at a 2 s spike, +14% at a 3.3 s vocal intro — named, the test
  bounds it at +20%); the Fish stays within the plan's named +4%; every
  other look's lull is below today's. An
  untold effect is today's frame for frame against its pinned pre-look
  module (`tests/test_pre_drop_looks.py`, rig `tests/
  pre_drop_look_harness.py`; storyboards `scripts/
  render_predrop_storyboards.py` -> `docs/evidence/predrop-storyboards/`).
  A member is told every key on every lull arm (NOT_TOLD's zeros when its
  pre-drop does not play), and its lull's ramp, dark point and breath are
  measured to the pre-drop, the breath ending exactly on it with no
  `BREATH_OVERRUN_S` (`phase_grammar._breath_gain`).
- **ONE DECISION, AT THE LULL, ON THE SCENE SHOWING**: the trigger clock
  hands the lull a `PreDropCandidate` (a sequence's from `FiringSequence.
  pre_drop_for`; his own grouped lull's from `drop_firing.his_pre_drops`),
  `_drive_phase` decides (kind on, gap inside the scene's
  `pre_drop_spike`/`pre_drop_intro` window, at least 200 ms after the lull
  fired) and `engine.fire_response_event` now RETURNS the record so the
  clock remembers the verdict (`PreDropTold`). That verdict alone drives
  the drop colour fade — a pre-drop the scene does not play leaves the
  change instant. A pre-drop's PART uses its OWN tier (`pre_drop_tier`),
  never the drop's.
- **TIMED FROM THE LULL'S ACTUAL FIRE**: the target is the pre-drop's mark
  plus the drop's own fire shift (moved with its drop), and
  `pre_drop_at_s` is that target minus the tick's position, so a lull a
  tick late still lands the pre-drop on its mark
  (`tests/test_pre_drop_show_clock.py`). The colour fade fires one tick
  early (`PRE_DROP_COLOUR_LEAD_MS`, LEAD family) and glides to the drop.
- **THE WATCHDOG IS SAFE BY ARITHMETIC AND BY RENDER**: the longest hang
  (10% of a 55.5 s approach + a 4.5 s gap) stays under
  `particle_handoff.PHASE_GRACE_S`; `tests/test_pre_drop_watchdog.py` also
  renders every phase effect as a stub member through the longest pre-drop.
- **THE EDITORS**: the Phase tab's Pre-drops card (per-kind on/min/max,
  per-entry look, help `pre-drop-scene-window`), the drop-sequence
  preview's kind switch and gap slider (the lull step carries the same
  candidate), Sonic's six `pre_drop_*` scene settings and
  `get_pre_drop_looks`/`set_pre_drop_look`. Specs: `tests/
  test_pre_drop_engine.py`, `test_pre_drop_preview.py`,
  `test_pre_drop_sonic.py`, `scripts/check_pre_drop_phase_tab.mjs`.

