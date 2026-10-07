#!/usr/bin/env python3
"""HOUSE LIGHTING phase 4 — his STARTING CONTENT: the colour sets, the two
house scenes and the seven modes (plan: /home/javi/fleet-spotfx/data/
standard-lighting-plan/report.md §7; his words 2026-10-04: "use the calm
color set for standard lighting, and create a similar color set with a
dimmer and redder background color for evenings. For the night light, a
deep purple and teal green foreground with 3 slow, large fish on a dark
blue background ... Melt should be used for all the wled strips. A
breathing effect on the singles that arent the hue lights ... The Hue
lights should be similar to how we have them in home assistant and should
be static"; his plan comments: the crystal is STAR in Standard and
Evening, and there is NO Party mode).

THIS IS HIS DATA. It writes exactly three files and nothing else:

  storage/color_sets.json            + 4 colour sets and 1 group
  storage/spectra/scenes.json        + 2 scenes ("House Star", "House Fish")
  storage/spectra/house_modes.json   + 7 modes, + the Hue bulbs house
                                       lighting leaves alone

Every pre-existing entry in the first two files is serialized before and
after and compared byte for byte — any difference aborts before the write
(scripts/seed_fish_scene.py's rule). Each file is backed up to
storage/spectra/backups/ before it is replaced, and the WHOLE-FILE diff is
printed. Dry run by default; --apply writes.

IDS ARE DETERMINISTIC (uuid5) so a re-run finds what it wrote. AN ENTRY HE
HAS EDITED SINCE IT WAS SEEDED IS LEFT ALONE (reported, not overwritten)
unless --overwrite is passed — a starting point must never clobber his
tuning.

FOUR DECISIONS THE DATA ENCODES, each found reading his live data:

  1. "CALM - EVENING" IS A GROUP OF COPIES, NOT A SECOND GROUP OVER THE
     SAME SETS. A colour set fired by its own id wears EVERY enclosing
     group's overrides, alphabetically-last winning a conflict (AGENTS.md,
     2026-08-19). "Calm - Evening" sorts after "Calm", so a second group
     over Calm - Purple/Green/Cyan would turn Standard red too — in every
     colour journey leg and every music show that names one of them. The
     copies carry the redder, dimmer background themselves; the originals
     are not touched.
  2. THE NEW SETS ARE OPTED OUT OF THE MUSIC POOLS (scene_v2_opt_out), the
     same as the Calm members they copy, so they never turn up in a music
     show. House lighting names them explicitly, which the opt-out does not
     affect (spectra/services/drift_conductor.py's house pool).
  3. THE HOUSE SCENES HAVE NO SEQUENCER ENTRY, so the music engine never
     draws them: every automatic scene pick builds its candidates from
     storage/spectra/sequencer.json's entries (selection_kernel.
     build_scene_candidates). They also carry no flares — nothing plays on
     them at rest.
  4. THE BREATHING TARGETS THE `single-color-effect` VIRTUAL (the porch
     rail and the dining table), never the Singles category, which also
     holds the Hue virtual: the Hue bulbs are held over the bridge and must
     never breathe.

HOME ASSISTANT'S WORDS — every value input_select.lighting_mode can take
(read from HA 2026-10-05: Daytime, Evening, Dim, Bedtime, Travel, Party)
plus "Away": Daytime and Party → Standard (HA's own wled_lighting_updates
already treats Party as Daytime; there is no Party mode), Evening →
Evening, Dim → Dim, Bedtime → Night light, Travel and Away → Away. HA's
"unknown"/"unavailable" are deliberately NOT mapped: an unmapped word keeps
the current mode, so an HA restart never flips the house to Standard at
3am. The media centre's "TV" / "TV paused" reach the two TV modes by name.

THE HUE LOOKS ARE HOME ASSISTANT'S OWN, read from its scenes (2026-10-05):
standard_daytime 3521 K full; standard_evening 2000 K (living) / 2005 K
(dining) full; standard_nighttime (Dim) xy red-orange, living 50% / dining
full; bedtime, travel and away off; media_mode (TV playing) off;
media_pause living #ff9d31 at 29%, dining 2095 K at 54%. The crystal's
levels are HA's WLED presets' master brightness: Daytime bri 15 (6%),
Evening 34 (13%), Nightlight 7 (3%), media_mode bri 3 (1.2%).

NOTHING HERE SWITCHES HOUSE LIGHTING ON. HouseSettings.enabled is left as
it is (off unless he switched it on): seeding is inert until he does.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

NS = uuid.UUID("3c0f4f1e-6c1a-5d4e-9a7b-6f0e2b1d9a55")

#: input_select.lighting_mode's options, read from his Home Assistant
#: (2026-10-05), plus "Away" (presence) — every one must reach a mode.
HA_LIGHTING_MODES = ("Daytime", "Evening", "Dim", "Bedtime", "Travel", "Party", "Away")
#: The words the media centre reaches the TV modes by (spectra/services/
#: house.py media_words).
MEDIA_WORDS = ("TV", "TV paused")

CALM_GROUP = "Calm"
CALM_MEMBERS = ("Calm - Purple", "Calm - Green", "Calm - Cyan")
EVENING_GROUP = "Calm - Evening"
NIGHT_SET = "Night Light"
SCENE_STAR = "House Star"
SCENE_FISH = "House Fish"

#: Calm's backgrounds are #ff9940 (an orange) at full; evening's are redder
#: and dimmer.
EVENING_BG = "#e8471c"
EVENING_BG_BRIGHTNESS = 0.55

# The Hue areas (live device ids).
HUE_LIVING = "hue-lights"
HUE_DINING = "dining-hues"

# The fixtures (live device ids).
CRYSTAL = "crystal"
TV = "tv-backlight"
SCONCE_L = "sconce-kitchen-left"
SCONCE_R = "sconce-kitchen-right"
PORCH = "porch-rail"
TABLE = "dining-table"


def _sid(*parts: str) -> str:
    return str(uuid.uuid5(NS, ":".join(parts)))


def _mid(name: str) -> str:
    return uuid.uuid5(NS, f"mode:{name}").hex[:12]


class SeedError(RuntimeError):
    pass


# ── content ────────────────────────────────────────────────────────────────

def _by_name(store: dict, name: str, kind: Optional[str] = None) -> dict:
    hits = [v for v in store.values() if isinstance(v, dict)
            and (v.get("name") or "").strip().lower() == name.lower()
            and (kind is None or v.get("kind", "set") == kind)]
    if len(hits) != 1:
        raise SeedError(f"expected exactly one {kind or 'entry'} named {name!r}, "
                        f"found {len(hits)}")
    return hits[0]


def _card(raw: dict) -> dict:
    """Validate through SpotFX's own ColorSetCard and return the canonical
    dict color_set_store.save() would write."""
    from models.color_set import ColorSetCard
    return json.loads(ColorSetCard(**raw).model_dump_json())


def colour_cards(color_sets: dict) -> dict[str, dict]:
    """id -> canonical card for every colour card this seeds."""
    calm = _by_name(color_sets, CALM_GROUP, "group")
    members = [_by_name(color_sets, n, "set") for n in CALM_MEMBERS]
    member_ids = {m.get("color_set_id") for m in calm.get("members", [])}
    if member_ids != {m["id"] for m in members}:
        raise SeedError(f"the {CALM_GROUP!r} group's members are not exactly "
                        f"{list(CALM_MEMBERS)} — refusing to guess which sets to copy")
    out: dict[str, dict] = {}
    copies = []
    for src in members:
        colour = src["name"].split(" - ", 1)[1]
        cid = _sid("color-set", f"{EVENING_GROUP} {colour}")
        entries = []
        for e in src.get("entries", []):
            e = copy.deepcopy(e)
            e["bg_color"] = EVENING_BG
            e["background_brightness"] = EVENING_BG_BRIGHTNESS
            entries.append(e)
        out[cid] = _card({
            "id": cid, "name": f"{EVENING_GROUP} {colour}", "color": src.get("color", "#ffffff"),
            "kind": "set", "labels": ["calm", "evening", "house"],
            "entries": entries, "scene_v2_opt_out": True,
        })
        copies.append(cid)
    gid = _sid("color-set", EVENING_GROUP)
    out[gid] = _card({
        "id": gid, "name": EVENING_GROUP, "color": "#c0502a", "kind": "group",
        "labels": ["calm", "evening", "house"],
        "members": [{"color_set_id": c, "weight": 1.0} for c in copies],
        "entries": [
            {"scope": {"virtual_ids": [], "categories": ["Singles"], "roles": []},
             "color_kind": "solid", "color_value": "#ff8a3d", "bg_color": "#ff8a3d",
             "bg_mode": "overwrite", "brightness": 1.0, "background_brightness": 0.45},
            {"scope": {"virtual_ids": [], "categories": ["Matrix"], "roles": []},
             "color_kind": None, "color_value": None, "bg_color": "#ff5a1f",
             "bg_mode": "overwrite", "brightness": 1.0, "background_brightness": 0.45},
        ],
        "mode": calm.get("mode", "cycle"), "cycle_behavior": calm.get("cycle_behavior", "wrap"),
        "exclude_current": calm.get("exclude_current", True),
        "palette_sync": True, "scene_v2_opt_out": False,
    })
    nid = _sid("color-set", NIGHT_SET)
    out[nid] = _card({
        "id": nid, "name": NIGHT_SET, "color": "#3a1e8c", "kind": "set",
        "labels": ["night", "house"], "scene_v2_opt_out": True,
        "entries": [
            # The crystal: deep purple and teal fish on dark-blue water.
            {"scope": {"virtual_ids": [], "categories": ["Matrix"], "roles": []},
             "color_kind": "gradient",
             "color_value": "linear-gradient(90deg, #5a14b4 0.00%,#00c8a0 100.00%)",
             "bg_color": "#0a1550", "bg_mode": "overwrite",
             "brightness": 1.0, "background_brightness": 1.0},
            # The strips and the singles in Dim: Home Assistant's own deep
            # red-orange (standard_nighttime's Hue colour).
            {"scope": {"virtual_ids": [], "categories": ["Strips"], "roles": []},
             "color_kind": "gradient",
             "color_value": "linear-gradient(90deg, #ff2a00 0.00%,#ff6a10 100.00%)",
             "bg_color": "#200400", "bg_mode": "overwrite",
             "brightness": 1.0, "background_brightness": 0.3},
            {"scope": {"virtual_ids": [], "categories": ["Singles"], "roles": []},
             "color_kind": "solid", "color_value": "#ff4a12", "bg_color": None,
             "bg_mode": None, "brightness": 1.0, "background_brightness": None},
        ],
    })
    return out


def _breathing(modulation_speed: float) -> dict:
    return {"target_kind": "virtual", "target": "single-color-effect",
            "effect_type": "gradient",
            "params": {"modulate": True, "modulation_effect": "sine",
                       "modulation_speed": modulation_speed, "speed": 2.0,
                       "gradient_roll": 0},
            "color": {"mode": "set"}}


def _melt(speed: float) -> dict:
    return {"target_kind": "category", "target": "Strips", "effect_type": "melt",
            "params": {"speed": speed, "reactivity": 0.3, "blur": 1.0, "flip": False},
            "color": {"mode": "set"}}


def scene_entries() -> dict[str, dict]:
    """id -> canonical SceneV2 dict for the two house scenes."""
    from spectra.models.scene import SceneV2
    star = {
        "id": _sid("scene", SCENE_STAR), "name": SCENE_STAR, "labels": ["house"],
        "accept_all_sets": True,
        "devices": [
            {"target_kind": "category", "target": "Matrix", "effect_type": "radial",
             # STAR, slow: the six-pointed star turning on its own (a
             # base_rotation floor; spin is the music's squared gain).
             "params": {"polygon": True, "edges": 6, "star": 0.3, "twist": 0,
                        "x_offset": 0.5, "y_offset": 0.5, "spin": 0.25,
                        "base_rotation": 0.03},
             "color": {"mode": "set"}},
            _melt(0.12),
            _breathing(0.8),
        ],
    }
    fish = {
        "id": _sid("scene", SCENE_FISH), "name": SCENE_FISH, "labels": ["house"],
        "accept_all_sets": True,
        "devices": [
            {"target_kind": "category", "target": "Matrix", "effect_type": "fish",
             # Three large, slow fish that do not react to music.
             "params": {"particle_count": 3, "blob_size": 4.0, "base_speed": 0.08,
                        "reactivity_scale": 0.0, "brightness_audio": 0.0,
                        "size_audio": 0.0, "speed_jump": 0.0, "speed_jog": 0.0,
                        "jiggle": 0.05, "spin": 0.1, "flap_rate": 1.0,
                        "camera_follow": 0.0, "color_shift": 0,
                        "tether_scatter": 0.0},
             "color": {"mode": "set"}},
            _melt(0.08),
            _breathing(0.5),
        ],
    }
    out = {}
    for raw in (star, fish):
        for i, dev in enumerate(raw["devices"]):
            dev["id"] = _sid("scene-device", raw["name"], str(i))
        _check_params(raw)
        out[raw["id"]] = json.loads(SceneV2(**raw).model_dump_json())
    return out


def _check_params(scene: dict) -> None:
    """Every param must be a real key of the vendored effect's own schema —
    effect schemas allow extra keys, so a typo would otherwise land as an
    inert, unread key."""
    from fx import device_model
    for dev in scene["devices"]:
        cls = device_model._effect_class(dev["effect_type"])
        if cls is None:
            raise SeedError(f"{scene['name']}: no effect {dev['effect_type']!r}")
        keys = {str(getattr(k, "schema", k)) for k in cls.schema().schema}
        unknown = sorted(set(dev["params"]) - keys)
        if unknown:
            raise SeedError(f"{scene['name']}: {dev['effect_type']} has no param(s) {unknown}")


def _hook(target: str, *, level=None, motion=None, fps=None, off=False,
          kind: str = "fixture") -> dict:
    out: dict[str, Any] = {"target": {"kind": kind, "id": target if kind != "everything" else None}}
    if level is not None:
        out["level"] = level
    if motion is not None:
        out["motion"] = motion
    if fps is not None:
        out["fps"] = fps
    if off:
        out["off"] = True
    return out


def _hold(area: str, *, kelvin=None, color=None, brightness=100.0) -> dict:
    out: dict[str, Any] = {"area": area, "look": "hold", "brightness": brightness}
    if kelvin is not None:
        out["kelvin"] = kelvin
    if color is not None:
        out["color"] = color
    return out


def _off(area: str) -> dict:
    return {"area": area, "look": "off"}


def _resting(crystal: float, strips: float, singles: float, *, crystal_motion: float,
             strip_motion: float, single_motion: float, crystal_fps: int = 20) -> list[dict]:
    return [
        _hook(CRYSTAL, level=crystal, motion=crystal_motion, fps=crystal_fps),
        _hook(TV, level=strips, motion=strip_motion, fps=20),
        _hook(SCONCE_L, level=strips, fps=20),
        _hook(SCONCE_R, level=strips, fps=20),
        _hook(PORCH, level=singles, motion=single_motion, fps=10),
        _hook(TABLE, level=singles, fps=10),
    ]


def modes(cards: dict, scenes: dict) -> list[dict]:
    """The seven modes, as HouseMode dicts (validated by the caller)."""
    calm = None
    evening = _sid("color-set", EVENING_GROUP)
    night = _sid("color-set", NIGHT_SET)
    star = _sid("scene", SCENE_STAR)
    fish = _sid("scene", SCENE_FISH)
    for cid, c in cards.items():
        if c["name"] == CALM_GROUP and c["kind"] == "group":
            calm = cid
    if calm is None:
        raise SeedError("the Calm group is missing")

    def mode(name, aliases, scene, colour, fixtures, hue, music, music_hue, notes):
        return {"id": _mid(name), "name": name, "ha_aliases": aliases,
                "scenes": [{"scene_id": scene, "weight": 1.0}],
                "color_sets": [{"card_id": colour, "weight": 1.0}],
                # One scene per mode and a still colour journey: the motion
                # is the effects' own (Star turning, Melt, the breathing,
                # the fish). Turn the journey on per mode to let the
                # colours wander too.
                "flow": {"scene_every_min": 0.0, "journey_deg_per_min": 0.0,
                         "intensity": 0.25},
                "fixtures": fixtures, "hue": hue, "music": music,
                "music_hue": music_hue, "notes": notes}

    return [
        mode("Standard", ["Daytime", "Party"], star, calm,
             _resting(6.0, 40.0, 100.0, crystal_motion=0.015, strip_motion=0.12,
                      single_motion=0.8),
             [_hold(HUE_LIVING, kelvin=3521), _hold(HUE_DINING, kelvin=3521)],
             "show", "room",
             "Starting look (phase 4). Calm on Star; crystal at HA's Daytime preset "
             "brightness (bri 15 = 6%). Hue = HA's standard_daytime, 3521 K full. "
             "Answers to Party too: there is no Party mode, and HA's own crystal "
             "script treats Party as Daytime."),
        mode("Evening", [], star, evening,
             _resting(13.0, 30.0, 100.0, crystal_motion=0.0125, strip_motion=0.10,
                      single_motion=0.6),
             [_hold(HUE_LIVING, kelvin=2000), _hold(HUE_DINING, kelvin=2005)],
             "show", "room",
             "Starting look (phase 4). Calm - Evening (redder, dimmer background) on "
             "Star; crystal at HA's Evening preset brightness (bri 34 = 13%). Hue = "
             "HA's standard_evening, 2000 K living / 2005 K dining, full."),
        mode("Dim", [], fish, night,
             _resting(3.0, 12.0, 50.0, crystal_motion=0.016, strip_motion=0.08,
                      single_motion=0.45),
             [_hold(HUE_LIVING, color="#ff3900", brightness=50.0),
              _hold(HUE_DINING, color="#ff4401", brightness=100.0)],
             "show", "room",
             "Starting look (phase 4). The Night light fish on the crystal at HA's "
             "Nightlight preset brightness (bri 7 = 3%), strips and singles dim red-"
             "orange. Hue = HA's standard_nighttime: deep red-orange, living 50%, "
             "dining full."),
        mode("Night light", ["Bedtime"], fish, night,
             [_hook(CRYSTAL, level=3.0, motion=0.016, fps=15),
              _hook(TV, off=True), _hook(SCONCE_L, off=True), _hook(SCONCE_R, off=True),
              _hook(PORCH, off=True), _hook(TABLE, off=True)],
             [_off(HUE_LIVING), _off(HUE_DINING)],
             "ignore", "hold",
             "Starting look (phase 4). Only the crystal: three large, slow fish in "
             "deep purple and teal on dark blue, at 3%. Every other fixture off; Hue "
             "off (HA's bedtime). Never lights the bedroom or the loft."),
        mode("Away", ["Travel"], star, calm,
             [_hook("", off=True, kind="everything")],
             [_off(HUE_LIVING), _off(HUE_DINING)],
             "ignore", "hold",
             "Starting look (phase 4). Every Spectra fixture off, Hue off (HA's "
             "away_lighting / travel scenes). HA keeps its own presence lights."),
        mode("TV", [], star, evening,
             [_hook(CRYSTAL, level=1.2, motion=0.01, fps=20),
              _hook(TV, level=15.0, fps=20), _hook(SCONCE_L, level=15.0, fps=20),
              _hook(SCONCE_R, level=15.0, fps=20),
              _hook(PORCH, level=30.0, motion=0.6, fps=10), _hook(TABLE, level=30.0, fps=10)],
             [_off(HUE_LIVING), _off(HUE_DINING)],
             "ignore", "hold",
             "Starting look (phase 4): a film playing. Crystal at HA's media_mode "
             "brightness (bri 3 = 1.2%), sconces and singles dim, Hue off (HA's "
             "media_mode). The TV strip goes to Hyperion by itself while the media "
             "centre is on."),
        mode("TV paused", [], star, evening,
             [_hook(CRYSTAL, level=6.0, motion=0.01, fps=20),
              _hook(TV, level=35.0, fps=20), _hook(SCONCE_L, level=35.0, fps=20),
              _hook(SCONCE_R, level=35.0, fps=20),
              _hook(PORCH, level=60.0, motion=0.6, fps=10), _hook(TABLE, level=60.0, fps=10)],
             [_hold(HUE_LIVING, color="#ff9d31", brightness=29.0),
              _hold(HUE_DINING, kelvin=2095, brightness=54.0)],
             "ignore", "hold",
             "Starting look (phase 4): a film paused or at a menu. Hue = HA's "
             "media_pause: living #ff9d31 at 29%, dining 2095 K at 54%."),
    ]


# ── planning ───────────────────────────────────────────────────────────────

class FilePlan:
    def __init__(self, path: Path, before: Optional[str], after: str,
                 added: list[str], updated: list[str], kept: list[str]):
        self.path, self.before, self.after = path, before, after
        self.added, self.updated, self.kept = added, updated, kept

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def diff(self) -> str:
        return "".join(difflib.unified_diff(
            (self.before or "").splitlines(keepends=True),
            self.after.splitlines(keepends=True),
            fromfile=f"{self.path} (before)", tofile=f"{self.path} (after)", n=2))


def _upsert(store: dict, new: dict[str, dict], overwrite: bool, label: str):
    """Add or update entries by id. One he EDITED since it was seeded (it
    exists and differs) is kept unless overwrite. Pre-existing entries are
    never touched otherwise."""
    added, updated, kept = [], [], []
    out = dict(store)
    for nid, entry in new.items():
        name = entry.get("name")
        clash = [v for k, v in store.items() if k != nid and isinstance(v, dict)
                 and (v.get("name") or "").strip().lower() == name.lower()]
        if clash:
            raise SeedError(f"a {label} called {name!r} already exists with a different "
                            f"id — refusing to make a second")
        if nid not in store:
            out[nid] = entry
            added.append(name)
        elif store[nid] == entry:
            pass
        elif overwrite:
            out[nid] = entry
            updated.append(name)
        else:
            kept.append(name)
    return out, added, updated, kept


def _assert_untouched(before: dict, after: dict, touched: set, label: str) -> None:
    for k, v in before.items():
        if k in touched:
            continue
        if json.dumps(after.get(k), indent=2) != json.dumps(v, indent=2):
            raise SeedError(f"{label}: pre-existing entry {k} would change — aborting")


def _read(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8") if path.exists() else None


def plan(root: Path, *, overwrite: bool = False) -> list[FilePlan]:
    colors_path = root / "storage" / "color_sets.json"
    scenes_path = root / "storage" / "spectra" / "scenes.json"
    modes_path = root / "storage" / "spectra" / "house_modes.json"

    colors_raw = _read(colors_path)
    scenes_raw = _read(scenes_path)
    if colors_raw is None or scenes_raw is None:
        raise SeedError(f"{colors_path} and {scenes_path} must exist")
    colors = json.loads(colors_raw)
    scenes = json.loads(scenes_raw)

    new_cards = colour_cards(colors)
    colors_after, c_add, c_upd, c_kept = _upsert(colors, new_cards, overwrite, "colour set")
    _assert_untouched(colors, colors_after, set(new_cards) if overwrite else set(c_add), "color_sets.json")

    new_scenes = scene_entries()
    scenes_after, s_add, s_upd, s_kept = _upsert(scenes, new_scenes, overwrite, "scene")
    _assert_untouched(scenes, scenes_after, set(new_scenes) if overwrite else set(s_add), "scenes.json")

    plans = [
        FilePlan(colors_path, colors_raw, json.dumps(colors_after, indent=2), c_add, c_upd, c_kept),
        FilePlan(scenes_path, scenes_raw, json.dumps(scenes_after, indent=2), s_add, s_upd, s_kept),
        _plan_modes(modes_path, colors_after, scenes_after, overwrite),
    ]
    for p in plans[:2]:
        if p.before is not None and json.dumps(json.loads(p.before), indent=2) != p.before:
            raise SeedError(f"{p.path} is not in the store's own JSON layout — a rewrite "
                            "would reformat entries this script never touches; refusing")
    return plans


def _plan_modes(path: Path, cards: dict, scenes: dict, overwrite: bool) -> FilePlan:
    from spectra.models.house_mode import HouseLibrary, HouseMode
    before = _read(path)
    raw = json.loads(before) if before else {}
    lib = HouseLibrary(**raw) if raw else HouseLibrary()
    added, updated, kept = [], [], []
    wanted = [HouseMode(**m) for m in modes(cards, scenes)]
    by_id = {m.id: i for i, m in enumerate(lib.modes)}
    names = {m.name.lower(): m for m in lib.modes}
    aliases = {a.lower(): m for m in lib.modes for a in m.ha_aliases}
    for w in wanted:
        clash = names.get(w.name.lower())
        if clash is not None and clash.id != w.id:
            raise SeedError(f"a mode called {w.name!r} already exists — refusing to make a second")
        for a in w.ha_aliases + [w.name]:
            other = aliases.get(a.lower())
            if other is not None and other.id != w.id:
                raise SeedError(f"Home Assistant's {a!r} already belongs to {other.name!r}")
        if w.id not in by_id:
            lib.modes.append(w)
            added.append(w.name)
            continue
        cur = lib.modes[by_id[w.id]]
        same = (cur.model_dump(exclude={"created_ms", "updated_ms"})
                == w.model_dump(exclude={"created_ms", "updated_ms"}))
        if same:
            continue
        if overwrite:
            lib.modes[by_id[w.id]] = w.model_copy(update={"created_ms": cur.created_ms})
            updated.append(w.name)
        else:
            kept.append(w.name)
    after = json.dumps(lib.model_dump(), indent=2)
    if before is not None and not (added or updated):
        after = before
    return FilePlan(path, before, after, added, updated, kept)


# ── writing ────────────────────────────────────────────────────────────────

def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply(plans: list[FilePlan], backup_dir: Path) -> list[Path]:
    """Back every changing file up, then write them. Re-reads each file just
    before writing and refuses if it changed since the plan was made."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups = []
    for p in plans:
        if not p.changed:
            continue
        if _read(p.path) != p.before:
            raise SeedError(f"{p.path} changed while planning — run again")
        if p.before is not None:
            dest = backup_dir / f"{p.path.stem}-pre-house-phase4-{stamp}.json"
            dest.write_text(p.before, encoding="utf-8")
            backups.append(dest)
    for p in plans:
        if p.changed:
            _write_atomic(p.path, p.after)
    return backups


def check_mapping(modes_text: str) -> list[str]:
    """Every Home Assistant lighting_mode value and media word must reach a
    mode. Returns the problems (empty = complete)."""
    from spectra.models.house_mode import HouseLibrary
    lib = HouseLibrary(**json.loads(modes_text))
    problems = []
    for word in HA_LIGHTING_MODES + MEDIA_WORDS:
        low = word.lower()
        hit = [m.name for m in lib.modes if m.answers_to(word)] or \
              [m.name for m in lib.modes if m.name.strip().lower() == low]
        if not hit:
            problems.append(f"no mode answers to {word!r}")
    return problems


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace seeded entries he has edited since (default: keep his)")
    ap.add_argument("--root", type=Path, default=REPO,
                    help="the checkout whose storage/ is seeded (default: this one)")
    args = ap.parse_args(argv)
    try:
        plans = plan(args.root, overwrite=args.overwrite)
    except SeedError as exc:
        print(f"REFUSED: {exc}")
        return 2
    for p in plans:
        print(f"== {p.path}")
        print(f"   added: {p.added or '-'}   updated: {p.updated or '-'}   "
              f"kept (edited since seeding): {p.kept or '-'}")
        if p.changed:
            print(p.diff())
        else:
            print("   no change")
    problems = check_mapping(plans[2].after)
    for prob in problems:
        print(f"MAPPING: {prob}")
    if problems:
        return 3
    if not args.apply:
        print("dry run — nothing written (pass --apply)")
        return 0
    try:
        backups = apply(plans, args.root / "storage" / "spectra" / "backups")
    except SeedError as exc:
        print(f"REFUSED: {exc}")
        return 2
    for b in backups:
        print(f"backup: {b}")
    print("written. House lighting stays switched "
          "off until he switches it on (House tab).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
