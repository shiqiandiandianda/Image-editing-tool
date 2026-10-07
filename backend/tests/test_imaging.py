from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - dependency-free source check
    Image = None  # type: ignore[assignment,misc]

from frame_repair.errors import ArtifactError, PersistenceConflict
from frame_repair.geometry import Rect
from frame_repair.imaging import (
    ImageSnapshot,
    atomic_save_version,
    compose_preview,
    crop_raster,
    load_snapshot,
    normalize_channels,
    raster_from_image,
    raster_to_png_bytes,
    save_png_atomic,
    snapshot_png_atomic,
    validate_artifact_image,
)
from frame_repair.raster import Raster, outside_pixels_equal
from frame_repair.versions import ImageVersion


@unittest.skipIf(Image is None, "Pillow is required by the image pipeline")
class ImagingTests(unittest.TestCase):
    def raster(self, width: int = 8, height: int = 6) -> Raster:
        return Raster.from_rows(
            [
                [((x * 19 + y) % 256, (y * 23 + x) % 256, (x + y) % 256) for x in range(width)]
                for y in range(height)
            ]
        )

    def test_import_normalizes_jpeg_to_rgb_and_png_roundtrip(self):
        image = Image.new("L", (3, 2), 127)
        stream = io.BytesIO()
        image.save(stream, format="JPEG")
        raster = raster_from_image(stream.getvalue())
        self.assertEqual((raster.width, raster.height, raster.channels), (3, 2, 3))
        snapshot = load_snapshot(raster_to_png_bytes(raster))
        self.assertEqual(snapshot.content_hash, raster.sha256)

    def test_rgba_is_preserved_and_crop_is_frozen(self):
        raster = Raster.from_rows([[(1, 2, 3, 4), (5, 6, 7, 8)]])
        loaded = raster_from_image(raster_to_png_bytes(raster))
        self.assertEqual(loaded.channels, 4)
        self.assertEqual(crop_raster(loaded, Rect(1, 0, 1, 1)).pixels, ((5, 6, 7, 8),))

    def test_compose_resizes_artifact_and_retains_outside_pixels(self):
        base = self.raster(12, 12)
        context = Rect(2, 2, 8, 8)
        target = Rect(4, 4, 4, 4)
        artifact = Raster.solid(16, 16, (240, 1, 2))
        preview = compose_preview(base, artifact, context=context, target=target)
        self.assertTrue(outside_pixels_equal(base, preview, target))
        self.assertEqual(preview.at(target.x, target.y), (240, 1, 2))

    def test_compose_normalizes_rgb_artifact_to_rgba_base(self):
        base = Raster.solid(8, 8, (1, 2, 3, 4))
        artifact = Raster.solid(8, 8, (9, 8, 7))
        preview = compose_preview(base, artifact, context=Rect(0, 0, 8, 8), target=Rect(2, 2, 4, 4))
        self.assertEqual(preview.at(2, 2), (9, 8, 7, 255))

    def test_validate_artifact_rejects_ratio_and_resolution(self):
        expected = Rect(0, 0, 8, 4)
        with self.assertRaises(ArtifactError):
            validate_artifact_image(raster_to_png_bytes(Raster.solid(8, 8)), expected)
        with self.assertRaises(ArtifactError):
            validate_artifact_image(raster_to_png_bytes(Raster.solid(4, 2)), expected)

    def test_atomic_png_save_and_immutable_version(self):
        raster = self.raster()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            png = save_png_atomic(raster, root / "snapshots" / "base.png")
            self.assertEqual(load_snapshot(png).content_hash, raster.sha256)
            snapshot_png_atomic(
                ImageSnapshot(raster, raster.sha256), root / "snapshots" / "base-2.png"
            )
            version = ImageVersion("v1", raster, raster.sha256, "v0", "job")
            saved = atomic_save_version(version, root, make_current=True)
            self.assertTrue(saved.path.exists())
            self.assertEqual((root / "current.version").read_text(), "v1\n")
            with self.assertRaises(PersistenceConflict):
                atomic_save_version(
                    ImageVersion(
                        "v1",
                        Raster.solid(8, 6, (0, 0, 0)),
                        Raster.solid(8, 6, (0, 0, 0)).sha256,
                        "v0",
                        "other",
                    ),
                    root,
                )
            self.assertFalse(list(root.rglob("*.tmp")))

    def test_normalize_channels(self):
        rgba = normalize_channels(self.raster(), 4)
        self.assertEqual(rgba.channels, 4)
        self.assertTrue(all(pixel[3] == 255 for pixel in rgba.pixels))


if __name__ == "__main__":
    unittest.main()
