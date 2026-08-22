import pathlib
import tempfile
import unittest

from scripts.config_layout import (
    LayoutError,
    install_layout,
    preflight_install_layout,
    prepare_uninstall,
)

PROJECT = pathlib.Path(__file__).resolve().parents[1]


class ConfigLayoutIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.config_dir = self.root / "printer_data" / "config"
        self.config_dir.mkdir(parents=True)
        self.printer_cfg = self.config_dir / "printer.cfg"
        self.moonraker_cfg = self.config_dir / "moonraker.conf"
        self.printer_cfg.write_text("[include mainsail.cfg]\n", encoding="utf-8")
        self.moonraker_cfg.write_text(
            "[server]\nhost: 0.0.0.0\n", encoding="utf-8"
        )
        self.source_cfg = PROJECT / "tool_vision.cfg"

    def tearDown(self):
        self.temporary.cleanup()

    def _backup(self, name):
        return (
            self.root
            / "printer_data"
            / "config_backups"
            / "tool-vision"
            / name
        )

    def _install(self, backup_name="install-1"):
        return install_layout(
            config_dir=self.config_dir,
            config_source=self.source_cfg,
            printer_config=self.printer_cfg,
            moonraker_config=self.moonraker_cfg,
            backup_dir=self._backup(backup_name),
        )

    def test_fresh_install_prepares_file_and_never_edits_machine_configs(self):
        before_printer = self.printer_cfg.read_bytes()
        before_moonraker = self.moonraker_cfg.read_bytes()

        backup = self._install()

        target = self.config_dir / "tool_vision.cfg"
        self.assertEqual(target.read_bytes(), self.source_cfg.read_bytes())
        self.assertEqual(self.printer_cfg.read_bytes(), before_printer)
        self.assertEqual(self.moonraker_cfg.read_bytes(), before_moonraker)
        self.assertEqual(
            (backup / "machine-config" / "printer.cfg").read_bytes(),
            before_printer,
        )
        self.assertEqual(
            (backup / "machine-config" / "moonraker.conf").read_bytes(),
            before_moonraker,
        )

    def test_custom_printer_config_places_editable_file_beside_it(self):
        custom_dir = self.config_dir / "machine-a"
        custom_dir.mkdir()
        custom_printer = custom_dir / "printer.cfg"
        custom_printer.write_text("[include base.cfg]\n", encoding="utf-8")
        legacy_state = self.config_dir / "tool_vision_state.json"
        legacy_state.write_text('{"schema_version": 2}\n', encoding="utf-8")

        backup = install_layout(
            config_dir=self.config_dir,
            config_source=self.source_cfg,
            printer_config=custom_printer,
            moonraker_config=self.moonraker_cfg,
            backup_dir=self._backup("custom-printer"),
        )

        self.assertEqual(
            (custom_dir / "tool_vision.cfg").read_bytes(),
            self.source_cfg.read_bytes(),
        )
        self.assertFalse((self.config_dir / "tool_vision.cfg").exists())
        self.assertEqual(
            (custom_dir / "tool_vision_state.json").read_bytes(),
            legacy_state.read_bytes(),
        )
        self.assertTrue(
            (backup / "legacy" / "config-root" / legacy_state.name).is_file()
        )

    def test_upgrade_copies_legacy_files_but_keeps_manual_layout_intact(self):
        recent_dir = self.config_dir / "Printer-Setup"
        legacy_dir = self.config_dir / "Tool-Vision"
        recent_dir.mkdir()
        legacy_dir.mkdir()
        preferred_cfg = "[tool_vision]\npin: ^RECENT\n"
        (recent_dir / "tool_vision.cfg").write_text(
            preferred_cfg, encoding="utf-8"
        )
        (recent_dir / "tool_vision_state.json").write_text(
            '{"schema_version": 2}\n', encoding="utf-8"
        )
        (legacy_dir / "tool_vision.cfg").write_text(
            "[tool_vision]\npin: ^OLDER\n", encoding="utf-8"
        )
        (legacy_dir / "tool_vision_results.json").write_text(
            '{"schema_version": 1}\n', encoding="utf-8"
        )
        (legacy_dir / "moonraker_update_manager.conf").write_text(
            "[update_manager tool-vision]\npath: /old\n", encoding="utf-8"
        )
        old_printer = (
            "[include mainsail.cfg]\n[include Tool-Vision/tool_vision.cfg]\n"
        )
        old_moonraker = (
            "[server]\n"
            "[include Tool-Vision/moonraker_update_manager.conf]\n"
        )
        self.printer_cfg.write_text(old_printer, encoding="utf-8")
        self.moonraker_cfg.write_text(old_moonraker, encoding="utf-8")

        backup = self._install()

        new_dir = self.config_dir
        self.assertEqual(
            (new_dir / "tool_vision.cfg").read_text(encoding="utf-8"),
            preferred_cfg,
        )
        self.assertTrue((new_dir / "tool_vision_state.json").is_file())
        self.assertTrue((new_dir / "tool_vision_results.json").is_file())
        self.assertTrue(legacy_dir.is_dir())
        self.assertTrue(recent_dir.is_dir())
        self.assertTrue((legacy_dir / "tool_vision.cfg").is_file())
        self.assertEqual(self.printer_cfg.read_text(encoding="utf-8"), old_printer)
        self.assertEqual(
            self.moonraker_cfg.read_text(encoding="utf-8"), old_moonraker
        )
        self.assertTrue(
            (backup / "legacy" / "Tool-Vision" / "tool_vision.cfg").is_file()
        )
        self.assertTrue(
            (backup / "legacy" / "Printer-Setup" / "tool_vision.cfg").is_file()
        )
        self.assertTrue(
            (
                backup
                / "legacy"
                / "Tool-Vision"
                / "moonraker_update_manager.conf"
            ).is_file()
        )

    def test_conflicting_legacy_data_is_backed_up_and_preserved(self):
        new_dir = self.config_dir
        old_dir = self.config_dir / "Tool-Vision"
        old_dir.mkdir()
        (new_dir / "tool_vision.cfg").write_text(
            "[tool_vision]\npin: ^NEW\n", encoding="utf-8"
        )
        (old_dir / "tool_vision.cfg").write_text(
            "[tool_vision]\npin: ^OLD\n", encoding="utf-8"
        )
        (new_dir / "tool_vision_state.json").write_text(
            "new-state\n", encoding="utf-8"
        )
        (old_dir / "tool_vision_state.json").write_text(
            "old-state\n", encoding="utf-8"
        )

        backup = self._install()

        self.assertEqual(
            (new_dir / "tool_vision.cfg").read_text(encoding="utf-8"),
            "[tool_vision]\npin: ^NEW\n",
        )
        self.assertEqual(
            (old_dir / "tool_vision.cfg").read_text(encoding="utf-8"),
            "[tool_vision]\npin: ^OLD\n",
        )
        self.assertEqual(
            (old_dir / "tool_vision_state.json").read_text(encoding="utf-8"),
            "old-state\n",
        )
        self.assertTrue(
            (backup / "legacy" / "Tool-Vision" / "tool_vision.cfg").is_file()
        )
        self.assertTrue(
            (
                backup
                / "current"
                / "tool_vision_state.json"
            ).is_file()
        )

    def test_repeated_install_is_safe_and_creates_a_new_local_backup(self):
        self._install("install-1")
        target = self.config_dir / "tool_vision.cfg"
        first_target = target.read_bytes()
        first_printer = self.printer_cfg.read_bytes()
        first_moonraker = self.moonraker_cfg.read_bytes()

        second_backup = self._install("install-2")

        self.assertEqual(target.read_bytes(), first_target)
        self.assertEqual(self.printer_cfg.read_bytes(), first_printer)
        self.assertEqual(self.moonraker_cfg.read_bytes(), first_moonraker)
        self.assertTrue(
            (second_backup / "machine-config" / "printer.cfg").is_file()
        )
        self.assertTrue(
            (
                second_backup
                / "current"
                / "tool_vision.cfg"
            ).is_file()
        )

    def test_existing_moonraker_updater_sections_are_not_changed(self):
        content = (
            "[server]\n"
            "[update_manager]\n"
            "enable_auto_refresh: True\n"
            "[update_manager tool-vision]\n"
            "path: /home/test/Tool-Vision\n"
        )
        self.moonraker_cfg.write_text(content, encoding="utf-8")

        self._install()

        self.assertEqual(self.moonraker_cfg.read_text(encoding="utf-8"), content)

    def test_explicit_data_paths_disable_default_data_copy(self):
        new_dir = self.config_dir
        old_dir = self.config_dir / "Tool-Vision"
        old_dir.mkdir()
        (new_dir / "tool_vision.cfg").write_text(
            "[tool_vision]\nstate_file: /custom/state.json\n"
            "result_file: /custom/result.json\n",
            encoding="utf-8",
        )
        (old_dir / "tool_vision_state.json").write_text(
            "old-state\n", encoding="utf-8"
        )
        (old_dir / "tool_vision_results.json").write_text(
            "old-result\n", encoding="utf-8"
        )

        self._install()

        self.assertFalse((new_dir / "tool_vision_state.json").exists())
        self.assertFalse((new_dir / "tool_vision_results.json").exists())
        self.assertTrue((old_dir / "tool_vision_state.json").is_file())

    def test_uninstall_stops_until_manual_integrations_are_removed(self):
        self._install("install")
        self.printer_cfg.write_text(
            "[include *.cfg]\n", encoding="utf-8"
        )
        self.moonraker_cfg.write_text(
            "[server]\n[update_manager tool-vision]\ntype: git_repo\n",
            encoding="utf-8",
        )
        blocked_backup = self._backup("uninstall-blocked")

        with self.assertRaises(LayoutError):
            prepare_uninstall(
                config_dir=self.config_dir,
                printer_config=self.printer_cfg,
                moonraker_config=self.moonraker_cfg,
                backup_dir=blocked_backup,
            )

        self.assertTrue(
            (blocked_backup / "machine-config" / "printer.cfg").is_file()
        )
        self.printer_cfg.write_text("[include mainsail.cfg]\n", encoding="utf-8")
        self.moonraker_cfg.write_text("[server]\n", encoding="utf-8")
        ready_backup = self._backup("uninstall-ready")
        prepare_uninstall(
            config_dir=self.config_dir,
            printer_config=self.printer_cfg,
            moonraker_config=self.moonraker_cfg,
            backup_dir=ready_backup,
        )
        self.assertTrue(
            (
                self.config_dir
                / "tool_vision.cfg"
            ).is_file()
        )

    def test_backup_directory_inside_config_root_is_rejected(self):
        with self.assertRaises(LayoutError):
            install_layout(
                config_dir=self.config_dir,
                config_source=self.source_cfg,
                printer_config=self.printer_cfg,
                moonraker_config=self.moonraker_cfg,
                backup_dir=self.config_dir / "backups" / "install",
            )

    def test_preflight_checks_layout_without_modifying_files(self):
        before_printer = self.printer_cfg.read_bytes()
        before_moonraker = self.moonraker_cfg.read_bytes()
        target = self.config_dir / "tool_vision.cfg"

        preflight_install_layout(
            config_dir=self.config_dir,
            config_source=self.source_cfg,
            printer_config=self.printer_cfg,
            moonraker_config=self.moonraker_cfg,
            backup_dir=self._backup("preflight"),
        )

        self.assertFalse(target.exists())
        self.assertFalse(self._backup("preflight").exists())
        self.assertEqual(self.printer_cfg.read_bytes(), before_printer)
        self.assertEqual(self.moonraker_cfg.read_bytes(), before_moonraker)


if __name__ == "__main__":
    unittest.main()
