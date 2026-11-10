---
name: sung-labels
description: >
  Sung labels, Claude's colour meanings and a song's word matches (lyrics
  plan step 3, PR #499): spectra/services/sung_labels.py, lyric_matches.py,
  lyric_reading.py, color_meanings.py, colour_words.py and claude_text.py;
  the /sung-labels correction page; the Test Bed's Sung words lane and Word
  matches row; and Sonic's lyrics domain (spectra/services/lyric_console.py).
  Load before touching any of these files, before adding a sung-label/
  reading setting or route, or before a report shaped like "a word isn't
  matching / a re-draft wiped his edits / Sonic can't read or change the
  sung labels / the weak-match threshold doesn't do anything."
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
`tests/test_lyric_console.py`). Sonic does not read or change word colours yet;
that coverage is still owed.

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
3. **THE WEAK-MATCH THRESHOLD IS A LIVE SETTING, not a hardcoded constant**
   (`SungLabelSettings.weak_match_threshold`, default 0.6 — matching
   `lyric_matches.WEAK_MATCH_THRESHOLD`'s own default, the two kept in sync
   by hand since models stay pure). `sung_labels.weak_match_threshold()`/
   `set_weak_match_threshold()` are the getter/setter; `lyric_reading.
   read_song()` reads the LIVE value and threads it into both
   `build_system_prompt` and `parse_reply` (both keep an optional param
   defaulting to the module constant, for existing direct callers/tests).
   `lyric_matches.payload()` reports the live value too, not the constant.
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

## Sonic reach (`spectra/services/lyric_console.py`, domain `lyrics`)

Built as the coverage follow-up this skill exists to record. Load
`.claude/skills/sonic-ops/SKILL.md` before changing anything here.

- **Reads**: `get_lyric_reading_settings` (auto_read, weak_match_threshold,
  Claude availability), `list_sung_label_targets` (every colour set's/
  effect's name + label count, kind-filterable — call this first to get
  the exact name the other ops expect), `get_sung_labels` (one named
  target's labels, plus meanings for a colour set), `get_lyric_matches`
  (one song's matches — `song` omitted means whatever is playing now).
- **Writes, no confirmation needed**: `edit_sung_label` (add/remove one
  word on a target's labels or, colour-set-only, things/moods/places),
  `add_lyric_match`/`delete_lyric_match`/`restore_lyric_matches` (a match
  is named by its PHRASE TEXT, disambiguated by `label` or `occurrence`
  when the same phrase repeats — never by its internal id), turning
  `auto_read` OFF, and changing `weak_match_threshold` alone.
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
  `absorb_console.py`'s own settings asks apply.
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
  `SongMatches`, `Reading`, `ClaudeGuess`, `HisMatch`).
- `spectra/services/{sung_labels,lyric_matches,lyric_reading,color_meanings,
  colour_words,claude_text}.py` — the mechanism (see each module's own
  docstring).
- `spectra/api/{sung_labels,lyric_matches}.py` — the page's own routes.
- `spectra/web/src/sunglabels/{SungLabelsPage.tsx,sungLabels.ts}` — the
  correction page.
- `spectra/web/src/testbed/` — the Sung words lane and Word matches row
  (`TestbedLaneBar.tsx`/`TestbedPage.tsx`).
- `spectra/services/lyric_console.py` — Sonic's `lyrics` domain, wired into
  `spectra/services/settings_agent.py`'s `_DOMAIN_OP_DICTS`/
  `ALL_OPERATIONS`, with its MCP wrappers in `settings_mcp_server.py`.

## Specs

`tests/test_sung_labels.py`, `tests/test_lyric_reading.py`,
`tests/test_lyric_console.py` (the Sonic domain — round trips, the
ask-first flow for both Claude-spending ops and the auto_read on/off
asymmetry, the import boundary), `tests/test_scene_console.py::
test_dispatch_recognizes_exactly_the_declared_operation_set` (the
exhaustive merged-dispatch proof — update its hand-imported domain list
when a domain is ADDED, not just when an op is added to an existing one),
`tests/test_settings_agent_cli.py::
test_the_lyrics_domain_widening_parses_from_its_structured_tool_result`
(the CLI/MCP manifest widening — every "current manifest" synthetic
fixture's `tools` array needed the 11 new tool names added, per the
sonic-ops skill's own step 7). Help: `sung-labels-reading` (updated with
the threshold and Sonic reach) in `spectra/web/src/help/helpContent.ts`.
