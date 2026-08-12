"""
Offline smoke test for Color Group Palette Sync.

Asserts, with no LedFX writes (pure selection logic on live storage data):
  1. representative_hue: solid hex, gradient circular-mean, rainbow rejection
     (agreement < 0.5), and grey/white/brightness-only cards -> None;
  2. parallel families anchor exactly: Mid - X and Power - X derive the SAME
     hue for every shared theme, so a group switch keeps the color family;
  3. sync picks: firing a synced group after another continues from the room's
     palette (exact-member match first, else nearest hue), advance=0 stays on
     the anchored member, and unsynced groups keep legacy cursor behavior;
  4. bounce cycling is unchanged for unsynced groups (regression).

USAGE
  .venv/bin/python scripts/smoke_palette_sync.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.state import state                                   # noqa: E402
from services import color_set_store                             # noqa: E402
from services.gradient_interpolation import (                    # noqa: E402
    hue_distance,
    representative_hue,
)
from services.trigger_engine import TriggerEngine                # noqa: E402

FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAIL
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL = 1


def fresh_engine() -> TriggerEngine:
    te = object.__new__(TriggerEngine)
    te._color_cursor = {}
    te._color_cursor_dir = {}
    te._color_cursor_prev = {}
    te._palette_hue = None
    return te


def card_hue(card) -> float | None:
    return representative_hue([card.color] + [e.color_value for e in card.entries])


def fire(te: TriggerEngine, group, advance: int = 1) -> str:
    """Pick + mimic _execute_set_color's publish (last set id + palette hue)."""
    cid = te._select_color_set_member(group, "default", advance, "forward")
    chosen = color_set_store.get_by_id(cid)
    state.last_color_set_id = cid
    h = card_hue(chosen)
    if h is not None:
        te._palette_hue = h
    return chosen.name


def main() -> int:
    cards = {c.name: c for c in color_set_store.list_all()}

    print("representative_hue:")
    check("solid hex red", representative_hue(["#ff0000"]) == 0.0)
    check("grey/white -> None", representative_hue(["#ffffff", "#808080"]) is None)
    check("empty/None -> None", representative_hue([None, ""]) is None)
    rainbow = ("linear-gradient(90deg, rgb(255,0,0) 0%, rgb(255,255,0) 25%, "
               "rgb(0,255,0) 50%, rgb(0,0,255) 75%, rgb(255,0,255) 100%)")
    check("rainbow gradient rejected", representative_hue([rainbow]) is None)
    grad = representative_hue(["linear-gradient(90deg, rgb(0,82,255) 0%, rgb(133,0,255) 100%)"])
    check("gradient circular mean", grad is not None and 230 < grad < 300,
          f"hue={grad and round(grad, 1)}")

    print("parallel families (live data):")
    themes = ["Fire", "Blush", "Bright Purple", "Purple Mid",
              "Purple Blue Waves", "Green with Yellow", "Ice", "Blue with Cyan"]
    for t in themes:
        mid, pwr = cards.get(f"Mid - {t}"), cards.get(f"Power - {t}")
        if mid is None or pwr is None:
            continue
        hm, hp = card_hue(mid), card_hue(pwr)
        check(f"Mid/Power '{t}' hues match",
              hm is not None and hp is not None and hue_distance(hm, hp) < 1.0,
              f"{hm and round(hm)} vs {hp and round(hp)}")

    print("sync picks:")
    fg, pg = cards["First Group"], cards["Power Group"]
    if not (fg.palette_sync and pg.palette_sync):
        print("  SKIP — palette_sync not enabled on First Group/Power Group")
        return FAIL

    te = fresh_engine()
    state.last_color_set_id = ""
    a = fire(te, fg, 1)                     # first fire -> member 0
    b = fire(te, fg, 1)                     # advance within the group
    check("cycle advances", a != b, f"{a} -> {b}")
    theme_b = b.split(" - ", 1)[1]
    c = fire(te, pg, 0)                     # group switch, advance 0
    check("adv=0 group switch keeps family", c == f"Power - {theme_b}", f"{b} -> {c}")
    d = fire(te, pg, 1)                     # advance from the anchored family
    themes_pg = [color_set_store.get_by_id(m.color_set_id).name.split(" - ", 1)[1]
                 for m in pg.members]
    expect = themes_pg[(themes_pg.index(theme_b) + 1) % len(themes_pg)]
    check("adv=1 continues from room's family", d == f"Power - {expect}", f"{c} -> {d}")

    lines = cards["Lines"]
    e = fire(te, lines, 0)                  # different family names: hue anchor
    lh, ph = card_hue(cards[e]), te._palette_hue
    check("cross-family hue anchor is nearest",
          lh is not None and all(
              hue_distance(lh, ph) <= hue_distance(h, ph) + 1e-6
              for m in lines.members
              if (h := card_hue(color_set_store.get_by_id(m.color_set_id))) is not None),
          f"room hue {ph and round(ph)} -> {e}")

    print("unsynced regression:")
    te2 = fresh_engine()
    calm = cards["Calm"].model_copy()
    calm.palette_sync = False
    calm.cycle_behavior = "bounce"
    seq = [fire(te2, calm, 1) for _ in range(5)]
    check("bounce sequence", [s.split(" - ")[1] for s in seq]
          == ["Purple", "Green", "Cyan", "Green", "Purple"], " -> ".join(seq))

    print("OK" if not FAIL else "FAILURES")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
