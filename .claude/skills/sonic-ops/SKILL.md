---
name: sonic-ops
description: >
  The checklist for adding, changing or removing a Sonic operation
  (spectra/services/sonic_ops.py's SonicOperation, merged by
  settings_agent.ALL_OPERATIONS from each domain's own OPERATIONS dict).
  Load BEFORE writing a new SonicOperation, before wiring a new domain
  module into settings_agent.py, or when a feature PR adds a user-facing
  setting/action and needs to decide whether Sonic owes it a follow-up.
  This is the "steps spread across six paragraphs of AGENTS.md" this
  skill exists to collect into one place.
---

# Adding (or auditing) a Sonic operation

`spectra/services/sonic_ops.py`'s own docstring is the mechanism's
binding statement: ONE `SonicOperation` declaration is simultaneously the
allowlist, the tool schema, and the discovery catalogue — there is no
second place for a capability's guard and its documentation to drift
apart. `settings_agent.ALL_OPERATIONS` merges every domain module's
`OPERATIONS` dict; a name not in it cannot be discovered OR dispatched.

## The rule this skill exists to enforce (AGENTS.md)

> Any change that adds or changes a user-facing setting or action owes a
> Sonic follow-up — an operation, or a named entry on an exclusion list
> with the reason — plus the skill update. It is a follow-up task filed
> when the feature ships, not a gate on the feature's own PR or deploy.

So: shipping a feature never has to wait on this. But before it's
considered DONE, walk this checklist.

## The checklist

1. **Pick (or confirm) the domain.** `sonic_ops.OperationDomain` is the
   closed `Literal` of legal domains — a NEW domain needs a new module
   (`<name>_console.py`) wired into `settings_agent._DOMAIN_OP_DICTS` and
   `ALL_OPERATIONS`. `_DOMAIN_NAMES` is DERIVED from that tuple — never
   hand-type a domain list anywhere else (this is what went stale for
   `"drops"` for its whole life, found in the 2026-10-06 audit).
2. **Write the handler**, following the two-step shape every domain
   already uses: a pure `_validate_*`/pure read function that never
   writes, called by an `apply_*`/`_op_*` wrapper that writes + logs only
   after validation succeeds. Catch your OWN domain's error type inside
   the `_op_*` wrapper and return `{"status": "rejected", "reason": ...}`
   — `settings_agent._dispatch()` stays domain-agnostic; it never imports
   a domain's exception class.
3. **Declare the `SonicOperation`**: `name`, `domain`, `kind`
   ("read"/"write"), a one-line `summary` (the tool description the
   model sees), `instructions` (the how-to — units, conventions, "call
   list_X first" — lives HERE, not in `settings_agent.SYSTEM_PROMPT`,
   which must never grow a paragraph per capability), `input_schema`
   (plain JSON Schema), `handler`.
4. **Add it to the domain module's `OPERATIONS` dict.** That's the whole
   wiring into the API backend — `ALL_OPERATIONS`/`TOOLS` are derived.
5. **Add the MCP wrapper** in `settings_mcp_server.py` — ONE
   hand-written `@mcp.tool()` function per operation (the `mcp` package's
   `add_tool()` introspects a real Python signature; there is no
   programmatic "register from a dict" path). Mirror an existing
   wrapper's shape exactly: same arg names, same defaults, call
   `await _call("op_name", **kwargs)`. `test_settings_mcp_server_starts_
   from_a_clean_cwd` (tests/test_settings_agent_cli.py) asserts this
   file's tool NAMES equal `set(settings_agent.ALL_OPERATIONS)` exactly
   — forgetting a wrapper fails it immediately, offline, no live model
   needed.
6. **Name a new enum type** in `settings_mcp_server.py` if your op takes
   a choice-constrained field — build it from the SAME source the API
   schema reads (`Literal[tuple(sorted(your_module.YOUR_CHOICES))]`),
   never re-typed.
7. **If the op is a genuinely new WIDENING** (a new domain, or a
   meaningfully new write shape), add one synthetic CLI transcript
   fixture (`tests/fixtures/cli_transcript_synthetic_<name>_applied.json`)
   on the CURRENT full tool manifest, plus a test proving it parses from
   its structured `tool_result` (never the model's reply prose) — see
   `cli_transcript_synthetic_device_applied.json` /
   `cli_transcript_synthetic_scene_entry_param_applied.json` for the
   shape to copy. **Every widening makes EVERY existing fixture's `tools`
   list stale** (the manifest check compares the exact set) — update
   those fixtures' `tools` field to the new full set, don't leave them
   silently broken (tests that assert specific OLD fixtures are now
   correctly refused as stale are a DIFFERENT, deliberate class — read
   `test_old_real_captures_are_now_correctly_refused_as_a_stale_
   manifest`/`test_first_widenings_synthetic_scene_fixtures_are_now_ALSO_
   correctly_refused` before touching either kind).
8. **Tests**: a round trip (read shows what write wrote), validation
   (out-of-range/wrong-type/unknown-key all refused, nothing persisted),
   undo where the domain has one, the op's presence/shape in
   `ALL_OPERATIONS`, and discoverability via `list_operations`. Never
   touch live storage — isolate every `*_FILE` the op reads/writes, the
   same discipline every existing console test follows.
9. **Help + skill.** Update (or write) the relevant `helpContent.ts`
   entries — including this operation's own skill file's "Sonic reach"
   section — in the SAME change. `HelpLink`'d from somewhere real, or it's
   an orphan by the help-page rule.
10. **If you're deliberately NOT adding an operation** for a new
    setting/action (a safety fence, an opaque id, a visual act), name it
    — in the owning module's docstring ("What should stay off-limits") —
    rather than leaving the gap implicit. That's what lets a future audit
    tell "considered and excluded" from "forgotten."

## Fuzzy name matching

If your op resolves something by NAME rather than requiring an id
(`force_scene`/`force_color`'s own 2026-10-06 build; show/house console's
pre-existing `difflib.get_close_matches` convention), prefer
`spectra/services/name_resolve.resolve_name()` — it adds the
dropped-qualifier tier ("Orbits" → "Orbits V2") on top of the existing
exact/close-match discipline, and refuses a near-tie rather than guessing
between two plausible candidates. Don't invent a third name-matching
convention.

## Proofs for THIS mechanism (not any one operation)

`tests/test_scene_console.py::
test_dispatch_recognizes_exactly_the_declared_operation_set` (the
exhaustive merged-boundary proof — built from every domain's own
`OPERATIONS` dict, so it never has to be hand-updated for a new op),
`tests/test_settings_agent_cli.py` (the CLI/MCP backend's own manifest
discipline).
