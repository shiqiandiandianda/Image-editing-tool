from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ImageEditAdapter(Protocol):
    def edit(self, image, instruction: str):
        """Return an edited context image with the exact input dimensions."""


@dataclass(frozen=True)
class UnconfiguredImageEditAdapter:
    def edit(self, image, instruction: str):
        raise RuntimeError(
            "no image-edit provider is configured; native Codex capability is not verified"
        )
