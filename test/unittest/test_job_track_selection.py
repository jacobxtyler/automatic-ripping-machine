import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/opt/arm")

from arm.ripper.handbrake import HandBrakeTrackInfoProcessor  # noqa: E402
from arm.ripper.makemkv import TrackInfoProcessor, parse_line  # noqa: E402
from arm.ui import app  # noqa: E402
from arm.ui.jobs import jobs as jobs_module  # noqa: E402
from arm.ui.jobs.jobs import apply_manual_track_selection, build_track_views  # noqa: E402


class TrackQuery:
    def __init__(self, tracks):
        self._tracks = tracks

    def all(self):
        return self._tracks


def make_job(tracks=None, **overrides):
    values = {
        "job_id": 7,
        "manual_mode": True,
        "manual_start": False,
        "status": "waiting",
        "disctype": "bluray",
        "title": "Example",
        "config": SimpleNamespace(MINLENGTH="60", MAXLENGTH="99999"),
    }
    values.update(overrides)
    job = SimpleNamespace(**values)
    job.tracks = TrackQuery(tracks or [])
    return job


def make_track(track_id, **overrides):
    values = {
        "track_id": track_id,
        "track_number": str(track_id),
        "length": 3600,
        "aspect_ratio": "16:9",
        "fps": 23.976,
        "main_feature": False,
        "basename": "Example",
        "filename": "",
        "orig_filename": None,
        "new_filename": None,
        "ripped": True,
        "status": None,
        "source": "MakeMKV",
        "process": False,
        "chapters": 10,
        "filesize": 1024,
        "playlist_id": None,
        "segment_count": None,
        "segment_map": None,
        "video_resolution": None,
        "video_codec": None,
        "audio_languages": None,
        "subtitle_languages": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestManualTrackSelection(unittest.TestCase):
    def test_applies_exact_selected_ids(self):
        tracks = [make_track(1), make_track(2, process=True)]
        job = make_job(tracks)

        count = apply_manual_track_selection(job, [(1, True), (2, False)])

        self.assertEqual(count, 1)
        self.assertTrue(tracks[0].process)
        self.assertFalse(tracks[1].process)
        self.assertTrue(job.manual_start)

    def test_rejects_empty_selection_without_mutating(self):
        track = make_track(1, process=True)
        job = make_job([track])

        with self.assertRaisesRegex(ValueError, "at least one"):
            apply_manual_track_selection(job, [(1, False)])

        self.assertTrue(track.process)
        self.assertFalse(job.manual_start)

    def test_rejects_forged_and_duplicate_track_ids(self):
        job = make_job([make_track(1)])
        for rows in ([(99, True)], [(1, True), (1, False)]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "invalid title"):
                apply_manual_track_selection(job, rows)

    def test_rejects_stale_or_non_waiting_job(self):
        job = make_job([make_track(1)], status="ripping")

        with self.assertRaisesRegex(ValueError, "no longer waiting"):
            apply_manual_track_selection(job, [(1, True)])

    def test_equal_runtime_views_emphasize_real_differences(self):
        tracks = [
            make_track(1, chapters=12, filesize=10_000, playlist_id="00001.mpls"),
            make_track(2, chapters=10, filesize=9_000, playlist_id="00002.mpls"),
        ]

        views = build_track_views(make_job(tracks), tracks)

        self.assertTrue(all(view["equal_runtime"] for view in views))
        self.assertIn("chapters", views[0]["differing_fields"])
        self.assertIn("filesize", views[0]["differing_fields"])
        self.assertIn("playlist_id", views[0]["differing_fields"])
        self.assertEqual(views[0]["duration"], "01:00:00")
        self.assertEqual(views[0]["filesize"], "9.8 KiB")

    def test_legacy_missing_metadata_uses_placeholders(self):
        track = make_track(1, length=0, chapters=0, filesize=0, fps=0, aspect_ratio=None, source=None)

        view = build_track_views(make_job([track]), [track])[0]

        for field in ("duration", "filesize", "chapters", "fps", "aspect", "resolution", "source"):
            self.assertEqual(view[field], "—")

    def test_template_contains_accessible_mobile_labels_and_controls(self):
        template = Path("/opt/arm/arm/ui/jobs/templates/jobdetail.html").read_text(encoding="utf-8")
        css = Path("/opt/arm/arm/ui/static/css/job_details.css").read_text(encoding="utf-8")

        self.assertIn("Select recommended", template)
        self.assertIn("Select eligible", template)
        self.assertIn("Clear selection", template)
        self.assertIn('aria_label="Rip title "', template)
        self.assertIn('data-label="Duration"', template)
        self.assertIn("content: attr(data-label)", css)


class TestManualTrackSelectionRoute(unittest.TestCase):
    def setUp(self):
        app.config["LOGIN_DISABLED"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def _post_selection(self, job, rows):
        entries = [SimpleNamespace(data={"track_ref": track_id, "checkbox": selected})
                   for track_id, selected in rows]
        form = MagicMock()
        form.validate_on_submit.return_value = True
        form.track_ref.entries = entries
        job_model = SimpleNamespace(query=SimpleNamespace(get=MagicMock(return_value=job)))
        with app.test_request_context("/jobdetailload?job_id=7", method="POST"), \
                patch.object(jobs_module, "TrackFormDynamic", return_value=form), \
                patch.object(jobs_module, "Job", job_model), \
                patch.object(jobs_module.db.session, "commit") as commit:
            response = jobs_module.jobdetail_load.__wrapped__()
        return response, commit

    def test_route_rejects_empty_selection(self):
        track = make_track(1)
        response, commit = self._post_selection(make_job([track]), [(1, False)])

        self.assertEqual(response.status_code, 302)
        self.assertFalse(track.process)
        commit.assert_not_called()

    def test_route_rejects_forged_track_id(self):
        track = make_track(1)
        response, commit = self._post_selection(make_job([track]), [(99, True)])

        self.assertEqual(response.status_code, 302)
        self.assertFalse(track.process)
        commit.assert_not_called()

    def test_route_rejects_stale_submission(self):
        track = make_track(1)
        response, commit = self._post_selection(make_job([track], status="ripping"), [(1, True)])

        self.assertEqual(response.status_code, 302)
        self.assertFalse(track.process)
        commit.assert_not_called()

    def test_route_commits_valid_selection_once(self):
        tracks = [make_track(1), make_track(2)]
        response, commit = self._post_selection(make_job(tracks), [(1, False), (2, True)])

        self.assertEqual(response.status_code, 302)
        self.assertFalse(tracks[0].process)
        self.assertTrue(tracks[1].process)
        commit.assert_called_once_with()


class TestMakeMKVTrackMetadata(unittest.TestCase):
    @patch("arm.ripper.makemkv.utils.put_track")
    def test_rich_metadata_and_title_reset(self, put_track):
        processor = TrackInfoProcessor(make_job(), 0)
        lines = [
            'TINFO:0,9,0,"1:00:00"',
            'TINFO:0,8,0,"12"',
            'TINFO:0,11,0,"1073741824"',
            'TINFO:0,16,0,"00001.mpls"',
            'TINFO:0,25,0,"2"',
            'TINFO:0,26,0,"10,11"',
            'TINFO:0,27,0,"title00.mkv"',
            'SINFO:0,0,1,6201,"Video"',
            'SINFO:0,0,6,0,"AVC"',
            'SINFO:0,0,19,0,"1920x1080"',
            'SINFO:0,1,1,6202,"Audio"',
            'SINFO:0,1,4,0,"English"',
            'SINFO:0,1,6,0,"DTS-HD MA"',
            'SINFO:0,2,1,6203,"Subtitles"',
            'SINFO:0,2,3,0,"eng"',
            'TINFO:1,9,0,"0:10:00"',
            'TINFO:1,27,0,"title01.mkv"',
        ]
        for line in lines:
            processor._process_message(parse_line(line)[1])
        processor._add_track()

        self.assertEqual(put_track.call_count, 2)
        first = put_track.call_args_list[0]
        self.assertEqual(first.kwargs["playlist_id"], "00001.mpls")
        self.assertEqual(first.kwargs["segment_count"], 2)
        self.assertEqual(first.kwargs["segment_map"], "10,11")
        self.assertEqual(first.kwargs["video_resolution"], "1920x1080")
        self.assertEqual(first.kwargs["video_codec"], "AVC")
        self.assertEqual(first.kwargs["audio_languages"], "English (DTS-HD MA)")
        self.assertEqual(first.kwargs["subtitle_languages"], "eng")
        second = put_track.call_args_list[1]
        self.assertIsNone(second.kwargs["playlist_id"])
        self.assertIsNone(second.kwargs["audio_languages"])


class TestHandBrakeTrackMetadata(unittest.TestCase):
    @patch("arm.ripper.handbrake.db.session.commit")
    @patch("arm.ripper.handbrake.utils.put_track")
    def test_parses_metadata_and_resets_between_titles(self, put_track, _commit):
        job = make_job()
        lines = [
            "scan: BD has 2 title(s)",
            "  + title 1:",
            "    + Main Feature",
            "    + playlist: 00001.MPLS",
            "    + duration: 01:02:03",
            "    + size: 1920x1080, pixel aspect: 1/1, display aspect: 1.78, 23.976 fps",
            "    + video codec: h264",
            "    + chapters:",
            "      + 1: cells 0 to 0, 100 blocks",
            "      + 2: cells 1 to 1, 100 blocks",
            "    + audio tracks:",
            "      + 1, English (DTS-HD MA) (5.1 ch)",
            "    + subtitle tracks:",
            "      + 1, English (PGS)",
            "  + title 2:",
            "    + duration: 00:10:00",
        ]

        HandBrakeTrackInfoProcessor(job).process(lines)

        self.assertEqual(put_track.call_count, 2)
        first = put_track.call_args_list[0]
        self.assertEqual(first.args[2], 3723)
        self.assertEqual(first.kwargs["chapters"], 2)
        self.assertEqual(first.kwargs["playlist_id"], "00001.MPLS")
        self.assertEqual(first.kwargs["video_resolution"], "1920x1080")
        self.assertEqual(first.kwargs["video_codec"], "h264")
        self.assertEqual(first.kwargs["audio_languages"], "English (DTS-HD MA)")
        self.assertEqual(first.kwargs["subtitle_languages"], "English (PGS)")
        second = put_track.call_args_list[1]
        self.assertEqual(second.args[2], 600)
        self.assertIsNone(second.kwargs["playlist_id"])
        self.assertEqual(second.kwargs["chapters"], 0)


if __name__ == "__main__":
    unittest.main()
