"""Seed SPECTRA storage from spot-effects' SceneV2 world — the Mid Group
migration's S1 half (decision: v2-randomness-scope, "grow the model").

Reads READ-ONLY:  storage/scenes_v2.json, storage/sequencer.json
Writes (--apply): storage/spectra/scenes.json, storage/spectra/sequencer.json,
                  storage/spectra/room_color.json (default room journey)

Per scene: loads through the SPECTRA model (legacy flare_bands become the
flare response class), seeds color_set_jump=True on the flare class (the
legacy Color lane's jump, now wheel-aware through the selector), and — for
the seven Mid Group scenes — authors the value bindings the legacy scenes
carried, each with the V2 rebuild's STATIC VALUE AS ITS FALLBACK. Scene ids
are preserved, so ported sequencer entries stay valid. The S2 engine
increment animates what these declarations state.

Legacy sources of truth: data/spectra-midgroup-scenes/report.md (Part A
inventory) and the live "Choose Dance" composite (intensity lanes 0/0.4/0.7).
Two authored flattenings, on record:
  - Dancers' dance_type: the legacy chooser rolled a WEIGHTED RANDOM style
    within each intensity lane; a steps binding carries one value per lane,
    so each lane gets its weighted favourite (ballet / cowboy / kpop).
  - Black Hole's legacy "edges 1→8" bind has no identifiable blackhole param
    in the V2 rebuild (the aspect label maps to nothing there) — skipped.

Dry-run by default (prints the plan); --apply writes. Idempotent: re-running
--apply overwrites SPECTRA storage with the same result; it never touches
the spot-effects files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config
from spectra.models.scene import SceneV2
from spectra.services.color_journey import RoomColorState, save_room


def imap(out_min: float, out_max: float, fallback) -> dict:
    return {"bind": "signal", "signal": "trigger_intensity", "mode": "map",
            "in_min": 0.0, "in_max": 1.0, "out_min": out_min, "out_max": out_max,
            "fallback": fallback}


def isteps(steps: list[tuple[float, object]], fallback) -> dict:
    return {"bind": "signal", "signal": "trigger_intensity", "mode": "steps",
            "steps": [{"threshold": t, "value": v} for t, v in steps],
            "fallback": fallback}


def dice_steps(letter: str | None, steps: list[tuple[float, object]], fallback) -> dict:
    return {"bind": "signal", "signal": "random", "mode": "steps", "dice": letter,
            "steps": [{"threshold": t, "value": v} for t, v in steps],
            "fallback": fallback}


# scene name → effect_type → param → binding JSON. Fallbacks are the V2
# rebuild's static values (verified against live storage before authoring).
BINDINGS: dict[str, dict[str, dict[str, dict]]] = {
    "Black Hole V2": {
        "blackhole": {
            "swirl": imap(-6.0, 6.0, 0.0),
            "blob_size": imap(1.5, 2.0, 1.75),
            "spawn_rate": imap(0.5, 2.0, 1.0),
            "beat_burst": imap(0.0, 6.0, 2.0),
        },
    },
    "Orbits V2": {
        "orbits": {
            "particle_count": imap(1, 8, 3),
            "blob_size": imap(4.0, 1.0, 2.5),
            # Legacy random reverse flip per fire (frozen to off in the
            # rebuild) — restored as an uncorrelated 50/50 roll.
            "reverse": dice_steps(None, [(0.0, False), (0.5, True)], False),
        },
        "orbits1d": {
            "particle_count": imap(2, 6, 3),
            "blob_size": imap(3.0, 1.0, 2.0),
        },
    },
    "Mid Star V2": {
        "radial": {
            # The 1-of-3 radial shape pick, weights 2:2:1 via thresholds
            # 0.4/0.8 — star and edges share dice "a" so variants land as
            # authored pairs, never scrambled halves.
            "star": dice_steps("a", [(0.0, 0.3), (0.4, -0.3), (0.8, 0.0)], 0.3),
            "edges": dice_steps("a", [(0.0, 6), (0.4, 3), (0.8, 5)], 6),
            "spin": imap(0.1, 1.0, 0.55),
        },
    },
    "Fireworks V2": {
        "fireworks": {
            "burst_size": imap(5, 14, 8),
            "beat_burst": imap(1.0, 6.0, 4.0),
        },
    },
    "Squiggles V2": {
        "squiggles": {
            "beat_burst": imap(1.0, 5.0, 2.0),
        },
    },
    "Dancers V2": {
        "dancer": {
            "burst_size": imap(7, 16, 10),
            "base_speed": imap(0.6, 1.8, 1.0),
            "dance_intensity": imap(0.7, 1.7, 1.0),
            # Choose Dance lanes 0 / 0.4 / 0.7, each lane's weighted
            # favourite; no fallback — no signal leaves the effect default,
            # exactly like the rebuild.
            "dance_type": isteps([(0.0, "ballet"), (0.4, "cowboy"),
                                  (0.7, "kpop")], None),
        },
    },
    "Eye V2": {
        "eye": {
            "drift_speed": imap(0.35, 0.8, 0.5),
            "snap_threshold": imap(0.75, 0.45, 0.6),
            "snap_hold": imap(0.15, 0.5, 0.2),
            "flames": imap(0.2, 0.6, 0.35),
        },
    },
}


def migrate_scene(raw: dict) -> tuple[dict, list[str]]:
    """One scene's SPECTRA form + a human log of what was authored."""
    log: list[str] = []
    # Seed color_set_jump on the RAW legacy input so the model's flare-kinds
    # migration auto-names it into the "Colour Jump" drift-jump kind (a
    # post-construction attribute write would bypass validation and vanish).
    raw = dict(raw)
    if raw.get("flare_bands") and "flare" not in (raw.get("responses") or {}):
        raw["responses"] = {**(raw.get("responses") or {}),
                            "flare": {"bands": raw.pop("flare_bands"),
                                      "color_set_jump": True,
                                      "reroll_dice": True}}
        log.append("flare class: color_set_jump=True (legacy Color lane)")
    scene = SceneV2(**raw)   # flare-kinds migration runs here
    table = BINDINGS.get(scene.name, {})
    for dev in scene.devices:
        per_effect = table.get(dev.effect_type, {})
        for pname, binding in per_effect.items():
            static = dev.params.get(pname)
            b = dict(binding)
            if static is not None and b.get("fallback") is not None:
                b["fallback"] = static   # the rebuild's static IS the fallback
            dev.params[pname] = b
            log.append(f"{dev.target}/{dev.effect_type}.{pname}: "
                       f"{b['signal']}/{b['mode']}"
                       + (f" dice={b['dice']}" if b.get("dice") else "")
                       + f" fallback={b.get('fallback')}")
    return json.loads(scene.model_dump_json()), log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write SPECTRA storage (default: dry-run print)")
    parser.add_argument("--source", type=Path,
                        default=config.REPO_ROOT / "storage",
                        help="spot-effects storage dir (read-only)")
    args = parser.parse_args()

    scenes_file = args.source / "scenes_v2.json"
    sequencer_file = args.source / "sequencer.json"
    if not scenes_file.exists():
        raise SystemExit(f"no {scenes_file} — nothing to migrate")
    raw_scenes = json.loads(scenes_file.read_text(encoding="utf-8"))

    out_scenes: dict[str, dict] = {}
    for sid, raw in raw_scenes.items():
        migrated, log = migrate_scene(raw)
        out_scenes[sid] = migrated
        print(f"— {raw['name']} ({len(log)} change(s))")
        for line in log:
            print(f"    {line}")

    seq_raw = {}
    if sequencer_file.exists():
        seq_raw = json.loads(sequencer_file.read_text(encoding="utf-8"))
        print(f"— sequencer: {len(seq_raw.get('curve_profiles', {}))} curve "
              f"profile(s), config carried as-is (enabled stays "
              f"{seq_raw.get('config', {}).get('enabled', False)})")

    if not args.apply:
        print(f"\nDRY RUN — would write {len(out_scenes)} scenes to "
              f"{config.SCENES_FILE} (use --apply)")
        return

    config.SPECTRA_STORAGE.mkdir(parents=True, exist_ok=True)
    config.SCENES_FILE.write_text(json.dumps(out_scenes, indent=2),
                                  encoding="utf-8")
    if seq_raw:
        config.SEQUENCER_FILE.write_text(json.dumps(seq_raw, indent=2),
                                         encoding="utf-8")
    if not config.ROOM_COLOR_FILE.exists():
        save_room(RoomColorState())
        print(f"wrote default room journey → {config.ROOM_COLOR_FILE}")
    print(f"wrote {len(out_scenes)} scenes → {config.SCENES_FILE}")


if __name__ == "__main__":
    main()
