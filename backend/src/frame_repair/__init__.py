"""Deterministic primitives for the frame repair backend."""

from .adapters import CodexCliImageEditAdapter, DeterministicTestAdapter, GeneratedArtifact
from .errors import (
    BackendError,
    CodexCliArtifactAmbiguous,
    CodexCliArtifactInvalid,
    CodexCliArtifactMissing,
    CodexCliError,
    CodexCliFailed,
    CodexCliNotFound,
    CodexCliTimeout,
    CodexCliUnreachable,
    ConflictError,
    IdempotencyConflict,
    PersistenceConflict,
    ValidationError,
)
from .geometry import AspectRatio, Rect, Size, context_rect, validate_target_rect
from .jobs import JobManager, JobStatus
from .persistence import SQLiteStateStore
from .raster import Raster
from .versions import VersionStore

__all__ = [
    "AspectRatio", "BackendError", "ConflictError", "IdempotencyConflict", "PersistenceConflict",
    "CodexCliArtifactAmbiguous", "CodexCliArtifactInvalid", "CodexCliArtifactMissing",
    "CodexCliError", "CodexCliFailed", "CodexCliImageEditAdapter",
    "CodexCliNotFound", "CodexCliTimeout", "GeneratedArtifact",
    "CodexCliUnreachable",
    "DeterministicTestAdapter", "JobManager", "JobStatus", "Raster", "Rect", "Size", "SQLiteStateStore", "ValidationError",
    "VersionStore", "context_rect", "validate_target_rect", "ImageSnapshot", "SavedVersion",
    "atomic_save_version", "compose_preview", "crop_image", "crop_raster", "load_image",
    "load_snapshot", "normalize_channels", "normalize_image", "paste_raster",
    "raster_from_image", "raster_to_png_bytes", "resize_and_paste", "resize_raster",
    "save_png", "save_png_atomic", "save_snapshot", "save_version_atomic",
    "snapshot_png_atomic", "validate_artifact_image",
]
from .imaging import (
    ImageSnapshot,
    SavedVersion,
    atomic_save_version,
    compose_preview,
    crop_image,
    crop_raster,
    load_image,
    load_snapshot,
    normalize_channels,
    normalize_image,
    paste_raster,
    raster_from_image,
    raster_to_png_bytes,
    resize_and_paste,
    resize_raster,
    save_png,
    save_png_atomic,
    save_snapshot,
    save_version_atomic,
    snapshot_png_atomic,
    validate_artifact_image,
)
