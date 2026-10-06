from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from threading import Lock

from .adapters import GeneratedArtifact, ImageEditorAdapter
from .artifacts import validate_generated_artifact
from .errors import BackendError, ConflictError, IdempotencyConflict, ValidationError
from .geometry import AspectRatio, Rect, context_rect, validate_target_rect
from .raster import Raster, outside_pixels_equal
from .versions import ImageVersion, VersionStore


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PREVIEW_READY = "preview_ready"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    CONFLICT = "version_conflict"


@dataclass(slots=True)
class Job:
    job_id: str
    idempotency_key: str
    request_hash: str
    ratio: AspectRatio
    target: Rect
    context: Rect
    base_version_id: str
    base_hash: str
    input_hash: str
    instruction: str
    preserve: str
    status: JobStatus = JobStatus.QUEUED
    artifact: GeneratedArtifact | None = None
    preview: Raster | None = None
    error_code: str | None = None
    error_message: str | None = None
    accepted_version_id: str | None = None
    attempts: int = 0


class JobManager:
    """Serial coordinator whose contracts map directly to a future SQLite worker."""

    def __init__(self, versions: VersionStore, adapter: ImageEditorAdapter, *, max_concurrency: int = 1) -> None:
        if max_concurrency != 1:
            raise ValidationError("only serial worker mode is verified in the first backend milestone")
        self.versions = versions
        self.adapter = adapter
        self.max_concurrency = max_concurrency
        self._jobs: dict[str, Job] = {}
        self._by_idempotency: dict[str, str] = {}
        self._lock = Lock()

    def submit(self, *, job_id: str, idempotency_key: str, ratio: AspectRatio, target: Rect,
               context_margin: int = 0, context_enabled: bool = False,
               instruction: str, preserve: str) -> Job:
        if not instruction.strip():
            raise ValidationError("instruction cannot be empty")
        base = self.versions.current
        validate_target_rect(target, base.raster.size, ratio)
        context = context_rect(target, base.raster.size, context_margin, context_enabled)
        request = {
            "ratio": ratio.value,
            "target": [target.x, target.y, target.width, target.height],
            "context": [context.x, context.y, context.width, context.height],
            "base_version_id": base.version_id,
            "base_hash": base.content_hash,
            "instruction": instruction,
            "preserve": preserve,
        }
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self._lock:
            existing_id = self._by_idempotency.get(idempotency_key)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing.request_hash != request_hash:
                    raise IdempotencyConflict("idempotency key was already used for a different request")
                return existing
            job = Job(job_id, idempotency_key, request_hash, ratio, target, context,
                      base.version_id, base.content_hash, base.raster.crop(context).sha256,
                      instruction, preserve)
            self._jobs[job_id] = job
            self._by_idempotency[idempotency_key] = job_id
            return job

    def get(self, job_id: str) -> Job:
        return self._jobs[job_id]

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
        elif job.status in (JobStatus.PREVIEW_READY, JobStatus.REJECTED, JobStatus.ACCEPTED, JobStatus.CANCELLED):
            return job
        else:
            raise BackendError("running cancellation requires an adapter-specific operation")
        return job

    def run_next(self) -> Job | None:
        with self._lock:
            queued = next((job for job in self._jobs.values() if job.status == JobStatus.QUEUED), None)
            if queued is None:
                return None
            queued.status = JobStatus.RUNNING
            queued.attempts += 1
        try:
            base = self.versions.get(queued.base_version_id)
            reference = base.raster.crop(queued.context)
            artifact = self.adapter.edit(reference, queued.instruction, job_id=queued.job_id)
            validate_generated_artifact(artifact, queued.target, queued.ratio)
            patch = artifact.raster.resize_nearest(queued.target.width, queued.target.height)
            preview = base.raster.paste(patch, queued.target)
            if not outside_pixels_equal(base.raster, preview, queued.target):
                raise ValidationError("preview changed pixels outside the target rectangle")
            queued.artifact = artifact
            queued.preview = preview
            queued.status = JobStatus.PREVIEW_READY
        except BackendError as exc:
            queued.status = JobStatus.FAILED
            queued.error_code, queued.error_message = exc.code, str(exc)
        except Exception as exc:
            queued.status = JobStatus.FAILED
            queued.error_code, queued.error_message = "UNEXPECTED_ERROR", str(exc)
        return queued

    def reject(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != JobStatus.PREVIEW_READY:
            raise ValidationError("only a preview can be rejected")
        job.status = JobStatus.REJECTED
        return job

    def accept(self, job_id: str) -> ImageVersion:
        job = self.get(job_id)
        if job.status != JobStatus.PREVIEW_READY or job.preview is None:
            raise ValidationError("only a ready preview can be accepted")
        try:
            version = self.versions.accept(job.preview, base_version_id=job.base_version_id,
                                           base_hash=job.base_hash, job_id=job.job_id)
        except ConflictError as exc:
            job.status = JobStatus.CONFLICT
            job.error_code, job.error_message = exc.code, str(exc)
            raise
        job.accepted_version_id = version.version_id
        job.status = JobStatus.ACCEPTED
        return version
