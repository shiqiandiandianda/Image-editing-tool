from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4
from types import SimpleNamespace

from .adapter import DeterministicImageEditAdapter
from .api_models import PreviewInfo, RepairJobResponse, RepairSubmissionPayload

from backend.src.frame_repair import (
    AspectRatio,
    ConflictError,
    CodexCliImageEditAdapter,
    DeterministicTestAdapter,
    JobManager,
    JobStatus,
    Rect,
    SQLiteStateStore,
    VersionStore,
)
from backend.src.frame_repair.imaging import (
    ImageSnapshot,
    atomic_save_version,
    load_snapshot,
    raster_to_png_bytes,
    save_png_atomic,
)


class ServiceError(Exception):
    status_code = 400
    code = "BAD_REQUEST"


class JobNotFound(ServiceError):
    status_code = 404
    code = "JOB_NOT_FOUND"


class AssetNotFound(ServiceError):
    status_code = 404
    code = "ASSET_NOT_FOUND"


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
class UploadedAsset:
    id: str
    name: str
    snapshot: ImageSnapshot
    version_id: str
    path: Path | None = None
    versions: VersionStore | None = None
    state_store: SQLiteStateStore | None = None


@dataclass(slots=True)
class _StoredJob:
    response: RepairJobResponse
    request_hash: str
    adapter_result: object
    asset_id: str | None = None
    version_store: VersionStore | None = None


class RepairService:
    """HTTP coordinator for legacy metadata requests and real image jobs.

    Requests without an uploaded image preserve the original deterministic API
    contract. Uploaded images use the frame_repair core: frozen base, one
    synchronous worker, preview composition, and compare-and-swap acceptance.
    """

    def __init__(self, adapter=None, *, data_root: str | Path | None = None) -> None:
        self.adapter = adapter or DeterministicImageEditAdapter()
        self._jobs: OrderedDict[str, _StoredJob] = OrderedDict()
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._assets: dict[str, UploadedAsset] = {}
        self._lock = RLock()
        root = Path(data_root or os.environ.get("FRAME_REPAIR_DATA_ROOT", ".frame-repair-data"))
        self.data_root = root
        self.assets_root = root / "assets"
        self.previews_root = root / "previews"
        self.versions_root = root / "versions"
        self.state_root = root / "state"
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self.previews_root.mkdir(parents=True, exist_ok=True)
        self.versions_root.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._codex_mode = os.environ.get("FRAME_REPAIR_ADAPTER", "").lower() in {"codex", "codex_cli"}
        if self._codex_mode and adapter is None:
            self.adapter = CodexCliImageEditAdapter(
                executable=os.environ.get("CODEX_EXECUTABLE", "codex"),
                work_root=root / "codex-work",
                timeout_seconds=float(os.environ.get("CODEX_TIMEOUT_SECONDS", "300")),
                keep_workdirs=os.environ.get("CODEX_KEEP_WORKDIRS", "0") == "1",
            )
        self._db = sqlite3.connect(self.data_root / "state.sqlite3", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, name TEXT NOT NULL, version_id TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, asset_id TEXT, response_json TEXT NOT NULL)")
        self._db.commit()
        self._load_state()

    def _load_state(self) -> None:
        """Reload asset identities and reviewable jobs after a process restart."""
        for row in self._db.execute("SELECT id, name, version_id, path FROM assets"):
            path = Path(row[3])
            if not path.exists():
                continue
            try:
                snapshot = load_snapshot(path)
            except Exception:
                continue
            versions = VersionStore(snapshot.raster)
            state_store = None
            version_id = row[2]
            state_path = self.state_root / f"{row[0]}.sqlite"
            if state_path.exists():
                try:
                    state_store = SQLiteStateStore(state_path)
                    current = state_store.current_version()
                    versions._versions[current.version_id] = current
                    versions._current_id = current.version_id
                    version_id = current.version_id
                except Exception:
                    state_store = None
            self._assets[row[0]] = UploadedAsset(row[0], row[1], snapshot, version_id, path, versions, state_store)
        for row in self._db.execute("SELECT id, idempotency_key, request_hash, asset_id, response_json FROM jobs ORDER BY rowid"):
            try:
                response = RepairJobResponse.model_validate_json(row[4])
            except Exception:
                continue
            version_store = None
            core = None
            asset = self._assets.get(row[3]) if row[3] else None
            if asset and response.execution_status == "preview_ready":
                preview_path = self.previews_root / f"{row[0]}.png"
                if preview_path.exists():
                    try:
                        version_store = asset.versions or VersionStore(asset.snapshot.raster)
                        core = SimpleNamespace(
                            preview=load_snapshot(preview_path).raster,
                            base_version_id=version_store.current.version_id,
                            base_hash=version_store.current.content_hash,
                        )
                    except Exception:
                        pass
            self._jobs[row[0]] = _StoredJob(response, row[2], core, row[3], version_store)
            self._idempotency[row[1]] = (row[0], row[2])

    def _persist_job(self, job_id: str, stored: _StoredJob) -> None:
        response_json = stored.response.model_dump_json(by_alias=True)
        previous = self._db.execute(
            "SELECT id FROM jobs WHERE idempotency_key = ?", (stored.response.idempotency_key,)
        ).fetchone()
        # The test/API service intentionally permits its in-memory state to be
        # reset between sessions. Remove an orphaned persisted row with the
        # same key before inserting the new in-memory job.
        if previous is not None and previous[0] != job_id:
            self._db.execute("DELETE FROM jobs WHERE id = ?", (previous[0],))
        self._db.execute(
            "INSERT INTO jobs(id, idempotency_key, request_hash, asset_id, response_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET response_json=excluded.response_json, asset_id=excluded.asset_id",
            (job_id, stored.response.idempotency_key, stored.request_hash, stored.asset_id, response_json),
        )
        self._db.commit()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _hash_payload(payload: RepairSubmissionPayload) -> str:
        encoded = json.dumps(payload.model_dump(by_alias=True, exclude_none=True), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_geometry(payload: RepairSubmissionPayload) -> None:
        target, context = payload.target_rect, payload.context_rect
        rw, rh = (int(part) for part in payload.target_ratio.split(":"))
        if target.w * rh != target.h * rw:
            raise InvalidRepair(f"targetRect must match ratio {payload.target_ratio}")
        if context.x > target.x or context.y > target.y or context.right < target.right or context.bottom < target.bottom:
            raise InvalidRepair("contextRect must contain targetRect")
        if payload.context_expansion_enabled and payload.context_margin_px < 0:
            raise InvalidRepair("contextMarginPx must be non-negative")
        if not payload.context_expansion_enabled and payload.context_margin_px != 0:
            raise InvalidRepair("contextMarginPx must be zero when context expansion is disabled")

    @staticmethod
    def _public_status(review_status: str) -> str:
        return {"pending": "review", "accepted": "accepted", "rejected": "rejected"}[review_status]

    def upload(self, data: bytes, name: str) -> dict[str, object]:
        if not data or len(data) > 50 * 1024 * 1024:
            raise InvalidRepair("image must be between 1 byte and 50 MiB")
        try:
            snapshot = load_snapshot(data)
        except Exception as exc:
            raise InvalidRepair(f"unable to decode image: {exc}") from exc
        asset_id = f"asset-{uuid4().hex}"
        version_id = f"{asset_id}-v0"
        path = self.assets_root / f"{asset_id}.png"
        save_png_atomic(snapshot.raster, path)
        versions = VersionStore(snapshot.raster)
        state_store = SQLiteStateStore(self.state_root / f"{asset_id}.sqlite")
        state_store.save_version(versions.current, current=True)
        asset = UploadedAsset(
            asset_id,
            Path(name).name or "image",
            snapshot,
            version_id,
            path,
            versions,
            state_store,
        )
        with self._lock:
            self._assets[asset_id] = asset
            self._db.execute(
                "INSERT OR REPLACE INTO assets(id, name, version_id, sha256, path) VALUES(?,?,?,?,?)",
                (asset.id, asset.name, asset.version_id, asset.snapshot.content_hash, str(path)),
            )
            self._db.commit()
        return {
            "id": asset.id,
            "name": asset.name,
            "width": snapshot.raster.width,
            "height": snapshot.raster.height,
            "sha256": snapshot.content_hash,
            "versionId": version_id,
            "src": f"/api/repair/assets/{asset.id}",
            "url": f"/api/repair/assets/{asset.id}",
        }

    # Names used by the first API draft are kept as thin aliases so clients
    # generated against either draft continue to work.
    register_image = upload

    def asset_bytes(self, asset_id: str) -> bytes:
        with self._lock:
            asset = self._assets.get(asset_id)
        if not asset or not asset.path or not asset.path.exists():
            raise AssetNotFound(asset_id)
        return asset.path.read_bytes()

    def current_asset_bytes(self, asset_id: str) -> bytes:
        with self._lock:
            asset = self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFound(asset_id)
        versions = asset.versions
        if versions is None:
            return asset.path.read_bytes() if asset.path else b""
        return raster_to_png_bytes(versions.current.raster)

    page_image = asset_bytes

    def submit(self, payload: RepairSubmissionPayload, *, header_idempotency_key: str | None = None) -> RepairJobResponse:
        self._validate_geometry(payload)
        request_hash = self._hash_payload(payload)
        key = header_idempotency_key or payload.idempotency_key or f"request-{request_hash}"
        with self._lock:
            existing = self._idempotency.get(key)
            if existing:
                job_id, existing_hash = existing
                if existing_hash != request_hash:
                    raise IdempotencyConflict("Idempotency-Key was already used for a different request")
                return self._jobs[job_id].response
            asset = self._assets.get(payload.image_id) if payload.image_id else None
            if payload.image_id and asset is None:
                raise AssetNotFound(payload.image_id)
            if asset is not None and payload.base_version_id not in {asset.version_id, "v0", "local-current"}:
                raise JobConflict("baseVersionId does not match the frozen uploaded image")
            job_id = f"repair-{uuid4().hex}"
            annotation_id = f"annotation-{uuid4().hex}"
            now = self._now()
            if asset is None:
                legacy_adapter = self.adapter if isinstance(self.adapter, DeterministicImageEditAdapter) else DeterministicImageEditAdapter()
                result = legacy_adapter.edit(target_size=(payload.target_rect.w, payload.target_rect.h), context_size=(payload.context_rect.w, payload.context_rect.h), instruction=payload.instruction, job_id=job_id)
                response = self._legacy_response(payload, key, job_id, annotation_id, now, result)
                stored = _StoredJob(response, request_hash, result)
            else:
                stored = self._run_image_job(payload, key, job_id, annotation_id, now, request_hash, asset)
            self._jobs[job_id] = stored
            self._idempotency[key] = (job_id, request_hash)
            self._persist_job(job_id, stored)
            return stored.response

    def _legacy_response(self, payload, key, job_id, annotation_id, now, result) -> RepairJobResponse:
        return RepairJobResponse(id=job_id, annotationId=annotation_id, status="review", executionStatus="preview_ready", reviewStatus="pending", ratio=payload.target_ratio, targetRect=payload.target_rect, contextRect=payload.context_rect, createdAt=now, issueText=payload.issue_text, pageId=payload.page_id, baseVersionId=payload.base_version_id, adapter="deterministic_adapter", preview=PreviewInfo(targetSize=result.target_size, contextSize=result.context_size, codexVerified=False, applied=False), idempotencyKey=key)

    def _run_image_job(self, payload, key, job_id, annotation_id, now, request_hash, asset) -> _StoredJob:
        base = asset.snapshot.raster
        versions = asset.versions or VersionStore(base)
        try:
            adapter = (
                DeterministicTestAdapter()
                if isinstance(self.adapter, DeterministicImageEditAdapter)
                else self.adapter
            )
            manager = JobManager(versions, adapter)
            target = Rect(payload.target_rect.x, payload.target_rect.y, payload.target_rect.w, payload.target_rect.h)
            context = Rect(payload.context_rect.x, payload.context_rect.y, payload.context_rect.w, payload.context_rect.h)
            current = versions.current
            base = current.raster
            if payload.base_version_id not in {current.version_id, asset.version_id, "local-current"}:
                raise JobConflict("baseVersionId does not identify the current immutable asset version")
            if not target.within(base.size) or not context.within(base.size):
                raise InvalidRepair("targetRect/contextRect is outside the frozen image")
            if context.x > target.x or context.y > target.y or context.right < target.right or context.bottom < target.bottom:
                raise InvalidRepair("contextRect must contain targetRect")
            # submit validates against the frozen base and also computes the core request hash.
            core_job = manager.submit(job_id=job_id, idempotency_key=key, ratio=AspectRatio(payload.target_ratio), target=target, context_margin=0, context_enabled=False, instruction=payload.instruction, preserve=payload.preserve_text)
            if asset.state_store is not None:
                asset.state_store.save_job(core_job)
            # The API payload contains the explicit context rectangle. Keep it as the frozen reference.
            core_job.context = context
            core_job.input_hash = base.crop(context).sha256
            finished = manager.run_next()
            if asset.state_store is not None:
                asset.state_store.save_job(core_job)
            if finished is None or finished.status != JobStatus.PREVIEW_READY or finished.preview is None:
                code = finished.error_code if finished else "WORKER_ERROR"
                message = finished.error_message if finished else "worker did not produce a result"
                response = RepairJobResponse(id=job_id, annotationId=annotation_id, status="failed", executionStatus="failed", reviewStatus="pending", ratio=payload.target_ratio, targetRect=payload.target_rect, contextRect=payload.context_rect, createdAt=now, issueText=payload.issue_text, pageId=payload.page_id, baseVersionId=payload.base_version_id, adapter="codex_cli" if self._codex_mode else "local-deterministic", preview=None, errorCode=code, errorMessage=message, idempotencyKey=key)
                return _StoredJob(response, request_hash, finished, asset.id, versions)
            preview_path = self.previews_root / f"{job_id}.png"
            save_png_atomic(finished.preview, preview_path)
            origin = finished.artifact.origin if finished.artifact else "local-deterministic"
            if origin == "mock":
                origin = "local-deterministic"
            verified = origin == "codex_cli"
            response = RepairJobResponse(id=job_id, annotationId=annotation_id, status="review", executionStatus="preview_ready", reviewStatus="pending", ratio=payload.target_ratio, targetRect=payload.target_rect, contextRect=payload.context_rect, createdAt=now, issueText=payload.issue_text, pageId=payload.page_id, baseVersionId=asset.version_id, adapter=origin, preview=PreviewInfo(targetSize=(target.width, target.height), contextSize=(context.width, context.height), codexVerified=verified, applied=False, origin=origin, provider="codex-cli" if verified else "local-deterministic", message="Codex CLI 生成结果" if verified else "本地确定性预览", previewUrl=f"/api/repair/previews/{job_id}"), idempotencyKey=key)
            return _StoredJob(response, request_hash, finished, asset.id, versions)
        except Exception as exc:
            response = RepairJobResponse(id=job_id, annotationId=annotation_id, status="failed", executionStatus="failed", reviewStatus="pending", ratio=payload.target_ratio, targetRect=payload.target_rect, contextRect=payload.context_rect, createdAt=now, issueText=payload.issue_text, pageId=payload.page_id, baseVersionId=asset.version_id, adapter="codex_cli" if self._codex_mode else "local-deterministic", preview=None, errorCode=getattr(exc, "code", "WORKER_ERROR"), errorMessage=str(exc), idempotencyKey=key)
            return _StoredJob(response, request_hash, exc, asset.id, versions)

    def preview_bytes(self, job_id: str) -> bytes:
        job = self._stored(job_id)
        path = self.previews_root / f"{job_id}.png"
        if not path.exists() or not job.response.preview or not job.response.preview.available:
            raise JobConflict("preview is not available")
        return path.read_bytes()

    preview_image = preview_bytes

    def list(self, *, include_rejected: bool = False) -> list[RepairJobResponse]:
        with self._lock:
            return [entry.response for entry in reversed(self._jobs.values()) if include_rejected or entry.response.review_status != "rejected"]

    def get(self, job_id: str) -> RepairJobResponse:
        return self._stored(job_id).response

    def accept(self, job_id: str) -> RepairJobResponse:
        with self._lock:
            stored = self._stored(job_id)
            job = stored.response
            if job.review_status != "pending" or job.execution_status != "preview_ready":
                raise JobConflict("only a ready preview can be accepted")
            if stored.version_store is not None and stored.adapter_result is not None:
                core_job = stored.adapter_result
                try:
                    version = stored.version_store.accept(core_job.preview, base_version_id=core_job.base_version_id, base_hash=core_job.base_hash, job_id=job_id)
                    atomic_save_version(version, self.versions_root / (stored.asset_id or job.page_id), make_current=True)
                    job.accepted_version_id = version.version_id
                    job.base_version_id = version.version_id
                    asset = self._assets.get(stored.asset_id or "")
                    if asset is not None:
                        asset.version_id = version.version_id
                        if asset.state_store is not None:
                            asset.state_store.save_version(version, current=True)
                            asset.state_store.save_job(core_job)
                    if job.preview:
                        job.preview.applied = True
                except ConflictError as exc:
                    job.status = "version_conflict"
                    job.execution_status = "version_conflict"
                    job.error_code = getattr(exc, "code", "VERSION_CONFLICT")
                    job.error_message = str(exc)
                    self._persist_job(job_id, stored)
                    raise JobConflict(str(exc)) from exc
                except Exception as exc:
                    job.status = "failed"
                    job.execution_status = "failed"
                    job.error_code = getattr(exc, "code", "PERSISTENCE_ERROR")
                    job.error_message = str(exc)
                    self._persist_job(job_id, stored)
                    raise JobConflict(str(exc)) from exc
            job.status = "accepted"
            job.review_status = "accepted"
            job.accepted_at = self._now()
            self._persist_job(job_id, stored)
            return job

    def reject(self, job_id: str) -> RepairJobResponse:
        with self._lock:
            job = self._stored(job_id).response
            if job.review_status != "pending" or job.execution_status != "preview_ready":
                raise JobConflict("only a ready preview can be rejected")
            job.status, job.review_status, job.rejected_at = "rejected", "rejected", self._now()
            self._persist_job(job_id, self._stored(job_id))
            return job

    def cancel(self, job_id: str) -> RepairJobResponse:
        with self._lock:
            job = self._stored(job_id).response
            if job.status in {"accepted", "rejected", "failed", "cancelled"}:
                return job
            job.status, job.execution_status = "cancelled", "cancelled"
            self._persist_job(job_id, self._stored(job_id))
            return job

    def _stored(self, job_id: str) -> _StoredJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFound(job_id) from exc

    def close(self) -> None:
        for asset in self._assets.values():
            if asset.state_store is not None:
                asset.state_store.close()
        self._db.close()
