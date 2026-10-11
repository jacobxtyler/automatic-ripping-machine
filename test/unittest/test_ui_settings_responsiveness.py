import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/opt/arm")

from arm.ui import app  # noqa: E402
from arm.ui.settings import settings as settings_module  # noqa: E402


class TestSettingsResponsiveness(unittest.TestCase):
    def setUp(self):
        app.config["LOGIN_DISABLED"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        settings_module._diagnostics_cache = None
        settings_module._diagnostics_cache_time = 0.0
        settings_module._drive_operation_locks.clear()

    @patch.object(settings_module, "render_template")
    @patch.object(settings_module, "is_read_only", return_value=False)
    @patch.object(settings_module, "SystemInfoDrives")
    @patch.object(settings_module, "SettingsForm")
    @patch.object(settings_module, "ServerUtil")
    @patch.object(settings_module.SystemInfo, "query")
    @patch.object(settings_module.Job, "query")
    @patch.object(settings_module.ui_utils, "generate_comments", return_value={})
    @patch.object(settings_module.ui_utils, "arm_db_cfg", return_value={})
    @patch.object(settings_module.drive_utils, "get_drives", return_value=[])
    @patch.object(settings_module.drive_utils, "update_tray_status")
    @patch.object(settings_module.drive_utils, "update_job_status")
    @patch.object(settings_module.ui_utils, "git_check_version")
    @patch.object(settings_module.ui_utils, "get_git_revision_hash")
    @patch.object(settings_module.ui_utils, "git_check_updates")
    @patch.object(settings_module, "check_hw_transcode_support")
    def test_settings_does_not_run_slow_or_mutating_checks(
            self, hw_check, update_check, git_hash, version_check, update_jobs, update_trays,
            get_drives, arm_db_cfg, generate_comments, job_query, system_query, server_util,
            settings_form, drive_form, is_read_only, render_template):
        job_query.filter_by.return_value.count.return_value = 0
        system_query.filter_by.return_value.first.return_value = MagicMock()
        render_template.return_value = "rendered"

        with app.test_request_context("/settings"):
            result = settings_module.settings.__wrapped__()

        self.assertEqual(result, "rendered")
        update_trays.assert_not_called()
        update_jobs.assert_not_called()
        version_check.assert_not_called()
        git_hash.assert_not_called()
        update_check.assert_not_called()
        hw_check.assert_not_called()

    @patch.object(settings_module.SystemDrives, "query")
    def test_active_job_toggle_does_not_probe_hardware(self, drive_query):
        drive = MagicMock(job_id_current=42)
        drive_query.filter_by.return_value.one.return_value = drive

        with app.test_request_context("/drive/eject/1"):
            response = settings_module.drive_eject.__wrapped__("1")

        self.assertEqual(response.status_code, 302)
        drive.tray_status.assert_not_called()
        drive.eject.assert_not_called()

    @patch.object(settings_module.SystemDrives, "query")
    def test_idle_drive_toggle_is_guarded(self, drive_query):
        drive = MagicMock(job_id_current=None)
        drive_query.filter_by.return_value.one.return_value = drive
        operation_lock = threading.Lock()
        operation_lock.acquire()

        with patch.object(settings_module, "_drive_operation_lock", return_value=operation_lock):
            with app.test_request_context("/drive/eject/1"):
                response = settings_module.drive_eject.__wrapped__("1")

        self.assertEqual(response.status_code, 302)
        drive.eject.assert_not_called()
        operation_lock.release()

    @patch.object(settings_module.SystemDrives, "query")
    def test_idle_drive_toggle_remains_available(self, drive_query):
        drive = MagicMock(job_id_current=None)
        drive.eject.return_value = None
        drive_query.filter_by.return_value.one.return_value = drive

        with app.test_request_context("/drive/eject/1"):
            response = settings_module.drive_eject.__wrapped__("1")

        self.assertEqual(response.status_code, 302)
        drive.eject.assert_called_once_with(method="toggle")


class TestDiagnostics(unittest.TestCase):
    def setUp(self):
        app.config["LOGIN_DISABLED"] = True
        settings_module._diagnostics_cache = None
        settings_module._diagnostics_cache_time = 0.0

    def test_collect_diagnostics_success(self):
        with patch.object(settings_module, "_read_local_version", return_value="2.0"), \
                patch.object(settings_module, "_read_remote_version", return_value="2.1"), \
                patch.object(settings_module, "_read_git_commit", return_value="abc1234"), \
                patch.object(settings_module, "_read_remote_commit", return_value="def5678"), \
                patch.object(settings_module, "_probe_hw_transcode_support",
                             return_value={"intel": True, "nvidia": False, "amd": True}):
            result = settings_module._collect_diagnostics()

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["update_available"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["hw_support"]["intel"])
        self.assertFalse(result["hw_support"]["nvidia"])

    def test_collect_diagnostics_preserves_partial_results(self):
        with patch.object(settings_module, "_read_local_version", return_value="2.0"), \
                patch.object(settings_module, "_read_remote_version",
                             side_effect=subprocess.TimeoutExpired("git", 10)), \
                patch.object(settings_module, "_read_git_commit", return_value="abc1234"), \
                patch.object(settings_module, "_read_remote_commit",
                             side_effect=settings_module.requests.Timeout()), \
                patch.object(settings_module, "_probe_hw_transcode_support",
                             side_effect=subprocess.TimeoutExpired("HandBrakeCLI", 10)):
            result = settings_module._collect_diagnostics()

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["local_version"], "2.0")
        self.assertIsNone(result["remote_version"])
        self.assertIsNone(result["update_available"])
        self.assertEqual(result["hw_support"], {"intel": None, "nvidia": None, "amd": None})
        self.assertEqual(result["errors"], ["remote_version", "update", "hw_support"])

    def test_collect_diagnostics_reports_unavailable(self):
        failure = OSError("unavailable")
        with patch.object(settings_module, "_read_local_version", side_effect=failure), \
                patch.object(settings_module, "_read_remote_version", side_effect=failure), \
                patch.object(settings_module, "_read_git_commit", side_effect=failure), \
                patch.object(settings_module, "_read_remote_commit",
                             side_effect=settings_module.requests.Timeout()), \
                patch.object(settings_module, "_probe_hw_transcode_support", side_effect=failure):
            result = settings_module._collect_diagnostics()

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["update_available"])
        self.assertTrue(all(value is None for value in result["hw_support"].values()))

    def test_diagnostics_endpoint_reuses_five_minute_cache(self):
        cached = settings_module._unknown_diagnostics(status="ready")
        cached["local_version"] = "cached"
        settings_module._diagnostics_cache = cached
        settings_module._diagnostics_cache_time = 100.0

        with patch.object(settings_module.time, "monotonic", return_value=399.0), \
                patch.object(settings_module, "_collect_diagnostics") as collect:
            with app.test_request_context("/settings/diagnostics"):
                response = settings_module.settings_diagnostics.__wrapped__()

        self.assertEqual(response.get_json()["local_version"], "cached")
        collect.assert_not_called()

    def test_concurrent_refresh_returns_immediately(self):
        settings_module._diagnostics_refresh_lock.acquire()
        try:
            with app.test_request_context("/settings/diagnostics"):
                response = settings_module.settings_diagnostics.__wrapped__()
        finally:
            settings_module._diagnostics_refresh_lock.release()

        result = response.get_json()
        self.assertEqual(result["status"], "refreshing")
        self.assertIsNone(result["hw_support"]["intel"])

    def test_diagnostics_ui_has_tri_state_labels(self):
        script = Path("/opt/arm/arm/ui/static/js/diagnostics.js").read_text(encoding="utf-8")
        template = Path(
            "/opt/arm/arm/ui/settings/templates/settings/sysinfo.html"
        ).read_text(encoding="utf-8")

        self.assertIn("Checking...", template)
        for label in ("Supported", "Unsupported", "Unavailable"):
            self.assertIn(label, script)


if __name__ == "__main__":
    unittest.main()
