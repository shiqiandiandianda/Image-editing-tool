from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeterministicPreview:
    """A safe local adapter result: metadata only, never a Codex claim."""

    target_size: tuple[int, int]
    context_size: tuple[int, int]
    origin: str = "deterministic_adapter"
    provider: str = "local-deterministic"
    codex_verified: bool = False


@dataclass(slots=True)
class DeterministicImageEditAdapter:
    """Deterministic adapter used for local/API tests.

    It deliberately does not call a model or mutate image files. The result
    only proves the request/preview/review protocol and geometry path.
    """

    calls: int = 0

    def edit(self, *, target_size: tuple[int, int], context_size: tuple[int, int], instruction: str, job_id: str) -> DeterministicPreview:
        if not instruction.strip():
            raise ValueError("instruction cannot be empty")
        self.calls += 1
        return DeterministicPreview(target_size=target_size, context_size=context_size)
