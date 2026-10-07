"""scripts/seed_spectra_fx_live.py — the go-day seeder normalizes
`global_brightness` to 1.0 instead of copying the source LedFX config
verbatim (pixel-brightness-chain report, §5/§9), so a future re-seed can
never reintroduce the stale 0.96 that dimmed every fixture 4% with no UI
anywhere in SPECTRA to fix it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _seeder():
    path = (Path(__file__).resolve().parent.parent / "scripts"
           / "seed_spectra_fx_live.py")
    spec = importlib.util.spec_from_file_location("seed_spectra_fx_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_config(global_brightness):
    return {
        "configuration_version": "2.0.0",
        "global_brightness": global_brightness,
        "devices": [],
        "virtuals": [],
    }


def test_apply_writes_1_0_even_when_source_holds_a_stale_value(tmp_path, monkeypatch):
    source = tmp_path / "ledfx_config.json"
    source.write_text(json.dumps(_source_config(0.96)))
    dest_dir = tmp_path / "fx-live"

    from spectra import config as scfg
    monkeypatch.setattr(scfg, "FX_LIVE_CONFIG_DIR", dest_dir)

    module = _seeder()
    monkeypatch.setattr(sys, "argv",
                        ["seed_spectra_fx_live.py", "--source", str(source),
                         "--apply"])
    module.main()

    written = json.loads((dest_dir / "config.json").read_text())
    assert written["global_brightness"] == 1.0


def test_apply_leaves_1_0_unchanged(tmp_path, monkeypatch):
    source = tmp_path / "ledfx_config.json"
    source.write_text(json.dumps(_source_config(1.0)))
    dest_dir = tmp_path / "fx-live"

    from spectra import config as scfg
    monkeypatch.setattr(scfg, "FX_LIVE_CONFIG_DIR", dest_dir)

    module = _seeder()
    monkeypatch.setattr(sys, "argv",
                        ["seed_spectra_fx_live.py", "--source", str(source),
                         "--apply"])
    module.main()

    written = json.loads((dest_dir / "config.json").read_text())
    assert written["global_brightness"] == 1.0
