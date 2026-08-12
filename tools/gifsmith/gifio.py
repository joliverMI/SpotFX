"""GIF read/write helpers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageSequence


def write_gif(frames: list[Image.Image], path: str | Path, duration_ms: int = 80) -> Path:
    """Write frames as a looping GIF. Frame duration only matters to
    gifplayer/browser previews — keybeat2d is beat-driven."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Quantize every frame against ONE shared palette — per-frame ADAPTIVE
    # palettes can disagree and invert colors on playback.
    strip = Image.new("RGB", (frames[0].width, frames[0].height * len(frames)))
    for i, frame in enumerate(frames):
        strip.paste(frame, (0, i * frames[0].height))
    shared_palette = strip.convert("P", palette=Image.ADAPTIVE, colors=256)
    palettized = [
        f.quantize(palette=shared_palette, dither=Image.Dither.NONE) for f in frames
    ]
    palettized[0].save(
        path,
        save_all=True,
        append_images=palettized[1:],
        duration=duration_ms,
        loop=0,
        # No disposal: frames are full and opaque, and Pillow's disposal=2
        # background-restore corrupts read-back with a shared palette.
        optimize=True,
    )
    return path


def read_gif_frames(path: str | Path) -> list[Image.Image]:
    with Image.open(path) as img:
        return [frame.convert("RGB").copy() for frame in ImageSequence.Iterator(img)]


def tint_frames(frames: list[Image.Image], hex_color: str) -> list[Image.Image]:
    """Multiply white-master frames by a solid color (portable pre-tint
    fallback for stock LedFX installs without the keybeat2d tint patch)."""
    color = hex_color.lstrip("#")
    r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
    return [
        Image.merge(
            "RGB",
            [
                channel.point(lambda v, s=scale: round(v * s / 255))
                for channel, scale in zip(frame.split(), (r, g, b))
            ],
        )
        for frame in frames
    ]
