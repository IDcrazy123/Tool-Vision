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

    def test_installer_links_every_extension_module_and_uses_v2_health(self):
        installer = (PROJECT / "install.sh").read_text(encoding="utf-8")
        for module in (
            "tool_vision.py", "tool_vision_client.py", "tool_vision_state.py",
            "tool_vision_toolchanger.py",
        ):
            self.assertIn(module, installer)
        self.assertIn("/api/v2/health", installer)
        self.assertNotIn("git clone", installer)

    def test_systemd_arguments_match_app_parser(self):
        unit = (PROJECT / "server" / "tool-vision.service.in").read_text(
            encoding="utf-8"
        )
        self.assertIn("--log-directory", unit)
        self.assertIn("WorkingDirectory=@PROJECT_DIR@", unit)


if __name__ == "__main__":
    unittest.main()
