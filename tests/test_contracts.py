import configparser
import pathlib
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_example_config_has_one_valid_tool_vision_section(self):
        parser = configparser.RawConfigParser(
            allow_no_value=True,
            inline_comment_prefixes=("#", ";"),
            strict=True,
        )
        loaded = parser.read(PROJECT / "tool_vision.cfg", encoding="utf-8")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(parser.sections(), ["tool_vision"])
        self.assertEqual(parser.get("tool_vision", "camera_width"), "0")
        self.assertEqual(parser.get("tool_vision", "camera_height"), "0")

    def test_server_has_no_forced_resize_or_fixed_frame_constants(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT / "server").glob("*.py")
        )
        self.assertNotIn("cv2.resize", source)
        self.assertNotIn("FRAME_WIDTH =", source)
        self.assertNotIn("FRAME_HEIGHT =", source)

    def test_klipper_extension_does_not_rewrite_printer_config(self):
        source = (PROJECT / "klippy" / "extras" / "tool_vision.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("SAVE_TOOL_PARAMETER", source)
        self.assertNotIn("SAVE_CONFIG", source)
        self.assertNotIn("printer.cfg", source)

    def test_installer_persists_runtime_without_git_clone(self):
        installer = (PROJECT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("printer_data/tool-vision", installer)
        self.assertIn("RUNTIME_DIR}/klippy/extras/tool_vision.py", installer)
        self.assertIn("RUNTIME_DIR}/server/requirements.txt", installer)
        self.assertNotIn("git clone", installer)
        self.assertNotIn("Axiscope", installer)
        self.assertNotIn("kTAMV", installer)

    def test_camera_station_is_not_fabricated_in_example_config(self):
        config = (PROJECT / "tool_vision.cfg").read_text(encoding="utf-8")
        for key in (
            "camera_x_pos:",
            "camera_y_pos:",
            "camera_z_pos:",
            "camera_safe_z:",
        ):
            active = [
                line for line in config.splitlines()
                if line.strip().startswith(key) and not line.lstrip().startswith("#")
            ]
            self.assertEqual(active, [])


if __name__ == "__main__":
    unittest.main()
