"""Mask-aware previews: see a GIF exactly as the physical matrix will show it.

The hex crystal panel only lights ~37% of its 37x72 grid cells; a stroke that
looks fine in the raw GIF can vanish on the lattice. These previews sample
only mask-true cells so problems show up headlessly (ASCII for a quick look,
PNG contact sheet for an agent to Read).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .device_profiles import profile_mask
from .gifio import read_gif_frames

LIT_THRESHOLD = 32  # 0-255 luminance below this renders as dark


def _fit_frame(frame: Image.Image, cols: int, rows: int) -> Image.Image:
    if frame.size != (cols, rows):
        frame = frame.resize((cols, rows), Image.LANCZOS)
    return frame


def ascii_preview(gif_path: str | Path, profile: dict, frame_index: int = 0) -> str:
    """One frame through the device mask: '#' lit, '.' real-but-dark,
    ' ' gap cell."""
    frames = read_gif_frames(gif_path)
    frame = _fit_frame(frames[frame_index % len(frames)], profile["cols"], profile["rows"])
    gray = frame.convert("L")
    mask = profile_mask(profile)
    lines = []
    for row_index, row in enumerate(mask):
        chars = []
        for col_index, real in enumerate(row):
            if not real:
                chars.append(" ")
            elif gray.getpixel((col_index, row_index)) >= LIT_THRESHOLD:
                chars.append("#")
            else:
                chars.append(".")
        lines.append("".join(chars))
    header = f"frame {frame_index % len(frames)}/{len(frames)} of {Path(gif_path).name}"
    return header + "\n" + "\n".join(lines)


def contact_sheet(
    gif_path: str | Path,
    profile: dict,
    out_png: str | Path,
    cell_scale: int = 6,
    per_row: int = 6,
) -> Path:
    """All frames rendered through the mask: lit cells as colored dots on a
    dark grid, gap cells absent. Read the PNG to inspect every frame."""
    frames = read_gif_frames(gif_path)
    cols, rows = profile["cols"], profile["rows"]
    mask = profile_mask(profile)

    tile_w, tile_h = cols * cell_scale, rows * cell_scale
    pad = cell_scale * 2
    sheet_cols = min(per_row, len(frames))
    sheet_rows = (len(frames) + per_row - 1) // per_row
    sheet = Image.new(
        "RGB",
        (sheet_cols * (tile_w + pad) + pad, sheet_rows * (tile_h + pad) + pad),
        (18, 18, 22),
    )
    draw = ImageDraw.Draw(sheet)

    for index, frame in enumerate(frames):
        frame = _fit_frame(frame, cols, rows)
        origin_x = pad + (index % per_row) * (tile_w + pad)
        origin_y = pad + (index // per_row) * (tile_h + pad)
        draw.rectangle(
            [origin_x, origin_y, origin_x + tile_w, origin_y + tile_h],
            fill=(8, 8, 10),
        )
        for row_index, row in enumerate(mask):
            for col_index, real in enumerate(row):
                if not real:
                    continue
                r, g, b = frame.getpixel((col_index, row_index))[:3]
                if max(r, g, b) < LIT_THRESHOLD:
                    color = (35, 35, 40)  # real-but-dark cell
                else:
                    color = (r, g, b)
                cx = origin_x + col_index * cell_scale + cell_scale // 2
                cy = origin_y + row_index * cell_scale + cell_scale // 2
                radius = max(1, cell_scale // 2 - 1)
                draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
        draw.text((origin_x + 2, origin_y + tile_h - 12), str(index), fill=(140, 140, 150))

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def coverage_report(gif_path: str | Path, profile: dict) -> dict:
    """Per-frame count of lit real cells — catches frames where the figure
    thins out to nothing on the lattice."""
    frames = read_gif_frames(gif_path)
    mask = profile_mask(profile)
    lit_counts = []
    for frame in frames:
        frame = _fit_frame(frame, profile["cols"], profile["rows"])
        gray = frame.convert("L")
        lit = sum(
            1
            for row_index, row in enumerate(mask)
            for col_index, real in enumerate(row)
            if real and gray.getpixel((col_index, row_index)) >= LIT_THRESHOLD
        )
        lit_counts.append(lit)
    return {
        "frames": len(frames),
        "lit_min": min(lit_counts),
        "lit_max": max(lit_counts),
        "lit_per_frame": lit_counts,
    }
