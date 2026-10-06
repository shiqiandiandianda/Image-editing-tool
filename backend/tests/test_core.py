from __future__ import annotations

import sys
import unittest
from pathlib import Path
from threading import Barrier, Thread

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from frame_repair.adapters import DeterministicTestAdapter, UnconfiguredCodexAdapter
from frame_repair.errors import (
    AdapterUnavailable,
    BackendError,
    ArtifactError,
    ConflictError,
    IdempotencyConflict,
    ValidationError,
)
from frame_repair.geometry import (
    AspectRatio,
    Rect,
    Size,
    context_rect,
    validate_target_rect,
)
from frame_repair.jobs import JobManager, JobStatus
from frame_repair.raster import Raster, outside_pixels_equal
from frame_repair.versions import VersionStore


class CoreTests(unittest.TestCase):
    def raster(self, width=12, height=12):
        return Raster.from_rows([
            [
                ((x * 17 + y) % 256, (y * 19 + x) % 256, (x + y) % 256)
                for x in range(width)
            ]
            for y in range(height)
        ])

    def manager(self, adapter=None):
        return JobManager(VersionStore(self.raster()), adapter or DeterministicTestAdapter())

    def test_ratio_and_bounds_are_strict(self):
        rect = Rect(0, 0, 8, 8)
        self.assertIs(validate_target_rect(rect, Size(12, 12), AspectRatio.SQUARE), rect)
        self.assertEqual(
            validate_target_rect(Rect(0, 0, 16, 9), Size(20, 20), AspectRatio.LANDSCAPE),
            Rect(0, 0, 16, 9),
        )
        self.assertEqual(
            validate_target_rect(Rect(0, 0, 9, 16), Size(20, 20), AspectRatio.PORTRAIT),
            Rect(0, 0, 9, 16),
        )
        with self.assertRaises(ValidationError):
            validate_target_rect(Rect(0, 0, 8, 7), Size(12, 12), AspectRatio.SQUARE)
        with self.assertRaises(ValidationError):
            validate_target_rect(Rect(8, 8, 8, 8), Size(12, 12), AspectRatio.SQUARE)

    def test_context_expansion_is_optional_and_clipped(self):
        target = Rect(2, 3, 4, 4)
        self.assertEqual(context_rect(target, Size(12, 12), 5, False), target)
        self.assertEqual(context_rect(target, Size(12, 12), 5, True), Rect(0, 0, 11, 12))

    def test_snapshot_crop_hash_and_original_are_immutable(self):
        original = self.raster()
        cropped = original.crop(Rect(2, 2, 4, 4))
        self.assertNotEqual(original.sha256, cropped.sha256)
        self.assertEqual(original.at(2, 2), ((2 * 17 + 2) % 256, (2 * 19 + 2) % 256, 4))

    def test_submit_is_idempotent_and_conflicting_reuse_is_rejected(self):
        manager = self.manager()
        kwargs = dict(
            job_id="j1",
            idempotency_key="same",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )
        first = manager.submit(**kwargs)
        self.assertIs(manager.submit(**kwargs), first)
        with self.assertRaises(IdempotencyConflict):
            manager.submit(**{**kwargs, "job_id": "j2", "instruction": "different"})

    def test_serial_run_preview_accept_keeps_outside_pixels(self):
        adapter = DeterministicTestAdapter(lambda raster: raster.resize_nearest(11, 11))
        manager = self.manager(adapter)
        job = manager.submit(
            job_id="j1",
            idempotency_key="k1",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            context_margin=5,
            context_enabled=True,
            instruction="repair",
            preserve="background",
        )
        self.assertEqual(job.context, Rect(0, 0, 11, 11))
        self.assertIs(manager.run_next(), job)
        self.assertEqual(job.status, JobStatus.PREVIEW_READY)
        self.assertTrue(
            outside_pixels_equal(manager.versions.current.raster, job.preview, job.target)
        )
        version = manager.accept("j1")
        self.assertEqual(manager.versions.current.version_id, version.version_id)
        self.assertEqual(job.status, JobStatus.ACCEPTED)
        self.assertEqual(adapter.calls, 1)
        self.assertIsNone(manager.run_next())

    def test_result_ratio_mismatch_fails_without_preview(self):
        adapter = DeterministicTestAdapter(lambda raster: Raster.solid(3, 2, (1, 2, 3)))
        manager = self.manager(adapter)
        job = manager.submit(
            job_id="j1",
            idempotency_key="k1",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )
        manager.run_next()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_code, ArtifactError.code)
        self.assertIsNone(job.preview)

    def test_version_accept_is_atomic_compare_and_swap(self):
        for attempt in range(20):
            store = VersionStore(self.raster())
            base = store.current
            barrier = Barrier(2)
            outcomes = []

            def accept(job_id):
                barrier.wait(timeout=2)
                try:
                    version = store.accept(
                        self.raster(),
                        base_version_id=base.version_id,
                        base_hash=base.content_hash,
                        job_id=job_id,
                    )
                except ConflictError:
                    outcomes.append(("conflict", job_id))
                except Exception as exc:  # pragma: no cover - keeps thread failures visible
                    outcomes.append(("error", type(exc).__name__))
                else:
                    outcomes.append(("accepted", version.version_id))

            threads = [
                Thread(target=accept, args=(f"job-{attempt}-a",)),
                Thread(target=accept, args=(f"job-{attempt}-b",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(sorted(kind for kind, _ in outcomes), ["accepted", "conflict"])
            accepted_id = next(value for kind, value in outcomes if kind == "accepted")
            self.assertEqual(store.current.version_id, accepted_id)
            self.assertEqual(len(store._versions), 2)

    def test_cancel_race_with_dispatch_never_runs_a_cancelled_job(self):
        for attempt in range(40):
            adapter = DeterministicTestAdapter()
            manager = self.manager(adapter)
            job = manager.submit(
                job_id=f"cancel-race-{attempt}",
                idempotency_key=f"cancel-race-{attempt}",
                ratio=AspectRatio.SQUARE,
                target=Rect(2, 2, 4, 4),
                instruction="repair",
                preserve="line",
            )
            barrier = Barrier(2)
            outcome = {}

            def dispatch():
                barrier.wait(timeout=2)
                outcome["run"] = manager.run_next()

            def cancel():
                barrier.wait(timeout=2)
                try:
                    result = manager.cancel(job.job_id)
                except BackendError as exc:
                    outcome["cancel_error"] = exc
                else:
                    outcome["cancel_status"] = result.status

            threads = [Thread(target=dispatch), Thread(target=cancel)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
            if outcome.get("cancel_status") == JobStatus.CANCELLED:
                self.assertEqual(adapter.calls, 0)
                self.assertEqual(job.status, JobStatus.CANCELLED)
            else:
                self.assertEqual(adapter.calls, 1)
                self.assertNotEqual(job.status, JobStatus.CANCELLED)

    def test_accept_detects_changed_formal_base(self):
        manager = self.manager()
        job = manager.submit(
            job_id="j1",
            idempotency_key="k1",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )
        manager.run_next()
        current = manager.versions.get("v0")
        manager.versions.accept(
            self.raster(),
            base_version_id="v0",
            base_hash=current.content_hash,
            job_id="other",
        )
        with self.assertRaises(ConflictError):
            manager.accept("j1")
        self.assertEqual(job.status, JobStatus.CONFLICT)

    def test_unconfigured_codex_is_explicitly_blocked(self):
        manager = self.manager(UnconfiguredCodexAdapter())
        manager.submit(
            job_id="j1",
            idempotency_key="k1",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )
        job = manager.run_next()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_code, AdapterUnavailable.code)

    def test_cancel_and_reject_are_terminal_without_writing_a_version(self):
        manager = self.manager()
        cancelled = manager.submit(
            job_id="cancel",
            idempotency_key="cancel",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )
        manager.cancel(cancelled.job_id)
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertIsNone(manager.run_next())
        preview = manager.submit(
            job_id="reject",
            idempotency_key="reject",
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )
        manager.run_next()
        manager.reject(preview.job_id)
        self.assertEqual(preview.status, JobStatus.REJECTED)
        self.assertEqual(manager.versions.current.version_id, "v0")


if __name__ == "__main__":
    unittest.main()
