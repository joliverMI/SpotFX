"""Proof for scripts/check_effect_scene_skills_current.py — the structural
gate behind card a-skill-per-effect-scene-kept-current-by-jgt7's rule.

Every scenario here is checked RED first (on the real manifest, so a stale
manifest entry would itself break these) and then GREEN once the skill file
is included — the "must be able to fail on the defect it exists for, prove
it, red first" requirement. Most tests evaluate synthetic file lists; the
git-diff tests drive real `git` in throwaway repositories, and ONE test
(`test_the_real_branch_diff_leaves_no_effect_or_scene_skill_stale`) runs
the gate against this branch's own real diff — that is the enforcement, so
the stale-skill check fires on every pytest run rather than only when
someone remembers to run the script.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from scripts import check_effect_scene_skills_current as gate


def _manifest():
    return gate.load_manifest()


def test_manifest_loads_and_has_both_sections():
    m = _manifest()
    assert "effects" in m and "scenes" in m
    assert "acknowledged_effect_gaps" in m
    assert len(m["effects"]) >= 10
    assert len(m["scenes"]) == 10


def test_effect_change_without_skill_is_a_violation():
    m = _manifest()
    changed = {"fx/effects/blackhole.py"}
    report = gate.evaluate(m, changed)
    assert not report.ok
    assert any(v.kind == "effect" and v.entity == "blackhole-effect" for v in report.violations)


def test_effect_change_with_skill_is_clean():
    m = _manifest()
    changed = {
        "fx/effects/blackhole.py",
        ".claude/skills/blackhole-effect/SKILL.md",
    }
    report = gate.evaluate(m, changed)
    assert report.ok, report.render()


def test_scene_trigger_change_without_skill_is_a_violation():
    m = _manifest()
    changed = {"scripts/seed_fish_scene.py"}
    report = gate.evaluate(m, changed)
    assert not report.ok
    assert any(v.kind == "scene" and v.entity == "fish-scene" for v in report.violations)


def test_scene_trigger_change_with_skill_is_clean():
    m = _manifest()
    changed = {
        "scripts/seed_fish_scene.py",
        ".claude/skills/fish-scene/SKILL.md",
    }
    report = gate.evaluate(m, changed)
    assert report.ok, report.render()


def test_unrelated_file_change_is_clean():
    m = _manifest()
    changed = {"AGENTS.md", "spectra/services/engine.py"}
    report = gate.evaluate(m, changed)
    assert report.ok, report.render()


def test_new_registered_effect_with_no_skill_or_gap_entry_is_flagged():
    m = _manifest()
    changed = {"fx/effects/brand_new_effect.py"}
    report = gate.evaluate(m, changed, registered_effect_files=changed)
    assert not report.ok
    assert any(v.kind == "new_effect" for v in report.violations)


def test_new_registered_effect_named_in_acknowledged_gaps_is_not_flagged():
    m = json.loads(json.dumps(_manifest()))  # deep copy, don't mutate the real manifest
    m["acknowledged_effect_gaps"]["files"].append("fx/effects/brand_new_effect.py")
    changed = {"fx/effects/brand_new_effect.py"}
    report = gate.evaluate(m, changed, registered_effect_files=changed)
    assert report.ok, report.render()


def test_a_non_effect_helper_module_is_never_flagged_as_a_new_effect():
    # fx/effects/twod.py has no NAME = ... class attribute (a shared base,
    # not a registered effect) — declares_registered_effect must say so,
    # or every helper module edit would spuriously demand a new skill.
    text = (gate.REPO_ROOT / "fx" / "effects" / "twod.py").read_text()
    assert not gate.declares_registered_effect(text)


def test_a_registered_effect_module_is_detected_as_such():
    text = (gate.REPO_ROOT / "fx" / "effects" / "blackhole.py").read_text()
    assert gate.declares_registered_effect(text)


def test_every_effect_manifest_entry_names_a_real_existing_skill_file():
    m = _manifest()
    for name, entry in m["effects"].items():
        skill = gate.REPO_ROOT / entry["skill"]
        assert skill.is_file(), f"{name}: {entry['skill']} does not exist"


def test_every_scene_manifest_entry_names_a_real_existing_skill_file():
    m = _manifest()
    for name, entry in m["scenes"].items():
        skill = gate.REPO_ROOT / entry["skill"]
        assert skill.is_file(), f"{name}: {entry['skill']} does not exist"


def test_every_live_registered_effect_is_either_mapped_or_acknowledged():
    """The real repo, right now: every fx/effects/*.py that declares NAME =
    must appear in the manifest somewhere — this is what catches an effect
    that was added to the repo without ever being classified."""
    m = _manifest()
    mapped = set()
    for entry in m["effects"].values():
        mapped |= set(entry.get("files", []))
    mapped |= set(m["acknowledged_effect_gaps"]["files"])

    registered = gate.find_registered_effect_files()
    unclassified = {f for f in registered if f not in mapped}
    assert not unclassified, f"unclassified registered effects: {sorted(unclassified)}"


def test_cli_reports_nonzero_on_a_violation_and_zero_when_clean(capsys):
    rc = gate.main(["--files", "fx/effects/blackhole.py"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "blackhole-effect" in out

    rc = gate.main(
        [
            "--files",
            "fx/effects/blackhole.py",
            ".claude/skills/blackhole-effect/SKILL.md",
        ]
    )
    assert rc == 0


def test_the_real_branch_diff_leaves_no_effect_or_scene_skill_stale():
    try:
        changed = gate.git_changed_files(None, require_committed_diff=True)
    except gate.GitDiffUnavailable as exc:
        pytest.fail(
            "the effect/scene skill gate could not compute this branch's real "
            f"diff, so it checked nothing: {exc}"
        )
    report = gate.evaluate(
        _manifest(), changed, gate.find_registered_effect_files()
    )
    assert report.ok, report.render()


def test_an_annotated_name_attribute_still_declares_a_registered_effect():
    text = 'class Foo(Effect):\n    NAME: str = "Foo"\n'
    assert gate.declares_registered_effect(text)


def test_no_file_triggers_both_an_effect_skill_and_a_scene_skill():
    m = _manifest()
    effect_files = {f for e in m["effects"].values() for f in e["files"]}
    scene_files = {f for e in m["scenes"].values() for f in e["files"]}
    assert not effect_files & scene_files, sorted(effect_files & scene_files)


def test_every_manifest_trigger_file_exists():
    m = _manifest()
    listed = {f for e in m["effects"].values() for f in e["files"]}
    listed |= {f for e in m["scenes"].values() for f in e["files"]}
    listed |= set(m["acknowledged_effect_gaps"]["files"])
    missing = sorted(f for f in listed if not (gate.REPO_ROOT / f).is_file())
    assert not missing, missing


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if k not in gate._GIT_LOCATION_ENV}
    subprocess.run(
        [
            "git",
            "-c", "user.name=gate-test",
            "-c", "user.email=gate-test@example.invalid",
            "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


def _write(repo, rel, text="x\n"):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _repo_on_master(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", "master")
    _write(repo, "fx/effects/blackhole.py", 'NAME = "Blackhole"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    return repo


def test_committed_branch_changes_are_part_of_the_changed_set(tmp_path):
    repo = _repo_on_master(tmp_path)
    _write(repo, "fx/effects/blackhole.py", 'NAME = "Blackhole"\nX = 1\n')
    _git(repo, "commit", "-q", "-am", "touch the effect")
    changed = gate.git_changed_files(None, repo_root=repo)
    assert "fx/effects/blackhole.py" in changed


def test_a_brand_new_untracked_skill_directory_lists_its_skill_file(tmp_path):
    repo = _repo_on_master(tmp_path)
    _write(repo, ".claude/skills/new-effect/SKILL.md")
    changed = gate.git_changed_files(None, repo_root=repo)
    assert ".claude/skills/new-effect/SKILL.md" in changed
    assert ".claude/skills/new-effect/" not in changed


def test_a_staged_rename_counts_both_the_old_and_the_new_path(tmp_path):
    repo = _repo_on_master(tmp_path)
    _git(repo, "mv", "fx/effects/blackhole.py", "fx/effects/blackhole_v2.py")
    changed = gate.git_changed_files(None, repo_root=repo)
    assert {"fx/effects/blackhole.py", "fx/effects/blackhole_v2.py"} <= changed


def test_an_unresolvable_base_ref_raises_instead_of_reading_as_nothing_changed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", "work")
    _write(repo, "fx/effects/blackhole.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "only commit")
    with pytest.raises(gate.GitDiffUnavailable):
        gate.git_changed_files(None, repo_root=repo)
    with pytest.raises(gate.GitDiffUnavailable):
        gate.git_changed_files("no-such-ref", repo_root=repo)


def test_without_a_required_committed_diff_the_working_tree_is_still_checked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", "work")
    _write(repo, "fx/effects/blackhole.py")
    changed = gate.git_changed_files(
        None, repo_root=repo, require_committed_diff=False
    )
    assert "fx/effects/blackhole.py" in changed


def test_a_directory_that_is_not_a_git_repo_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(gate.GitDiffUnavailable):
        gate.git_changed_files(None, repo_root=tmp_path, require_committed_diff=False)


def test_cli_fails_when_the_diff_cannot_be_computed(capsys):
    rc = gate.main(["--base", "refs/heads/no-such-base-ref-for-the-skill-gate"])
    assert rc == 1
    assert "could not compute" in capsys.readouterr().out
