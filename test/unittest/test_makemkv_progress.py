import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arm.ripper import makemkv
from arm.ui import json_api


class TestMakeMkvJsonProgress(unittest.TestCase):
    def make_job(self):
        return SimpleNamespace(job_id=42, stage=None)

    @patch('arm.ui.json_api.db.session.commit')
    @patch('arm.ui.json_api.read_log_line')
    def test_progress_without_batch_metadata_is_reported(self, read_log_line, commit):
        read_log_line.side_effect = [
            ['PRGV:500,0,1000\n', 'PRGC:1,0,"Saving title"\n'],
            ['', ''],
        ]

        results = json_api.process_makemkv_logfile(self.make_job(), {})

        self.assertEqual(results['progress'], '50.00')
        self.assertEqual(results['progress_round'], 50.0)
        self.assertEqual(results['eta'], 'Unknown')
        self.assertEqual(results['stage'], 'Saving title')
        commit.assert_called_once()

    @patch('arm.ui.json_api.authenticated_state', return_value=False)
    @patch('arm.ui.json_api.read_log_line')
    def test_malformed_batch_metadata_does_not_omit_active_job(self, read_log_line, authenticated_state):
        job = SimpleNamespace(
            job_id=42,
            logfile='job.log',
            disctype='dvd',
            status='ripping',
            stage=None,
            get_d=lambda: {'job_id': '42'},
        )
        query = MagicMock()
        query.filter.return_value.all.return_value = [job]
        read_log_line.side_effect = [
            ['PRGV:250,0,1000\n', 'PRGC:1,0,"Saving title"\n'],
            ['BINF:not-valid\n'],
        ]

        with patch.object(json_api.db.session, 'query', return_value=query), \
                patch.object(json_api.db.session, 'commit'):
            results = json_api.get_x_jobs('joblist')

        self.assertTrue(results['success'])
        self.assertIn(0, results['results'])
        self.assertEqual(results['results'][0]['progress'], '25.00')
        self.assertEqual(results['results'][0]['eta'], 'Unknown')

    @patch('arm.ui.json_api.time', return_value=1000000010)
    @patch('arm.ui.json_api.db.session.commit')
    @patch('arm.ui.json_api.read_log_line')
    def test_valid_batch_metadata_reports_track_stage_and_eta(self, read_log_line, commit, current_time):
        read_log_line.side_effect = [
            ['PRGV:500,0,1000\n', 'PRGC:1,0,"Saving title"\n'],
            ['BINF:1000000000,2,3,0000\n'],
        ]

        with patch('builtins.open', MagicMock()):
            results = json_api.process_makemkv_logfile(self.make_job(), {})

        self.assertEqual(results['stage'], 'Track 2/3<br>Saving title')
        self.assertEqual(results['eta'], '00h00m10s')
        self.assertEqual(results['progress'], '50.00')
        commit.assert_called_once()


class TestMakeMkvSequentialTracks(unittest.TestCase):
    def make_job(self, tracks):
        return SimpleNamespace(
            job_id=42,
            devpath='/dev/sr0',
            drive=SimpleNamespace(mdisc=0),
            no_of_titles=len(tracks),
            tracks=tracks,
            config=SimpleNamespace(
                MAINFEATURE=False,
                MAXLENGTH='99999',
                MINLENGTH='100',
                MKV_ARGS='',
            ),
        )

    @patch('arm.ripper.makemkv.process_single_tracks')
    @patch('arm.ripper.makemkv.get_track_info')
    @patch('arm.ripper.makemkv.utils.get_drive_mode', return_value='auto')
    def test_unrestricted_job_uses_sequential_workflow(self, get_drive_mode, get_track_info, process_tracks):
        job = self.make_job([])

        makemkv.makemkv_mkv(job, '/raw')

        process_tracks.assert_called_once_with(job, '/raw', 'auto', unlimited=True)

    @patch('arm.ripper.makemkv.time', return_value=1000000000)
    @patch('arm.ripper.makemkv.run', return_value=iter(()))
    def test_unrestricted_tracks_are_eligible_ordered_and_batched(self, run, current_time):
        tracks = [
            SimpleNamespace(track_number='10', length=1000000, filename='ten.mkv', process=False),
            SimpleNamespace(track_number='2', length=99, filename='two.mkv', process=False),
            SimpleNamespace(track_number='3', length=100, filename='three.mkv', process=False),
        ]
        job = self.make_job(tracks)

        with tempfile.TemporaryDirectory() as temporary_directory:
            progress_path = str(Path(temporary_directory) / '42.log')
            with patch('arm.ripper.makemkv.progress_log', return_value=progress_path):
                makemkv.process_single_tracks(job, temporary_directory, 'auto', unlimited=True)

            self.assertEqual([call.args[0][4] for call in run.call_args_list], ['3', '10'])
            self.assertNotIn('all', [value for call in run.call_args_list for value in call.args[0]])
            self.assertEqual(
                Path(progress_path + '.batchinfo').read_text().splitlines(),
                ['BINF:1000000000,1,2,0000', 'BINF:1000000000,2,2,0000'],
            )
            self.assertFalse(tracks[1].process)
            self.assertTrue(tracks[0].process)
            self.assertTrue(tracks[2].process)


if __name__ == '__main__':
    unittest.main()
