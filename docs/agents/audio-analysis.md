# Audio analysis: xcorr identity, whole-song check, librosa offsets

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## The root xcorr engine's identity is the TRACK actually playing, never `profile.spotify_uri`

`TriggerEngine._last_uri` (`services/trigger_engine.py`) is what `apply_save`/
`reload_shape_offset`/`systemic_residual_for` and the sweep (`services/
auto_offset_service.py`) key on to decide whether a measurement belongs to
the song currently loaded. `load_profile(profile, track_uri=...)` sets it
from `track_uri` (i.e. `state.current_track.spotify_uri`), **not**
`profile.spotify_uri` — the two diverge for the ~24 profiles main.py's
title/artist fallback (no `spotify:track:` match found, matched by
title+artist instead) loads, whose own stored `spotify_uri` is a stale
`ledfx:artist:title` pseudo-URI from before the song ever got a real match.
Before this fix (`data/false-lock-continued-search/report.md`, 2026-09-22),
every sweep snap for those songs was silently dropped in `apply_save` (no
log line either) and the song ran the whole play at the un-corrected `+0ms`
loaded-baseline offset — a real defect independent of any individual lock
being right or wrong. `main.py`'s call site passes `track_uri=
track.spotify_uri` explicitly; any other caller of `load_profile` (e.g.
`services/guest_source.py`) that has no separate track identity omits it
and falls back to `profile.spotify_uri`, which already equals the track
for it. `apply_save` now logs every dropped snap instead of returning
silently. **The run() loop gates on the
same identity** (`_loaded_track_uri()`), and it is the ONLY writer of
`state.timing` — the block SPECTRA's bridge reads its `shape_offset_ms` off.
Gating it on `profile.spotify_uri` (fixed 2026-10-06) skipped every tick for
those songs, so the PREVIOUS song's lock stayed in the broadcast and SPECTRA
fired the whole song off it (Caro on Greenlights' −1977 ms vs its own
−525 ms: ~1.45 s late, playhead correct). `state.timing` now carries `uri`
and `spectra/services/bridge.py::shape_offset_ms` refuses a block naming a
different track. Spec: `tests/test_stale_timing_lateness.py`.

**A hard lock can be a correct MEASUREMENT of a wrong SHAPE** — the same
report's root finding. Two captures of the same recording can land in two
different timing frames (a stale Spotify poll poisoning `song_start` at
capture time, `services/audio_shape_service.py`), and a lock that
perfectly, unanimously matches the wrong one is indistinguishable from a
correct lock by "keep searching longer" or the post-lock mismatch monitor
— both only re-measure the shape's own internal alignment, which is
self-consistent either way. `services/frame_advisory.py` is an ADVISORY,
not a gate: when a hard lock lands more than 2s from the room's current
band (the systemic learner's centre at confidence ≥ 0.25, else the median
of this session's own locked plays) on a song with hand-authored (not
`ai_generated`) triggers, `frame_suspect` is recorded on the
`lock_history` entry and shown on the lock badge tooltip / Timing page row
— never refusing the lock or changing when triggers fire. Regression
fixture: `tests/test_false_lock_frame_mismatch.py`, driven against his real
captured audio for MIA (`tests/fixtures/`, the two captures that sit
~5375ms apart in their own timelines) through the real production kernel
(`xcorr_window_full`/`EvidenceAccumulator`/`SweepEvaluator.lock_and_stop`).

## THE WHOLE-SONG CHECK — the per-song offset watchdog (2026-10-13)

`services/whole_song_check.py`'s module docstring is the binding statement
(data/lock-investigation/report.md §5.4/§8; the Admiral's call, option A:
correct automatically). The per-play sweep only ever searches ±2.5–3.5 s of
the STORED offset and its twin gates (drift cap, envelope, 0.20 margin) also
keep the truth out, so an offset more than ~3 s wrong was re-saved forever
(El Efecto +325 vs truth +11,750). After a play that did not hard-lock (and
every `xcorr_whole_song_locked_every`-th that did), `AutoOffsetService.
_schedule_whole_song_check` — called AFTER the play's final save, on its own
task, the vote on a worker thread — votes the play's own frames over ±15 s
of the whole song and REPLACES the stored offset (a Set List slot's history
becomes just that entry, or its median never moves) only on a clear, strong,
better, far-enough majority. Four things:

- **Every outcome is recorded**: `storage/whole_song_checks.json` (bounded),
  `GET /api/lock-history/whole-song`, the Timing page's card (both apps,
  `timingviz/WholeSongCheckPanel.tsx`), a WARNING per correction. Settings:
  `PUT /api/lock-history/whole-song/settings` (the ONE validator,
  `whole_song_check.SETTINGS`), reached by Sonic's `lock` domain
  (`spectra/services/lock_console.py`, over HTTP — SPECTRA may not import it;
  its `KEYS` mirror is asserted equal in `tests/test_lock_console.py`).
- **A seek or a pause is not a new offset**: the capture clock runs from the
  play's fixed song start, so frames after a scrub read as offset + the jump
  and could win the vote by a landslide. `whole_song_check.TimelineWatch`
  (fed Spotify's progress once a second in the frame loop) cuts the frames at
  the first seek, pause or song change; a play cut short is too short to judge.
- **Rec. 4 rides with it**: `SweepEvaluator.stronger_elsewhere` withholds a
  save (per-window and final) when `xcorr_withhold_resave_min_repeats` windows
  whose OLD test point WAS the value about to be saved found one other offset
  beating it on r — the Ponle Dembow re-save. Recorded before the envelope clip.
- **The sweep-world driver turns both OFF** (`tests/sweep_world_driver.py`
  `SETTINGS`), because every pinned-baseline trace comparison predates them;
  a world testing them turns them on with `settings_over`.
- **Proof**: `scripts/check_whole_song_check.py` (`--live-shapes DIR` adds the
  report's 20 locked songs, read-only) + `tests/test_whole_song_check.py`, on
  his two failing songs' REAL stored shapes (`tests/fixtures/whole_song/`)
  with a live capture synthesised the way §5.4 measured — the twin he was
  stuck on scores r ≈ 0.55 against ≈ 0.93 at the truth, as measured live.
  NOT built here, deliberately: the first-sweep planning freeze, library
  compensation from River's 8097 feed, recapture and monitor recovery.

## `librosa_offset_ms` is unreliable — don't shift section/beat times by it

`LibrosaAnalysis.librosa_offset_ms` is meant to convert WAV-capture time to
song-relative time, but the stored values can't be trusted: nonzero on ~74% of
the 671 analyses, with outliers into the tens of thousands of seconds (one is
75,308,324 ms). The codebase is split on it —
`embedded_trigger_service` adds it, while `load_sections_for_uri()` and its
consumers (`signal_resolver._section_energy`, the `section_energy` binding,
`trigger_engine._section_intensity`) read section/beat ms **raw**.

**Follow the raw convention for anything that has to line up with playback
position at runtime**, so baked values agree with the live bindings. Evidence:
user-authored triggers in profiles with `offset == 0` snap exactly to librosa
beats (median distance 0 ms, 70% within 40 ms). On nonzero-offset songs a
per-song best-fit shift (voting over `beat_ms - trigger_ms`) matched the stored
offset in **0 of 126** files — the stored number is noise, not a real shift.

## Backfilling trigger intensity from section energy

`scripts/backfill_trigger_intensity.py` sets each `MusicTrigger.intensity` from
the librosa section energy at its timestamp; a trigger within 2 beats *before* a
section line takes the **next** section's energy (a build placed just ahead of
the drop should fire at the drop's level). Dry-run by default; `--apply` writes
and first copies `storage/profiles/` to `storage/backups/profiles-preintensity-<stamp>/`.
Idempotent. Current library state: `--curve minmax --floor 0.05`.

### Raw `energy_rms` skews high — renormalize it

`librosa_service._detect_sections` divides by the loudest section only
(`energy / max_e`) with **no floor subtraction**, so a song's quietest section
lands at `min/max` — median **0.33** library-wide, never near 0. It also works
in **linear RMS**, and modern masters are heavily limited (median song-wide
dynamic range only **~9.6 dB**), compressing real loudness differences into a
narrow band near the top. Raw trigger intensities came out p25=0.68, median=0.84.

`--curve` picks the mapping (all per-song):
- `minmax` (default) — linear min-max stretch. Fixes the missing floor, keeps
  relative magnitude. Gives p25=0.50, median=0.76, 25% below 0.5.
- `raw` — original behavior.
- `rank` — percentile rank. Uniform spread (p25=0.27, median=0.54, 45% below
  0.5) but discards magnitude; near-equal sections can land far apart.
- `dbstretch` — **counterintuitive: pushes values UP, not down.** Because energy
  is already max-normalized, linear 0.5 is only −6 dB, so dB mapping raises it.
  Does not help if the complaint is "everything reads too high".

`--gamma` post-shapes (>1 pushes down), `--floor` lifts the bottom. A floor is
worth keeping: under bare `minmax` the quietest section maps to exactly 0.0,
which hit **427 triggers (4.2%)** and makes any effect scaled by
`trigger_intensity` a no-op.

### Safe to run against a live app

`profile_manager` caches only a `{uri: filename}` index and re-parses each
profile from disk on every `load_profile_by_uri`, so there is no in-memory
profile object to clobber the edit (unlike the HA storage-file gotcha). Writes
are atomic (tmp + replace) and use `ensure_ascii=True` to match how the app
serializes profiles (`\uXXXX`).

`storage/audio_shapes/*.wav` writes (`services/audio_shape_service._save_wav_and_analyze`)
are also tmp+`os.replace` atomic, for the same live-safety reason: an offline
batch pass (`scripts/rerun_librosa.py`) can be reading a WAV from the same
path while a live re-capture of that song overwrites it — a direct in-place
`sf.write` truncates before streaming, so a concurrent reader can land on a
partial file (`soundfile`'s "System error"/"Format not recognised"). This was
the 2026-08-14 librosa-backfill failure root cause (19/500 songs); the same
race exists for anything else that writes into `audio_shapes/` — write atomically.

**A capture used to be cut off at BOTH ends — fixed 2026-09-09**
(`services/audio_shape_service.py`). Beginning: pre-roll from the always-on
PCM ring buffer only ran for `force_recapture=True` ("to preserve legacy
behavior"), silently dropping the head of every ORDINARY capture between
song-start and URI-detection (typically 5-10s). It now runs for an ordinary
TRACK CHANGE too — but **gated on `at_track_boundary` (or an explicit
force-recapture), NEVER on every `_start`**. The splice is only sound when
the ring buffer between `song_start` and now really is THIS song's own
contiguous audio, and the boundary flag is exactly that evidence:
`on_track_change` saw the URI flip into this track and computed the
acoustic boundary `song_start` came from. A MID-SONG start has no such
signal — `_start` also runs from `on_track_change`'s tail for any playing
song with no complete shape (a resume after a pause discarded a too-short
partial), where `song_start` is `now - progress` and the intervening ring
buffer holds the PAUSE. Splicing there stamped silence as the song's own
head, fed it to librosa AND the WAV, and inflated the `captured_ms` the
too-short guard reads — a shape that should have been rejected persisted
with minutes of wrong audio. So a mid-song start takes the ordinary
no-pre-roll path and says so in the log. End: both
tail-wait sites (`on_track_change`'s boundary-wait, `_stop_and_save`'s
tail-wait) used `if 0 < wait_s <= 3.0: sleep(wait_s)` — a wait that needed
MORE than 3s got skipped ENTIRELY (zero wait) rather than shortened, which
is exactly the "stopping immediately is what cut the end off captures"
failure the surrounding comment already named. `_capped_wait_s()` (module-
level, one definition instead of two inline copies) now sleeps
`min(needed, cap)` at both sites instead of an all-or-nothing window (the
cap's own row, unit and status: `docs/SPECTRA_TIMING_CONVENTIONS.md`'s
master table, beside the `audio_latency_ms` it is derived from). Spec:
`tests/test_audio_shape_capture_trim.py` (no live audio device — the ring
buffer / capture stream / recorder are faked at the seam, matching this
file's own "no live access from tests, ever" rule; it carries BOTH the
track-change case that must splice and the mid-song-resume case that must
not).

**A second hole opened right after that fix, AT THE SEAM ITSELF — fixed
2026-09-26** (`data/dream-on-capture-loop/report.md`). Splicing pre-roll in
closed the head-truncation gap, but `_start()` then opens a brand-new
`AudioCaptureStream` — and any audio that played between the pre-roll
snapshot's own end and that new stream's first delivered callback was still
lost. Measured 160-370ms, comfortably over the 200ms gap-discard limit, on
roughly half of all real track-boundary captures library-wide (his "Dream
On"/"Money for Nothing" capture-loop reports were this, not duration or a
fixed cap — nothing in the pipeline caps capture length).
`AudioShapeService._seal_preroll_seam` closes it: on the new stream's very
first live frame, it re-snapshots the still-continuously-running PCM ring
buffer from exactly where the pre-roll splice ended through exactly where
the live sample begins, and synthesizes the hole the same way pre-roll
itself is synthesized (`synthesize_frames_from_pcm`). One-shot per capture
(`_preroll_end_monotonic`, cleared regardless of outcome the moment it's
consulted); a no-op when there was no pre-roll to begin with (mid-song
start). Spec: `tests/test_audio_capture_seam.py`.

A second, unproven cause in the same report — a 4-10s callback stall
roughly 25-40s into some captures, correlated (not proven) with the
*previous* song's detached finalize pipeline (npz save, WAV write, librosa
launch) — is INSTRUMENTED ONLY, not fixed: the WAV write already runs on a
`ThreadPoolExecutor` and librosa already launches in its own single-use
`ProcessPoolExecutor` (`_save_wav_and_analyze`), so nothing in that
pipeline's own code obviously starves the concurrent capture thread by
inspection. `_finalize_capture` now logs its own start/end wall-clock
window, `_save_wav_and_analyze` logs its WAV-write and librosa sub-phase
durations, and both audio callbacks (`api/audio_capture.py`'s per-song
stream, `api/pcm_ring_buffer.py`'s always-on stream) log sounddevice
status/overflow flags at WARNING — enough to correlate a future stall
against an exact window without guessing. Do not move the WAV write or
librosa off-thread further on the strength of this report alone; the
report's own words are "correlation, not proven."

**The audio-shape URI index refreshes on a lookup MISS only when it could
have missed something (2026-10-20, `data/absorb-music-plan/report.md`
§4.2).** `services/audio_analyzer._build_shape_index`'s docstring is the
binding statement. A miss used to re-parse every sidecar (142 ms, 3,294
times on 2026-10-13, 468 s of event-loop blocking). Now a miss refreshes
only when the directory's mtime moved, the last look was racy, or 30 s
passed, and a refresh re-parses only sidecars whose (mtime, size) moved. So
a sidecar another process writes is found on the next miss (a new directory
entry), an in-place rewrite that changes a sidecar's `spotify_uri` is seen
within 30 s, and an in-process `AudioShapeRecorder.save()` updates the
index directly. **After a capture, the recapture playlist and the
`needs_recapture` flag are touched only on real success**
(`audio_shape_service._after_successful_capture`: shape + WAV + librosa
landed, and a forced recapture COMMITTED); `recapture_playlist.remove_track`
is blocking Spotify HTTP (call it via `asyncio.to_thread`) and caches the
playlist id. A forced recapture's "≥1 anchor candidate" commit check applies
only when the anchor pass ran (`settings.anchor_enabled`). Specs:
`tests/test_audio_shape_index_miss.py`, `tests/test_recapture_playlist_cache.py`,
`tests/test_capture_success_bookkeeping.py`.

