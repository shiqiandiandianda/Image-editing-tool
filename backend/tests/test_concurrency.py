from __future__ import annotations

import builtins
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, current_thread
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from frame_repair.adapters import DeterministicTestAdapter
from frame_repair.errors import BackendError, ConflictError, ValidationError
from frame_repair.geometry import AspectRatio, Rect
from frame_repair.jobs import JobManager, JobStatus
from frame_repair.raster import Raster
from frame_repair.versions import VersionStore


class ObservedLock:
    """Notify before a named contender waits for the real lock."""

    def __init__(self, contender_name, contender_arrived):
        self._lock = Lock()
        self._contender_name = contender_name
        self._contender_arrived = contender_arrived

    def __enter__(self):
        if current_thread().name == self._contender_name:
            self._contender_arrived.set()
        self._lock.acquire()
        return self

    def __exit__(self, *_):
        self._lock.release()


class ConcurrencyTests(unittest.TestCase):
    def manager(self, adapter=None):
        return JobManager(
            VersionStore(Raster.solid(12, 12, (10, 20, 30))),
            adapter or DeterministicTestAdapter(),
        )

    def submit(self, manager, job_id):
        return manager.submit(
            job_id=job_id,
            idempotency_key=job_id,
            ratio=AspectRatio.SQUARE,
            target=Rect(2, 2, 4, 4),
            instruction="repair",
            preserve="line",
        )

    def test_version_cas_rechecks_base_after_a_competing_accept(self):
        store = self.manager().versions
        base = store.current
        first_checked_base = Event()
        contender_arrived = Event()
        release_first = Event()
        store._lock = ObservedLock("contender", contender_arrived)

        def gated_uuid4():
            # Pause after the base comparison, before insertion and pointer update.
            if current_thread().name == "first":
                first_checked_base.set()
                if not release_first.wait(5):
                    raise TimeoutError("accept release was not signalled")
            else:
                # The unfixed implementation reaches here without waiting for the lock.
                contender_arrived.set()
            return uuid4()

        def accept(name):
            current_thread().name = name
            return store.accept(
                Raster.solid(12, 12, (40, 50, 60)),
                base_version_id=base.version_id,
                base_hash=base.content_hash,
                job_id=name,
            )

        with patch("frame_repair.versions.uuid4", side_effect=gated_uuid4):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(accept, "first")
                try:
                    self.assertTrue(first_checked_base.wait(5))
                    second = pool.submit(accept, "contender")
                    self.assertTrue(contender_arrived.wait(5))
                finally:
                    release_first.set()
                accepted = first.result(timeout=5)
                with self.assertRaises(ConflictError):
                    second.result(timeout=5)
        self.assertEqual(store.current, accepted)
        self.assertEqual(len(store._versions), 2)
        self.assertEqual(store.get("v0"), base)

    def test_cancel_cannot_overwrite_a_selected_dispatch(self):
        adapter = DeterministicTestAdapter()
        manager = self.manager(adapter)
        job = self.submit(manager, "selected")
        selected = Event()
        contender_arrived = Event()
        release_dispatch = Event()
        manager._lock = ObservedLock("cancel", contender_arrived)

        def gated_next(*args):
            queued = builtins.next(*args)
            selected.set()
            if not release_dispatch.wait(5):
                raise TimeoutError("dispatch release was not signalled")
            return queued

        def dispatch():
            current_thread().name = "dispatch"
            return manager.run_next()

        def cancel():
            current_thread().name = "cancel"
            try:
                return manager.cancel(job.job_id).status
            finally:
                # Also signals in the unfixed implementation that bypasses the lock.
                contender_arrived.set()

        with patch("frame_repair.jobs.next", side_effect=gated_next, create=True):
            with ThreadPoolExecutor(max_workers=2) as pool:
                dispatched = pool.submit(dispatch)
                try:
                    self.assertTrue(selected.wait(5))
                    cancelled = pool.submit(cancel)
                    self.assertTrue(contender_arrived.wait(5))
                finally:
                    release_dispatch.set()
                self.assertIs(dispatched.result(timeout=5), job)
                try:
                    cancellation_status = cancelled.result(timeout=5)
                except BackendError:
                    pass  # The dispatch won; running cancellation is explicitly unsupported.
                else:
                    self.assertNotEqual(cancellation_status, JobStatus.CANCELLED)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(job.status, JobStatus.PREVIEW_READY)

    def test_successful_cancel_prevents_dispatch_and_accept(self):
        adapter = DeterministicTestAdapter()
        manager = self.manager(adapter)
        job = self.submit(manager, "cancelled")
        self.assertEqual(manager.cancel(job.job_id).status, JobStatus.CANCELLED)
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(manager.run_next) for _ in range(2)]
            self.assertTrue(all(attempt.result(timeout=5) is None for attempt in attempts))
        with self.assertRaises(ValidationError):
            manager.accept(job.job_id)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(job.attempts, 0)
        self.assertIsNone(job.preview)
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(manager.versions.current.version_id, "v0")

    def test_worker_slot_is_reserved_until_adapter_returns(self):
        entered = Event()
        release = Event()

        def gated_edit(reference):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("adapter release was not signalled")
            return reference

        adapter = DeterministicTestAdapter(gated_edit)
        manager = self.manager(adapter)
        first_job = self.submit(manager, "first")
        second_job = self.submit(manager, "second")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(manager.run_next)
            try:
                self.assertTrue(entered.wait(5))
                second = pool.submit(manager.run_next)
                self.assertIsNone(second.result(timeout=5))
                self.assertEqual(adapter.calls, 1)
                self.assertEqual(first_job.status, JobStatus.RUNNING)
                self.assertEqual(second_job.status, JobStatus.QUEUED)
                with self.assertRaises(BackendError):
                    manager.cancel(first_job.job_id)
            finally:
                release.set()
            self.assertIs(first.result(timeout=5), first_job)
        self.assertIs(manager.run_next(), second_job)
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(second_job.status, JobStatus.PREVIEW_READY)


if __name__ == "__main__":
    unittest.main()
