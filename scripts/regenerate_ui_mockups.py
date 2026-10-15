#!/usr/bin/env python3
"""Regenerate docs/design/spectra-ui-mockups.html from the Admiral-approved
artifact — MECHANICALLY, never by retyping.

The approved design is `data/ui-layout-plan/explainer-final.html` in the
fleet-spotfx home (the artifact he edited and said "it's ready to build").
Its `<style>` block (the `.sp` rules every mockup is drawn with) and its
`<script>` block (the real song data plus the DOM builders that populate
each frame) are the design; the rest of that file is prose and embedded
base64 screenshots of the OLD live app.

This copies those two blocks VERBATIM into a small frames-only page in the
repo, so `scripts/check_ui_fidelity.py` can render the approved frames with
no dependency on a path outside the checkout. Run it only when he approves
a NEW artifact — and when you do, re-run the fidelity gate: a frame whose
drawing moved is a real change to compare against.

RUN: python3 scripts/regenerate_ui_mockups.py [--artifact PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = Path.home() / "fleet-spotfx/data/ui-layout-plan/explainer-final.html"
OUT = REPO / "docs/design/spectra-ui-mockups.html"

# The artifact's script reaches for these ids in build()/controls(); they
# belong to prose widgets this page does not render, so they are stubbed
# hidden rather than editing its script (which must stay verbatim).
STUBS = (
    '<div id="simctl" style="display:none">'
    '<button data-speed="1" class="on"></button><button data-speed="4"></button>'
    '<button data-jump></button><button data-drop class="on"></button>'
    '<span id="simread"></span></div>'
    '<div id="homectl" style="display:none"><button data-follow></button>'
    '<button data-full></button></div>'
    '<button id="houseDemo" style="display:none"></button>'
    '<span id="houseHint" style="display:none"></span>'
    '<span id="houseToast" style="display:none"></span>'
    '<div id="shiftA" style="display:none"></div><div id="shiftB" style="display:none"></div>'
    '<span id="shiftAm" style="display:none"></span><span id="shiftBm" style="display:none"></span>'
    '<button id="themeBtn" style="display:none"></button>'
)

HEADER = """<!doctype html><html><head><meta charset="utf-8">
<title>SPECTRA UI mockups — the approved design, frames only</title>
<!--
  THE DESIGN OF RECORD, frames only.

  Derived MECHANICALLY (never retyped) from the Admiral-approved artifact
  data/ui-layout-plan/explainer-final.html in the fleet-spotfx home — the
  one he edited and said "it's ready to build". Its <style> block (the
  `.sp` rules every mockup is drawn with) and its <script> block (the real
  song data and the DOM builders that populate each frame) are copied
  VERBATIM; what is dropped is the explainer's own prose and its embedded
  base64 screenshots of the OLD live app, neither of which is part of the
  design.

  It lives in the repo so scripts/check_ui_fidelity.py — the design-
  fidelity gate — can render the approved frames beside the live chrome
  with no dependency on a path outside this checkout. The gate still
  PREFERS the fleet copy when it is present, so firstmate's own artifact
  stays authoritative; this is the fallback and the frozen reference.

  Regenerate (only when he approves a new artifact):
    python3 scripts/regenerate_ui_mockups.py
-->
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = ap.parse_args()
    if not args.artifact.is_file():
        print(f"the approved artifact is not at {args.artifact} — nothing to do.")
        return 1
    src = args.artifact.read_text()

    style = re.search(r"<style>\n/\* ── Explainer chrome.*?</style>", src, re.S)
    script = re.search(r"<script>\n/\* ═+ DATA.*?</script>", src, re.S)
    if not style or not script:
        print("could not find the artifact's own style/script blocks — "
              "has its shape changed? refusing to guess.")
        return 1

    widths = dict(re.findall(
        r'<div class="fw" data-w="(\d+)"[^>]*>\s*<div class="frame" id="([^"]+)"></div>', src))
    frames = re.findall(
        r'<div class="fw"[^>]*>\s*<div class="frame" id="([^"]+)"></div>\s*</div>', src)
    if not frames:
        print("no mockup frames found — refusing to write an empty reference.")
        return 1
    by_id = {fid: w for w, fid in widths.items()}

    body = "\n".join(
        f'<div class="fhead"><span class="lbl">{fid} · {by_id.get(fid, "1440")}px</span></div>\n'
        f'<div class="fw native" data-w="{by_id.get(fid, "1440")}" style="max-width:none">'
        f'<div class="frame" id="{fid}"></div></div>'
        for fid in frames
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(f'{HEADER}{style.group(0)}\n</head><body>'
                   f'<div class="wrap" style="max-width:none">\n{STUBS}\n{body}\n</div>\n'
                   f'{script.group(0)}\n</body></html>\n')
    print(f"wrote {OUT.relative_to(REPO)} — {len(frames)} frames: {' '.join(frames)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
