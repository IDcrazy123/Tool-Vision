import configparser
import pathlib
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]


class RewriteContracts(unittest.TestCase):
    def test_example_cfg_has_no_required_camera_or_tuning_values(self):
        parser = configparser.RawConfigParser(
            allow_no_value=True, inline_comment_prefixes=("#", ";"), strict=True
        )
        loaded = parser.read(PROJECT / "tool_vision.cfg", encoding="utf-8")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(parser.options("tool_vision"), [])
        self.assertEqual(
            parser.sections(),
            [
                "tool_vision",
                "gcode_macro TV_STATUS",
                "gcode_macro TV_SETUP_CAMERA",
                "gcode_macro TV_SETUP_SWITCH",
                "gcode_macro TV_CALIBRATE",
                "gcode_macro TV_REPORT",
            ],
        )

    def test_old_detector_and_station_tuning_are_absent_from_active_extension(self):
        source = (PROJECT / "klippy" / "extras" / "tool_vision.py").read_text(
            encoding="utf-8"
        )
        for obsolete in (
            "camera_x_pos", "zswitch_x_pos", "detector_gamma",
            "detector_sensitivity", "camera_min_focus_score", "camera_roi_x_min",
            "tool_numbers",
        ):
            self.assertNotIn('config.get("%s"' % obsolete, source)

    def test_server_keeps_native_resolution_and_no_magic_focus_gate(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT / "server").glob("*.py")
        )
        self.assertNotIn("cv2.resize", source)
        self.assertNotIn("focus_ok", source)
        self.assertNotIn("min_focus", source)

    def test_measurement_does_not_modify_production_offsets(self):
        source = (PROJECT / "klippy" / "extras" / "tool_vision.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("SAVE_TOOL_PARAMETER", source)
        self.assertNotIn("SET_TOOL_PARAMETER", source)
        self.assertNotIn("SAVE_CONFIG", source)

    def test_installer_links_modules_and_registers_moonraker_runtime(self):
        installer = (PROJECT / "install.sh").read_text(encoding="utf-8")
        for module in (
            "tool_vision.py", "tool_vision_client.py", "tool_vision_state.py",
            "tool_vision_toolchanger.py",
        ):
            self.assertIn(module, installer)
        self.assertIn("/api/v2/health", installer)
        self.assertIn('systemctl restart "${SERVICE_NAME}"', installer)
        self.assertIn('RUNTIME_DIR="${SOURCE_DIR}"', installer)
        self.assertIn("moonraker_update_manager.conf", installer)
        self.assertIn('systemctl restart "${MOONRAKER_SERVICE}"', installer)
        self.assertIn("git clone --branch", installer)
        self.assertIn("status --porcelain", installer)
        self.assertIn("sudo -v", installer)
        self.assertIn("moonraker.asvc", installer)
        self.assertIn("grep -Fxq 'tool-vision'", installer)

        uninstaller = (PROJECT / "uninstall.sh").read_text(encoding="utf-8")
        self.assertIn("moonraker.asvc", uninstaller)
        self.assertIn("grep -Fvx 'tool-vision'", uninstaller)

    def test_moonraker_updater_tracks_git_runtime_and_managed_services(self):
        parser = configparser.RawConfigParser(strict=True)
        loaded = parser.read(
            PROJECT / "moonraker_update_manager.conf.in", encoding="utf-8"
        )
        self.assertEqual(len(loaded), 1)
        section = "update_manager tool-vision"
        self.assertIn("update_manager", parser.sections())
        self.assertEqual(parser.get(section, "type"), "git_repo")
        self.assertEqual(parser.get(section, "path"), "@REPO_DIR@")
        self.assertEqual(parser.get(section, "primary_branch"), "@PRIMARY_BRANCH@")
        self.assertEqual(parser.get(section, "virtualenv"), "@VIRTUALENV@")
        self.assertEqual(
            parser.get(section, "requirements"), "server/requirements.txt"
        )
        self.assertEqual(
            parser.get(section, "managed_services"), "tool-vision klipper"
        )

    def test_systemd_arguments_match_app_parser(self):
        unit = (PROJECT / "server" / "tool-vision.service.in").read_text(
            encoding="utf-8"
        )
        self.assertIn("--log-directory", unit)
        self.assertIn("WorkingDirectory=@PROJECT_DIR@", unit)


if __name__ == "__main__":
    unittest.main()
