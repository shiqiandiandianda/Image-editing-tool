from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import AdapterUnavailable
from .raster import Raster


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    raster: Raster
    origin: str
    provider_operation_id: str | None = None


class ImageEditorAdapter(Protocol):
    def edit(self, reference: Raster, instruction: str, *, job_id: str) -> GeneratedArtifact:
        ...


class UnconfiguredCodexAdapter:
    def edit(self, reference: Raster, instruction: str, *, job_id: str) -> GeneratedArtifact:
        raise AdapterUnavailable("Codex image adapter is not configured or verified")


class DeterministicTestAdapter:
    def __init__(self, transform=None) -> None:
        self.calls = 0
        self._transform = transform or (lambda raster: raster)

    def edit(self, reference: Raster, instruction: str, *, job_id: str) -> GeneratedArtifact:
        self.calls += 1
        return GeneratedArtifact(self._transform(reference), "mock", f"mock-{job_id}-{self.calls}")
