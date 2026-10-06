from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from frame_repair.adapters import DeterministicTestAdapter
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


if __name__ == "__main__":
    unittest.main()
