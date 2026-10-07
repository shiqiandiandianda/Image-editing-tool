from __future__ import annotations

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.main import app, service


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        # The app-level service is intentionally in-memory for this local MVP.
        service._jobs.clear()
        service._idempotency.clear()
        service.adapter.calls = 0
        self.client = TestClient(app)

    @staticmethod
    def payload(**overrides):
        value = {
            "pageId": "sample-page",
            "baseVersionId": "local-current",
            "targetRatio": "1:1",
            "targetRect": {"x": 20, "y": 30, "w": 40, "h": 40},
            "contextExpansionEnabled": True,
            "contextMarginPx": 8,
            "contextRect": {"x": 12, "y": 22, "w": 56, "h": 56},
            "issueText": "bad hand",
            "instruction": "repair the hand shape",
            "preserveText": "keep line art",
        }
        value.update(overrides)
        return value

    def test_submit_exposes_preview_and_review_states(self):
        response = self.client.post("/api/repair/jobs", json=self.payload())
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["status"], "review")
        self.assertEqual(body["executionStatus"], "preview_ready")
        self.assertEqual(body["reviewStatus"], "pending")
        self.assertEqual(body["preview"]["origin"], "deterministic_adapter")
        self.assertFalse(body["preview"]["codexVerified"])
        self.assertEqual(service.adapter.calls, 1)

    def test_accept_is_review_only_and_does_not_claim_codex(self):
        job = self.client.post("/api/repair/jobs", json=self.payload()).json()
        response = self.client.post(f"/api/repair/jobs/{job['id']}/accept")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["reviewStatus"], "accepted")
        self.assertEqual(body["executionStatus"], "preview_ready")
        self.assertFalse(body["preview"]["applied"])
        self.assertFalse(body["preview"]["codexVerified"])
        self.assertEqual(self.client.post(f"/api/repair/jobs/{job['id']}/accept").status_code, 409)

    def test_reject_is_audited_but_hidden_from_default_list(self):
        job = self.client.post("/api/repair/jobs", json=self.payload()).json()
        response = self.client.post(f"/api/repair/jobs/{job['id']}/reject")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reviewStatus"], "rejected")
        self.assertEqual(self.client.get("/api/repair/jobs").json(), [])
        self.assertEqual(len(self.client.get("/api/repair/jobs?include_rejected=true").json()), 1)

    def test_idempotency_does_not_repeat_adapter_call(self):
        payload = self.payload(idempotencyKey="same-request")
        first = self.client.post("/api/repair/jobs", json=payload)
        second = self.client.post("/api/repair/jobs", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(service.adapter.calls, 1)
        conflict = self.client.post(
            "/api/repair/jobs",
            json=self.payload(idempotencyKey="same-request", issueText="different"),
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_invalid_ratio_and_missing_job(self):
        bad = self.client.post(
            "/api/repair/jobs",
            json=self.payload(targetRatio="16:9"),
        )
        self.assertEqual(bad.status_code, 422)
        missing = self.client.get(f"/api/repair/jobs/{uuid4()}")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
