#!/usr/bin/env python3
"""Structural gate: a change that touches an effect or scene must also touch
that effect/scene's own skill file (`.claude/skills/<name>/SKILL.md`).

Card a-skill-per-effect-scene-kept-current-by-jgt7, his ask verbatim: "have
dj make sure we have a skill for each effect/scene and a rule to update the
skills as we work on each effect/scene and add more". The rule half of that
ask is stated as prose in AGENTS.md (the helpContent.ts precedent — "a topic
isn't done when it's written"); THIS script is the structural half, because
a rule that only says "remember to update the skill" lapses exactly when
things are busy, and that isn't a guess — his own board-check habit was
written down and still failed twice within the hour. Fail loud here, not a
reminder that can be skipped.

WHAT IT CHECKS, precisely:
  1. A changed file under `fx/effects/*.py` (or an instrument/measurement
     check or test the manifest names as belonging to that effect) requires
     the matching effect skill's SKILL.md to be among the changed files too.
  2. A changed file the manifest names as belonging to a SCENE requires
     that scene's skill's SKILL.md to be among the changed files too.
     (Scenes have no git-tracked per-scene file of their own — their live
     data lives in the gitignored `storage/spectra/scenes.json`, see
     AGENTS.md's "A worktree's own storage/spectra/*.json is gitignored"
     note — so scene triggers are a hand-curated list of the scripts/tests
     that author or assert that scene's own data: its seed script, a
     flare-kind migration naming it, a test of its stored config. This is a
     named, accepted limitation, not a silent gap: see the manifest's own
     `note` fields and AGENTS.md.)
     THE MAPPING RULE: an effect's code and its instruments require ONLY
     that effect's skill; a scene's authored data/configuration requires
     ONLY that scene's skill. No file is listed under both.
  3. A NEW registered effect module (a `fx/effects/*.py` file whose class
     body declares `NAME = "..."`, annotated or not) that appears in neither
     `effects.*.files` nor `acknowledged_effect_gaps.files` in the
     manifest is flagged outright — "new effect with no skill and no
     acknowledged gap". This is what makes "new effects get one as they
     are created" enforceable rather than aspirational: a brand-new effect
     cannot land silently unclassified.

WHAT IT DELIBERATELY DOES NOT DO: it cannot detect a scene-only edit made
purely through the live app (a flare-kind tweak saved via the Scenes page)
— nothing under `storage/spectra/` is git-tracked. Scene skills stay
current only for changes that pass through this repo's own scripts/tests;
a live-only scene edit is the acknowledged gap the AGENTS.md rule covers
by asking the AGENT to update the scene skill by hand when it does that
kind of work, same as the `helpContent.ts` rule already relies on human
diligence for anything not machine-checkable.

USAGE:
  .venv/bin/python scripts/check_effect_scene_skills_current.py
      # real usage: diffs the working branch against its merge-base with
      # origin/master (or --base), unions in the working tree's own
      # uncommitted/staged/untracked changes, and evaluates them.

  .venv/bin/python scripts/check_effect_scene_skills_current.py --files a b c
      # synthetic file list, skips git entirely — this is also how you
      # check a specific PR's file list.

WHERE IT IS ENFORCED: tests/test_effect_scene_skills_current.py runs this
same real-diff evaluation on every pytest run
(`test_the_real_branch_diff_leaves_no_effect_or_scene_skill_stale`), so the
gate fires wherever the suite does, not only when someone remembers to run
this script.

A DIFF THAT CANNOT BE COMPUTED IS A FAILURE, NEVER A CLEAN PASS: no
resolvable base ref, or any git command failing, raises GitDiffUnavailable
and exits 1 — an empty changed-file set would otherwise print "OK" having
checked nothing.

Exit 0 = clean (or nothing effect/scene-shaped changed). Exit 1 = named
violations (printed with the exact skill path to touch), or a diff that
could not be computed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / ".claude" / "skills" / "EFFECT_SCENE_MAP.json"
EFFECTS_DIR = "fx/effects/"
NAME_ATTR_RE = re.compile(r'^\s*NAME\s*(?::[^=]*)?=\s*["\']')
BASE_REF_CANDIDATES = ("origin/master", "origin/main", "master", "main")


class GitDiffUnavailable(RuntimeError):
    """The changed-file set could not be computed — never read as "nothing
    changed"."""


@dataclass
class Violation:
    kind: str  # "effect" | "scene" | "new_effect"
    entity: str  # the effect/scene skill name, or the new effect's file
    changed_trigger_files: list[str]
    skill_path: str | None

    def render(self) -> str:
        if self.kind == "new_effect":
            return (
                f"NEW EFFECT MODULE WITH NO SKILL AND NO ACKNOWLEDGED GAP: "
                f"{self.entity!r} declares a registered effect (NAME = ...) "
                f"but is not listed under 'effects' or 'acknowledged_effect_gaps' "
                f"in {MANIFEST_PATH.relative_to(REPO_ROOT)}.\n"
                f"  -> Either write a skill for it under .claude/skills/<name>/SKILL.md "
                f"and add it to the manifest's 'effects' map, or explicitly add it to "
                f"'acknowledged_effect_gaps' with a reason."
            )
        label = "effect" if self.kind == "effect" else "scene"
        files = ", ".join(self.changed_trigger_files)
        return (
            f"{label.upper()} CHANGED WITHOUT ITS SKILL: {self.entity!r} "
            f"({files}) changed, but {self.skill_path} did not.\n"
            f"  -> Update {self.skill_path} in the same change."
        )


@dataclass
class Report:
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def render(self) -> str:
        if self.ok:
            return "OK: no effect/scene skill is stale relative to the changed files."
        lines = [f"{len(self.violations)} effect/scene skill violation(s):", ""]
        for v in self.violations:
            lines.append(v.render())
            lines.append("")
        return "\n".join(lines).rstrip()


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text())


def _norm(paths: list[str]) -> set[str]:
    return {p.strip().replace("\\", "/") for p in paths if p.strip()}


_GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


def _git(repo_root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError as exc:
        raise GitDiffUnavailable(f"git is not available: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or f"exit status {exc.returncode}"
        raise GitDiffUnavailable(f"`git {' '.join(args)}` failed: {detail}") from exc


def _ref_exists(repo_root: Path, ref: str) -> bool:
    try:
        _git(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except GitDiffUnavailable:
        return False
    return True


def git_changed_files(
    base: str | None,
    repo_root: Path = REPO_ROOT,
    require_committed_diff: bool = True,
) -> set[str]:
    """Union of: committed diff against the branch's merge-base with a base
    ref, plus the working tree's own staged/unstaged/untracked changes.

    Raises GitDiffUnavailable when any git command fails. With
    `require_committed_diff` (the default) an unresolvable base ref raises
    too; without it, the committed half is skipped when no base resolves and
    only the working tree is evaluated."""
    changed: set[str] = set()

    base_ref = base
    if base_ref is None:
        base_ref = next(
            (c for c in BASE_REF_CANDIDATES if _ref_exists(repo_root, c)), None
        )
        if base_ref is None and require_committed_diff:
            raise GitDiffUnavailable(
                "no base ref resolves (tried "
                + ", ".join(BASE_REF_CANDIDATES)
                + ") — the branch's committed changes cannot be computed; "
                "pass --base <ref>"
            )
    elif not _ref_exists(repo_root, base_ref):
        raise GitDiffUnavailable(f"base ref {base_ref!r} does not resolve to a commit")

    if base_ref is not None:
        merge_base = _git(repo_root, "merge-base", "HEAD", base_ref).strip()
        if not merge_base:
            raise GitDiffUnavailable(f"no merge-base between HEAD and {base_ref!r}")
        changed |= _norm(
            _git(repo_root, "diff", "--name-only", "--no-renames", merge_base, "HEAD").splitlines()
        )

    status = _git(repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = status.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        changed.add(path)
        if ("R" in xy or "C" in xy) and i < len(entries):
            changed.add(entries[i])
            i += 1

    return {p for p in _norm(list(changed)) if p}


def declares_registered_effect(text: str) -> bool:
    return any(NAME_ATTR_RE.match(line) for line in text.splitlines())


def find_registered_effect_files(repo_root: Path = REPO_ROOT) -> set[str]:
    out = set()
    effects_dir = repo_root / "fx" / "effects"
    if not effects_dir.is_dir():
        return out
    for p in effects_dir.glob("*.py"):
        if p.name == "__init__.py":
            continue  # package init, not a registered effect module
        try:
            text = p.read_text()
        except OSError:
            continue
        if declares_registered_effect(text):
            out.add(f"fx/effects/{p.name}")
    return out


def evaluate(
    manifest: dict,
    changed_files: set[str],
    registered_effect_files: set[str] | None = None,
) -> Report:
    report = Report()
    changed = _norm(changed_files)

    all_mapped_effect_files: set[str] = set()
    all_mapped_effect_files |= set(manifest.get("acknowledged_effect_gaps", {}).get("files", []))

    for name, entry in manifest.get("effects", {}).items():
        entry_files = _norm(entry.get("files", []))
        all_mapped_effect_files |= entry_files
        skill_path = entry["skill"]
        trigger_hits = sorted(changed & entry_files)
        if trigger_hits and skill_path not in changed:
            report.violations.append(
                Violation("effect", name, trigger_hits, skill_path)
            )

    for name, entry in manifest.get("scenes", {}).items():
        entry_files = _norm(entry.get("files", []))
        skill_path = entry["skill"]
        trigger_hits = sorted(changed & entry_files)
        if trigger_hits and skill_path not in changed:
            report.violations.append(
                Violation("scene", name, trigger_hits, skill_path)
            )

    # New/unmapped registered effect modules.
    if registered_effect_files is None:
        registered_effect_files = set()
    for f in sorted(changed & registered_effect_files):
        if f not in all_mapped_effect_files:
            report.violations.append(Violation("new_effect", f, [f], None))

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Explicit changed-file list (skips git entirely).",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Base ref to diff against (default: auto-detect origin/master etc.)",
    )
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="Path to the effect/scene skill manifest JSON.",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))

    if args.files is not None:
        changed = set(args.files)
    else:
        try:
            changed = git_changed_files(args.base, require_committed_diff=True)
        except GitDiffUnavailable as exc:
            print(f"FAILED: could not compute the changed files to check: {exc}")
            return 1
    registered = find_registered_effect_files() & changed

    report = evaluate(manifest, changed, registered)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
