"""Deterministic primitives for the frame repair backend."""

from .errors import BackendError, ConflictError, IdempotencyConflict, ValidationError
from .geometry import AspectRatio, Rect, Size, context_rect, validate_target_rect
from .jobs import JobManager, JobStatus
from .raster import Raster
from .versions import VersionStore

__all__ = [
    "AspectRatio", "BackendError", "ConflictError", "IdempotencyConflict",
    "JobManager", "JobStatus", "Raster", "Rect", "Size", "ValidationError",
    "VersionStore", "context_rect", "validate_target_rect",
]
