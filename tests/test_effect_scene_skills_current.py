"""Proof for scripts/check_effect_scene_skills_current.py — the structural
gate behind card a-skill-per-effect-scene-kept-current-by-jgt7's rule.

Every scenario here is checked RED first (on the real manifest, so a stale
manifest entry would itself break these) and then GREEN once the skill file
is included — the "must be able to fail on the defect it exists for, prove
it, red first" requirement. Pure-function tests over synthetic file lists;
no git repo state and no real branch history is needed, so these run fast
and hermetically under plain pytest.
"""
from __future__ import annotations

import json

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
