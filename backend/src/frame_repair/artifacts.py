from __future__ import annotations

from .adapters import GeneratedArtifact
from .errors import ArtifactError
from .geometry import AspectRatio, Rect


def validate_generated_artifact(artifact: GeneratedArtifact, target: Rect, ratio: AspectRatio) -> None:
    image = artifact.raster
    numerator, denominator = ratio.parts
    if image.width * denominator != image.height * numerator:
        raise ArtifactError(f"generated artifact aspect ratio must be {ratio.value}")
    if image.channels not in (3, 4):
        raise ArtifactError("generated artifact must be RGB or RGBA")
    if image.width <= 0 or image.height <= 0:
        raise ArtifactError("generated artifact is empty")
