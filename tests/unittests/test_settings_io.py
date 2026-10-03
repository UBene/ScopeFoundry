from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from qtpy import QtWidgets

from ScopeFoundry import BaseMicroscopeApp, HardwareComponent, Measurement, ini_io
from ScopeFoundry.base_app.base_app import WRITE_RES
from ScopeFoundry.base_app.state_history import StateHistory


class Measure1(Measurement):
    name = "measure1"

    def setup(self):
        self.settings.New("string", str, ro=True, initial="0")
        self.settings.New("float", float, ro=True, initial=0.0)
        self.settings.New("choices", int, choices=INITIAL_CHOICES)
        self.settings.New("array", bool, is_array=True, initial=[False, False, False])


class Hardware1(HardwareComponent):
    name = "hardware1"

    def setup(self):
        self.settings.New("string", str, ro=True, initial="0")
        self.settings.New("float", float, ro=True, initial=0.0)
        self.settings.New("choices", int, choices=INITIAL_CHOICES)
        self.settings.New("protected_int", int, initial=0, protected=True)


INITIAL_CHOICES = [("choice 0", 0), ("choice 1", 1), ("choice 2", 2), ("choice 3", 3)]


class SettingsIOTest(unittest.TestCase):

    def setUp(self):
        self.app = BaseMicroscopeApp([])
        self.ms = self.app.add_measurement(Measure1(self.app))
        self.hw = self.app.add_hardware(Hardware1(self.app))
        self.root = Path(__file__).parent

        self.mms = self.ms.settings
        self.hws = self.hw.settings

    def test_initial_value_set(self):
        self.assertEqual(self.mms["string"], "0")
        self.assertEqual(self.mms["float"], 0.0)
        self.assertEqual(self.mms["choices"], 0)
        self.assertTrue(np.all(self.mms["array"] == np.array([False, False, False])))
        self.assertEqual(self.hws["string"], "0")
        self.assertEqual(self.hws["float"], 0.0)
        self.assertEqual(self.hws["choices"], 0)

    def test_all_correct(self):
        self.app.settings_load_ini(
            self.root / "settings_io_test_correct.ini",
            show_report=False,
        )
        self.assertEqual(self.mms["string"], "1")
        self.assertEqual(self.mms["float"], 1.0)
        self.assertEqual(self.mms["choices"], 1)
        self.assertEqual(self.hws["string"], "1")
        self.assertEqual(self.hws["float"], 1.0)
        self.assertEqual(self.hws["choices"], 1)
        self.assertEqual(self.hws["protected_int"], 0)

    def test_first_section_wrong_and_continue(self):
        self.app.settings_load_ini(
            self.root / "settings_io_test_measure1_false.ini", show_report=False
        )
        self.assertEqual(self.hws["string"], "2")
        self.assertEqual(self.hws["float"], 2.0)
        self.assertEqual(self.hws["choices"], 2)

    def test_reporting(self):
        self.app.settings_load_ini(
            self.root / "settings_io_test_measure1_false_2.ini", show_report=False
        )
        self.assertTrue("meeeeeeasurement/measure1/straaaaang" in self.app._report)
        self.assertTrue(
            self.app._report["meeeeeeasurement/measure1/straaaaang"]
            is WRITE_RES.MISSING
        )
        self.assertTrue(
            self.app._report["hardware/hardware1/protected_int"], "PROTECTED"
        )

    def test_first_section_wrong_and_continue(self):
        fname = self.root / "settings_io_test_measure1_false_2.ini"
        self.app.settings_load_ini(fname, show_report=False)
        self.assertTrue("meeeeeeasurement/measure1/straaaaang" in self.app._report)
        self.assertTrue(
            self.app._report["meeeeeeasurement/measure1/straaaaang"]
            is WRITE_RES.MISSING
        )

        self.assertEqual(self.hws["string"], "2")
        self.assertEqual(self.hws["float"], 2.0)
        self.assertEqual(self.hws["choices"], 2)

    def test_first_setting_misspelled_and_continue(self):
        self.app.settings_load_ini(
            self.root / "settings_io_test_measure1_string_false.ini",
            show_report=False,
        )
        # self.assertEqual(self.hw1["string"], "2")
        self.assertEqual(self.hws["float"], 2.0)
        self.assertEqual(self.hws["choices"], 2)

    def test_roundtrip(self):

        # all values are initial values
        self.app.settings_save_ini(self.root / "settings_io_test_roundtrip.ini")

        # change them up
        self.mms["string"] = "1"
        self.mms["float"] = 1.0
        self.mms["choices"] = 1
        self.mms["array"] = np.array([False, False, True])
        self.hws["string"] = "1"
        self.hws["float"] = 1.0
        self.hws["choices"] = 1

        # make sure they are changed
        self.assertFalse(np.all(self.mms["array"] == np.array([False, False, False])))

        # load values
        self.app.settings_load_ini(
            self.root / "settings_io_test_roundtrip.ini", show_report=False
        )
        self.assertEqual(self.mms["string"], "0")
        self.assertEqual(self.mms["float"], 0.0)
        self.assertEqual(self.mms["choices"], 0)
        self.assertTrue(np.all(self.mms["array"] == np.array([False, False, False])))
        self.assertEqual(self.hws["string"], "0")
        self.assertEqual(self.hws["float"], 0.0)
        self.assertEqual(self.hws["choices"], 0)

    def test_profile_saves_selected_components_and_window_positions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.app.profile_manager.profiles_dir = Path(temp_dir)
            self.app.settings["sample"] = "not saved"
            self.hws["float"] = 2.0
            self.hws["choices"] = 1
            self.mms["float"] = 3.0

            self.app.profile_manager.save_profile(
                "test profile",
                setting_paths=["hw/hardware1/choices", "hw/hardware1/float"],
            )

            profile_dir = Path(temp_dir) / "test profile"
            self.assertTrue((profile_dir / "settings.ini").is_file())
            self.assertTrue((profile_dir / "window_positions.json").is_file())
            self.hws["float"] = 4.0
            self.hws["choices"] = 3
            self.mms["float"] = 5.0
            self.app.settings["sample"] = "changed"

            self.app.profile_manager.load_profile("test profile")

            self.assertEqual(self.hws["float"], 4.0)
            self.assertEqual(self.hws["choices"], 1)
            self.assertEqual(self.mms["float"], 5.0)
            self.assertEqual(self.app.settings["sample"], "changed")

    def test_profile_settings_tree_cascades_component_checks(self):
        tree, components, settings = self.app.profile_manager._make_settings_tree(
            "measure1"
        )
        hardware_item = components["hw/hardware1"]
        measurement_item = components["mm/measure1"]

        self.assertEqual(hardware_item.checkState(0).value, 0)
        self.assertEqual(measurement_item.checkState(0).value, 2)
        self.assertFalse(hardware_item.isExpanded())
        self.assertTrue(measurement_item.isExpanded())
        self.assertTrue(
            all(
                item.checkState(0).value == 2
                for path, item in settings.items()
                if path.startswith("mm/measure1/") and not item.isDisabled()
            )
        )
        for path in ("mm/measure1/string", "mm/measure1/float"):
            self.assertTrue(settings[path].isDisabled())
            self.assertEqual(settings[path].checkState(0).value, 0)

        hardware_item.setCheckState(0, hardware_item.checkState(0).Checked)
        self.assertTrue(
            all(
                item.checkState(0).value == 2
                for path, item in settings.items()
                if path.startswith("hw/hardware1/") and not item.isDisabled()
            )
        )
        for path in ("hw/hardware1/string", "hw/hardware1/float"):
            self.assertTrue(settings[path].isDisabled())
            self.assertEqual(settings[path].checkState(0).value, 0)

        settings["hw/hardware1/choices"].setCheckState(
            0, settings["hw/hardware1/choices"].checkState(0).Unchecked
        )
        self.assertEqual(hardware_item.checkState(0).value, 1)

    def test_update_selected_profile_preserves_settings_subset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.app.profile_manager.profiles_dir = Path(temp_dir)
            self.hws["choices"] = 1
            self.hws["float"] = 2.0
            self.app.profile_manager.save_profile(
                "selected profile", setting_paths=["hw/hardware1/choices"]
            )

            self.assertEqual(
                self.app.profile_manager.selected_profile_name, "selected profile"
            )
            self.assertEqual(
                self.app.profile_manager._read_selected_profile(), "selected profile"
            )
            self.hws["choices"] = 2
            self.hws["float"] = 3.0
            self.app.profile_manager.update_selected_profile()

            profile_settings = ini_io.load_settings(
                Path(temp_dir) / "selected profile" / "settings.ini"
            )
            self.assertEqual(list(profile_settings), ["hw/hardware1/choices"])
            self.hws["choices"] = 3
            self.app.profile_manager.load_profile("selected profile")
            self.assertEqual(self.hws["choices"], 2)
            self.assertEqual(self.hws["float"], 3.0)

    def test_delete_selected_profile_clears_saved_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.app.profile_manager.profiles_dir = Path(temp_dir)
            self.app.profile_manager.save_profile("selected profile", setting_paths=[])

            with patch(
                "ScopeFoundry.base_app.base_microscope_app.QtWidgets.QMessageBox.question",
                return_value=QtWidgets.QMessageBox.StandardButton.Yes,
            ):
                self.app.profile_manager.delete_selected_profile()

            self.assertFalse((Path(temp_dir) / "selected profile").exists())
            self.assertFalse((Path(temp_dir) / ".last_selected_profile").exists())
            self.assertEqual(self.app.profile_manager.selected_profile_name, "")

    def test_history_restores_state_and_retains_configured_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history = self.app.profile_manager.history
            history.history_dir = Path(temp_dir) / "history"
            self.hws["choices"] = 1
            first_entry = history.save_snapshot("checkpoint")
            self.hws["choices"] = 2
            history.restore_snapshot(first_entry.name)
            self.assertEqual(self.hws["choices"], 1)

            for index in range(history.max_entries + 1):
                self.hws["choices"] = index % 4
                history.save_snapshot(f"checkpoint {index}")
            self.assertEqual(len(history._entry_paths()), history.max_entries)
            reloaded_history = StateHistory(self.app, history.history_dir)
            self.assertEqual(len(reloaded_history._entry_paths()), history.max_entries)

    def test_history_menu_item_restores_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history = self.app.profile_manager.history
            history.history_dir = Path(temp_dir) / "history"
            self.hws["choices"] = 1
            entry = history.save_snapshot("menu checkpoint")
            self.hws["choices"] = 3

            history.refresh_menu()
            history_action = next(
                action
                for action in history.history_menu.actions()
                if action.data() == entry.name
            )
            history_action.trigger()

            self.assertEqual(self.hws["choices"], 1)

    def test_undo_is_a_top_level_menu_action(self):
        history = self.app.profile_manager.history
        with tempfile.TemporaryDirectory() as temp_dir:
            history.history_dir = Path(temp_dir) / "history"
            history.save_snapshot("tooltip checkpoint")
            history.refresh_menu()

            latest_history_item = history.history_menu.actions()[0]
            self.assertFalse(history.undo_action.icon().isNull())
            self.assertEqual(history.undo_action.toolTip(), latest_history_item.text())
            self.assertEqual(
                history.undo_action.statusTip(), latest_history_item.text()
            )

        self.assertIn(history.undo_action, self.app.ui.menubar.actions())
        self.assertEqual(history.undo_action.text(), "Undo")
        self.assertEqual(history.undo_action.shortcut().toString(), "Ctrl+Z")
        self.assertFalse(
            any(
                action.text().startswith("Undo")
                for action in history.history_menu.actions()
            )
        )

    def test_measurement_start_button_records_history(self):
        history = self.app.profile_manager.history
        button = self.ms.new_start_stop_button()
        with (
            patch.object(history, "save_snapshot") as save_snapshot,
            patch.object(self.ms, "_start") as start_measurement,
        ):
            button.click()

        start_measurement.assert_called_once_with()
        save_snapshot.assert_called_once_with(
            "mm/measure1/activation False -> True"
        )

    def test_nested_measurement_start_skips_history(self):
        history = self.app.profile_manager.history
        nested = self.app.measurements["measure1"]
        with (
            patch.object(nested, "_start") as start_measurement,
            patch.object(nested, "is_measuring", side_effect=[True, False]),
            patch.object(history, "save_snapshot") as save_snapshot,
        ):
            self.ms.start_nested_measure_and_wait(nested)

        start_measurement.assert_called_once_with()
        save_snapshot.assert_not_called()

    def test_settings_autosave_records_history(self):
        history = self.app.profile_manager.history
        with (
            patch.object(self.app, "settings_save_ini") as save_settings,
            patch.object(history, "save_snapshot") as save_snapshot,
        ):
            self.app.settings_auto_save_ini()

        save_settings.assert_called_once()
        save_snapshot.assert_called_once_with("Settings autosaved")

    def test_app_close_records_history_before_disconnect(self):
        history = self.app.profile_manager.history
        with (
            patch.object(history, "save_snapshot") as save_snapshot,
            patch.object(
                self.hw.settings, "disconnect_all_from_hardware"
            ) as disconnect,
        ):
            self.app.on_close()

        save_snapshot.assert_called_once_with("Application closing")
        disconnect.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
