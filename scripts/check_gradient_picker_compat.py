"""Executable proof that adopting LedFX's own colour picker
(`react-gcolor-picker`, wired in `web/src/components/ColorGradientPicker.tsx`
and `spectra/web/src/components/ColorGradientPicker.tsx`) needs no migration
of his existing stored colours and gradients.

Two checks against every colour/gradient string actually on disk in this repo
(`storage/color_sets.json`, `storage/gradients.json` if present — his real
data, not synthetic examples):

1. Backend compatibility — every gradient string still parses through
   SpotFX's own production interpolator (`services/gradient_interpolation.py`
   `_parse_linear`), the module that actually drives drift/morph. A failure
   here would mean colour drift silently falls back to an instant switch
   (see that module's docstring).
2. Picker round-trip — every string already matches the CSS grammar the
   picker both emits and accepts (explicit leading angle, hex or rgb() stops,
   a space before each `%`). This is what lets the picker load a stored
   value as `value=` and re-save it byte-for-byte compatible.

Dry-run only — reads storage, writes nothing.
Run from repo root: .venv/bin/python scripts/check_gradient_picker_compat.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.gradient_interpolation import _parse_linear, _HEX_FULL_RE  # noqa: E402

ROOT = Path(__file__).parent.parent
STORAGE = ROOT / "storage"

# Mirrors react-gcolor-picker's documented output grammar (README: colours
# followed by a space then a `%` position) plus LedFX's own accepted forms.
_PICKER_STOP_RE = re.compile(
    r"(#[0-9a-fA-F]{6}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))\s+[\d.]+%",
    re.IGNORECASE,
)
_PICKER_ANGLE_RE = re.compile(r"linear-gradient\(\s*-?\d+deg", re.IGNORECASE)


def picker_compatible(value: str) -> tuple[bool, str]:
    """Would react-gcolor-picker load this value and re-emit an equivalent
    string? True for a bare solid hex, or a linear-gradient with an explicit
    angle and >=2 well-formed stops."""
    if _HEX_FULL_RE.match(value):
        return True, "solid hex"
    if "linear-gradient" not in value:
        return False, "not a hex colour or a linear-gradient"
    if not _PICKER_ANGLE_RE.match(value.strip()):
        return False, "no explicit leading angle"
    stops = _PICKER_STOP_RE.findall(value)
    if len(stops) < 2:
        return False, f"only {len(stops)} well-formed stop(s) found"
    return True, f"{len(stops)} stops"


def find_color_strings(obj, found: set[str]) -> None:
    """Walk any JSON structure, collecting every string value that looks
    like a colour or gradient (hex or CSS linear-gradient)."""
    if isinstance(obj, dict):
        for v in obj.values():
            find_color_strings(v, found)
    elif isinstance(obj, list):
        for v in obj:
            find_color_strings(v, found)
    elif isinstance(obj, str):
        if obj.startswith("#") or "linear-gradient" in obj:
            found.add(obj)


def main() -> int:
    sources = [STORAGE / "color_sets.json", STORAGE / "gradients.json"]
    values: set[str] = set()
    for src in sources:
        if not src.exists():
            print(f"  (skip, not present: {src.relative_to(ROOT)})")
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        before = len(values)
        find_color_strings(data, values)
        print(f"  {src.relative_to(ROOT)}: {len(values) - before} distinct colour/gradient string(s)")

    if not values:
        print("No colour/gradient strings found on disk — nothing to prove against real data.")
        return 1

    print(f"\n{len(values)} distinct colour/gradient string(s) found across storage. Checking each:\n")

    backend_fail = []
    picker_fail = []
    gradients_seen = 0
    for value in sorted(values):
        is_gradient = "linear-gradient" in value
        if is_gradient:
            gradients_seen += 1
            parsed = _parse_linear(value)
            if parsed is None:
                backend_fail.append(value)

        ok, reason = picker_compatible(value)
        if not ok:
            picker_fail.append((value, reason))

    print(f"Gradients checked against services/gradient_interpolation.py's real parser: {gradients_seen}")
    print(f"  backend parse failures: {len(backend_fail)}")
    for v in backend_fail:
        print(f"    FAIL (backend): {v}")

    print(f"\nAll {len(values)} strings checked against the picker's output grammar:")
    print(f"  picker-incompatible: {len(picker_fail)}")
    for v, reason in picker_fail:
        print(f"    FAIL (picker): {v}  [{reason}]")

    ok = not backend_fail and not picker_fail
    print()
    if ok:
        print(f"PASS — all {len(values)} real stored colour/gradient string(s) parse through the "
              "production backend and match the picker's grammar. No migration needed.")
    else:
        print("FAIL — see failures above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
