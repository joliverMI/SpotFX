"""A category's effect options must include every effect the ENGINE
supports for that category's device kind, not just the effects a hand-
maintained curated list happens to name — found 2026-09-22
(a-scene-cant-select-an-effect-its-own-category-doesn't-curate). The
Admiral asked to copy Fireworks V2's Strips entry (effect_type
`fireworks1d`) onto the Fish scene and reported "the fireworks effect
didn't show as an option when I wanted to change it": storage/
device_categories.json's Strips curated `effects` list never named
`fireworks1d` at all — it was added for `blackhole1d`/`orbits1d` but not
this sibling — and the Eye V2 scene's own stored Matrix entry
(effect_type `eye`) has the identical gap on Matrix's own curated list.

`fx.device_model.category_effect_options()` fixes the cause: it unions a
category's curated names with every registered effect
(config/effect_params.json) whose own device dimension
(`effect_dimension()`, via fx.effects.twod.Twod class inheritance)
matches the category's (`category_dimension()`, via the Matrix/non-Matrix
category-tree split) — so a registered effect can never again be
unreachable from a category-target scene entry just because nobody
remembered to curate it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model


@pytest.fixture(autouse=True)
def _isolated_categories(tmp_path, monkeypatch):
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.refresh()
    yield
    device_model.refresh()


def _write_categories(path: Path, cats: dict) -> None:
    path.write_text(json.dumps(cats), encoding="utf-8")
    device_model.refresh()


def test_effect_dimension_splits_on_twod_inheritance():
    # 2D: renders into a real rows x cols matrix (subclasses fx.effects.twod.Twod).
    assert device_model.effect_dimension("radial") == "2d"
    assert device_model.effect_dimension("eye") == "2d"
    assert device_model.effect_dimension("fish") == "2d"
    assert device_model.effect_dimension("fireworks") == "2d"
    # 1D: a plain pixel-strip effect.
    assert device_model.effect_dimension("power") == "1d"
    assert device_model.effect_dimension("melt") == "1d"
    assert device_model.effect_dimension("fireworks1d") == "1d"
    assert device_model.effect_dimension("blackhole1d") == "1d"
    assert device_model.effect_dimension("orbits1d") == "1d"
    # Unresolvable module/class.
    assert device_model.effect_dimension("not-a-real-effect") is None


def test_category_dimension_matrix_subtree_is_2d_everything_else_1d(tmp_path):
    _write_categories(device_model.CATEGORIES_FILE, {
        "c1": {"id": "c1", "name": "Matrix", "virtuals": ["v-m"], "effects": []},
        "c2": {"id": "c2", "name": "Particles", "parent_id": "c1", "virtuals": ["v-m"], "effects": []},
        "c3": {"id": "c3", "name": "Strips", "virtuals": ["v-s"], "effects": []},
    })
    assert device_model.category_dimension("Matrix") == "2d"
    assert device_model.category_dimension("Particles") == "2d"  # inherits from its Matrix parent
    assert device_model.category_dimension("Strips") == "1d"
    assert device_model.category_dimension("no-such-category") == "1d"


def test_fireworks1d_reaches_strips_even_when_the_curated_list_forgot_it(tmp_path):
    # This is storage/device_categories.json's real shape as of the report:
    # Strips curates blackhole1d/orbits1d but never fireworks1d.
    _write_categories(device_model.CATEGORIES_FILE, {
        "c1": {"id": "c1", "name": "Matrix", "virtuals": ["v-m"],
               "effects": ["radial", "noise", "blender", "pacman"]},
        "c2": {"id": "c2", "name": "Strips", "virtuals": ["v-s"],
               "effects": ["melt", "power", "blackhole1d", "orbits1d"]},
    })
    options = device_model.category_effect_options("Strips")
    assert "fireworks1d" in options, "a registered 1D effect must be reachable from Strips"
    # Curated names still lead, in their curated order — the fix is additive.
    assert options[:4] == ["melt", "power", "blackhole1d", "orbits1d"]
    # A 2D-only effect must never leak into a 1D category.
    assert "radial" not in options
    assert "eye" not in options


def test_eye_reaches_matrix_even_when_the_curated_list_forgot_it(tmp_path):
    _write_categories(device_model.CATEGORIES_FILE, {
        "c1": {"id": "c1", "name": "Matrix", "virtuals": ["v-m"],
               "effects": ["radial", "noise", "pacman"]},
        "c2": {"id": "c2", "name": "Strips", "virtuals": ["v-s"], "effects": ["melt", "power"]},
    })
    options = device_model.category_effect_options("Matrix")
    assert "eye" in options
    assert "fish" in options
    # A 1D-only effect must never leak into a 2D category.
    assert "melt" not in options
    assert "power" not in options


def test_a_category_with_no_stored_curation_still_offers_its_dimension(tmp_path):
    _write_categories(device_model.CATEGORIES_FILE, {
        "c1": {"id": "c1", "name": "Matrix", "virtuals": ["v-m"], "effects": []},
    })
    options = device_model.category_effect_options("Matrix")
    assert set(options) == {
        e for e in device_model.effect_types() if device_model.effect_dimension(e) == "2d"
    }


def test_unknown_category_returns_empty_curated_but_still_no_crash(tmp_path):
    _write_categories(device_model.CATEGORIES_FILE, {})
    assert device_model.category_effect_options("Whatever") == [
        e for e in device_model.effect_types() if device_model.effect_dimension(e) == "1d"
    ]
