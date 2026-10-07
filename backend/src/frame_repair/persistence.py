"""Small SQLite repository for task and immutable-version metadata.

The image payload is encoded in the database only for the first local milestone. A
production deployment can replace `raster_json` with an immutable file path while
retaining the same version/hash and compare-and-swap fields.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from .jobs import Job
from .errors import PersistenceConflict
from .raster import Raster
from .versions import ImageVersion


def _raster_payload(raster: Raster) -> str:
    return json.dumps({"width": raster.width, "height": raster.height,
                       "channels": raster.channels, "pixels": raster.pixels}, separators=(",", ":"))


def _raster_from_payload(payload: str) -> Raster:
    value = json.loads(payload)
    return Raster(value["width"], value["height"], value["channels"],
                  tuple(tuple(pixel) for pixel in value["pixels"]))


class SQLiteStateStore:
    """Transactional storage for immutable versions and resumable job state."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self.initialize()

    def initialize(self) -> None:
        self.connection.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS image_versions (
          version_id TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          raster_json TEXT NOT NULL,
          parent_version_id TEXT REFERENCES image_versions(version_id),
          source_job_id TEXT,
          is_current INTEGER NOT NULL DEFAULT 0
            CHECK (is_current IN (0, 1))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_current_version
          ON image_versions(is_current) WHERE is_current = 1;
        CREATE TABLE IF NOT EXISTS jobs (
          job_id TEXT PRIMARY KEY,
          idempotency_key TEXT NOT NULL UNIQUE,
          request_hash TEXT NOT NULL,
          status TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          error_code TEXT,
          error_message TEXT,
          attempts INTEGER NOT NULL DEFAULT 0
        );
        """)
        self.connection.commit()

    def save_version(self, version: ImageVersion, *, current: bool = False) -> None:
        if version.content_hash != version.raster.sha256:
            raise PersistenceConflict("version content hash does not match raster")
        payload = _raster_payload(version.raster)
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT content_hash, raster_json, parent_version_id, source_job_id, is_current "
                "FROM image_versions WHERE version_id = ?",
                (version.version_id,),
            ).fetchone()
            if existing is not None:
                immutable = (
                    existing["content_hash"],
                    existing["raster_json"],
                    existing["parent_version_id"],
                    existing["source_job_id"],
                )
                expected = (
                    version.content_hash,
                    payload,
                    version.parent_version_id,
                    version.source_job_id,
                )
                if immutable != expected:
                    raise PersistenceConflict(
                        f"version {version.version_id} is immutable and cannot be replaced"
                    )
            else:
                self.connection.execute(
                    """INSERT INTO image_versions(
                        version_id, content_hash, raster_json, parent_version_id,
                        source_job_id, is_current
                    ) VALUES (?, ?, ?, ?, ?, 0)""",
                    (
                        version.version_id,
                        version.content_hash,
                        payload,
                        version.parent_version_id,
                        version.source_job_id,
                    ),
                )
            if current:
                self.connection.execute(
                    "UPDATE image_versions SET is_current = 0 WHERE is_current = 1"
                )
                self.connection.execute(
                    "UPDATE image_versions SET is_current = 1 WHERE version_id = ?",
                    (version.version_id,),
                )

    def load_version(self, version_id: str) -> ImageVersion:
        row = self.connection.execute(
            "SELECT * FROM image_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise KeyError(version_id)
        raster = _raster_from_payload(row["raster_json"])
        return ImageVersion(row["version_id"], raster, row["content_hash"],
                            row["parent_version_id"], row["source_job_id"])

    def current_version(self) -> ImageVersion:
        row = self.connection.execute(
            "SELECT version_id FROM image_versions WHERE is_current = 1"
        ).fetchone()
        if row is None:
            raise KeyError("no current image version")
        return self.load_version(row["version_id"])

    def save_job(self, job: Job) -> None:
        payload = {
            "ratio": job.ratio.value,
            "target": [job.target.x, job.target.y, job.target.width, job.target.height],
            "context": [job.context.x, job.context.y, job.context.width, job.context.height],
            "base_version_id": job.base_version_id,
            "base_hash": job.base_hash,
            "input_hash": job.input_hash,
            "instruction": job.instruction,
            "preserve": job.preserve,
            "preview": _raster_payload(job.preview) if job.preview else None,
            "accepted_version_id": job.accepted_version_id,
            "artifact_origin": job.artifact.origin if job.artifact else None,
            "provider_operation_id": (
                job.artifact.provider_operation_id if job.artifact else None
            ),
        }
        payload_json = json.dumps(payload, separators=(",", ":"))
        values = (
            job.job_id,
            job.idempotency_key,
            job.request_hash,
            job.status.value,
            payload_json,
            job.error_code,
            job.error_message,
            job.attempts,
        )
        with self._lock, self.connection:
            existing_job = self.connection.execute(
                "SELECT idempotency_key, request_hash FROM jobs WHERE job_id = ?",
                (job.job_id,),
            ).fetchone()
            existing_key = self.connection.execute(
                "SELECT job_id, request_hash FROM jobs WHERE idempotency_key = ?",
                (job.idempotency_key,),
            ).fetchone()
            if existing_job is not None and (
                existing_job["idempotency_key"] != job.idempotency_key
                or existing_job["request_hash"] != job.request_hash
            ):
                raise PersistenceConflict(
                    f"job {job.job_id} already exists with different request identity"
                )
            if existing_key is not None and (
                existing_key["job_id"] != job.job_id
                or existing_key["request_hash"] != job.request_hash
            ):
                raise PersistenceConflict(
                    f"idempotency key {job.idempotency_key} is already bound to another request"
                )
            if existing_job is None:
                self.connection.execute(
                    """INSERT INTO jobs(
                        job_id, idempotency_key, request_hash, status, payload_json,
                        error_code, error_message, attempts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
            else:
                self.connection.execute(
                    """UPDATE jobs SET status = ?, payload_json = ?, error_code = ?,
                        error_message = ?, attempts = ? WHERE job_id = ?""",
                    (
                        job.status.value,
                        payload_json,
                        job.error_code,
                        job.error_message,
                        job.attempts,
                        job.job_id,
                    ),
                )

    def get_job_record(self, job_id: str) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def close(self) -> None:
        self.connection.close()
