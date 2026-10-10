"""Tests for confirming an automatically identified title."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arm.ui import app
from arm.ui import json_api
from arm.ui.jobs import jobs as jobs_module
from arm.ui.jobs.jobs import can_confirm_title


def make_job(**overrides):
    values = {
        "job_id": 7,
        "status": "waiting",
        "manual_mode": False,
        "manual_start": False,
        "disctype": "dvd",
        "title": "Arrival",
        "year": "2016",
        "title_manual": None,
        "year_manual": None,
        "hasnicetitle": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestCanConfirmTitle(unittest.TestCase):
    def test_accepts_waiting_automatic_video_job(self):
        self.assertTrue(can_confirm_title(make_job()))

    def test_accepts_waiting_manual_mode_job(self):
        self.assertTrue(can_confirm_title(make_job(manual_mode=True)))

    def test_rejects_job_that_is_not_waiting(self):
        self.assertFalse(can_confirm_title(make_job(status="ripping")))

    def test_rejects_audio_job(self):
        self.assertFalse(can_confirm_title(make_job(disctype="music")))

    def test_rejects_already_confirmed_title(self):
        self.assertFalse(can_confirm_title(make_job(title_manual="Arrival")))


class TestConfirmTitleRoute(unittest.TestCase):
    def setUp(self):
        app.config["LOGIN_DISABLED"] = True

    def _confirm(self, job):
        job_model = SimpleNamespace(query=SimpleNamespace(get=MagicMock(return_value=job)))
        with app.test_request_context("/confirmtitle?job_id=7"), \
                patch.object(jobs_module, "Job", job_model), \
                patch.object(jobs_module, "url_for", return_value="/"), \
                patch.object(jobs_module.db.session, "add") as add, \
                patch.object(jobs_module.db.session, "commit") as commit:
            response = jobs_module.confirmtitle.__wrapped__()
        return response, add, commit

    def test_confirms_existing_title_without_starting_manual_track_selection(self):
        job = make_job(manual_mode=True)

        response, add, commit = self._confirm(job)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")
        self.assertEqual(job.title, "Arrival")
        self.assertEqual(job.title_manual, "Arrival")
        self.assertEqual(job.year_manual, "2016")
        self.assertTrue(job.hasnicetitle)
        self.assertFalse(job.manual_start)
        add.assert_called_once()
        commit.assert_called_once_with()

    def test_rejects_stale_confirmation(self):
        job = make_job(status="ripping")

        response, add, commit = self._confirm(job)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(job.hasnicetitle)
        self.assertFalse(job.manual_start)
        add.assert_not_called()
        commit.assert_not_called()


class TestConfirmTitleApi(unittest.TestCase):
    def test_exposes_backend_eligibility_as_json_boolean(self):
        job = make_job(
            logfile="job.log",
            config=SimpleNamespace(get_d=MagicMock(return_value={})),
            get_d=MagicMock(return_value={"job_id": "7"}),
        )
        query = MagicMock()
        query.filter.return_value.all.return_value = [job]

        with patch.object(json_api.db.session, "query", return_value=query), \
                patch.object(json_api, "process_logfile"), \
                patch.object(json_api, "authenticated_state", return_value=True):
            result = json_api.get_x_jobs("joblist")

        self.assertIs(result["results"][0]["can_confirm_title"], True)


if __name__ == "__main__":
    unittest.main()
