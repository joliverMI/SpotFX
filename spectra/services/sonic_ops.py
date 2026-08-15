"""ONE declaration shape for every operation Sonic — the settings-console
chat agent, standing order 5 — can perform, across both domains it is
authorized in (settings, scene). Per the Admiral's own architecture ruling
(corr, 2026-08-15, "we need to build good infrastructure ... helping the
Sonic agent find possible things to change ... adding some level of
programmatic access"):

  "The enumerated operation set that ENFORCES the boundary and the
  catalogue that lets Sonic DISCOVER what to change must be THE SAME
  DECLARATION. One source of truth."

A SonicOperation is that one declaration. It serves three roles at once, by
construction, never by convention:
  1. THE ALLOWLIST — settings_agent.ALL_OPERATIONS (a dict keyed by name,
     built from domain modules' own OPERATIONS dicts) is what a dispatcher
     looks a tool-call name up in; a name not present there cannot run,
     full stop. A capability that isn't declared here is simultaneously
     UNDISCOVERABLE (catalogue_entry() never mentions it) and UNREACHABLE
     (no dispatch branch exists to reach it) — the same property
     settings_agent.py's original two-tool design had, generalized.
  2. THE TOOL SCHEMA — tool_schema() is exactly the shape the Anthropic API
     (and the MCP wire adapter) hand the model: name/description/
     input_schema. This is what the model is ALLOWED to call.
  3. THE DISCOVERY CATALOGUE — catalogue_entry() is what the "list
     operations" meta-tool hands back when Sonic (or a human reading the
     transcript) asks what exists and how to use it. Same object as #2, so
     a capability's guard and its documentation cannot silently disagree —
     the failure mode being designed out is a hand-maintained doc that
     describes the system as someone once believed it to be.

`instructions` is the per-operation how-to (units, conventions, "call
get_scene_settings first to see the legal range") — it lives HERE, with
the operation it describes, specifically so the system prompt does NOT
grow one paragraph per capability. Adding an operation means adding one
SonicOperation to a domain's OPERATIONS dict; nothing else needs editing
to keep guard/doc/prompt in sync, because there is no second place for
them to drift apart from.

`handler` does the actual work and is expected to catch its OWN domain's
validation-error type internally and return a `{"status": "rejected",
...}` payload rather than raise — see settings_console.py/scene_console.py
for that half. The dispatcher (settings_agent.py) stays domain-agnostic:
it looks up the name, calls the handler, and treats a bare exception as a
last-resort safety net, never the expected rejection path."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

OperationDomain = Literal["settings", "scene", "meta"]
OperationKind = Literal["read", "write"]


@dataclass(frozen=True)
class SonicOperation:
    name: str
    domain: OperationDomain
    kind: OperationKind
    summary: str                      # one line, his language — the tool description
    instructions: str                 # how to call it / conventions specific to THIS op
    input_schema: dict
    handler: Callable[..., Any]       # may be sync or async; may raise TypeError on bad args

    def tool_schema(self) -> dict:
        return {"name": self.name, "description": self.summary, "input_schema": self.input_schema}

    def catalogue_entry(self, detail: bool = False) -> dict:
        entry: dict = {
            "name": self.name, "domain": self.domain, "kind": self.kind,
            "summary": self.summary,
        }
        if detail:
            entry["instructions"] = self.instructions
            entry["input_schema"] = self.input_schema
        return entry
