import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, '/opt/arm')

from arm.ripper import open_library, utils  # noqa: E402
from arm.ripper import main as ripper_main  # noqa: E402
from arm.ui.jobs.jobs import (  # noqa: E402
    audiobook_cover_url,
    build_audiobook_query,
    get_jobdetail_metadata,
    is_manual_audio_job,
    update_audio_manual_choice,
    update_audiobook_metadata,
    update_audiobook_title,
    validate_title_search_input,
)


class TestOpenLibraryParsing(unittest.TestCase):
    def test_parse_normal_response(self):
        payload = {
            "docs": [{
                "title": "The Hobbit",
                "author_name": ["J. R. R. Tolkien"],
                "first_publish_year": 1937,
                "key": "/works/OL262758W",
                "cover_i": 12345,
            }]
        }

        self.assertEqual(open_library.parse_search_results(payload), [{
            "title": "The Hobbit",
            "author": "J. R. R. Tolkien",
            "year": "1937",
            "open_library_work_key": "/works/OL262758W",
            "cover_id": "12345",
        }])

    def test_parse_missing_optional_fields(self):
        payload = {"docs": [{"title": "Dune"}]}

        self.assertEqual(open_library.parse_search_results(payload), [{
            "title": "Dune",
            "author": "",
            "year": "",
            "open_library_work_key": "",
            "cover_id": "",
        }])

    def test_parse_no_results(self):
        self.assertEqual(open_library.parse_search_results({"docs": []}), [])


class TestAudiobookPaths(unittest.TestCase):
    def test_destination_path_and_disc_formatting(self):
        job = SimpleNamespace(
            audiobook_author="Ursula K. Le Guin",
            title_manual="A Wizard: of Earthsea",
            title=None,
            audiobook_disc_number=3,
            config=SimpleNamespace(AUDIOBOOK_PATH="/audiobooks"),
        )

        self.assertEqual(utils.format_audiobook_disc_dir(3), "Disc 03")
        self.assertEqual(
            utils.audiobook_destination_dir(job),
            os.path.join("/audiobooks", "Ursula-K.-Le-Guin", "A-Wizard--of-Earthsea", "Disc 03")
        )

    def test_track_filename_uses_default_title(self):
        self.assertEqual(
            utils.audiobook_track_filename(7, "/tmp/source.mp3"),
            "07 - Track 07.mp3"
        )

    def test_move_audiobook_files(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination_root:
            source_file = os.path.join(source_dir, "abcde-track.mp3")
            with open(source_file, "w") as test_file:
                test_file.write("audio")

            track = SimpleNamespace(track_number="1", filename="Chapter 1")
            job = SimpleNamespace(
                audiobook_author="Author",
                title_manual="Book",
                title=None,
                audiobook_disc_number=1,
                config=SimpleNamespace(AUDIOBOOK_PATH=destination_root),
                tracks=SimpleNamespace(all=lambda: [track]),
            )

            with patch("arm.ripper.utils.database_updater") as updater:
                destination_dir = utils.move_audiobook_files(job, source_dir)

            self.assertTrue(os.path.isfile(os.path.join(destination_dir, "01 - Chapter-1.mp3")))
            updater.assert_called_once_with({"path": destination_dir}, job)

    def test_move_audiobook_files_uses_natural_file_and_track_order(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination_root:
            for file_name in ("track10.mp3", "track2.mp3", "track1.mp3"):
                with open(os.path.join(source_dir, file_name), "w") as test_file:
                    test_file.write("audio")

            tracks = [
                SimpleNamespace(track_number="10", filename="Chapter 10"),
                SimpleNamespace(track_number="2", filename="Chapter 2"),
                SimpleNamespace(track_number="1", filename="Chapter 1"),
            ]
            job = SimpleNamespace(
                audiobook_author="Author",
                title_manual="Book",
                title=None,
                audiobook_disc_number=1,
                config=SimpleNamespace(AUDIOBOOK_PATH=destination_root),
                tracks=SimpleNamespace(all=lambda: tracks),
            )

            with patch("arm.ripper.utils.database_updater"):
                destination_dir = utils.move_audiobook_files(job, source_dir)

            self.assertTrue(os.path.isfile(os.path.join(destination_dir, "01 - Chapter-1.mp3")))
            self.assertTrue(os.path.isfile(os.path.join(destination_dir, "02 - Chapter-2.mp3")))
            self.assertTrue(os.path.isfile(os.path.join(destination_dir, "03 - Chapter-10.mp3")))

    def test_create_audiobook_abcde_config_overrides_outputdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_config = os.path.join(tmpdir, "abcde.conf")
            destination_config = os.path.join(tmpdir, "abcde-audiobook.conf")
            output_dir = os.path.join(tmpdir, "book output")
            with open(source_config, "w") as source_file:
                source_file.write('OUTPUTDIR="/home/arm/music/"\nOUTPUTFORMAT="${TRACKNUM}"\n')

            utils.create_audiobook_abcde_config(source_config, destination_config, output_dir)

            with open(destination_config) as generated_file:
                generated_config = generated_file.read()

        self.assertIn('OUTPUTDIR="/home/arm/music/"', generated_config)
        self.assertIn('OUTPUTFORMAT="${TRACKNUM}"', generated_config)
        self.assertIn("ARM audiobook job override", generated_config)
        self.assertIn("OUTPUTDIR='", generated_config)
        self.assertIn("book output", generated_config)

    def test_rip_audiobook_uses_job_local_abcde_config(self):
        with tempfile.TemporaryDirectory() as raw_path, tempfile.TemporaryDirectory() as audiobook_path:
            job = SimpleNamespace(
                disctype="audiobook",
                audiobook_author="Author",
                title_manual="Book",
                title=None,
                audiobook_disc_number=1,
                job_id=42,
                stage="123",
                config=SimpleNamespace(RAW_PATH=raw_path, AUDIOBOOK_PATH=audiobook_path),
            )

            with patch("arm.ripper.utils.cfg.arm_config", {"ABCDE_CONFIG_FILE": "/missing/abcde.conf"}), \
                    patch("arm.ripper.utils.run_abcde", return_value=True) as run_abcde, \
                    patch("arm.ripper.utils.move_audiobook_files") as move_files:
                self.assertTrue(utils.rip_audiobook(job, "book.log"))

            expected_work_dir = os.path.join(raw_path, "audiobook_42_123")
            run_abcde.assert_called_once_with(
                job,
                "book.log",
                cwd=expected_work_dir,
                abcde_config_file=os.path.join(expected_work_dir, "abcde-audiobook.conf")
            )
            move_files.assert_called_once_with(job, expected_work_dir)


class TestAudiobookRouting(unittest.TestCase):
    def test_music_uses_musicbrainz_and_music_ripper(self):
        job = SimpleNamespace(disctype="music", title="Album", has_track_99=False, status=None)
        ripper_main.job = job
        ripper_main.log_file = "music.log"

        with patch("arm.ripper.main.identify.identify"), \
                patch("arm.ripper.main.utils.job_dupe_check", return_value=False), \
                patch("arm.ripper.main.utils.notify_entry"), \
                patch("arm.ripper.main.utils.check_for_wait"), \
                patch("arm.ripper.main.log_arm_params"), \
                patch("arm.ripper.main.check_fstab"), \
                patch("arm.ripper.main.music_brainz.main") as musicbrainz, \
                patch("arm.ripper.main.utils.rip_music", return_value=True) as rip_music, \
                patch("arm.ripper.main.utils.rip_audiobook") as rip_audiobook, \
                patch("arm.ripper.main.utils.notify"), \
                patch("arm.ripper.main.utils.scan_emby"), \
                patch("arm.ripper.main.db.session.commit"):
            ripper_main.main()

        musicbrainz.assert_called_once_with(job)
        rip_music.assert_called_once_with(job, "music.log")
        rip_audiobook.assert_not_called()

    def test_audiobook_skips_musicbrainz_and_uses_audiobook_ripper(self):
        job = SimpleNamespace(disctype="audiobook", title="Book", has_track_99=False, status=None)
        ripper_main.job = job
        ripper_main.log_file = "book.log"

        with patch("arm.ripper.main.identify.identify"), \
                patch("arm.ripper.main.utils.job_dupe_check", return_value=False), \
                patch("arm.ripper.main.utils.notify_entry"), \
                patch("arm.ripper.main.utils.check_for_wait"), \
                patch("arm.ripper.main.log_arm_params"), \
                patch("arm.ripper.main.check_fstab"), \
                patch("arm.ripper.main.music_brainz.main") as musicbrainz, \
                patch("arm.ripper.main.utils.rip_music") as rip_music, \
                patch("arm.ripper.main.utils.rip_audiobook", return_value=True) as rip_audiobook, \
                patch("arm.ripper.main.utils.notify"), \
                patch("arm.ripper.main.utils.scan_emby"), \
                patch("arm.ripper.main.db.session.commit"):
            ripper_main.main()

        musicbrainz.assert_not_called()
        rip_music.assert_not_called()
        rip_audiobook.assert_called_once_with(job, "book.log")


class TestAudiobookManualMetadata(unittest.TestCase):
    def test_update_audio_manual_choice_music_starts_job(self):
        job = SimpleNamespace(disctype="music", manual_start=False)

        update_audio_manual_choice(job, {"audio_disc_type": "music"})

        self.assertEqual(job.disctype, "music")
        self.assertTrue(job.manual_start)

    def test_update_audio_manual_choice_audiobook_waits_for_metadata(self):
        job = SimpleNamespace(disctype="music", manual_start=True)

        update_audio_manual_choice(job, {"audio_disc_type": "audiobook"})

        self.assertEqual(job.disctype, "audiobook")
        self.assertFalse(job.manual_start)

    def test_update_audio_manual_choice_rejects_invalid_type(self):
        with self.assertRaises(ValueError):
            update_audio_manual_choice(SimpleNamespace(), {"audio_disc_type": "data"})

    def test_update_audiobook_metadata_sets_manual_fields(self):
        job = SimpleNamespace()
        form_data = {
            "audiobook_author": "Octavia Butler",
            "audiobook_title": "Kindred",
            "audiobook_disc_number": "2",
            "audiobook_total_discs": "8",
            "audiobook_year": "1979",
            "open_library_work_key": "/works/OL33479W",
            "open_library_cover_id": "555",
        }

        update_audiobook_metadata(job, form_data)

        self.assertEqual(job.audiobook_author, "Octavia Butler")
        self.assertEqual(job.title, "Kindred")
        self.assertEqual(job.title_manual, "Kindred")
        self.assertEqual(job.audiobook_disc_number, 2)
        self.assertEqual(job.audiobook_total_discs, 8)
        self.assertEqual(job.year, "1979")
        self.assertEqual(job.year_manual, "1979")
        self.assertEqual(job.open_library_work_key, "/works/OL33479W")
        self.assertEqual(job.open_library_cover_id, "555")
        self.assertTrue(job.hasnicetitle)
        self.assertTrue(job.manual_start)

    def test_update_audiobook_metadata_requires_author_title_disc(self):
        with self.assertRaises(ValueError):
            update_audiobook_metadata(SimpleNamespace(), {
                "audiobook_author": "Author",
                "audiobook_title": "",
                "audiobook_disc_number": "1",
            })

    def test_update_audiobook_metadata_rejects_invalid_disc_number(self):
        with self.assertRaises(ValueError):
            update_audiobook_metadata(SimpleNamespace(), {
                "audiobook_author": "Author",
                "audiobook_title": "Book",
                "audiobook_disc_number": "0",
            })

    def test_update_audiobook_metadata_rejects_invalid_total_discs(self):
        with self.assertRaises(ValueError):
            update_audiobook_metadata(SimpleNamespace(), {
                "audiobook_author": "Author",
                "audiobook_title": "Book",
                "audiobook_disc_number": "1",
                "audiobook_total_discs": "many",
            })

    def test_update_audiobook_title_sets_audiobook_fields(self):
        job = SimpleNamespace(disctype="music")

        update_audiobook_title(job, {
            "audiobook_author": "Octavia Butler",
            "audiobook_title": "Kindred",
            "audiobook_disc_number": "2",
            "audiobook_total_discs": "8",
            "audiobook_year": "1979",
            "open_library_work_key": "/works/OL33479W",
            "open_library_cover_id": "555",
        })

        self.assertEqual(job.disctype, "audiobook")
        self.assertEqual(job.video_type, "audiobook")
        self.assertEqual(job.video_type_manual, "audiobook")
        self.assertIsNone(job.imdb_id)
        self.assertIsNone(job.imdb_id_manual)
        self.assertEqual(job.poster_url, "https://covers.openlibrary.org/b/id/555-L.jpg")
        self.assertEqual(job.poster_url_manual, "https://covers.openlibrary.org/b/id/555-L.jpg")


class TestAudiobookTitleSearchHelpers(unittest.TestCase):
    def test_build_audiobook_query_joins_author_and_title(self):
        self.assertEqual(build_audiobook_query("Kindred", "Octavia Butler"), "Octavia Butler Kindred")

    def test_audiobook_cover_url_returns_none_without_cover_id(self):
        self.assertIsNone(audiobook_cover_url(""))

    def test_validate_title_search_input_requires_disc_for_audiobook(self):
        with self.assertRaises(ValueError):
            validate_title_search_input(None, {
                "media_type": "audiobook",
                "title": "Kindred",
                "audiobook_disc_number": "",
            })

    def test_validate_title_search_input_allows_manual_music_without_title(self):
        job = SimpleNamespace(
            manual_mode=True,
            status="waiting",
            manual_start=False,
            disctype="music",
        )

        validate_title_search_input(job, {
            "media_type": "music",
            "title": "",
        })

    def test_is_manual_audio_job_matches_waiting_music_and_audiobook_jobs(self):
        self.assertTrue(is_manual_audio_job(SimpleNamespace(
            manual_mode=True,
            status="waiting",
            manual_start=False,
            disctype="music",
        )))
        self.assertTrue(is_manual_audio_job(SimpleNamespace(
            manual_mode=True,
            status="waiting",
            manual_start=False,
            disctype="audiobook",
        )))
        self.assertFalse(is_manual_audio_job(SimpleNamespace(
            manual_mode=False,
            status="waiting",
            manual_start=False,
            disctype="music",
        )))


class TestJobDetailMetadata(unittest.TestCase):
    def test_audio_jobs_skip_video_metadata_lookup(self):
        job = SimpleNamespace(disctype="audiobook", title="Book", year=None, imdb_id=None)

        with patch("arm.ui.jobs.jobs.ui_utils.metadata_selector") as metadata_selector:
            metadata = get_jobdetail_metadata(job)

        metadata_selector.assert_not_called()
        self.assertEqual(metadata, {"Ratings": [], "Plot": "", "background_url": None})

    def test_video_jobs_use_video_metadata_lookup(self):
        job = SimpleNamespace(disctype="dvd", title="Movie", year="2020", imdb_id="tt123")
        expected = {"Ratings": [{"Source": "Internet Movie Database", "Value": "7/10"}]}

        with patch("arm.ui.jobs.jobs.ui_utils.metadata_selector", return_value=expected) as metadata_selector:
            metadata = get_jobdetail_metadata(job)

        metadata_selector.assert_called_once_with("get_details", "Movie", "2020", "tt123")
        self.assertEqual(metadata, expected)


if __name__ == '__main__':
    unittest.main()
