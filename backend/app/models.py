from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AspectRatio(StrEnum):
    SQUARE = "1:1"
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"

    @property
    def value_pair(self) -> tuple[int, int]:
        left, right = self.value.split(":")
        return int(left), int(right)


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class Rect(BaseModel):
    x: NonNegativeInt
    y: NonNegativeInt
    width: PositiveInt
    height: PositiveInt

    def right(self) -> int:
        return self.x + self.width

    def bottom(self) -> int:
        return self.y + self.height

    def aspect_matches(self, ratio: AspectRatio) -> bool:
        rw, rh = ratio.value_pair
        return self.width * rh == self.height * rw

    def expand(self, pixels: int, image_width: int, image_height: int) -> Rect:
        if pixels < 0:
            raise ValueError("expansion must be non-negative")
        left = max(0, self.x - pixels)
        top = max(0, self.y - pixels)
        right = min(image_width, self.right() + pixels)
        bottom = min(image_height, self.bottom() + pixels)
        return Rect(x=left, y=top, width=right - left, height=bottom - top)


class BaseImage(BaseModel):
    image_id: UUID = Field(default_factory=uuid4)
    width: PositiveInt
    height: PositiveInt
    sha256: str = Field(min_length=64, max_length=64)
    version: int = Field(default=1, ge=1)


class RepairJob(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    base_image_id: UUID
    base_sha256: str = Field(min_length=64, max_length=64)
    target_rect: Rect
    context_rect: Rect
    ratio: AspectRatio
    expand_context: bool = False
    instruction: str = Field(min_length=1, max_length=4000)
    status: str = "preview"
