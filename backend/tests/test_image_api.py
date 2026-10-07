from __future__ import annotations

from io import BytesIO
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import main
from backend.app.service import RepairService


class ImageApiTests(unittest.TestCase):
    def test_upload_preview_accept_and_current_version(self) -> None:
        old_service = main.service
        with TemporaryDirectory() as root:
            main.service = RepairService(data_root=root)
            try:
                output = BytesIO()
                Image.new("RGB", (64, 64), (40, 50, 60)).save(output, "PNG")
                client = TestClient(main.app)
                upload = client.post(
                    "/api/repair/assets",
                    content=output.getvalue(),
                    headers={"content-type": "image/png", "x-filename": "page.png"},
                )
                self.assertEqual(upload.status_code, 201)
                asset = upload.json()
                payload = {
                    "pageId": asset["id"],
                    "imageId": asset["id"],
                    "baseVersionId": asset["versionId"],
                    "targetRatio": "1:1",
                    "targetRect": {"x": 16, "y": 16, "w": 16, "h": 16},
                    "contextExpansionEnabled": False,
                    "contextMarginPx": 0,
                    "contextRect": {"x": 16, "y": 16, "w": 16, "h": 16},
                    "issueText": "test issue",
                    "instruction": "preserve the image",
                    "preserveText": "line art",
                }
                job = client.post("/api/repair/jobs", json=payload)
                self.assertEqual(job.status_code, 201)
                body = job.json()
                self.assertEqual(body["executionStatus"], "preview_ready")
                self.assertFalse(body["preview"]["codexVerified"])
                self.assertEqual(client.get(body["preview"]["previewUrl"]).status_code, 200)
                accepted = client.post(f"/api/repair/jobs/{body['id']}/accept")
                self.assertEqual(accepted.status_code, 200)
                self.assertIsNotNone(accepted.json()["acceptedVersionId"])
                self.assertEqual(client.get(f"/api/repair/assets/{asset['id']}/current").status_code, 200)
            finally:
                main.service.close()
                main.service = old_service


if __name__ == "__main__":
    unittest.main()
