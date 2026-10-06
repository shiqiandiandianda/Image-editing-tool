from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .errors import ValidationError
from .geometry import Rect, Size

Pixel = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Raster:
    """Small deterministic in-memory raster used by the core and tests."""
    width: int
    height: int
    channels: int
    _pixels: tuple[Pixel, ...]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.channels not in (3, 4):
            raise ValidationError("unsupported raster dimensions or channel count")
        if len(self._pixels) != self.width * self.height:
            raise ValidationError("pixel count does not match raster dimensions")
        for pixel in self._pixels:
            if len(pixel) != self.channels or any(not 0 <= value <= 255 for value in pixel):
                raise ValidationError("pixels must be 8-bit RGB or RGBA tuples")

    @classmethod
    def solid(cls, width: int, height: int, color: Pixel = (0, 0, 0)) -> Raster:
        return cls(width, height, len(color), tuple(color for _ in range(width * height)))

    @classmethod
    def from_rows(cls, rows: list[list[Pixel]]) -> Raster:
        if not rows or not rows[0]:
            raise ValidationError("raster rows cannot be empty")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValidationError("raster rows must have equal width")
        channels = len(rows[0][0])
        return cls(width, len(rows), channels, tuple(pixel for row in rows for pixel in row))

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)

    @property
    def pixels(self) -> tuple[Pixel, ...]:
        return self._pixels

    @property
    def sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(struct.pack(">III", self.width, self.height, self.channels))
        digest.update(bytes(value for pixel in self._pixels for value in pixel))
        return digest.hexdigest()

    def at(self, x: int, y: int) -> Pixel:
        return self._pixels[y * self.width + x]

    def crop(self, rect: Rect) -> Raster:
        if not rect.within(self.size):
            raise ValidationError("crop rectangle is outside raster")
        rows = [
            [self.at(x, y) for x in range(rect.x, rect.right)]
            for y in range(rect.y, rect.bottom)
        ]
        return Raster.from_rows(rows)

    def resize_nearest(self, width: int, height: int) -> Raster:
        if width <= 0 or height <= 0:
            raise ValidationError("resize dimensions must be positive")
        rows = []
        for y in range(height):
            source_y = min(self.height - 1, y * self.height // height)
            rows.append([
                self.at(min(self.width - 1, x * self.width // width), source_y)
                for x in range(width)
            ])
        return Raster.from_rows(rows)

    def paste(self, patch: Raster, target: Rect) -> Raster:
        if target.width != patch.width or target.height != patch.height:
            raise ValidationError("patch dimensions must equal target dimensions before paste")
        if self.channels != patch.channels or not target.within(self.size):
            raise ValidationError("patch mode or target bounds do not match")
        rows = [
            list(self._pixels[y * self.width : (y + 1) * self.width])
            for y in range(self.height)
        ]
        for py in range(patch.height):
            for px in range(patch.width):
                rows[target.y + py][target.x + px] = patch.at(px, py)
        return Raster.from_rows(rows)


def outside_pixels_equal(before: Raster, after: Raster, target: Rect) -> bool:
    if (
        before.width != after.width
        or before.height != after.height
        or before.channels != after.channels
    ):
        return False
    for y in range(before.height):
        for x in range(before.width):
            if target.x <= x < target.right and target.y <= y < target.bottom:
                continue
            if before.at(x, y) != after.at(x, y):
                return False
    return True
