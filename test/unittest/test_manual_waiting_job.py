import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, '/opt/arm')

from arm.ui.jobs.jobs import is_manual_waiting_job  # noqa: E402


class TestManualWaitingJob(unittest.TestCase):
    def test_matches_waiting_video_jobs(self):
        for disctype in ("dvd", "bluray"):
            with self.subTest(disctype=disctype):
                self.assertTrue(is_manual_waiting_job(SimpleNamespace(
                    manual_mode=True,
                    status="waiting",
                    manual_start=False,
                    disctype=disctype,
                )))

    def test_rejects_jobs_not_waiting_for_manual_input(self):
        self.assertFalse(is_manual_waiting_job(SimpleNamespace(
            manual_mode=False,
            status="waiting",
            manual_start=False,
        )))
        self.assertFalse(is_manual_waiting_job(SimpleNamespace(
            manual_mode=True,
            status="success",
            manual_start=False,
        )))
        self.assertFalse(is_manual_waiting_job(SimpleNamespace(
            manual_mode=True,
            status="waiting",
            manual_start=True,
        )))


if __name__ == '__main__':
    unittest.main()
