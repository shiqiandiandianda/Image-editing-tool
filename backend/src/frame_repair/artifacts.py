from __future__ import annotations

from .adapters import GeneratedArtifact
from .errors import ArtifactError
from .geometry import Rect


def validate_generated_artifact(artifact: GeneratedArtifact, expected: Rect) -> None:
    image = artifact.raster
    if image.width * expected.height != image.height * expected.width:
        raise ArtifactError("generated artifact aspect ratio must match the model reference crop")
    if image.width < expected.width or image.height < expected.height:
        raise ArtifactError("generated artifact is lower resolution than the model reference crop")
    if image.channels not in (3, 4):
        raise ArtifactError("generated artifact must be RGB or RGBA")
    if image.width <= 0 or image.height <= 0:
        raise ArtifactError("generated artifact is empty")
