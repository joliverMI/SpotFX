"""gifsmith CLI — author, preview and publish GIF assets for LedFX matrices.

    python -m tools.gifsmith profile crystal-mapper
    python -m tools.gifsmith poses --list
    python -m tools.gifsmith render --style basic --energy normal
    python -m tools.gifsmith preview --gif build/gifs/dancer_basic.gif --device crystal-mapper --ascii
    python -m tools.gifsmith push --gif build/gifs/dancer_basic.gif --device crystal-mapper --fake-beat
    python -m tools.gifsmith restore --device crystal-mapper
    python -m tools.gifsmith publish --gif build/gifs/dancer_basic.gif --dest spotfx/dancer/
    python -m tools.gifsmith status

All commands are non-interactive. See .claude/skills/led-gif-assets/SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import DEFAULT_LEDFX_URL
from . import device_profiles, ledfx_io, manifest as manifest_mod, preview as preview_mod
from .gifio import read_gif_frames, tint_frames, write_gif
from .skeleton import build_dance, load_poses
from .styles import DANCES, dance_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_ROOT / "build" / "gifs"
MASTERS_DIR = Path(__file__).parent / "masters"


def cmd_profile(args) -> None:
    profile = device_profiles.extract_profile(args.virtual_id, args.ledfx)
    path = device_profiles.save_profile(profile)
    print(f"wrote {path}")
    for key in (
        "rows", "cols", "pixel_count", "real_pixel_count",
        "hex_lattice", "effective_width", "min_stroke_px",
    ):
        print(f"  {key}: {profile[key]}")


def cmd_poses(args) -> None:
    poses = load_poses()
    names = [name for name in poses if not name.startswith("_")]
    if args.show:
        print(json.dumps({args.show: poses[args.show]}, indent=2))
        return
    print(f"{len(names)} poses (any name + '!mirror' flips it):")
    for name in names:
        tags = ",".join(poses[name].get("tags", []))
        print(f"  {name:18s} [{tags}]")
    print("\ndance styles (style/energy):")
    for (style, energy), spec in DANCES.items():
        print(f"  {style}/{energy}: {' -> '.join(spec['poses'])}")


def _asset_name(style: str, energy: str) -> str:
    return f"dancer_{style}" + ("_big" if energy == "big" else "")


def cmd_render(args) -> None:
    spec = dance_spec(args.style, args.energy)
    profile = device_profiles.load_profile(args.device)
    color = args.color.lstrip("#")
    rgb = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))

    frames, beat_frames = build_dance(
        spec["poses"],
        tweens_per_beat=spec["tweens_per_beat"],
        width=profile["cols"],
        height=profile["rows"],
        stroke_px=profile["min_stroke_px"],
        color=rgb,
    )
    name = _asset_name(args.style, args.energy)
    out = Path(args.out) if args.out else BUILD_DIR / f"{name}.gif"
    write_gif(frames, out)
    meta = {
        "asset_id": name,
        "style": args.style,
        "energy": args.energy,
        "frames": len(frames),
        "beat_frames": beat_frames,
        "master_color": args.color,
        "device": args.device,
        "poses": spec["poses"],
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {out} ({len(frames)} frames, {out.stat().st_size} bytes)")
    print(f"beat_frames: {beat_frames}")


def cmd_preview(args) -> None:
    profile = device_profiles.load_profile(args.device)
    if args.png:
        path = preview_mod.contact_sheet(args.gif, profile, args.png)
        print(f"wrote {path}")
    if args.ascii or not args.png:
        print(preview_mod.ascii_preview(args.gif, profile, args.frame))
    report = preview_mod.coverage_report(args.gif, profile)
    print(
        f"coverage: {report['frames']} frames, lit real-cells per frame "
        f"min={report['lit_min']} max={report['lit_max']}"
    )
    if report["lit_min"] < 20:
        print("WARNING: some frames light <20 real cells — figure may vanish on the lattice")


def cmd_push(args) -> None:
    profile = device_profiles.load_profile(args.device)
    gif = Path(args.gif)
    dest = f"spotfx/_preview/{gif.name}"
    ledfx_io.upload_asset(gif, dest, args.ledfx)

    meta_file = gif.with_suffix(".meta.json")
    beat_frames = args.beat_frames
    if beat_frames is None and meta_file.exists():
        beat_frames = json.loads(meta_file.read_text()).get("beat_frames", "")

    prior = ledfx_io.get_active_effect(args.device, args.ledfx)
    ledfx_io.save_push_state(args.device, prior)

    config = dict(profile["recommended_effect_config"])
    config.update(
        {
            "image_location": dest,
            "beat_frames": beat_frames or "",
            "fake_beat": bool(args.fake_beat),
        }
    )
    ledfx_io.set_effect(args.device, "keybeat2d", config, args.ledfx)
    print(f"pushed keybeat2d({dest}) to {args.device}"
          + (" with fake_beat" if args.fake_beat else ""))
    print(f"restore with: python -m tools.gifsmith restore --device {args.device}")


def cmd_restore(args) -> None:
    prior = ledfx_io.pop_push_state(args.device)
    if prior:
        ledfx_io.set_effect(args.device, prior["type"], prior.get("config", {}), args.ledfx)
        print(f"restored {prior['type']} on {args.device}")
    else:
        ledfx_io.clear_effect(args.device, args.ledfx)
        print(f"no saved state — cleared effect on {args.device}")


def cmd_publish(args) -> None:
    dest_dir = args.dest.rstrip("/")
    for gif_arg in args.gif:
        gif = Path(gif_arg)
        meta_file = gif.with_suffix(".meta.json")
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        asset_id = meta.get("asset_id", gif.stem)
        dest = f"{dest_dir}/{gif.name}"

        ledfx_io.upload_asset(gif, dest, args.ledfx)
        live_frames = ledfx_io.gif_frame_count(dest, args.ledfx)
        local_frames = len(read_gif_frames(gif))
        if live_frames != local_frames:
            raise SystemExit(
                f"{asset_id}: LedFX reports {live_frames} frames, local GIF has {local_frames}"
            )

        MASTERS_DIR.mkdir(parents=True, exist_ok=True)
        master = MASTERS_DIR / gif.name
        if gif.resolve() != master.resolve():
            shutil.copy2(gif, master)

        profile_id = meta.get("device", args.device)
        device_cfg = {}
        try:
            device_cfg = device_profiles.load_profile(profile_id)["recommended_effect_config"]
        except SystemExit:
            pass

        entry = {
            "path": dest,
            "kind": "dance",
            "style": meta.get("style", args.style or ""),
            "energy": meta.get("energy", args.energy or "normal"),
            "frames": local_frames,
            "beat_frames": args.beat_frames or meta.get("beat_frames", ""),
            "ping_pong": False,
            "half_beat": False,
            "master_color": meta.get("master_color", "#ffffff"),
            "master_file": str(master.relative_to(REPO_ROOT)),
            "tags": args.tags.split(",") if args.tags else meta.get("poses") and ["dancer", "stick-figure"] or [],
            "device_overrides": {profile_id: device_cfg} if device_cfg else {},
        }
        manifest_mod.upsert_asset(asset_id, entry)
        _link_big_variants()
        print(f"published {asset_id} -> {dest} ({local_frames} frames)")


def _link_big_variants() -> None:
    manifest = manifest_mod.load_manifest()
    changed = False
    for asset_id, entry in manifest["assets"].items():
        big_id = f"{asset_id}_big"
        if not asset_id.endswith("_big") and big_id in manifest["assets"]:
            if entry.get("big_variant") != big_id:
                entry["big_variant"] = big_id
                changed = True
    if changed:
        manifest_mod.save_manifest(manifest)


def cmd_status(args) -> None:
    manifest = manifest_mod.load_manifest()
    live = {asset["path"] for asset in ledfx_io.list_assets(args.ledfx)}
    if not manifest["assets"]:
        print("manifest empty")
        return
    for asset_id, entry in sorted(manifest["assets"].items()):
        ok = entry["path"] in live
        marker = "ok " if ok else "MISSING"
        print(f"  [{marker}] {asset_id:24s} {entry['path']} "
              f"({entry.get('frames', '?')} frames, beat_frames '{entry.get('beat_frames', '')}')")
    orphans = [p for p in sorted(live) if p.startswith("spotfx/") and not p.startswith("spotfx/_preview/")
               and p not in {e["path"] for e in manifest["assets"].values()}]
    if orphans:
        print("live spotfx assets not in manifest:")
        for path in orphans:
            print(f"  {path}")


def cmd_tint(args) -> None:
    manifest = manifest_mod.load_manifest()
    entry = manifest["assets"].get(args.asset)
    if not entry:
        raise SystemExit(f"unknown asset '{args.asset}'")
    master = REPO_ROOT / entry["master_file"]
    frames = tint_frames(read_gif_frames(master), args.color)
    color_slug = args.color.lstrip("#").lower()
    out = BUILD_DIR / f"{args.asset}_{color_slug}.gif"
    write_gif(frames, out)
    print(f"wrote {out}")
    if args.upload:
        dest = str(Path(entry["path"]).parent / "tints" / out.name)
        ledfx_io.upload_asset(out, dest, args.ledfx)
        print(f"uploaded {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="gifsmith", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledfx", default=DEFAULT_LEDFX_URL, help="LedFX base URL")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profile", help="extract a device layout profile from live LedFX")
    p.add_argument("virtual_id")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("poses", help="list poses and dance styles")
    p.add_argument("--show", help="print one pose's angles")
    p.set_defaults(func=cmd_poses)

    p = sub.add_parser("render", help="render a dance style to a GIF (+ .meta.json sidecar)")
    p.add_argument("--style", required=True)
    p.add_argument("--energy", choices=["normal", "big"], default="normal")
    p.add_argument("--color", default="#ffffff", help="master color (keep white; tint at runtime)")
    p.add_argument("--device", default="crystal-mapper")
    p.add_argument("--out")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("preview", help="mask-aware ASCII/PNG preview + coverage check")
    p.add_argument("--gif", required=True)
    p.add_argument("--device", default="crystal-mapper")
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--ascii", action="store_true")
    p.add_argument("--png")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("push", help="push a GIF to a live device for eyeballing")
    p.add_argument("--gif", required=True)
    p.add_argument("--device", default="crystal-mapper")
    p.add_argument("--fake-beat", action="store_true", help="dance without audio")
    p.add_argument("--beat-frames")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("restore", help="restore the effect that push replaced")
    p.add_argument("--device", default="crystal-mapper")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("publish", help="upload GIF(s) to LedFX assets + update manifest")
    p.add_argument("--gif", nargs="+", required=True)
    p.add_argument("--dest", default="spotfx/dancer/")
    p.add_argument("--device", default="crystal-mapper")
    p.add_argument("--style")
    p.add_argument("--energy")
    p.add_argument("--beat-frames")
    p.add_argument("--tags")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("status", help="manifest vs live LedFX asset diff")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("tint", help="pre-tint a white master (fallback for stock LedFX)")
    p.add_argument("--asset", required=True)
    p.add_argument("--color", required=True)
    p.add_argument("--upload", action="store_true")
    p.set_defaults(func=cmd_tint)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
