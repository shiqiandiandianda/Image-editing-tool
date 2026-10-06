from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .errors import ConflictError
from .raster import Raster


@dataclass(frozen=True, slots=True)
class ImageVersion:
    version_id: str
    raster: Raster
    content_hash: str
    parent_version_id: str | None
    source_job_id: str | None


class VersionStore:
    def __init__(self, original: Raster) -> None:
        version = ImageVersion("v0", original, original.sha256, None, None)
        self._versions: dict[str, ImageVersion] = {version.version_id: version}
        self._current_id = version.version_id

    @property
    def current(self) -> ImageVersion:
        return self._versions[self._current_id]

    def get(self, version_id: str) -> ImageVersion:
        return self._versions[version_id]

    def accept(
        self,
        raster: Raster,
        *,
        base_version_id: str,
        base_hash: str,
        job_id: str,
    ) -> ImageVersion:
        current = self.current
        if current.version_id != base_version_id or current.content_hash != base_hash:
            raise ConflictError("formal base image changed while the result was under review")
        version_id = f"v{len(self._versions)}-{uuid4().hex[:8]}"
        version = ImageVersion(version_id, raster, raster.sha256, current.version_id, job_id)
        self._versions[version_id] = version
        self._current_id = version_id
        return version
