---
name: absorb-music
description: >
  Absorb Music — silent, unattended capture of a linked Spotify playlist on
  Serenity (data/absorb-music-plan/report.md, phases 0-5): the SpotFX runner
  (services/absorb.py, absorb_silence.py, absorb_schedule.py, absorb_bar.py,
  absorb_store.py, absorb_spotify.py, routers/absorb_router.py), SPECTRA's
  /absorb page (spectra/web/src/absorb/) and Sonic's absorb domain
  (spectra/services/absorb_console.py). Load before touching any of these,
  before adding an Absorb setting or route, or before a report shaped like
  "absorb didn't run / the house stayed silent / Sonic started it anyway".
---

# Absorb Music

AGENTS.md's "ABSORB MUSIC" section and each module's own docstring are the
binding statements (`services/absorb.py` for the runner, `absorb_silence.py`
for the house guard, `absorb_schedule.py` for the schedule). His five plan
answers, verbatim: "yes, yes, nothing, resume, yes" — head required; skipped
songs listed, tagged; lights untouched; resume after his music goes quiet;
allowed while sleeping, gated on the silence proof. Six things worth knowing
cold:

1. **It lives in SpotFX (`:8000`), not SPECTRA.** SPECTRA's page reaches
   `/api/absorb/*` same-origin and Sonic reaches it over HTTP; neither may
   import `services.absorb` (scripts/check_process_split.py). SPECTRA's only
   own piece of the runtime is `spectra/services/absorb_hold.py` — the
   light stand-down, read off the websocket's `absorb.lights_held`.
2. **ONE START DOOR.** `POST /api/absorb/start` → `AbsorbRunner.start` →
   `_gates` (no playlist, a Jukebox night running — services/jukebox/night.py,
   which in turn refuses to start under an open window — anchors off,
   analysis off, music playing, the guard's `ready`, a night/camera run, the
   device, the playlist) then
   `guard.open` (the silence proof, River's hard block, the Order 27 rule).
   The page, the schedule and Sonic all go through it; a new caller must
   too. A refusal is a RECORDED run answered 200 — "did it run, why not?"
   is always a read.
3. **ONE VALIDATOR.** `PUT /api/absorb/config` → `absorb.apply_config_patch`
   (partial; unknown key and out-of-range are 422 by name;
   `absorb_schedule.problems` refuses an impossible window). `?dry_run=true`
   validates identically and writes nothing — Sonic uses it so it never asks
   him about an edit that would be refused.
4. **THE STORES ARE FOUR** (`models/absorb.py`): his config, the run (+
   bounded history), the ledger (parks and filings, across runs), the
   schedule's memory. Only an edit writes the config; a run never does.
5. **A HEAD RATE WITH NOTHING COMMITTED IS "NONE", NEVER 0 %.** Both the
   page (`absorbSummary.ts`) and Sonic (`absorb_head_report`) hold this.
6. **THE HIDDEN PLAYER WORKS THE BACKLOG BETWEEN WINDOWS** (the Jukebox
   plan's phase 4, `services/absorb_lane.py` — its docstring is the binding
   statement; `AbsorbConfig.use_capture_lane`, ships OFF). It learns only
   FRESH songs (Absorb's own bar) on "Serenity Capture" through the capture
   lane (capture_lane/), never captures over a shape (so a re-capture with
   its realign stays a window's), never writes his playlists (a learned song
   is filed as "already captured" at the next window), and rests — cancelling
   its song — during an Absorb window, a Jukebox night, sleeping or an
   unreadable sleep, and while the SECOND ACCOUNT'S SWITCH (SPECTRA's
   Settings page, `fx/second_account.py`, ships OFF) is off or unreadable —
   `use_capture_lane` on is not enough by itself. `GET /api/absorb/lane`
   reads it; the page's Hidden player card switches it.

## Sonic reach

`spectra/services/absorb_console.py`, domain `"absorb"`, in
`lock_console.py`'s shape (SPECTRA-side ops over SpotFX's own routes, one
validator, one store; `http` is the injectable transport). Twelve
operations: `absorb_status` (+ `include_playlist`), `absorb_head_report`
("how many got their heads last night?"), `start_absorb`, `stop_absorb`,
`absorb_skip_song`, `list_absorb_parked`, `retry_absorb_song` (one song, by
title), `get_absorb_settings`, `set_absorb_setting` (`SETTING_KEYS`:
max_attempts, play_window_size, overrun_grace_min, recently_captured_max,
run_while_sleeping, use_capture_lane), `set_absorb_force_recapture`, `set_absorb_window`
(replaces the list; `schedule_on` is the schedule switch),
`set_absorb_playlist` (exact name or link, from `GET /api/absorb/playlists`;
a close name is refused NAMING the candidate, a followed-not-owned
playlist is refused).

**ASKING FIRST is a two-call protocol, not prompt wording**: a write that
newly lets Absorb act on the house or his playlists without a press —
start, force recapture ON, the schedule newly opening (or opening different)
windows, the playlist changing while the schedule is on, run_while_sleeping
back ON, use_capture_lane ON, Recently Captured's cap LOWERED — answers `needs_confirmation`
with a `confirm_id` and writes nothing; only a second call carrying the id
acts. An id is single-use, expires (`CONFIRM_TTL_S`), belongs to one op and
one argument set, and is refused if his config changed since he was asked.
The page itself asks before only two of these (Start, force recapture ON);
Sonic is stricter, never looser. Stop / skip / retry / the plain numbers act
at once, as on the page — stopping gives the house back.

Every timeout stays inside the CLI backend's 60 s forward
(`settings_mcp_server._call`): a slow start reaches him as "it may still
have opened", never the forwarder's "did not run".

Deliberately off-limits (named in the module docstring, and keep it so):
editing either playlist's contents, bulk-clearing `needs_recapture`, and
the settings that are his plan's decisions — head_max_ms, order, warm_up,
recently_captured_includes_skipped, the Q4 quiet rules, silence_recheck_s,
captured_playlist_name. A NEW AbsorbConfig field owes either a place in
`SETTING_KEYS` / its own op, or a named line on that list.

## Proofs

`tests/test_absorb_console.py` (Sonic against the REAL router over
`tests/absorb_world.py`; the route's own refusals through Sonic — music,
anchors, River's hard block, the sleeping rule, Home Assistant unreadable —
with the house volume never written), `tests/test_absorb_runner.py`,
`tests/test_absorb_silence.py`, `tests/test_absorb_schedule.py`,
`tests/test_absorb_stand_down.py`, `tests/test_absorb_api.py`,
`tests/test_absorb_lane.py` (the backlog on the hidden player),
`scripts/check_absorb_page.mjs` (via `tests/test_absorb_page.py`).
