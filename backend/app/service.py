from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from .adapter import DeterministicImageEditAdapter, DeterministicPreview
from .api_models import PreviewInfo, RectPayload, RepairJobResponse, RepairSubmissionPayload


class ServiceError(Exception):
    status_code = 400
    code = "BAD_REQUEST"


class JobNotFound(ServiceError):
    status_code = 404
    code = "JOB_NOT_FOUND"


class JobConflict(ServiceError):
    status_code = 409
    code = "JOB_CONFLICT"


class IdempotencyConflict(ServiceError):
    status_code = 409
    code = "IDEMPOTENCY_CONFLICT"


class InvalidRepair(ServiceError):
    status_code = 422
    code = "VALIDATION_ERROR"


@dataclass(slots=True)
class _StoredJob:
    response: RepairJobResponse
    request_hash: str
    adapter_result: DeterministicPreview


class RepairService:
    """HTTP-facing coordinator for the deterministic local MVP adapter."""

    def __init__(self, adapter: DeterministicImageEditAdapter | None = None) -> None:
        self.adapter = adapter or DeterministicImageEditAdapter()
        self._jobs: OrderedDict[str, _StoredJob] = OrderedDict()
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._lock = RLock()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _hash_payload(payload: RepairSubmissionPayload) -> str:
        # by_alias keeps this stable with the browser wire contract.
        encoded = json.dumps(payload.model_dump(by_alias=True, exclude_none=True), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_geometry(payload: RepairSubmissionPayload) -> None:
        target = payload.target_rect
        context = payload.context_rect
        rw, rh = (int(part) for part in payload.target_ratio.split(":"))
        if target.w * rh != target.h * rw:
            raise InvalidRepair(f"targetRect must match ratio {payload.target_ratio}")
        if context.x > target.x or context.y > target.y or context.right < target.right or context.bottom < target.bottom:
            raise InvalidRepair("contextRect must contain targetRect")
        if payload.context_expansion_enabled:
            if payload.context_margin_px < 0:
                raise InvalidRepair("contextMarginPx must be non-negative")
        elif payload.context_margin_px != 0:
            raise InvalidRepair("contextMarginPx must be zero when context expansion is disabled")

    @staticmethod
    def _public_status(review_status: str) -> str:
        return {"pending": "review", "accepted": "accepted", "rejected": "rejected"}[review_status]

    def submit(self, payload: RepairSubmissionPayload, *, header_idempotency_key: str | None = None) -> RepairJobResponse:
        self._validate_geometry(payload)
        request_hash = self._hash_payload(payload)
        key = header_idempotency_key or payload.idempotency_key or f"request-{request_hash}"
        with self._lock:
            existing = self._idempotency.get(key)
            if existing:
                existing_job_id, existing_hash = existing
                if existing_hash != request_hash:
                    raise IdempotencyConflict("Idempotency-Key was already used for a different request")
                return self._jobs[existing_job_id].response

            job_id = f"repair-{uuid4().hex}"
            annotation_id = f"annotation-{uuid4().hex}"
            now = self._now()
            # This adapter is intentionally synchronous: the MVP returns a
            # ready preview and exposes execution/review states separately.
            result = self.adapter.edit(
                target_size=(payload.target_rect.w, payload.target_rect.h),
                context_size=(payload.context_rect.w, payload.context_rect.h),
                instruction=payload.instruction,
                job_id=job_id,
            )
            response = RepairJobResponse(
                id=job_id,
                annotationId=annotation_id,
                status="review",
                executionStatus="preview_ready",
                reviewStatus="pending",
                ratio=payload.target_ratio,
                targetRect=payload.target_rect,
                contextRect=payload.context_rect,
                createdAt=now,
                issueText=payload.issue_text,
                pageId=payload.page_id,
                baseVersionId=payload.base_version_id,
                adapter="deterministic_adapter",
                preview=PreviewInfo(
                    targetSize=result.target_size,
                    contextSize=result.context_size,
                    codexVerified=False,
                    applied=False,
                ),
                idempotencyKey=key,
            )
            self._jobs[job_id] = _StoredJob(response, request_hash, result)
            self._idempotency[key] = (job_id, request_hash)
            return response

    def list(self, *, include_rejected: bool = False) -> list[RepairJobResponse]:
        with self._lock:
            return [entry.response for entry in self._jobs.values() if include_rejected or entry.response.review_status != "rejected"]

    def get(self, job_id: str) -> RepairJobResponse:
        with self._lock:
            try:
                return self._jobs[job_id].response
            except KeyError as exc:
                raise JobNotFound(job_id) from exc

    def accept(self, job_id: str) -> RepairJobResponse:
        with self._lock:
            job = self._stored(job_id).response
            if job.review_status != "pending" or job.execution_status != "preview_ready":
                raise JobConflict("only a ready preview can be accepted")
            job.status = "accepted"
            job.review_status = "accepted"
            job.accepted_at = self._now()
            # Acceptance records review intent only. No formal image version is
            # written by this deterministic adapter.
            if job.preview:
                job.preview.applied = False
            return job

    def reject(self, job_id: str) -> RepairJobResponse:
        with self._lock:
            job = self._stored(job_id).response
            if job.review_status != "pending" or job.execution_status != "preview_ready":
                raise JobConflict("only a ready preview can be rejected")
            job.status = "rejected"
            job.review_status = "rejected"
            job.rejected_at = self._now()
            return job

    def _stored(self, job_id: str) -> _StoredJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFound(job_id) from exc
