from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from frame_repair.adapters import DeterministicTestAdapter
from frame_repair.errors import PersistenceConflict
from frame_repair.geometry import AspectRatio, Rect
from frame_repair.jobs import JobManager
from frame_repair.persistence import SQLiteStateStore
from frame_repair.raster import Raster
from frame_repair.versions import VersionStore


class PersistenceTests(unittest.TestCase):
    def test_version_and_job_metadata_round_trip(self) -> None:
        raster = Raster.solid(4, 4, (20, 30, 40))
        versions = VersionStore(raster)
        manager = JobManager(versions, DeterministicTestAdapter())
        job = manager.submit(job_id="j1", idempotency_key="k1", ratio=AspectRatio.SQUARE,
                             target=Rect(0, 0, 4, 4), instruction="repair", preserve="line")
        manager.run_next()
        store = SQLiteStateStore()
        store.save_version(versions.current, current=True)
        store.save_job(job)
        restored = store.load_version("v0")
        self.assertEqual(restored.content_hash, raster.sha256)
        record = store.get_job_record("j1")
        self.assertEqual(record["status"], "preview_ready")
        store.close()

    def test_version_rows_are_immutable_and_replays_are_idempotent(self) -> None:
        raster = Raster.solid(2, 2, (20, 30, 40))
        store = SQLiteStateStore()
        version = VersionStore(raster).current
        store.save_version(version, current=True)
        store.save_version(version, current=True)
        changed = type(version)(version.version_id, Raster.solid(2, 2, (1, 2, 3)),
                                Raster.solid(2, 2, (1, 2, 3)).sha256, None, None)
        with self.assertRaises(PersistenceConflict):
            store.save_version(changed, current=True)
        self.assertEqual(store.current_version().content_hash, raster.sha256)
        store.close()

    def test_job_idempotency_key_cannot_be_rebound(self) -> None:
        raster = Raster.solid(4, 4, (20, 30, 40))
        manager = JobManager(VersionStore(raster), DeterministicTestAdapter())
        first = manager.submit(job_id="j1", idempotency_key="k1", ratio=AspectRatio.SQUARE,
                               target=Rect(0, 0, 4, 4), instruction="repair", preserve="line")
        store = SQLiteStateStore()
        store.save_job(first)
        with self.assertRaises(PersistenceConflict):
            other = manager.submit(job_id="j2", idempotency_key="k2", ratio=AspectRatio.SQUARE,
                                   target=Rect(0, 0, 4, 4), instruction="repair", preserve="line")
            other.idempotency_key = "k1"
            store.save_job(other)
        store.close()


if __name__ == "__main__":
    unittest.main()
