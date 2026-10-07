from __future__ import annotations

import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, TypeAlias

from .errors import ArtifactError, PersistenceConflict, ValidationError
from .geometry import Rect
from .raster import Raster, outside_pixels_equal
from .versions import ImageVersion

try:  # Pillow is a runtime dependency of the image pipeline.
    from PIL import Image, ImageOps
    from PIL.Image import Image as PillowImage
except ImportError:  # pragma: no cover - dependency-free import diagnostics
    Image = None  # type: ignore[assignment,misc]
    ImageOps = None  # type: ignore[assignment,misc]
    PillowImage = object  # type: ignore[misc,assignment]

ImageSource: TypeAlias = str | Path | bytes | bytearray | memoryview | BinaryIO | PillowImage


@dataclass(frozen=True, slots=True)
class ImageSnapshot:
    """A normalized, immutable image snapshot and its content hash."""

    raster: Raster
    content_hash: str
    source_path: Path | None = None

    def __post_init__(self) -> None:
        if self.content_hash != self.raster.sha256:
            raise ValidationError("snapshot content hash does not match raster")


@dataclass(frozen=True, slots=True)
class SavedVersion:
    """The durable PNG path for an immutable version."""

    version_id: str
    content_hash: str
    path: Path


def _require_pillow() -> None:
    if Image is None:  # pragma: no cover - only used in incomplete environments
        raise ValidationError("Pillow is required for image file processing")


def _open_source(source: ImageSource) -> tuple[PillowImage, Path | None]:
    _require_pillow()
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = Path(source)
        try:
            image = Image.open(source_path)
        except (OSError, ValueError) as exc:
            raise ValidationError(f"unable to open image: {source_path}") from exc
        return image, source_path
    if isinstance(source, (bytes, bytearray, memoryview)):
        try:
            return Image.open(io.BytesIO(bytes(source))), None
        except (OSError, ValueError) as exc:
            raise ValidationError("unable to decode image bytes") from exc
    if hasattr(source, "read"):
        try:
            return Image.open(source), None
        except (OSError, ValueError) as exc:
            raise ValidationError("unable to decode image stream") from exc
    if isinstance(source, PillowImage):
        return source, None
    raise TypeError("image source must be a path, bytes, binary stream, or Pillow image")


def raster_from_image(source: ImageSource) -> Raster:
    """Decode an image into a metadata-free RGB/RGBA raster.

    EXIF orientation is applied before pixels are read. Palette, grayscale, CMYK,
    and other Pillow modes are normalized to RGB, while images carrying alpha or
    palette transparency are normalized to RGBA.
    """

    image, _ = _open_source(source)
    original_image = image
    close_image = not isinstance(source, PillowImage)
    try:
        image.load()
        if ImageOps is not None:
            image = ImageOps.exif_transpose(image)
        has_alpha = "A" in image.getbands() or (
            image.mode == "P" and "transparency" in image.info
        )
        mode = "RGBA" if has_alpha else "RGB"
        if image.mode != mode:
            image = image.convert(mode)
        image = image.copy()
        pixels = list(image.getdata())
        rows = [
            [
                tuple(pixel)
                for pixel in pixels[y * image.width : (y + 1) * image.width]
            ]
            for y in range(image.height)
        ]
        try:
            return Raster.from_rows(rows)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValidationError("decoded image has invalid dimensions or pixels") from exc
    except (OSError, ValueError) as exc:
        raise ValidationError("unable to decode image pixels") from exc
    finally:
        if close_image:
            image.close()
            if original_image is not image:
                original_image.close()


def load_snapshot(source: ImageSource) -> ImageSnapshot:
    """Load and hash one frozen normalized image snapshot."""

    raster = raster_from_image(source)
    source_path = Path(source) if isinstance(source, (str, Path)) else None
    return ImageSnapshot(raster, raster.sha256, source_path)


def _pillow_from_raster(raster: Raster) -> PillowImage:
    _require_pillow()
    mode = "RGBA" if raster.channels == 4 else "RGB"
    image = Image.new(mode, (raster.width, raster.height))
    image.putdata(list(raster.pixels))
    return image


def raster_to_png_bytes(raster: Raster) -> bytes:
    """Encode a Raster as a deterministic metadata-free PNG byte string."""

    image = _pillow_from_raster(raster)
    try:
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False)
        return output.getvalue()
    finally:
        image.close()


def _atomic_write_bytes(data: bytes, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
    return destination


def save_png_atomic(raster: Raster, path: str | Path) -> Path:
    """Save a PNG via a same-directory temporary file and atomic replace."""

    return _atomic_write_bytes(raster_to_png_bytes(raster), path)


def snapshot_png_atomic(snapshot: ImageSnapshot, path: str | Path) -> Path:
    """Persist a frozen snapshot after rechecking its hash."""

    if snapshot.content_hash != snapshot.raster.sha256:
        raise PersistenceConflict("snapshot content hash changed before save")
    return save_png_atomic(snapshot.raster, path)


def crop_raster(raster: Raster, rect: Rect) -> Raster:
    """Crop a normalized raster, retaining immutable Raster semantics."""

    return raster.crop(rect)


def resize_raster(raster: Raster, width: int, height: int) -> Raster:
    """Resize through Pillow's high-quality Lanczos filter."""

    if width <= 0 or height <= 0:
        raise ValidationError("resize dimensions must be positive")
    image = _pillow_from_raster(raster)
    try:
        resized = image.resize((width, height), resample=Image.Resampling.LANCZOS)
        return raster_from_image(resized)
    finally:
        image.close()


def paste_raster(base: Raster, patch: Raster, target: Rect) -> Raster:
    """Paste a same-sized RGB/RGBA patch into a base raster."""

    if target.width != patch.width or target.height != patch.height:
        raise ValidationError("patch dimensions must equal target dimensions before paste")
    if base.channels != patch.channels or not target.within(base.size):
        raise ValidationError("patch mode or target bounds do not match")
    return base.paste(patch, target)


def compose_preview(
    base: Raster,
    artifact: Raster,
    *,
    context: Rect,
    target: Rect,
    resample: Literal["nearest", "lanczos"] = "lanczos",
) -> Raster:
    """Resize a generated context artifact and write only the target rectangle.

    The artifact can be larger than the frozen context but must have the same
    aspect ratio. Pixels outside ``target`` are byte-for-byte retained.
    """

    if not target.within(base.size) or not context.within(base.size):
        raise ValidationError("context and target must be inside the base raster")
    if target.x < context.x or target.y < context.y:
        raise ValidationError("target must be contained by context")
    if target.right > context.right or target.bottom > context.bottom:
        raise ValidationError("target must be contained by context")
    if resample not in ("nearest", "lanczos"):
        raise ValidationError("resample must be nearest or lanczos")
    artifact = normalize_channels(artifact, base.channels)
    if artifact.width * context.height != artifact.height * context.width:
        raise ArtifactError("generated artifact aspect ratio must match context")
    if artifact.width < context.width or artifact.height < context.height:
        raise ArtifactError("generated artifact is lower resolution than context")
    context_patch = (
        artifact.resize_nearest(context.width, context.height)
        if resample == "nearest"
        else resize_raster(artifact, context.width, context.height)
    )
    offset = Rect(target.x - context.x, target.y - context.y, target.width, target.height)
    target_patch = context_patch.crop(offset)
    preview = paste_raster(base, target_patch, target)
    if not outside_pixels_equal(base, preview, target):
        raise ValidationError("preview changed pixels outside the target rectangle")
    return preview


def validate_artifact_image(
    source: ImageSource,
    expected: Rect,
    *,
    min_resolution: bool = True,
) -> Raster:
    """Decode and validate one real CLI image artifact before compositing."""

    try:
        image = raster_from_image(source)
    except ValidationError as exc:
        raise ArtifactError("generated artifact is not a readable image") from exc
    if image.width * expected.height != image.height * expected.width:
        raise ArtifactError("generated artifact aspect ratio must match the model reference crop")
    if min_resolution and (image.width < expected.width or image.height < expected.height):
        raise ArtifactError("generated artifact is lower resolution than the model reference crop")
    if image.width <= 0 or image.height <= 0:
        raise ArtifactError("generated artifact is empty")
    return image


def atomic_save_version(
    version: ImageVersion,
    root: str | Path,
    *,
    make_current: bool = False,
) -> SavedVersion:
    """Store an immutable version PNG and optional current pointer atomically.

    Existing version files are accepted only when their decoded hash matches the
    requested immutable version. The current pointer is replaced last, so an
    interrupted write cannot point at a partial PNG.
    """

    if version.content_hash != version.raster.sha256:
        raise PersistenceConflict("version content hash does not match raster")
    root_path = Path(root)
    versions_dir = root_path / "versions"
    destination = versions_dir / f"{version.version_id}.png"
    if destination.exists():
        try:
            existing = load_snapshot(destination)
        except ValidationError as exc:
            raise PersistenceConflict(
                f"version {version.version_id} image is unreadable"
            ) from exc
        if existing.content_hash != version.content_hash:
            raise PersistenceConflict(
                f"version {version.version_id} already has different content"
            )
    else:
        save_png_atomic(version.raster, destination)
    metadata = {
        "version_id": version.version_id,
        "content_hash": version.content_hash,
        "parent_version_id": version.parent_version_id,
        "source_job_id": version.source_job_id,
    }
    metadata_path = versions_dir / f"{version.version_id}.json"
    if metadata_path.exists():
        try:
            existing_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PersistenceConflict(
                f"version {version.version_id} metadata is unreadable"
            ) from exc
        if existing_metadata != metadata:
            raise PersistenceConflict(
                f"version {version.version_id} metadata is immutable and cannot be replaced"
            )
    _atomic_write_bytes(
        (json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        metadata_path,
    )
    if make_current:
        _atomic_write_bytes(
            (version.version_id + "\n").encode(), root_path / "current.version"
        )
    return SavedVersion(version.version_id, version.content_hash, destination)

# Stable aliases used by API/worker integration code.
load_image = raster_from_image
normalize_image = raster_from_image
save_png = save_png_atomic
crop_image = crop_raster
resize_and_paste = compose_preview
save_version_atomic = atomic_save_version
save_snapshot = snapshot_png_atomic

def normalize_channels(raster: Raster, channels: int) -> Raster:
    """Convert RGB/RGBA pixels to the destination channel count."""

    if channels not in (3, 4):
        raise ValidationError("channel count must be RGB (3) or RGBA (4)")
    if raster.channels == channels:
        return raster
    if raster.channels == 3 and channels == 4:
        return Raster.from_rows(
            [[pixel + (255,) for pixel in row] for row in _raster_rows(raster)]
        )
    if raster.channels == 4 and channels == 3:
        return Raster.from_rows(
            [[pixel[:3] for pixel in row] for row in _raster_rows(raster)]
        )
    raise ValidationError("unsupported raster channel conversion")


def _raster_rows(raster: Raster) -> list[list[tuple[int, ...]]]:
    return [
        [raster.at(x, y) for x in range(raster.width)]
        for y in range(raster.height)
    ]
