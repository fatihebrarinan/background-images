"""Checks downloaded images and turns them into wallpapers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MIN_WIDTH = 1920
MIN_HEIGHT = 1000
MIN_ASPECT = 1.25
MAX_ASPECT = 2.6
MAX_EDGE = 3840
JPEG_QUALITY = 90
DUPLICATE_DISTANCE = 5

# Space imagery is legitimately huge; Pillow's default limit would refuse it.
Image.MAX_IMAGE_PIXELS = 500_000_000


class Rejected(Exception):
    """The file cannot be used as a wallpaper."""


@dataclass(frozen=True)
class Wallpaper:
    size: int
    dhash: str


def fits_screen(width: int, height: int) -> bool:
    """Tell whether an image of this size makes a good landscape wallpaper."""
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return False
    return MIN_ASPECT <= width / height <= MAX_ASPECT


def prepare(source: Path, destination: Path) -> Wallpaper:
    """Validate `source` and write a size-limited JPEG to `destination`."""
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise Rejected(f"unreadable image: {error}") from error

    if not fits_screen(*image.size):
        raise Rejected(f"unsuitable size {image.width}x{image.height}")

    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    image.save(destination, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return Wallpaper(destination.stat().st_size, difference_hash(image))


def difference_hash(image: Image.Image) -> str:
    """A 64-bit fingerprint that survives resizing and recompression."""
    small = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = small.tobytes()
    bits = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            bits = bits << 1 | (left > right)
    return f"{bits:016x}"


def is_duplicate(dhash: str, known: list[str]) -> bool:
    value = int(dhash, 16)
    return any((value ^ int(other, 16)).bit_count() <= DUPLICATE_DISTANCE for other in known)
