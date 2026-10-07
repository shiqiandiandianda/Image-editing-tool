from __future__ import annotations

import base64
import binascii
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from .errors import (
    AdapterUnavailable,
    CodexCliArtifactAmbiguous,
    CodexCliArtifactInvalid,
    CodexCliArtifactMissing,
    CodexCliFailed,
    CodexCliNotFound,
    CodexCliTimeout,
    CodexCliUnreachable,
)
from .raster import Raster


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    raster: Raster
    origin: str
    provider_operation_id: str | None = None


class ImageEditorAdapter(Protocol):
    def edit(
        self, reference: Raster, instruction: str, *, job_id: str
    ) -> GeneratedArtifact:
        ...


class UnconfiguredCodexAdapter:
    def edit(
        self, reference: Raster, instruction: str, *, job_id: str
    ) -> GeneratedArtifact:
        raise AdapterUnavailable("Codex image adapter is not configured or verified")


class DeterministicTestAdapter:
    def __init__(self, transform=None) -> None:
        self.calls = 0
        self._transform = transform or (lambda raster: raster)

    def edit(
        self, reference: Raster, instruction: str, *, job_id: str
    ) -> GeneratedArtifact:
        self.calls += 1
        return GeneratedArtifact(
            self._transform(reference), "mock", f"mock-{job_id}-{self.calls}"
        )


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_PATH_KEYS = ("artifact_path", "output_path", "image_path", "file_path", "saved_path")
_DATA_KEYS = ("image_base64", "image_data", "base64", "data", "result")
_OPERATION_KEYS = (
    "id",
    "provider_operation_id",
    "operation_id",
    "operationId",
    "call_id",
    "callId",
)
_SAFE_JOB_ID = re.compile(r"[^A-Za-z0-9_.-]+")


class CodexCliImageEditAdapter:
    """Run ``codex exec`` in an isolated directory and return one image artifact.

    The JSONL event stream must explicitly declare an image path or image bytes.
    Unreferenced files are ignored; in particular this adapter never chooses the
    newest PNG in a directory.
    """

    def __init__(
        self,
        executable: str = "codex",
        *,
        work_root: str | Path | None = None,
        timeout_seconds: float = 300.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        keep_workdirs: bool = False,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.executable = executable
        self.work_root = Path(work_root) if work_root is not None else None
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run
        self.keep_workdirs = keep_workdirs

    def edit(
        self, reference: Raster, instruction: str, *, job_id: str
    ) -> GeneratedArtifact:
        if not instruction.strip():
            raise ValueError("instruction cannot be empty")
        workdir = self._create_workdir(job_id)
        try:
            input_path = workdir / "input.png"
            last_message_path = workdir / "last-message.txt"
            self._write_png(reference, input_path)
            command = self._command(input_path, last_message_path, workdir, instruction)
            try:
                completed = self.runner(
                    command,
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise CodexCliNotFound(
                    f"Codex CLI executable was not found: {self.executable}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise CodexCliTimeout(
                    f"Codex CLI timed out after {self.timeout_seconds:g} seconds"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                if len(detail) > 1000:
                    detail = detail[-1000:]
                suffix = f": {detail}" if detail else ""
                if any(
                    marker in detail.lower()
                    for marker in ("tls", "certificate", "unknownissuer", "websocket")
                ):
                    raise CodexCliUnreachable(
                        f"Codex service was unreachable{suffix}"
                    )
                raise CodexCliFailed(
                    f"Codex CLI exited with status {completed.returncode}{suffix}"
                )
            events = self._parse_events(completed.stdout)
            artifact_path, artifact_bytes = self._find_artifact(
                events, workdir, input_path
            )
            if artifact_bytes is not None:
                artifact_path = workdir / "event-artifact.png"
                artifact_path.write_bytes(artifact_bytes)
            if artifact_path is None:
                raise CodexCliArtifactMissing(
                    "Codex CLI completed without an event-declared image artifact"
                )
            raster = self._read_raster(artifact_path)
            operation_id = self._find_operation_id(events)
            return GeneratedArtifact(raster, "codex_cli", operation_id)
        finally:
            if not self.keep_workdirs:
                shutil.rmtree(workdir, ignore_errors=True)

    def _create_workdir(self, job_id: str) -> Path:
        parent = self.work_root
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        safe_id = _SAFE_JOB_ID.sub("-", job_id).strip(".-") or "job"
        return Path(
            tempfile.mkdtemp(prefix=f"{safe_id}-", dir=str(parent) if parent else None)
        )

    def _command(
        self, input_path: Path, last_message_path: Path, workdir: Path, instruction: str
    ) -> list[str]:
        prompt = (
            "Edit the attached image according to this instruction. Preserve every "
            "area outside the requested repair and produce exactly one image result. "
            "Use the built-in image generation/editing capability. The JSONL event "
            "stream must contain the generated image result (or an explicitly "
            f"declared artifact path). Instruction: {instruction}"
        )
        return [
            self.executable,
            "exec",
            "--json",
            "--image",
            str(input_path),
            "--output-last-message",
            str(last_message_path),
            "--skip-git-repo-check",
            "--ephemeral",
            "-C",
            str(workdir),
            prompt,
        ]

    @staticmethod
    def _write_png(raster: Raster, path: Path) -> None:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - dependency is project declared
            raise CodexCliFailed(
                "Pillow is required for the Codex CLI adapter"
            ) from exc
        mode = "RGBA" if raster.channels == 4 else "RGB"
        image = Image.new(mode, (raster.width, raster.height))
        image.putdata(list(raster.pixels))
        image.save(path, format="PNG")

    @staticmethod
    def _read_raster(path: Path) -> Raster:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - dependency is project declared
            raise CodexCliFailed(
                "Pillow is required for the Codex CLI adapter"
            ) from exc
        try:
            with Image.open(path) as source:
                source.load()
                if source.mode not in ("RGB", "RGBA"):
                    source = source.convert(
                        "RGBA" if "A" in source.getbands() else "RGB"
                    )
                if hasattr(source, "get_flattened_data"):
                    pixels = list(source.get_flattened_data())
                else:  # Pillow < 12 compatibility
                    pixels = list(source.getdata())
                rows = [
                    [
                        tuple(pixel)
                        for pixel in pixels[y * source.width : (y + 1) * source.width]
                    ]
                    for y in range(source.height)
                ]
                return Raster.from_rows(rows)
        except (OSError, ValueError) as exc:
            raise CodexCliArtifactMissing(
                f"Codex artifact is not a readable image: {path}"
            ) from exc

    @staticmethod
    def _parse_events(stdout: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Some CLI versions print a human-readable warning around JSONL.
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    @classmethod
    def _find_artifact(
        cls, events: Sequence[dict[str, Any]], workdir: Path, input_path: Path
    ) -> tuple[Path | None, bytes | None]:
        paths: list[Path] = []
        byte_results: list[bytes] = []
        invalid = False
        for event in events:
            for key, value in cls._walk_values(event):
                if key in _PATH_KEYS and isinstance(value, str):
                    candidate = cls._safe_path(value, workdir)
                    if (
                        candidate is None
                        or candidate == input_path.resolve()
                        or not candidate.is_file()
                    ):
                        invalid = True
                    elif candidate not in paths:
                        paths.append(candidate)
                if key in _DATA_KEYS and isinstance(value, str):
                    decoded = cls._decode_image_data(value)
                    if decoded is not None:
                        if decoded not in byte_results:
                            byte_results.append(decoded)
        if invalid:
            raise CodexCliArtifactInvalid(
                "Codex CLI declared an artifact outside the task workspace, "
                "the input image, or a missing path"
            )
        if len(paths) + len(byte_results) > 1:
            raise CodexCliArtifactAmbiguous(
                "Codex CLI declared more than one image artifact"
            )
        if paths:
            return paths[0], None
        if byte_results:
            return None, byte_results[0]
        return None, None

    @staticmethod
    def _walk_values(value: Any, parent_key: str = ""):
        if isinstance(value, dict):
            for key, nested in value.items():
                if isinstance(key, str):
                    yield key, nested
                yield from CodexCliImageEditAdapter._walk_values(nested, str(key))
        elif isinstance(value, list):
            for nested in value:
                yield from CodexCliImageEditAdapter._walk_values(nested, parent_key)

    @staticmethod
    def _safe_path(raw: str, workdir: Path) -> Path | None:
        if not raw or raw.startswith(("data:", "http://", "https://")):
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = workdir / candidate
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(workdir.resolve())
        except (OSError, ValueError):
            return None
        if resolved.suffix.lower() not in _IMAGE_SUFFIXES:
            return None
        return resolved

    @staticmethod
    def _decode_image_data(raw: str) -> bytes | None:
        if raw.startswith("data:"):
            try:
                header, encoded = raw.split(",", 1)
            except ValueError:
                return None
            if ";base64" not in header.lower() or not header.lower().startswith(
                "data:image/"
            ):
                return None
        else:
            encoded = raw
        if len(encoded) < 32:
            return None
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            return decoded
        if decoded.startswith((b"\xff\xd8\xff", b"GIF8", b"RIFF")):
            return decoded
        return None

    @staticmethod
    def _find_operation_id(events: Sequence[dict[str, Any]]) -> str | None:
        # Prefer the operation attached to the selected image event. A stream
        # can contain unrelated tool calls before the image result.
        for event in events:
            pairs = list(CodexCliImageEditAdapter._walk_values(event))
            has_image = any(
                key in _DATA_KEYS
                and isinstance(value, str)
                and CodexCliImageEditAdapter._decode_image_data(value) is not None
                for key, value in pairs
            ) or any(key in _PATH_KEYS for key, _ in pairs)
            if not has_image:
                continue
            for key, value in pairs:
                if key in _OPERATION_KEYS and isinstance(value, (str, int)):
                    return str(value)
        for event in events:
            for key, value in CodexCliImageEditAdapter._walk_values(event):
                if key in _OPERATION_KEYS and isinstance(value, (str, int)):
                    return str(value)
        return None
