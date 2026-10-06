from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


class ImageEditAdapter(Protocol):
    def edit(self, image: Image.Image, instruction: str) -> Image.Image:
        """Return an edited image with the exact input dimensions."""


@dataclass(frozen=True)
class UnconfiguredImageEditAdapter:
    def edit(self, image: Image.Image, instruction: str) -> Image.Image:
        raise RuntimeError(
            "no image-edit provider is configured; native Codex capability is not verified"
        )
