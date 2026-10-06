from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import ValidationError


@dataclass(frozen=True, slots=True)
class Size:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValidationError("image dimensions must be positive")


@dataclass(frozen=True, slots=True)
class Rect:
    """Integer, left-closed/right-open image coordinates."""
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if min(self.x, self.y, self.width, self.height) < 0:
            raise ValidationError("rectangle coordinates and dimensions must be non-negative")
        if self.width == 0 or self.height == 0:
            raise ValidationError("rectangle dimensions must be positive")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def within(self, size: Size) -> bool:
        return self.right <= size.width and self.bottom <= size.height


class AspectRatio(str, Enum):
    SQUARE = "1:1"
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"

    @property
    def parts(self) -> tuple[int, int]:
        left, right = self.value.split(":")
        return int(left), int(right)


def validate_target_rect(rect: Rect, image_size: Size, ratio: AspectRatio) -> Rect:
    if not rect.within(image_size):
        raise ValidationError("target rectangle is outside the frozen image")
    numerator, denominator = ratio.parts
    if rect.width * denominator != rect.height * numerator:
        raise ValidationError(f"target rectangle must have aspect ratio {ratio.value}")
    return rect


def context_rect(target: Rect, image_size: Size, margin: int, enabled: bool) -> Rect:
    if margin < 0:
        raise ValidationError("context margin must be non-negative")
    if not enabled or margin == 0:
        return target
    x = max(0, target.x - margin)
    y = max(0, target.y - margin)
    right = min(image_size.width, target.right + margin)
    bottom = min(image_size.height, target.bottom + margin)
    return Rect(x, y, right - x, bottom - y)
