# Sonic settings console and colour-set behaviour

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## SPECTRA settings console (standing order 5: talk to the software)

`/settings` — a small Sonnet-class model, not a form, is the only thing
that changes anything here. Mechanism `spectra/services/settings_console.py`
(scope: the RoomControlState fields already labelled "agent-tellable"
in `room_controls.py`'s own docstring — brightness, ambient enable/colour,
global transition, scene-change tier, the PLACEMENT RULE R3 knobs,
midsong-snap-to-beat/display-mode/rainbow-select-limit, and the drop
detector's two thresholds). **Force Scene and Force Colour are no longer
excluded** (2026-10-06, the Admiral's ruling: "allow some flexibility in
phrasing ... it should be a close match") — `set_force_scene`/
`set_force_color`/`get_force_pins` resolve a scene/colour-set by NAME
through `spectra/services/name_resolve.py` (exact, then a dropped
qualifier like "V2", then a fuzzy match refusing a near-tie) rather than
needing the opaque id the original exclusion was about, then write
through `room_controls.apply_patch` — the same writer a human PUT uses,
so the identical reconcilers run. `SETTINGS_REGISTRY` is an
explicit allowlist whose bounds/choices are READ off RoomControlState's own
`Field(ge=, le=)`/`Literal[...]` (`room_controls.field_bounds`/
`field_choices`) — never a second hand-typed copy of the range.
`apply_change()` is the only write path: re-validates the full candidate
through `RoomControlState.model_validate` (the same class GET/PUT
`/api/room-controls` binds to) and writes through `room_controls.
save_room_controls` + the (now-shared) `reconcile_ambient_if_changed` — the
identical two calls the human PUT handler makes, factored out so the agent
can't diverge from what a human save does. A bounded, visible change log
(`storage/spectra/settings_log.json`) plus `undo_last_change()` (reverts by
re-running `apply_change` with the old value — an undo is validated exactly
like any other change) is the mis-transcription safety net, not a
confirm-before-apply step — voice dictation mangles his product names
routinely (captain-shared.md), so the record + one-step undo answer that
without adding a round-trip to every spoken command.

THE AUTHORITY BOUNDARY IS STRUCTURAL, not prompt wording — read `settings_
agent.py`'s module docstring first if touching this. The model — now called
Sonic in the UI/prompt — is handed exactly the tools declared in
`settings_agent.ALL_OPERATIONS`, a dict of `spectra/services/sonic_ops.py`
`SonicOperation` entries merged from each domain module's own `OPERATIONS`
dict (originally just `get_settings`/`set_setting`; widened 2026-08-15 to
Sonic's scene/flare authority below — see that section). `_dispatch()` is
the complete, exhaustive name->handler mapping, so there is no third
branch to reach for a shell/file/HTTP/service-control/light-driving call,
whatever the prompt or transcript says, and the SAME `SonicOperation` dict
also IS the `list_operations` discovery catalogue Sonic queries at
runtime instead of the prompt trying to describe every capability — see
`sonic_ops.py`'s own docstring for why guard and catalogue are one
declaration. `tests/test_settings_console.py`/`tests/test_scene_console.py`
prove this without a network call (fabricated tool names/keys rejected,
nothing persists on rejection) plus one live-model smoke test skipped
without `ANTHROPIC_API_KEY`. Model id from `spectra.config.
settings_agent_model()` (env `SPECTRA_SETTINGS_AGENT_MODEL`, default
`claude-sonnet-5`); API key from `settings_agent_api_key()` (env
`ANTHROPIC_API_KEY`) — unset means a stated 503, never a silent no-op.

**The 2026-10-06 Sonic coverage audit build widened four domains at
once** (Pulse/every effect's per-entry params, Force Scene/Force Colour by
name, house-wide settings, and drop detection's full edit set — see each
domain's own entry below and the `pulse-effect`/`house-lighting`/
`drop-detection` skills for the cold-start detail). **Before adding,
changing or removing ANY Sonic operation, load the `sonic-ops` skill** —
it is the one checklist (console module → `ALL_OPERATIONS` → MCP wrapper
→ CLI fixtures → help topic → skill line → tests) that previously lived
spread across this file; AGENTS.md itself no longer repeats those steps.
The standing rule: a change that adds or changes a user-facing setting or
action owes a Sonic follow-up — an operation, or a named exclusion with
the reason — plus the skill update, filed as a follow-up task when the
feature ships, never a gate on the feature's own deploy.

**Sonic's scene/flare authority (2026-08-15, his own ask: "manage flares
and the settings within the scenes and creating scenes")** — a SECOND
mechanism module, `spectra/services/scene_console.py`, zero import of
`settings_console.py`/`room_controls.py`, whose only write surface is
`scene_store.save()`. `SCENE_SETTINGS_REGISTRY` (8 scalar keys: entry
blend, choreography timing, colour-journey pace, colour-set acceptance,
the drop shockwave on/off switch, and the per-scene drop timing offset
(2026-10-12, see drop_timing.py's own entry above) — charge/lull phase
ramps REMOVED 2026-08-20, see the Override Blend entry above; the ramp is
a computed dynamic stretch now, not a scene setting)
reads bounds off `SceneV2`/`PhaseChoreography`/`SceneColorJourney`'s own
`Field(ge=,le=)`, same discipline as the room registry. Named `FlareKind`
create/update/remove
(upsert by name) and `create_scene` (name + labels only — no device/effect
authoring, that stays the Initial Set tab) round out the original
enumerated set; device/effect SELECTION (which effect, drift, colour mode)
is deliberately NOT in scope, still true after the widening below.
**Reversed for VALUES only, 2026-10-06 (his own ruling: "yes, as long as
it doesn't limit more than we currently have")**: `get_scene_entry_params`/
`set_scene_entry_param` read and write any registered effect param's
CURRENT value on one scene's one device entry — the Pulse settings
among them — validated against the real effect registry (type/range/
options), with a ⚡-bound value REPLACED (and named as such) rather than
refused. **The property that protects his authored
scenes**: `create_scene` only ever builds a fresh `SceneV2(name=...)` — id
is the model's own `default_factory=uuid4`, so a created scene can never
collide with, and therefore never overwrite, an existing one. Reachable by
chat from `/scenes` too, not just `/settings`: `spectra/web/src/
components/SonicChatPopover.tsx` is a floating 💬 button + panel mounted
on `ScenesPage.tsx`, talking to the same `POST /settings-console/message`
endpoint. Full detail, the four adversarial refusal proofs, and the
fabrication-hunt re-proof against the widened CLI tool manifest:
`docs/SPECTRA_SPEC.md` §55, `tests/test_scene_console.py`.

**Sonic's overwrite/backup/undo/preview/restore authority (same night,
his follow-up: "edit scenes and overwrite them, back them up ahead of
time, an easy undo-last-agent-change button, a preview and check-in,
restore the backup if it's not right")** — the delete/overwrite exclusion
above is now PARTIALLY reversed, deliberately, with a safety net that
makes it so: `overwrite_scene` wholesale-replaces an existing scene's
name/labels/settings/flare_kinds in one shot (still never `devices`).
Every write that touches an EXISTING scene — `set_scene_setting`,
`set_flare_kind`, `remove_flare_kind`, `overwrite_scene`,
`restore_scene_backup` — now runs through `scene_console.
_write_and_verify_backup()` FIRST: snapshots the scene's pre-edit state,
writes it to the per-scene backup ring, then RE-READS THE FILE FROM DISK
to confirm the write actually landed before allowing `scene_store.save()`
to run — a successful write call alone is never trusted. Retention: the
last `SCENE_BACKUP_RING_SIZE` (10) edits per scene (oldest evicted first,
so undo-of-an-undo works), PLUS a permanent, never-pruned genesis snapshot
per scene captured on its first-ever edit — the anchor his 9 real scenes
can always return to regardless of how many edits pile up after it.
`undo_last_scene_change()` (no scene_id — global, most-recent-first,
mirroring the settings console's own "Undo last") and
`restore_scene_backup(scene_id, backup_id | "genesis")` are both
themselves backed-up edits, which is what makes undoing an undo work.
Every edit's `preview` field, and the standalone `get_scene_preview()`
read op, are `_diff_scenes()` — a real field-level comparison of two
STORED SceneV2 snapshots, never the model's own account of what it did;
the frontend renders this in its own visually distinct message
(`.settings-console-msg-preview`, both `SonicChatPopover.tsx` and
`SettingsConsolePage.tsx`) so it can never blend with Sonic's prose. The
plain, model-free "↺ Undo last" button (`POST /api/settings-console/
scene-undo`, mirroring `/undo`'s existing settings-only pattern) needs no
live model call — undo is a deterministic restore from an
already-verified backup. **Deploy held on this one, by the captain's own
order**, pending an adversarial proof run against a REAL model (not just
tests) on the live instance: an out-of-set op, a bad argument, a
non-scene-setting reach, a shell/restart attempt, the unavailable-tool
fabrication case specifically, an overwrite refused because its backup
fails, a fabricated restore claim caught against stored data, and
`create_scene`'s fresh-id guarantee reconfirmed under the real model.
Full detail: `docs/SPECTRA_SPEC.md` §56, `tests/test_scene_console.py`
section 9 (backup/undo/preview/restore), `tests/test_settings_agent_cli.py`
section 5c (the CLI backend's fabrication guard re-proven a second time).

**Sonic's parameter discovery + the "did it work" line** (2026-08-17,
`docs/SPECTRA_SPEC.md` §72): `fx/device_model.py`'s `param_descriptions()`/
`param_catalogue()` read a param's "what it does" text LIVE off the
vendored effect's own `CONFIG_SCHEMA` (`cls.schema()`, same MRO-merge
`scripts/backfill_param_defaults.py` already uses) — never a second
hand-written copy that could drift from the real schema; type/range/
default still come from the existing `effect_params()` registry. Two new
scene-domain `SonicOperation`s (`list_scene_params`/`get_param_info`,
`spectra/services/scene_console.py`) expose this narrowly (names first,
one param's full detail per call) — remember `settings_mcp_server.py` is
hand-maintained (one wrapper per `ALL_OPERATIONS` entry, not generated),
so a new operation needs a wrapper added there too, and the CLI backend's
`tests/fixtures/cli_transcript_synthetic_*.json` manifests updated to
list it or `_verify_tool_manifest` refuses every one of them as stale.
Separately: every `scene_console.py`/`settings_console.py` write result
now carries a deterministic `summary` string (and a rejection's own
`reason` already served that role) — `run_turn()`/`settings_agent_cli.
_parse_transcript()` collect a `rejected` list alongside `changes` so a
refusal is structurally available too, not only in the model's prose.
`spectra/web/src/lib/sonicPreview.ts`'s `fmtValue()` must never
`JSON.stringify` a raw object/array — a nested field like `flare_kinds`
diffs wholesale on any edit (`_diff_scenes`'s documented whole-field
behaviour), so a naive stringify is a real, previously-shipped path for
dumping a JSON blob into his chat; summarize (count/names) instead.

**Sonic can copy one device entry between scenes** (`copy_scene_device_
entry`, 2026-09-22, his ask: "copy the strips initial set from Fireworks
V2 to Fish"). The first crack in "device/effect editing is not in scope
for Sonic" — deliberately narrow: it copies exactly ONE `SceneDeviceConfig`
entry's effect_type/params/effect_steps/color/brightness/
background_brightness/drift (never `devices` wholesale, never a second
entry) from a source scene to a destination scene's entry for the SAME
target (a category name or virtual name, matched case-insensitively —
`scene_console._find_target_entries`), preserving the DESTINATION entry's
own `id` (or minting a fresh one via the model's own default_factory if it
had none for that target) so nothing that references the entry breaks.
`dry_run` defaults `True` and returns a per-field before/after diff with
nothing saved — Sonic's own instructions require showing him that diff and
getting his confirmation before ever calling it with `dry_run=False`. The
actual save goes through `scene_store.validate_for_save()` — the two
integrity guards (`accepted_set_ids`/dangling drift-profile refs) factored
OUT of `spectra/api/scenes.py::upsert_scene` into that one function
specifically so this write path and the human HTTP upsert can never
silently diverge on what a legal scene save requires. The editor itself
(a "copy from scene..." control on the Initial Set tab) was NOT built —
judged more than the small addition the ask called for; the Sonic path is
what he asked for. Spec: `tests/test_scene_console.py` §12.

**Subscription (CLI) backend — built, default OFF, not yet authorised
against his real account** (`data/spectra-console-subscription-backend/`:
scout report + the captain's ruling that provisioning an `ANTHROPIC_API_KEY`
is refused as an answer to "use my subscription, not credits"). `spectra/
services/settings_agent_cli.py` is a second `run_turn()` implementation
driving the real `claude` CLI headlessly (`-p`, non-interactive), authenticated
by `CLAUDE_CODE_OAUTH_TOKEN` (a `claude setup-token` long-lived token —
Anthropic's own documented mechanism for billing Claude Code automation to a
Pro/Max/Team/Enterprise subscription instead of API credits). `spectra/api/
settings_console.py`'s `POST /message` picks it over the API backend only
when `config.settings_agent_backend()` (env `SPECTRA_SETTINGS_AGENT_BACKEND`)
reads `"cli"` — default `"api"`, so this is inert until BOTH that env var is
set AND a token is provisioned; neither this file nor anything else in the
repo ever runs `claude setup-token` or reads an existing interactive `/login`
session itself. **THE WIDENED SURFACE IS STRUCTURAL, not a deploy note**: a
subprocess with its own working directory can auto-run project hooks and
auto-connect `.mcp.json` servers it finds there (non-bare `-p` mode — `--bare`
can't be used, it refuses to read the OAuth token at all), so every call
creates/verifies a dedicated, code-owned, empty working directory
(`config.settings_agent_cli_workdir()`, refuses if it ever contains a stray
`.claude/`, `.mcp.json`, or `CLAUDE.md`), passes `--strict-mcp-config` +
`--tools ""` + `--allowedTools` naming exactly the tools its own MCP
server (`spectra/services/settings_mcp_server.py`, a stdio wrapper around the
SAME `settings_agent._dispatch()` the API backend uses — no second authority;
one hand-written function per `ALL_OPERATIONS` entry, see that file's own
docstring for why it's not generated) exposes, and re-verifies the live
`system/init` tool manifest on every single response before trusting
anything in it — refusing the whole turn on a mismatch, **except one
deliberately narrow shape (2026-11-02, a stale un-restarted deploy):
extra-only drift (every expected tool present, plus newer ones this
process doesn't recognise yet) DEGRADES instead, since every tool_use
still has to round-trip the running process's own unwidened dispatch
table regardless — see that file's own module docstring section "A
STALE RESTART MUST DEGRADE" for the full reasoning.** That
refusal/degrade check exists because a live re-proof caught
`claude-haiku-4-5` fabricating tool-call output in plain prose, twice, when
the real tool manifest didn't contain what it claimed — `_parse_transcript()`
reads ONLY structured `tool_use`/`tool_result` blocks, never the model's
narrated text. Tests: `tests/test_settings_agent_cli.py` (offline, against
real captured transcripts in `tests/fixtures/cli_transcript_*.json` for the
original two-tool surface — now correctly refused as a stale manifest once
the tool set widened — plus hand-built, explicitly-labelled
`cli_transcript_synthetic_*.json` fixtures re-proving the same properties
against the current, wider surface) + a live smoke test skipped without
`CLAUDE_CODE_OAUTH_TOKEN`. **Enabling this against the captain's real account
is his call, not a deploy default** — flipping `SPECTRA_SETTINGS_AGENT_BACKEND`
and minting a token are both separate, deliberate, human actions.

**THE CLI BACKEND'S TOOLS RUN IN THE MAIN PROCESS (2026-10-04, Light Show
proof D1).** `settings_mcp_server.py` is a subprocess with no live stack
and its own copy of every in-process cache: Light Show fires there refused
"live stack is not up" and an arm there was overwritten by the main
process ("Armed" for nothing). Its `_call` now FORWARDS every tool to
`POST /spectra/api/settings-console/dispatch` (token-checked, the same
`settings_agent._dispatch`), named by `SPECTRA_SONIC_DISPATCH_URL`/`_TOKEN`
which `settings_agent_cli` sets; unreachable is a stated rejection, never a
local fallback. Every domain (show, room_effect, device, scene) inherits
it. Spec: `tests/test_sonic_main_process_dispatch.py`.

Voice reaches text by the browser RECORDING (MediaRecorder) and POSTing the
clip to `POST /api/settings-console/transcribe`, not the browser's built-in
SpeechRecognition (which ships audio to a third-party cloud and forecloses
ever routing it to a local transcriber). `spectra/services/transcription.py`
is the one seam that reaches it — its module docstring is TWO stacked wire
contracts, read it before touching any of this:

- **Browser-facing (ours to publish):** `POST /api/settings-console/
  transcribe`, multipart, one file field named `audio`. The browser
  negotiates `audio/webm;codecs=opus` explicitly (`MediaRecorder.
  isTypeSupported` + `recorder.mimeType` on the Blob, never a hardcoded
  guess) — WAV is not something this client emits. Response:
  `{text, vocabulary_honored}`.
- **Bridge-facing (2026-08-15, published and proven by the ship building the
  local-Whisper bridge — SPECTRA CONFORMS, does not renegotiate it):**
  `POST {whisper_bridge_url()}/transcribe`, RAW audio bytes as the body
  (never multipart — that shape stops at the API layer above), `Content-
  Type` forwarded unchanged from the browser, `X-Vocabulary` = the
  server-computed `vocabulary_hint()` string percent-encoded as a header.
  Response JSON: `{text, vocabulary_applied, content_type_received}`.
  `whisper_bridge_url()` (`spectra/config.py`) defaults to
  `http://127.0.0.1:8090` (verified, mirrors the bridge's own
  `STT_BRIDGE_PORT` default) — still `SPECTRA_WHISPER_BRIDGE_URL`-
  overridable, not a literal; loopback only works because both processes
  are plain host units on the same machine (see that function's docstring
  for the containerisation caveat, written down on purpose).

Two easy-to-miss bridge facts, enforced not assumed: **Content-Length
required, chunked rejected** — `transcribe()` only accepts `audio: bytes`
and refuses anything else (a file/iterator would silently make httpx
chunk); **25MB body cap**, checked before the request goes out
(`BRIDGE_MAX_AUDIO_BYTES`) rather than leaving the bridge's own rejection
to surface as a confusing generic error.

**A non-empty vocabulary hint the bridge doesn't confirm using is a hard
502, enforced twice, on purpose:** `transcribe()` itself raises
`VocabularyNotHonored` the instant `vocabulary_applied` isn't literally
`True` on a non-empty request (never returns a "generic" result), and
`settings_console.py`'s `post_transcribe` independently re-checks the
returned `vocabulary_honored` as a backstop against any OTHER
implementation (a stub, a future swap) that returns normally without
confirming. Neither trusts the other. `TranscriptionUnavailable` (bridge
unconfigured/unreachable/malformed, incl. connection-refused) is the
separate 503 path — the real bridge was confirmed DOWN the night this
landed (its test container was torn down); that is handled as this exact
honest-unavailable state, proven with `httpx.MockTransport` only, never by
probing/scanning the host. This whole feature — including the bridge call
above — ships UNVERIFIED against a live transcriber and against his room;
see the PR.

Spec: `scripts/check_settings_console.py` (both domains) +
`tests/test_settings_console.py` (settings) + `tests/test_scene_console.py`
(scene/flare).

## SPECTRA per-item mode availability + Colour Set/Group Preview

Two owner asks (2026-08-17), same button row. **Mode availability**:
`display_availability: "default"|"dark"|"light"` on `SceneV2`
(`spectra/models/scene.py`) and `ColorSetCard` — gates AUTOMATIC selection
only (`spectra/services/mode_availability.py`'s pure rule), never a manual
Fire/Preview/Force Scene. **`ColorSetCard` is defined TWICE** — the root
`models/color_set.py` (spot-effects' authoring model) and SPECTRA's
own read-only projection `spectra/services/color_sets.py` (`extra="ignore"`)
— a field added to one and not the other is silently dropped on every
SPECTRA-side read; `display_availability` had to be added to both. Don't
confuse this field with `ColorSetCard.display_mode`, the retired dark/light
"mode lane" variant-swap field (§36) — same three-value vocabulary,
unrelated meaning. Enforcement funnels through `scene_sequencer.
fire_scene_by_id` (the one scene-fire choke point, gates scene + resolved
colour set, Force Scene exempted) and `color_set_groups.
resolve_for_fire_mode_gated`/`_mode_available_members` (gates a Group card
itself before member substitution, then filters the member pool).

**Preview** (`spectra/services/room_preview.py` + `preview_pause.py`,
`spectra/api/room_preview.py`) replaces the Colour Set/Group editor's old
permanent "Apply to room": tap pauses SPECTRA's automatic changes 5s while
applying, then reverts; hold ½s pauses up to 60s and stays until released
(second press / timer / navigating away — `ColorSetsPage.tsx`'s unmount
effect + a `beforeunload` `sendBeacon`). Snapshot-and-revert goes straight
through `fx_seam` (mirrors `dark_light.py`'s own pattern) — NOT through
`drift_conductor`/the engine executor, since a preview must never touch
`active_set_id`/wheel position/fire_history. `preview_pause` outranks every
existing deferral (pause/dinner_party/ambient/force_scene) at `bridge.
conductor_deferral`/`sequencer_deferral` and `engine.fire_response_event`/
`fire_scene_update_event`. Live-drag colour edits call `POST /room-preview/
update` with at most one request in flight (a tick that lands mid-request
coalesces into one follow-up with the latest state, never queues).

Docs: `docs/SPECTRA_SPEC.md` §67/§68 for the full acceptance-criteria
writeup. Known gap, not fixed by this work: `ColorSetsPage.tsx`'s outer
`260px 1fr` grid has no phone-responsive layout (unlike `ScenesPage.tsx`'s
`useIsPhone()` treatment) — its toolbar is cramped at a real phone width,
though every control works once reached.

## SPECTRA per-scene colour-set PREFERENCE — a second axis, not the same control as availability

`SceneV2.preferred_color_set_mode` (`"default"|"dark"|"light"`,
`spectra/models/scene.py`, owner ask 2026-08-17: "black hole would prefer
dark mode color sets... they don't run light mode color sets unless the
system is set to light mode"). This is the design `docs/SPECTRA_SPEC.md`
§72 says superseded his own proposed "remove the redundant black
backgrounds" data-edit fix — that edit was investigated, found unsafe
(colour bleed between scenes once a black `bg_color` no longer resets a
virtual), and retired in favour of this build; his authored colour-set
data was never touched by either investigation. Deliberately separate from
`display_availability` above: that field gates whether an item plays AT
ALL in the current room mode; this one gates WHICH colour sets a scene
draws from once it does play. Resolution:
`spectra/services/mode_availability.color_set_preferred(card_availability,
scene_preference, room_mode)` — no preference matches everything; a
declared preference matches every set marked the same way plus every
UNMARKED ("default") set (additive, matching his own "you don't have to
change any color sets"); it excludes only a set marked the opposite mode.
**Hybrid vs explicit, generalised from his one stated case**: he named only
system Light overriding a Dark preference — symmetrized here (explicit
Dark also overrides a Light preference) so neither direction can strand a
scene with zero eligible sets — preference is consulted ONLY while the
room is Hybrid; an explicit Dark or Light room mode uses the
availability-filtered pool as-is. Wired at the one choke point that
already applies availability to a colour-set pool,
`scene_sequencer._default_eligible_sets` — not `drift_conductor`'s
destination pool or `scene_response.py`'s flare colour-jump pool, neither
of which apply availability there either (checked, not assumed to be
covered).

**The fallback that must not go wrong**: his real `color_sets.json` had 0
of 50 sets carrying any dark/light marking at build time, so on deploy day
every scene's preference matches nothing marked — the fallback MUST be the
full unfiltered pool, never empty (an empty pool would go a preferring
scene dark the instant this ships). `color_set_preferred()` guarantees
this by treating an unmarked card as matching every preference;
`tests/test_color_set_preference.py::
test_preference_never_produces_an_empty_pool_when_nothing_is_marked` proves
it against a 50-set unmarked library rather than asserting it. No second
marking system was built — the existing Mode availability toggle on a
Colour Set (`ColorSetsPage.tsx`) is the one surface that marks a set dark
or light; `ColorSetsTab.tsx` shows each set's marking read-only so it's
visible while choosing a scene's preference.

**Editing an existing SceneV2 by script: never round-trip through
`scene_store.save()`/`model_dump_json()` for a single-field change.**
Loading a scene through `SceneV2` and writing it back re-serializes EVERY
field in current canonical form — in particular it runs
`_migrate_flare_kinds`, the legacy flare-band migration shim, and
permanently rewrites `param_patch`/`gain`/`reroll_dice`/`color_set_jump`
into the newer `flare_kinds`/`kinds` shape on every scene it touches, even
though the model asserts the two are behaviourally equivalent — caught
(before merge) doing exactly this in `scripts/set_scene_colorset_
preference.py`'s first draft while setting one unrelated field. The fix,
and the pattern for any future single-field scene migration script: load
the RAW JSON dict, use `SceneV2(**raw)` only to READ (validation, name
matching, diagnostics), and write back by mutating the raw dict's specific
key directly — `tests/test_set_scene_colorset_preference.py` diffs
before/after JSON to prove only the intended key ever changes.

Docs: `docs/SPECTRA_SPEC.md` §74. Spec: `tests/test_color_set_preference.py`
+ `tests/test_set_scene_colorset_preference.py`. Migration:
`scripts/set_scene_colorset_preference.py` (dry-run default, `--apply`,
backs up the whole store first) sets Black Hole V2 / Black Hole V2 UI /
Fireworks V2 / Dancers V2 to `"dark"` — not run against live storage by
this build, an operator/deploy step same as `seed_star_strips.py`'s own
convention.

## SPECTRA colour-set / colour-group likelihood curves

His ask: colour Sets get a likelihood curve reusing the scene sequencer's
own structure; Groups get one too, default flat, that MULTIPLIES onto a
member Set's own curve rather than overwriting it. Sets already had this —
`SequencerConfig.color_set_entries` (`spectra/models/sequencer.py`) is
keyed generically by any `ColorSetCard` id and was already read by
`selection_kernel.select_color_set` (curve × genre × wheel-travel) — so a
Group's curve needed no new storage shape: it lives in the SAME dict, keyed
by the Group's own id. A Group never becomes its own selector candidate
(still `kind=="set"`-only, unchanged from §10); its curve instead
multiplies onto every member Set's score as a fourth factor
(`selection_kernel.group_curve_mult`, `Candidate.group_points`), resolved
via the reverse lookup `spectra/services/color_set_groups.
group_ids_by_set()`. A Set under more than one group (real data: 4 sets
under both "First Group" and "Blues") CHAINS every enclosing group's curve
by further multiplication — never "one wins". Flat/no entry is an exact
float `1.0` identity. The colour ladder gained its own rung,
`RUNG_NO_GROUP` (dropped before wheel-travel, before genre) so a set zeroed
only by an enclosing group's curve recovers the same way a wheel/genre veto
already did — only a set's OWN curve hitting zero stays ladder-proof.
`Pick.factors` carries the resolved `group` multiplier per candidate,
surfaced in `SequencerStatusStrip.tsx`'s "last colour pick" breakdown, so a
starved set is explainable by looking, not a silent mystery. The curve
preview-button/picker/window/Detach/Revert/Save-as-named-curve editor
(`SequencingTab.tsx`'s original inline implementation) was extracted
verbatim into `spectra/web/src/components/CurveAttachmentEditor.tsx` and is
now mounted on both a Set's and a Group's card in `ColorSetsPage.tsx`
("Likelihood" section) — same component, same safety rule, not a parallel
editor. **Reworked 2026-08-19** (card reopened, his words: no
expanded/collapsed selector sitting in the window — a button showing a
live `CurveThumbnail` of the curve in effect, pressing it opens the picker
— and an edit is an immediate one-off, "the status change IS the apply",
no separate Apply step): every edit (drag/add/remove point) writes
straight to the entry's own `inline_points` on the first touch, coalesced
like `ColorSetsPage`'s own live-drag preview updates, and is structurally
incapable of touching a shared `curves[id]` — only the explicit "Save as
named curve…" can, gated behind its overwrite warning as before. "↺ Revert
to original" undoes an edit session back to exactly what was attached
before it started. Full detail: `docs/SPECTRA_SPEC.md` §65/§76. Spec:
`tests/test_color_set_group_curves.py`.

## SPECTRA minimum dwell (rebuilt 2026-08-20 — read before touching "dwell" anywhere)

Dwell was rebuilt under the real definition of a "song transition" (his
words: it means transitions *within* a song, or scene trigger calls — not
between songs). The OLD mechanism — `SelectorEntry.dwell_weight`
(`spectra/models/sequencer.py`), resolved to a SONG COUNT
(`resolve_dwell_songs`, now removed) and gated only inside
`SceneSequencer._on_change_moment`'s own song-transition roll — is
RETIRED. It never touched the path he actually uses: SPECTRA-native
triggers (`trigger_engine._fire`'s `fire_scene` action) went through
`fire_scene_by_id` with zero dwell awareness of any kind, on ~22,000 real
fires.

New mechanism, `spectra/services/dwell.py` — read its own docstring before
touching this. A per-scene MINIMUM HOLD TIME, a curve over intensity (y =
SECONDS, not a likelihood), reusing the SAME `CurvePoint`/named-profile
curve-selector shape and `CurveAttachmentEditor.tsx` component the
sequencer's likelihood curves already use — `SceneV2.dwell_curve`
(`spectra/models/scene.py`, a `CurveAttachment` — the same curve_ref/
inline_points pair minus `SelectorEntry`'s genre_mult/dwell_weight).
`None` = his exact default, `dwell.DEFAULT_DWELL_CURVE` (16s @ intensity
0, 4s @ intensity 1, linear). Gated ENTIRELY at `scene_sequencer.
fire_scene_by_id` — the one choke point every automatic scene-change path
(sequencer roll, trigger `fire_scene`, automatic transition) already
funnels through — so it covers all of them uniformly for free, and fixes
a second bug as a side effect: the OLD mechanism's "current scene" belief
(`SceneSequencer._active_id`) went stale the instant a SPECTRA-native
trigger fired a different scene (it only updated from the sequencer's own
rolls or an OBSERVED legacy bridge fire); `dwell.py`'s state is
process-global, fed by the one function every real fire passes through,
so it structurally cannot have that staleness.

His four answers (binding, `data/plan-make-dwell-meaningful-under-the-
rea-4p73/HIS-DECISION.md` — "do all your recs"): **(A)** no clock reset on
an update effect — a minimum is a floor; only a REAL fire calls
`dwell.note_fired`, never a deferral. **(B)** intensity LATCHES at
entry — `dwell_seconds` is computed once, from the intensity the scene
actually fired at (the render intensity `fire_scene_by_id` was called
with), never re-evaluated while the hold is running. **(C)** every
AUTOMATIC path is gated; the manual editor Fire button is exempt (it
already bypasses `fire_scene_by_id`, same as disabled/mode-availability);
Force Scene still wins but the result NAMES the override
(`overrode_dwell=True`, forwarded through `room_controls.
reconcile_force_scene_if_changed` — same pattern as `overrode_disabled`).
**(D)** a deferred scene change fires the current scene's own UPDATE
EFFECT instead — `engine.fire_scene_update_event` (`scene_response.py`'s
`on_update`), called from dwell's deferral branch, which returns the
`on_update` record (not `None`) so the caller can log what happened.
Originally this meant the scene's own named, type="permanent"
`SceneV2.update_kind` (bypassing band selection entirely) — but 8 of his
9 real scenes had no `update_kind` authored, so most deferred dwells held
with nothing visible happening. **Replaced same-day (2026-08-20, his ask:
"make update scene act like a double intensity flare until we build it
out specifically")**: `on_update` now doubles the given intensity (clamped
to 1.0 — his accepted ceiling, so "double" and "full" read identical from
intensity 0.5 up) and runs it through the scene's own ordinary "flare"
ResponseClass — the SAME band-selection + kind-execution `on_event` runs
for a genuine flare (`_execute_band`, shared by both). No permanent-only
restriction, nothing new to author: every one of his real scenes already
has a "flare" response, so a deferred dwell now visibly flares on all of
them, not just the one (STAR) with an authored `update_kind`.
`SceneV2.update_kind` is untouched (still authorable, still validated) but
simply unread by this path now — reserved for whenever a real, purpose-
built update effect gets designed; don't repurpose it for that without a
fresh ask. Because `on_update` can now land a momentary kind, a dice
re-roll, or a colour rotate — none of which the original permanent-only
design ever produced — `fire_scene_update_event` also schedules their
releases the same way `fire_response_event` already does
(`pending_hold_groups`/`pending_color_rotate_holds`), which it never
needed to before.

**The interim hold is NEVER SILENT either way**: `fire_scene_by_id`
records every deferral to `fire_history`'s `"deferred"` bucket
(`{scene_name, remaining_dwell_s, update_result}`, both the durable count
and the show-log timeline, visible on the Review page), so "why didn't
the room change" is a log lookup, not a mystery indistinguishable from
triggers having stopped working — now doubly true since a scene with no
"flare" response at all (the only remaining no-op case) is rare to begin
with. Real-fixture proof against his actual scene library (not just a
synthetic harness): `scripts/check_update_effect_double_intensity.py`.

Frontend: `SequencingTab.tsx` mounts a SECOND `CurveAttachmentEditor`
below the likelihood one, `attachField="dwell_curve"` — a THIRD storage
path the shared component didn't have before (round-trips `POST /scenes`
via `useAttachCurve`, not `PUT /sequencer/config`), plus two small
additive props (`defaultPoints`/`noneLabel`) so "no override" previews his
real 16s/4s default instead of a misleading flat-1.0 line — never a
parallel control, the same component every other curve in this app uses.
**Those props only engage when the caller passes NO entry for an unset
item** — `CurveAttachmentEditor`'s 'none' state is keyed on `entries[id]`
being `undefined`; an entry present with both curve fields null reads as
'flat'. `SequencingTab`'s dwellEntries shipped fabricating a both-null
entry for every scene, so every unset scene (all nine of his — stored
`dwell_curve: null`, correct data) displayed "Flat 1.0" and clicking the
Default tile looked dead (it wrote null over null and the display lied
again after refetch) — his 2026-08-21 report, fixed by filtering unset
scenes out of the entries record, display-only, no data touched
(`scripts/check_dwell_curve_display.mjs` reproduces both sides). Any
future caller adapting a nullable single-field attachment into this
component must map "unset" to entry-absent, never to a both-null entry.
Spec: `tests/test_dwell.py`, `scripts/check_spectra.py`'s own MINIMUM
DWELL section (mirrors the Force Scene proof immediately above it).

**Rebased past #148 (My-triggers-only mode) and #150 (charge/lull ramp
scales to the real gap to the next trigger) — both landed on master the
same week and both touch this area; checked, not assumed, that they
compose.** `engine.fire_scene_update_event` gained a second caller (this
module's deferral) the same week #148 widened its own internal gate from
literal `"full"` to `("full", "triggers_only")` — the merged function
keeps BOTH: the widened gate AND the `Optional[dict]` return this module
needs to log what the update seam actually did
(`tests/test_dwell.py::test_fire_scene_update_event_runs_under_triggers_only`
proves the merge, all four tiers). The dwell gate itself never reads
`scene_change_mode` — it applies uniformly regardless (his decision C),
proven directly under `"triggers_only"` (his room's real live mode) in
`test_dwell_defers_correctly_regardless_of_scene_change_mode`, not just
the `"full"` default every other test here runs under. #150 removed
`SceneV2.phase_blend`/`PhaseBlend` entirely — unrelated to `dwell_curve`,
which sits lower in the same model and rebased clean. **The one real
interaction, named not silently accepted**: #150's charge/lull ramp
stretches toward the NEXT trigger's timestamp when it has no lull or drop
of its own ahead (`_phase_partner_gap_ms`, a FORWARD-looking gap read off
the trigger schedule) — if that next trigger
is a `fire_scene` action and dwell's minimum hasn't cleared, the dramatic
build lands on an update effect instead of the scene switch it visually
promised. `dwell.py` and `_phase_ramp_ms`'s own docstrings both spell out
why these are genuinely different gaps (not a shared formula that could
drift) and why predicting the other side isn't attempted — see either.

**`engine._update_gate` widened again, 2026-09-26 (Admiral order,
`data/scene-flare-flow-explainer/report.md` candidate 2), to
`("full", "triggers_only", "analysed")`** — a deferred scene-change
attempt under "Transitions + analysed" used to draw nothing, while the
identical deferral under "triggers_only" already drew the flare; the two
are meant to behave the same on a song with no authored triggers of its
own (`trigger_engine._effective_mode_for_song`'s per-song fallback
collapses "triggers_only" to exactly "analysed" there), so the asymmetry
was a bug, not a design line. "transitions" is still excluded — no
generated (non-authored) trigger, and therefore no deferral of one, ever
reaches this gate under "transitions" (`trigger_engine._trigger_allowed`
never lets a non-authored trigger fire there). See `_update_gate`'s own
docstring in `spectra/services/engine.py` for the full reasoning. Spec:
`tests/test_dwell.py`.

## SPECTRA scrubbing previews — flares, TRANSITIONS and the DROP SEQUENCE

Owner ask 2026-08-20, `data/timeline-preview-scrub-flares-and-drop-
sequences/HIS-VERBATIM-WORDS.md`, his own sequencing: "start with the
flares, then we will do lull charge drop". **The second half is now built
(2026-08-27, fm/flare-preview-offsets-everywhere, his order: "get it
finished and tested, then push it to transitions and to the drop
sequence") — see "THE OTHER TWO PREVIEWS" at the end of this section.**
The flare design below is still scoped to a single isolated `FlareKind`;
the other two are separate programs over the SAME hold, never second
holds.

`ResponseEngine.fire_kind(kind, intensity)` (`spectra/services/
scene_response.py`) fires ONE declared kind in isolation, bypassing band
selection — mirrors `on_event`'s fixed dice→moves→gain→colour order at
scale=1.0. `spectra/services/flare_preview.build_timeline(scene, kind,
intensity)` drives it against a SCRATCH `DriftConductor`/`ResponseEngine`
pair (real `scene_compiler.resolve_scene`/`compile_scene` resolution —
same reads a dry-run scene test-fire already makes — but `room_save=
lambda _st: None` on both, so nothing is ever persisted) wired to a
`RecordingExecutor` and a controllable fake clock: every write's real
relative timing (glide duration, hold_s before a momentary release,
`PULSE_RELEASE_S`) is computed in one synchronous burst, never actually
waited. This is his pre-authorised "catch-up" path ("ideally live, but
catch-up is fine if substantially easier") — and a better instrument for
his stated purpose than a live capture would be, since a live poll can
itself lie about a fast transition (see the CLIP v2 `dynamics.duration`
polling entry above); the returned `animation_start_s`/`animation_end_s`
are read straight off the real production constants, not sampled.
**One easy-to-repeat mistake, caught building this**: `conductor.
on_scene_fire` must be called with the scene's ORIGINAL `flare_kinds`/
`devices` (bindings intact), not the `resolve_scene`-resolved copy — the
resolved copy has already replaced every `ValueBinding` with a scalar, so
a dice-reroll kind previewed against it re-rolls nothing (zero writes).
`scene_compiler.fire_scene` itself gets this right by calling
`engine.on_scene_fired(scene, writes, ...)` with the pre-resolution
`scene`, not `resolved` — mirror that, not the resolved copy, in any
future code that seeds a conductor this way.

API: `spectra/api/flare_preview.py` — `POST /open` (computes the
timeline, arms `preview_pause` — see that module's docstring, now a
second caller alongside `room_preview.py` — does NOT fire live, see the
TRUE SIMULATION entry below), `POST /fire` (the live half — the ONLY
caller of `flare_preview_hold.open_hold`, called once per loop cycle by
the frontend), `POST /heartbeat` (re-arms; the frontend pings this every
5s while the overlay is open), `POST /close`. "Automatically pauses the
trigger engine" is this pause, kept alive only by the heartbeat — no
fixed-duration timer covers "however long he leaves the overlay open."

Frontend: `spectra/web/src/scenes/tabs/FlarePreviewOverlay.tsx`, opened
from a "▶ Preview" button on each flare-kind card in `ResponseTab.tsx`.
Two independently-positioned marker kinds, per his brief ("I would see
the marker for where the trigger should align, as well as some markers
showing start and end of animation" — deliberately not the same line):
the TRIGGER mark is draggable and DEFAULTS to coincident with the
computed animation start; the START/END markers are fixed, computed,
never dragged. Dragging the trigger mark writes `FlareKind.
trigger_offset_ms` (`spectra/models/scene.py`, signed ms, default 0,
**HIS sign convention** — negative = fire earlier, positive = fire
later, see the TRUE SIMULATION entry below for the full ruling and the
inverted-sign defect it corrects) via `setScene` — a real scene-DRAFT
edit, saved by the page's own Save button like any other field, not a
preview-only value discarded on close. **No longer descriptive only as
of 2026-08-21 — this field is what the live preview's own fire loop
schedules from** (see below), **and since the same day's follow-up (PR
fm/engine-reads-flare-trigger-offset, his ask: "make the engine read the
offset and work with the offset like we had in spot FX") THE REAL FIRING
PATH READS IT TOO**: `trigger_engine.tick()` relocates a `fire_response`
trigger's target by the fired band's authored kind offset
(`scene_response.band_trigger_offset_ms` — its docstring carries the
multi-kind aggregation rule: min over EVERY declared, enabled kind's
offset, zero included — it was min over the NONZERO offsets until the
2026-09-16 fix recorded under PER-FLARE TRIGGER MOMENT below — this is the
ONE band-wide relocation `tick()` still applies, unaffected by PER-FLARE
TRIGGER MOMENT below, which only changed what happens once the fire
lands), read LIVE off the ACTIVE scene at render intensity,
composed with the automatic lead exactly as #172 composes the
trigger-level sibling field (`target = timestamp + his_offset`, then
`fire_at = target - lead` — never the same sign added/subtracted). All 61
of his real flare kinds carried offset 0 when this shipped (re-verified
live), so it changed nothing stored. Two structural guards ride with it
in `tick()`, both needed because this target is LIVE (the active scene
changes between ticks): a fired-keys memory — `(trigger_id,
timestamp_ms)`, cleared with `_pins` on song change/rewind — that ALSO
fixes a pre-existing double-fire in the safety-net OR clause (any trigger
fired more than one tick early used to fire AGAIN when its nominal
target crossed the window — reproduced red pre-fix; the module
docstring's "fires once per crossing" was emergent, now explicit), and a
stranded-target net (a target relocated behind the window uncrossed
fires late-not-never, only while the raw mark is still ahead and
playback advanced). Scoped like the lead system: stored triggers only —
a bridge-classified flare has no forward notice, nothing to relocate.
Specs: `scripts/check_triggers.py` §11,
`tests/test_flare_kind_trigger_offset.py`.

**PER-FLARE TRIGGER MOMENT (2026-09-16, his order: "build the offset
independence for flares and implement it" — exactly the authorisation
`band_trigger_offset_ms`'s own docstring said this needed).** Before this,
a band fired ATOMICALLY (one `_execute_band_locked` burst), so ONE offset
had to speak for every kind attached to it — the aggregate `min()` above
is unchanged and still governs the band's own tick-level relocation, but
INSIDE the fire every kind now honours its OWN `trigger_offset_ms`
independently, ported verbatim from legacy `services/trigger_engine.py`'s
`MorphLane` shape: `_band_anchor_ms` (the same value `band_trigger_offset_
ms` always computed) stays the anchor; each attached kind then waits
`max(0, kind.trigger_offset_ms - anchor_ms)` (always >= 0 — structurally
so since the 2026-09-16 fix below, `_band_anchor_ms`'s min is taken over
EVERY declared offset including 0, matching legacy's own literal
min-over-all) before executing. A delay of 0 runs
INLINE (`ResponseEngine._run_kinds`, the extracted pipeline
`_execute_band_locked` always ran); any other delay is a
`PendingKindBatch`, scheduled by `services/engine.py` the SAME shape
`take_release_schedule`/`_release_group` already established for
momentary releases (`take_kind_batch_schedule`/`run_kind_batch`). A band
whose kinds all sit at 0 is byte-identical (no batch is ever created).
The fixed dice -> permanent -> momentary -> gain -> colour order still
governs collisions WITHIN one batch (so the per-fire singletons — one dice
roll, one colour jump — are now per batch); two kinds staggered into
DIFFERENT batches are deliberately reordered in real time — that IS the
feature. ONLY A FIRE `tick()` ALREADY RELOCATED BY THE ANCHOR STAGGERS
(`on_event(..., anchor_relocated=True)`, passed as `via_trigger` by
`engine.fire_response_event`, and by the drop-sequence preview that draws
that same relocation): a bridge-classified flare, `on_update` (dwell's
deferral and the `fire_scene_update` action) and `POST /api/engine/event`
run their band at their own un-moved moment, so they fire it ATOMICALLY
exactly as before — measuring from the anchor there would hold 0-offset
band-mates behind a mark nothing relocated. Four rules ride with it, all
in `scene_response.py`'s module docstring: a batch is due at the fire's START + its delay, never after
the inline burst; a batch is a fire in miniature (own `_fire_seq`,
captured once and threaded to every release it pushes, and no other fire
may arm or schedule its releases while it is still in flight —
`_fires_in_flight`; `engine._schedule_fire_tail` schedules what it armed once
it ends — the kind-batch
queue is the third queue every drain point must schedule, including
`flare_preview_hold` and `POST /api/engine/event`); a woken batch re-checks
the gate its fire passed and SKIPS (never fires) onto a changed scene;
and every outcome lands in `responses.kind_batch_log` (landed / skipped_* /
error). `fire_kind` (the isolated single-kind preview) is untouched: a
lone kind's own anchor is itself, so its delay is always 0. **FIXED
2026-09-16 (spotfx-zero-offset-fires-on-mark, captain's ruling "yes
fix"): an all-positive-offset band used to anchor on its positive value
(`_band_anchor_ms`'s min was over the NONZERO offsets only), so a 0-kind
was clamped to the band's already-delayed moment and fired late while its
own preview drew it on the mark.** `_band_anchor_ms` now takes the min
over EVERY declared offset, zero included — matching legacy's own
literal min-over-all — so a 0-kind on an all-positive band anchors the
fire (fires on the mark) and its positive sibling is deferred behind it;
a band containing a negative offset is unaffected (zero never competed
with it). **The anchor is also where a charge/lull/drop's phase drive
begins** (`on_event` runs `_drive_phase` at the relocated fire start), so
delaying a class's phase choreography now needs EVERY enabled kind in its
band, pooled alternatives included, to carry a positive offset — one
untouched-0 kind anchors the phase on the mark. Accepted on purpose, not
narrowed: exempting phase bands would be a new special case, and starting
on the mark honours the settled drop-begins-on-its-mark rule.
Measured against his real scenes at fix time: 0 of 83 authored
flare kinds (every response class) carried a nonzero offset, so this
changed nothing on disk.
Remaining out of scope: the automatic lead (`_response_switch_lead_ms`)
stays BAND-wide, subtracted once from the whole fire's start, so a kind
sharing a band with a smooth glide or a colour rotate fires earlier than
its own preview's per-kind head start shows. Spec:
`tests/test_flare_per_kind_stagger.py`, `tests/
test_flare_kind_batch_lifecycle.py`, `tests/
test_flare_preview_shows_stagger.py`.

Help: `spectra/web/src/help/helpContent.ts` id `flare-preview-timeline`
(under the `scenes-page` section, next to `flare-kind-edit-box`),
deep-linked from the overlay's own `<HelpLink topic="flare-preview-
timeline" />`.

Executable spec: `scripts/check_flare_preview.py` (dry-run-only, no live
storage write — asserts against the real `scene_response.py` timing
constants, not re-derived approximations; also proves a momentary
kind's release is silently skipped when its param has no resolvable
baseline, e.g. a boolean, matching real production behaviour rather than
being a gap this feature introduces).

**Correction, same day (2026-08-20): the preview above touched nothing
real, and his own live test caught it** ("i have tested some of the
flares and they do not actually change anything on the lights"). His
words on opening one, verbatim: "previewing a flare should temporarily
call the scene, and hold it while the preview window is open. then
release when it is closed" (his transcription drops letters — "hold" is
the only reading that fits). `spectra/services/flare_preview_hold.py` is
the live half, built ALONGSIDE `flare_preview.build_timeline` above,
which stays exactly as documented (a pure, hardware-free computation for
the browser's scrub/markers — unchanged). `open_hold(scene, kind,
intensity)` calls `flare_preview._scratch_engine` (now taking a
caller-supplied `executor`/`clock` rather than always building its own
`RecordingExecutor`, so the timeline model and the live fire can never
silently diverge in what they resolve) wired to `_SeamExecutor` — an
adapter onto `fx_seam.apply_writes`, the SAME ownership-routed seam
`room_preview.py`/`dark_light.py`/`ambient.py` already use for their own
explicit-owner writes, never a bespoke live-write path or the PRODUCTION
`engine.conductor`/`engine.responses` singletons (using those would make
"release" require deep-copying and restoring live engine-internal state —
the exact trap `room_preview.py`'s own docstring names for
`active_set_id`/wheel position). The scene's own compiled writes land via
`fx_seam.apply_writes` directly (skipping `scene_compiler.fire_scene`'s
`engine.on_scene_fired` call for the same reason), then `kind` fires for
real against the scratch pair via `ResponseEngine.fire_kind` — so a real
momentary/permanent/dice/gain/colour-jump write reaches his fixtures,
with real relative timing (`PULSE_HOLD_S`/`PULSE_RELEASE_S`/
`DICE_REROLL_GLIDE_MS`), not a `RecordingExecutor` entry.

**A facade PUT with `transition_ms>0` does not update `effect.config`
synchronously** — `fx/effects/__init__.py`'s `start_param_transitions`
stores a per-param tween, advanced once per RENDERED FRAME, not per PUT.
This bit the revert specifically: `transition_ms=0` (room_preview's own
convention, safe there because that module never creates a tween in the
first place) calls `_apply_config` directly WITHOUT clearing any
already-in-flight tween on the same key — a still-glide-ing flare param
would silently resume overwriting the "reverted" value on the very next
rendered frame, landing on the flare's own target instead of the true
baseline. Fixed with `REVERT_TRANSITION_MS=1` (mirrors `fx_executor.py`'s
own `JUMP_MS` convention): a positive duration always takes the
tween-RETARGET branch, replacing any dangling tween for that key from
wherever it currently sits — no snap, and no way for an old glide to fight
a revert. Any future revert/instant-write code in this codebase that
might race a param this same module (or the production engine) is
mid-tweening needs the same 1ms convention, not `transition_ms=0`.

**Release is deadline-driven, not close-driven — the same shape as
`spectra/services/preview_pause.py`'s own `_until`, not a bespoke
per-session `asyncio` task.** `_deadline` is a plain monotonic timestamp;
`open_hold`/`touch` only ever write it (a trivial operation that can't
itself fail); `run_supervised()` — started once from `spectra/app.py`'s
lifespan alongside `frame_watchdog`/`ownership_reconciler`/
`ambient_music_gate`'s own — independently checks every
`SWEEP_INTERVAL_S` (2s) whether a held hold's deadline has lapsed and
reverts it if so, exactly the "a write-time confirmation proves only the
moment it was taken" lesson `ambient_music_gate.py`'s own status-honesty
fix already established in this codebase. This is what makes a lapsed
heartbeat (browser closed rather than the tab's own unmount handler
firing, a dropped connection, a wedged tab) self-heal with NO dependency
on an explicit `/close` ever arriving: worst case `HEARTBEAT_TIMEOUT_S`
(15s, owned by this module, reused verbatim by `spectra/api/
flare_preview.py`'s `preview_pause` window rather than a second,
separately-tuned number) + `SWEEP_INTERVAL_S` (2s) = **17s** after the
last heartbeat. `active()` is itself a pure deadline read (mirrors
`preview_pause.active()`), so a caller never sees "active" reported past
the deadline just because the sweep hasn't ticked yet — reporting and
reverting are deliberately separate concerns.

**A service restart is the one case the deadline can't cover** — it's
in-memory only, same as `preview_pause`'s own `_until`, so it (and the
sweep's ability to know a hold was ever open) is wiped along with
everything else, while the light bytes a restart leaves behind are real.
Handled the same SHAPE as `fx/light_ownership.py`'s own
`recover_stale_handover()`: the pre-fire snapshot is persisted
(`FLARE_PREVIEW_HOLD_FILE`, tmp+`os.replace` atomic, mirroring
`dark_light.py`'s own pre-dark snapshot survival) the instant a hold
starts; `recover_stale_hold()`, called once from `spectra/app.py`'s
startup lifespan (after `handover.resume_own_room()` re-activates the
live stack — reverting is itself a real `fx_seam` write), lands any
snapshot still on disk before anything else touches the lights.
Deliberately NOT age-gated the way `recover_stale_handover()` is: that
gate exists because a young handing-over record might be a LIVE
orchestrator in the OTHER process, still legitimately mid-transition —
there is no second process that could legitimately hold a flare preview
open, so a leftover snapshot found at startup is unconditionally stale
and always gets landed back.

Snapshotting happens once per session (the first live fire — see the
TRUE SIMULATION rebuild below for what "first" means now): every
subsequent live fire in the same session re-fires scene+kind at the
current value without re-snapshotting, so a later revert always restores
the ORIGINAL pre-preview state, never a mid-session one. Help
(`spectra/web/src/help/helpContent.ts` id `flare-preview-timeline`) leads
with what opening a preview does to the room (real lights, paused live
show, ~17s worst-case abandonment revert AND a 3-minute absolute ceiling —
see "MAXIMUM HOLD CEILING" below, they are two different claims) before
any control explanation — Order 20: a feature whose help contradicts what
it now does has not shipped. Proof bar: a real headless render pipeline
(`fx.headless` +
`fx.facade`, ownership=spectra — the same rig `test_room_preview.py`
already uses), reading a written value off a live
`virtual.active_effect.config`, never a `RecordingExecutor`'s own write
log. Tests: `tests/test_flare_preview_hold.py` (fire+release, mid-session
re-fire, deadline lapse + sweep, `run_supervised()` end-to-end, restart
recovery) — `open_hold()` itself is unchanged by the rebuild below, only
who calls it and when.

**TRUE SIMULATION — loop + fire-on-the-mark (2026-08-21, PR
fm/preview-loops-and-fires-on-the-trigger, his report: "the preview only
happens once, it should happen every time, and it should fire with the
same timing as if the playhead was crossing a trigger").** Before this,
`/open` did two things in one call — computed the (hardware-free) ruler
timeline AND fired live, INSTANTLY, regardless of where the drawn trigger
mark sat: the drawing knew about the mark, the firing didn't.
`spectra/api/flare_preview.py` now splits this: `POST /open` computes the
timeline only (still arms `preview_pause`, no live write) and `POST
/fire` is the sole caller of `flare_preview_hold.open_hold`. The frontend
(`FlarePreviewOverlay.tsx`) calls `/fire` once per loop, timed by its
existing RAF playhead loop to land exactly when the playhead crosses
`animation_anchor_s` — a new field in `build_timeline`'s response
(`spectra/services/flare_preview.animation_anchor_s`/`trigger_mark_s`,
computed server-side so the ruler draw and the fire schedule are
ONE source of truth, never two independently-derived numbers). Firing at
the anchor every cycle is definitionally "lead `offset_ms`
early/late relative to the trigger mark's own crossing," since
`trigger_mark_s` is DEFINED from the anchor via the offset — there is no
second lead-time computation to keep in sync.

**The sign-convention fix this exposed, HIS RULING (same PR, corrected a
genuine inversion in the 2026-08-20 original build):** negative
`trigger_offset_ms` = fire earlier, positive = fire later, 0 =
coincident; dragging the trigger marker RIGHT makes the offset MORE
NEGATIVE. The original build had `trigger_mark_s = anchor + offset/1000`
(the opposite sign) — caught before any real value existed to migrate:
all 61 of his real flare kinds carried 0 at the time, confirmed by a
parallel live-data audit before the fix shipped, so nothing of his was
flipped. `FlareKind.trigger_offset_ms` is NO LONGER descriptive-only — it
is what the live preview loop schedules its fires from now. If you touch
this area again: `trigger_mark_s = animation_anchor_s -
trigger_offset_ms/1000` is the ONE formula (spectra/services/
flare_preview.py) — never re-derive it independently in the frontend or
you will reintroduce exactly this class of bug. Tests:
`scripts/check_flare_preview.py` (the sign proof, both directions),
`tests/test_flare_preview_api.py` (the open/fire route split),
`tests/test_spectra_trigger_offset_field.py` (the trigger-model field
shape).

**His scene-change/trigger-level equivalent, `SpectraTrigger.
trigger_offset_ms` (`spectra/models/trigger.py`, same field/units/sign),
is HONOURED too now (2026-08-21, PR fm/scene-changes-honour-trigger-
offset)** — and since 2026-08-27 (fm/flare-preview-offsets-everywhere) on
EVERY action kind, not just `fire_scene`. A silently-inert field is a
trap, and an OFFSET has no action-kind-specific meaning to justify one: it
only RELOCATES the moment, where a LEAD has to know what payoff it aligns
and how long that payoff takes, so an offset composes with an instant
apply (`select_color_set`, `fire_scene_update`) exactly as with a
crossfade. **Where the fired CONTENT also carries an authored offset, the
two ADD** — `SceneV2.trigger_offset_ms` for `fire_scene`,
`band_trigger_offset_ms` for `fire_response` — legal because both are
OFFSET family (same unit, same sign); it is only the oppositely-signed
LEAD that must never be added to either. An override rule was rejected: it
would silently discard whichever he authored second. Both default 0, so
this is provably inert against everything on disk. The care here: `tick()` already had
a lead-time system (`_lead_ms`, the three-anchor alignment above) whose
sign is the OPPOSITE of his — there, a POSITIVE lead means fire EARLIER
(`fire_at = target - lead`); his offset is NEGATIVE for earlier. The two
never combine by adding/subtracting the same sign — that would silently
invert one of them. They compose by each acting in its own native
direction against a shared, relocated base: `target_ms = trig.timestamp_ms
+ trig.trigger_offset_ms` (his convention, applied first), then
`fire_at = target_ms - lead_ms` (the existing lead system, unchanged) —
net `fire_at = trig.timestamp_ms + trig.trigger_offset_ms - lead_ms`,
which is byte-identical to the pre-existing formula whenever offset=0
(every one of his real fire_scene triggers, as of this field's
introduction — no stored data was touched). `tick()`'s own inline comment
has the full reasoning, including why the crossing-check's safety-net OR
clause must compare against `target_ms`, not the raw `trig.timestamp_ms`
— using the raw timestamp there would silently discard a positive
("later") offset by firing at the old mark anyway. Proof is offline only
(both sign extremes plus the composed case): `scripts/check_triggers.py`
§10, `tests/test_trigger_engine.py`. No live fixture proof exists for
this — his room is released (panic release taken back), so nothing can be
proven against real hardware right now.

**The preview's own live-fire loop honours the SAME automatic lead a real
trigger fire would apply (2026-08-21, PR fm/preview-must-hold-scene-
changes), and separately, opening a preview now genuinely holds SCENE
CHANGES too, not just flares/responses — a real live regression, not a
design gap.** His report, verbatim: "I was using spectra, playing music,
and tried to preview. now it won't even hold... The music show is playing
regardless of the fact that I have the preview window open and it says
'deferred by preview.'" Root cause: `bridge.py`'s `conductor_deferral`/
`sequencer_deferral` (the "deferred by preview" string he saw) already
checked `preview_pause.active()` — true, correctly gating the sequencer's
own rolls and drift — but `scene_sequencer.fire_scene_by_id`, the ONE
choke point every scene change funnels through INCLUDING his authored
`fire_scene` triggers (`trigger_engine._fire`/`_fire_transition`), never
consulted it at all; `preview_pause.py`'s own docstring had named that
function as gated since it was written — the documentation described a
gate that was never built. Fixed by gating `fire_scene_by_id` on
`preview_pause.active()` FIRST, ahead of even Force Scene — the one gate
in that function Force Scene does NOT override, matching `bridge.py`'s own
precedence (preview already outranked force_scene there too) — because a
hand-held preview is the most explicit, momentary override a room can be
under. Recorded to `fire_history`'s `"deferred"` bucket like the dwell
gate (never silent) but, unlike dwell, does NOT fire an update effect on a
skip: dwell's placeholder flare exists to make an otherwise-invisible hold
visible; a preview's whole point is an isolated, motionless room, so an
update effect would put motion into the exact thing he opened the preview
to judge. Self-heals on abandonment with no code beyond the existing
deadline: `preview_pause.active()` is a plain `time.monotonic()`
comparison, not a flag anyone must remember to clear, so a browser
close/dropped connection/wedged tab (heartbeats simply stop arriving)
resumes his show on its own within `HEARTBEAT_TIMEOUT_S` — proven directly
in `tests/test_preview_scene_hold.py` by letting a started pause's
deadline lapse and firing again WITHOUT ever calling `preview_pause.clear()`,
not just by testing the clean-close path.

Separately (same PR, his ask: "the preview must use the app's own
delay/offset setting when it fires... the same lead the real show applies
must apply here, or the preview lies about when his flare lands"): before
this, the live fire was scheduled at `animation_anchor_s` unconditionally
— an authored/manual ruler position with no reference to the AUTOMATIC
lead `trigger_engine._response_switch_lead_ms` computes for a real
trigger fire (`DICE_REROLL_GLIDE_MS` for a registry-smooth momentary
glide, or the intensity-scaled `color_rotate_ramp_ms` for a colour-rotate
kind). `scene_response.kind_lead_ms` is the per-KIND extraction of that
same computation (`_kind_would_glide` factored out of
`momentary_switch_would_glide`'s own band loop so the two can never
silently diverge) — reused, not reapproximated, since `ResponseEngine.
fire_kind` previews ONE kind in isolation, bypassing band selection
entirely, so there's no band for the band-scoped functions to loop over.
`spectra/services/flare_preview.fire_at_s(anchor_s, lead_ms)` composes it
with his own `trigger_offset_ms` EXACTLY the way #172 above composes
`SpectraTrigger.trigger_offset_ms` with `_lead_ms` — proven algebraically
in `build_timeline`'s own docstring and in `scripts/check_flare_preview.py`
§1c: since `trigger_mark_s = animation_anchor_s - offset_ms/1000` already
means `trigger_mark_s + offset_ms/1000 == animation_anchor_s` for ANY
offset, his authored offset is already baked into `animation_anchor_s` by
construction — so `target ≡ animation_anchor_s` and `fire_at_s = target -
lead_ms/1000` is the whole composition, with nothing left to add.
`trigger_mark_s`'s own formula/meaning is UNCHANGED — the drawn mark still
reflects only his authored offset; only WHEN THE WRITE ACTUALLY HAPPENS
moves, earlier by however long this kind's own switch/ramp needs. Frontend
(`FlarePreviewOverlay.tsx`) schedules its `/fire` loop against the new
`fire_at_s` field instead of `animation_anchor_s`, and the accent
"start"/"end" ruler markers move with it too (they represent when the
write lands, which is now `fire_at_s`, not the old fixed anchor).

His other two asks in the same brief were AUDITED, not rebuilt — both were
already correct as of PR #170/#172, verified rather than assumed: (1)
"fires every time the playhead crosses the trigger line, every lap" — the
RAF loop's own catch-up-avoiding `while (nextFireAt <= now) nextFireAt +=
durationS * 1000` shape was already sound; (2) "dragging the trigger mark
changes the flare's offset" — `dragTrigger`'s pointerup already called
`onTriggerOffsetChange` → `setKindTriggerOffset`, a real scene-draft edit.
Both audited with `scripts/check_flare_preview_frontend_loop.mjs` — a
plain Node script (no framework; this repo has no JS test tooling) that
extracts the exact scheduling/offset formulas VERBATIM from
`FlarePreviewOverlay.tsx`/`flareKindOps.ts` and drives them with a fake
clock: zero network, zero browser, so it can prove multi-lap firing
cadence and the lead-vs-no-lead schedule delta without ever risking a
real `/fire` HTTP call. **This offline-only proof was a deliberate
choice, not a shortcut**: a live isolated `python -m spectra` instance on
a spare port was tried first and aborted immediately after its bridge
connected to a real `ws://127.0.0.1:8000/ws` (a live, in-use service,
consistent with his room being in active use at the time) — `SPECTRA_
STORAGE_DIR` repoints scene/room storage but NOT `fx/light_ownership.py`'s
`OWNERSHIP_FILE` (a fixed, worktree-relative path) or the bridge's WS
target (`SPECTRA_BRIDGE_WS_URL`, not set by default), so an isolated
instance's flare-preview live-fire path is not automatically network-safe
by construction. If a future task needs a truly live-isolated proof, set
BOTH env vars explicitly and confirm nothing is reachable at the
`fx_seam` HTTP fallback target (`config.ledfx_url()`, `LEDFX_HOST`/
`LEDFX_PORT`) before opening any preview against it — don't assume
`SPECTRA_STORAGE_DIR` alone isolates the write path.

**MAXIMUM HOLD CEILING (2026-08-21, PR fm/preview-hold-needs-a-ceiling) —
his room was held 13m54s in one continuous window by a client that never
stopped heartbeating (a headless browser left running by mistake),
refusing 85 scene changes.** `HEARTBEAT_TIMEOUT_S`/`SWEEP_INTERVAL_S`
above only bound ABANDONMENT (how long a hold survives once heartbeats
STOP) — they say nothing about a client that keeps heartbeating forever,
which is exactly what happened: a bound a live client can push out
forever is not a bound. `flare_preview_hold.MAX_HOLD_DURATION_S` (180s,
3 minutes — long enough for a real unhurried look, several loops, an
intensity nudge; short enough that a forgotten tab is a brief nuisance,
not a lost show) is an ABSOLUTE ceiling on one continuous hold, counted
from the session's first real fire (`_session_started_at`) and enforced
by capping every `_rearm()` call against it — no number of heartbeats
moves it. Reaching it locks the session (`_locked_until_reopen`) so a
client that keeps calling `/fire`/`/heartbeat` afterward (the reported
failure mode — no further `/open` ever arrives) cannot silently
re-establish a new hold; only a genuine fresh `POST /open` (a real mount,
or him moving the intensity slider — never a bare heartbeat) calls
`clear_ceiling_lock()` and lets a new session begin. `preview_pause` —
armed independently by `spectra/api/flare_preview.py`, the thing that
actually refuses his scene changes — is capped to the SAME ceiling via
`flare_preview_hold.capped_pause_s()`, so it can never outlive the light
hold's own deadline; without this the scene gate could stay refused for
up to another `HEARTBEAT_TIMEOUT_S` after the lights already reverted.
The frontend (`FlarePreviewOverlay.tsx`) surfaces the ceiling firing as a
visible banner and stops its own loop, rather than silently continuing to
poll a room that already let go. Proof that the ceiling actually holds
while a client keeps heartbeating THE WHOLE TIME (never letting the
heartbeat lapse — a test where heartbeats stop only proves the
pre-existing abandonment bound, not this one):
`tests/test_flare_preview_hold.py` (real headless fixture) +
`tests/test_flare_preview_api.py` (the `preview_pause` capping, route
wiring).

**THE OTHER TWO PREVIEWS (2026-08-27, fm/flare-preview-offsets-everywhere;
`docs/SPECTRA_SPEC.md` §95).** Both live on the Scenes page's Phase
Choreography tab — the tab that already describes in words exactly what
they show — and both run on the ONE hold above, never a second one.

- **ONE HOLD, MANY PROGRAMS.** `flare_preview_hold.PreviewProgram` is the
  seam: a program supplies its held scene, any EXTRA virtuals it may touch
  (a transition's incoming scene can reach virtuals the outgoing one never
  does — leave them out of the snapshot and `close()` hands some back and
  silently keeps the rest), and what each named STEP does.
  `open_program_hold(program, intensity, step=...)` is the general entry;
  `open_hold(scene, kind, ...)` is now the thinnest program
  (`FlareKindProgram`) over it and is unchanged in behaviour. Everything
  hard — snapshot, deadline, sweep, 3-minute ceiling, restart recovery,
  both release queues, the 1ms tween-safe revert — stays in one place. A
  new preview supplies a program; **it never supplies a second hold.**
  `heartbeat`/`close` moved to `spectra/api/preview.py` (`/api/preview`)
  with the flare paths as thin aliases: the hold is shared, so its
  keep-alive is too.
- **TRANSITIONS** — `spectra/services/transition_preview.py`,
  `POST /api/preview/transition/{open,fire}`, `TransitionPreviewOverlay.tsx`.
  A scene transition anchors its MIDDLE (the settled family). The
  crossfade, the anchor fraction and the lead all come from
  `spectra/services/scene_transition_lead.py` — a NEW module that
  `trigger_engine._scene_transition_lead_ms_for` now CALLS, so the preview
  asks production's own function instead of re-deriving it. **The drag
  writes `SceneV2.trigger_offset_ms`** (new field, same family/clamp/sign
  as `FlareKind.trigger_offset_ms`), read on the firing path by
  `tick()`'s `_scene_offset_ms`. Its one honest bound, recorded rather
  than discovered: for an UNRESOLVED `fire_scene` pick (100% of his real
  triggers) the scene isn't known until the LOOKAHEAD pin commits
  `LOOKAHEAD_HORIZON_MS` (5s) ahead, so an offset inside that window lands
  and a larger negative one degrades to the un-relocated mark — late,
  never wrong. Forcing the pin earlier from the wider offset gate was
  considered and rejected: it would widen the window a pin's validity can
  drift, the exact risk `_pin_still_valid` exists to contain.
- **THE DROP SEQUENCE** — `spectra/services/phase_preview.py`,
  `POST /api/preview/sequence/{open,fire}`, `SequencePreviewOverlay.tsx`.
  Every ramp is `scene_response._phase_ramp_ms` (the show's own function),
  so the dynamic stretch to ~90% of the real gap is what the ruler draws,
  with the remaining ~10% as a separate HANG band — his spec verbatim, and
  the reason two gap sliders exist: the hang is a thing to SEE, not a
  number to set. Drop is never stretched and BEGINS on its mark. **The
  charge and lull marks are deliberately not draggable** — a band's offset
  is an aggregate over its attached kinds (`band_trigger_offset_ms`, min
  over every declared offset, zero included since the 2026-09-16 fix
  above), so a drag would have to pick one; the per-kind flare preview
  already authors it and the panel says so. **The DROP mark IS draggable,
  since 2026-10-12 — see the drop-timing-offset entry above** (it sets
  `SceneV2.drop_timing_offset_ms`, not a flare kind's offset, so there is
  no aggregate to pick between). `release_phases()` gained `force=` for the
  per-lap release (each step runs on a FRESH scratch pair, and a drop arms
  nothing by production's own rule — exactly when a sequence ends); every
  production call site keeps the guard.
- **Server computes every anchor and fire moment**; the frontend schedules
  against `cues[].at_s` and draws against returned markers.
  `PreviewRuler.tsx`/`usePreviewLoop.ts` are shared so all three previews
  draw one instrument. Offline proof of the multi-cue scheduling (formulas
  extracted VERBATIM, fake clock, no network):
  `scripts/check_preview_cue_loop.mjs`.

**PROVE EVERY HOLD FROM THE SHOW SIDE, not the preview side.** The
founding defect of this whole system was a hold that REPORTED itself as
set — the UI even said "deferred by preview" — while his triggers kept
firing underneath, because `fire_scene_by_id` never consulted
`preview_pause`; every test that existed asked the preview side and passed
throughout. `tests/test_preview_holds_the_show.py` is the standing bar for
any hold, new ones included: drive the REAL trigger engine over a real
position feed with a four-action-kind corpus while the hold is open and
measure THE ENGINE'S output — zero writes at `fx_seam` (the one seam a
light byte leaves SPECTRA through), zero response surges, and the
deferrals present and NAMED in `fire_history` (a held room and a broken
room must not look the same in the log) — then replay the same sweep after
release to prove the corpus was live. It includes a test that re-creates
the ungated pre-fix world and proves the harness goes RED on it: a proof
bar that cannot fail on the defect it was written for is decoration.

**§84's missing instrument is BUILT, offline** —
`scripts/check_scene_entry_ramp_landing.py` +
`tests/test_scene_entry_ramp_landing.py`. It runs the whole production
chain and then WATCHES the ramp with the mechanism the light itself is
driven by (`Effect._advance_tweens`, one step per rendered frame through
`fx.headless`'s real pipeline), with song position and wall clock 1:1.
Measured: the crossfade's midpoint lands +16.7 ms (one frame) of a 4000 ms
mark, for a named scene AND for the LOOKAHEAD-pinned shape all his real
triggers have; with the lead disabled it misses by +616.7 ms, exactly half
the crossfade. Not a room proof and not claimed as one. **Note for anyone
writing a similar instrument: `dwell` is process-global by design, so each
observation must reset it the way a song change would — otherwise the
second fire in one process is legitimately deferred by the first one's
dwell floor and renders nothing at all.**

