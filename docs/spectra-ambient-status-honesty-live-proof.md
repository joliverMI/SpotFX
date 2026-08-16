# PR #81 (Ambient status honesty) — live-fixture proof, 2026-08-16 ~01:48–02:03Z

Window was hard-capped at 02:03Z. This is an honest partial: the room's
actual live state at proof time did not match the brief's premise, so the
central claim (a stale `held: true` corrected against off bulbs) could not
be exercised without either manipulating his live room or waiting past the
window — both out of bounds. What follows is exactly what was watched
against his real fixtures, and what remains unproven.

## Deployed build confirmed

`spectra.service` (pid 941047) was running the merged fix at proof time —
`ambient_music_gate.run_supervised()` is wired into `spectra/app.py`'s
lifespan (grep-confirmed against the running checkout at
`/home/javi/SpotFX`), and `GET /spectra/api/engine/status` returned the new
`ambient` node shape (`setting`/`mode`/`held`, plus `verified_age_s`/`verify`
whenever something is claimed held).

## Premise mismatch found live — reported, not papered over

The brief stated "his lights are OFF right now — that is exactly the state
that produced the bug." At proof time this was **not** the case:

- `GET /spectra/api/engine/status` showed `dark: false`,
  `light_ownership: "spectra"`, and an active `executor.recent_writes`
  stream — SPECTRA was live-driving a real fireworks show across multiple
  virtuals (`crystal-mapper`, `radial-dummy`, `tv-mapper`, `hues`, etc.).
- Reading both of his real Hue bridges directly over CLIP v2
  (`GET /clip/v2/resource/light`, using the app keys stored in
  `/home/javi/SpotFX/storage/spectra/fx-live/config.json`, exactly the
  instrument `services/ambient.py::verify_held` itself uses):
  - `192.168.40.215` ("hue-lights"): 10 of 29 lights reporting `on: true,
    brightness: 9.49` (the rest — Old Color 1–5, White Flood, Basement,
    Office Light 1–3, Kitchen Lamp, Hallway, Bedroom Hall — off, consistent
    with not being part of tonight's active scene, not with a stale
    ambient claim).
  - `192.168.40.28` ("dining-hues"): all 7 lights `on: true, brightness:
    9.49`.
- `ambient` in engine status read `{"setting": "auto", "mode": "yielding",
  "held": false}` — no `verified_age_s`/`verify` key present, because
  nothing is currently claimed held.

So the room was mid-show, not dark, and Ambient was correctly yielding to
it — `held: false` while the show (not Ambient) drives real light state.
That is itself consistent with the fix (Ambient makes no false holding
claim here), but it is **not** the failure mode this PR fixes, and I could
not turn it into that condition without violating explicit limits: flipping
`ambient_mode` to `"always"` or pausing playback to force `"auto"` into a
genuine hold would be *enabling Ambient to create a nicer test* against a
room actively doing something else, and once held, the only way to then
exercise the "corrected against off bulbs" path is a bulb going dark that
I do not control. Both are out of scope by the brief's own rule ("if a
proof step would require turning a bulb on, do not do it — report that
part as unproven").

## What was watched and confirmed

1. **`held` is not falsely true right now.** Cross-checked `ambient.held:
   false` in engine status against real CLIP reads on both bridges at the
   same moment — the public claim matches reality; no light is being
   claimed held while dark or otherwise.
2. **Mode reflects a real precedence decision, not a replayed write.**
   `mode: "yielding"` with `setting: "auto"` and an active show in progress
   is the correct branch of `_desired_hold()` — nothing here is inferred
   from a stale write.
3. **Deployed code path confirmed live**, not just read in the diff: the
   running process is post-fix, `run_supervised()` is scheduled in its
   lifespan, and the `ambient` status shape includes the new fields.

## What remains unproven tonight

1. **The exact bug condition** — a claimed `held: true` surviving a bulb
   going dark, corrected to `partial` with `verified_age_s` — was not
   reproduced against his real bridges. Nothing is currently held, and
   nothing safe-to-do would make it so on his active, in-use room.
2. **Watching the periodic verifier tick against a live hold** — `verify_now()`
   only acts when `_held` is true (by design, "nothing to check"), so with
   `held: false` throughout the window there was no live tick to observe
   beyond confirming the task is scheduled.
3. **`verified_age_s` presence/behavior** was not observed live — the field
   only appears once something has been held and confirmed at least once;
   it did not appear in this window's status reads.

Offline proof of all three (mocked-bridge harness) already exists in
`tests/test_ambient_music_gate.py` / `tests/test_ambient.py`, per the PR's
own commit message acknowledging this exact gap. This session did not close
it — the room's real state tonight didn't offer the failure condition, and
the window closed before it could safely be arranged.

## Room left exactly as found

No writes were made anywhere: no PUTs to either Hue bridge, no
`ambient_mode`/`ambient_color` change, no pause/resume of playback, no
service restarts. The two CLIP reads above were `GET`-only, same as
`verify_held()` itself performs. `room_controls.json` (`ambient_mode:
"auto"`, `ambient_color: "#f5da8c"`) was read, never written.
