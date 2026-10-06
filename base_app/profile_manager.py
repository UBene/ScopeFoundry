import datetime
import inspect
import json
from functools import partial
from pathlib import Path
from shutil import rmtree
from typing import List

from qtpy import QtCore, QtGui, QtWidgets

from ScopeFoundry import h5_io, ini_io
from ScopeFoundry.base_app.state_history import StateHistory


class _ProposedValueDelegate(QtWidgets.QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() != 2:
            return None
        return super().createEditor(parent, option, index)


class _ProfileTreeHeader(QtWidgets.QHeaderView):
    def __init__(
        self,
        parent,
        take_current_values_callback,
        load_values_from_file_callback,
    ):
        super().__init__(QtCore.Qt.Orientation.Horizontal, parent)
        self._replace_label = QtWidgets.QLabel("To save", self.viewport())
        self._replace_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._replace_label.setFont(self.font())
        self._take_values_button = QtWidgets.QToolButton(self.viewport())
        self._take_values_button.setText("Take current values")
        self._take_values_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._take_values_button.setAutoRaise(True)
        self._load_file_button = QtWidgets.QToolButton(self.viewport())
        self._load_file_button.setText("Load from file")
        self._load_file_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._load_file_button.setAutoRaise(True)
        self._update_button_color()
        self._take_values_button.clicked.connect(
            lambda _checked=False: take_current_values_callback()
        )
        self._load_file_button.clicked.connect(
            lambda _checked=False: load_values_from_file_callback()
        )
        self.sectionResized.connect(self._position_controls)
        self.sectionMoved.connect(lambda *_args: self._position_controls())
        self.geometriesChanged.connect(self._position_controls)
        self._position_controls()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (
            QtCore.QEvent.Type.PaletteChange,
            QtCore.QEvent.Type.ApplicationPaletteChange,
        ):
            self._update_button_color()

    def _update_button_color(self):
        background = self.palette().color(QtGui.QPalette.ColorRole.Window)
        blue = "#0057B8" if background.lightness() > 127 else "#70BFFF"
        style = f"color: {blue};"
        self._take_values_button.setStyleSheet(style)
        self._load_file_button.setStyleSheet(style)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_controls()

    def _position_controls(self, *_args):
        logical_index = 2
        if self.count() <= logical_index or self.isSectionHidden(logical_index):
            self._replace_label.hide()
            self._take_values_button.hide()
            self._load_file_button.hide()
            return

        section_x = self.sectionViewportPosition(logical_index)
        section_width = self.sectionSize(logical_index)
        viewport_height = self.viewport().height()
        margin = 6
        spacing = 4
        take_button_width = self._take_values_button.sizeHint().width()
        file_button_width = self._load_file_button.sizeHint().width()
        button_height = max(
            self._take_values_button.sizeHint().height(),
            self._load_file_button.sizeHint().height(),
        )
        minimum_width = (
            self._replace_label.sizeHint().width()
            + take_button_width
            + file_button_width
            + 2 * margin
            + 2 * spacing
        )
        if section_width < minimum_width:
            self.resizeSection(logical_index, minimum_width)
            return
        label_width = max(
            0,
            section_width
            - 2 * margin
            - 2 * spacing
            - take_button_width
            - file_button_width,
        )
        self._replace_label.setGeometry(
            section_x + margin,
            0,
            label_width,
            viewport_height,
        )
        self._take_values_button.setGeometry(
            section_x + margin + label_width + spacing,
            max(0, (viewport_height - button_height) // 2),
            take_button_width,
            min(button_height, viewport_height),
        )
        self._load_file_button.setGeometry(
            section_x + margin + label_width + spacing + take_button_width + spacing,
            max(0, (viewport_height - button_height) // 2),
            file_button_width,
            min(button_height, viewport_height),
        )
        self._replace_label.setVisible(label_width > 0)
        self._take_values_button.setVisible(take_button_width > 0)
        self._load_file_button.setVisible(file_button_width > 0)


class ProfileManager:
    def __init__(self, app):
        self.app = app
        self.profiles_dir = self._profiles_dir_for_app()
        self.selected_profile_name = self._read_selected_profile()
        self.startup_profile_name = self._read_startup_profile()
        self.profile_menu = None
        self.history = StateHistory(app, self.profiles_dir / "history")

    def _app_implementation_dir(self):
        try:
            implementation_file = Path(inspect.getfile(type(self.app))).resolve()
        except (OSError, TypeError, ValueError):
            implementation_file = None
        if implementation_file is None or implementation_file.name.startswith("<"):
            return Path.cwd()
        return implementation_file.parent

    @staticmethod
    def _contains_profiles(profiles_dir: Path) -> bool:
        return profiles_dir.is_dir() and any(
            profile_dir.is_dir() and (profile_dir / "settings.ini").is_file()
            for profile_dir in profiles_dir.iterdir()
        )

    def _profiles_dir_for_app(self) -> Path:
        implementation_profiles = self._app_implementation_dir() / "profiles"
        if self._contains_profiles(implementation_profiles):
            return implementation_profiles
        return Path.cwd() / "profiles"

    def _app_implementation_ini_files(self):
        implementation_dir = self._app_implementation_dir()
        return sorted(
            path for path in implementation_dir.glob("*.ini") if path.is_file()
        )

    def initialize_startup_profile(self) -> None:
        """Load the startup profile or create it from a nearby INI file."""
        if self.startup_profile_name:
            self.load_profile(self.startup_profile_name)
            return

        startup_settings = self.profiles_dir / "start_up" / "settings.ini"
        if startup_settings.is_file():
            self._set_startup_profile("start_up")
            self.load_profile("start_up")
            return

        ini_files = self._app_implementation_ini_files()
        ini_file = None
        if len(ini_files) == 1:
            ini_file = ini_files[0]
        elif ini_files:
            names = [path.name for path in ini_files]
            selected_name, accepted = QtWidgets.QInputDialog.getItem(
                self.app.ui,
                "Choose startup settings",
                "Choose an INI file for the startup profile:",
                names,
                0,
                False,
            )
            if accepted:
                ini_file = ini_files[names.index(selected_name)]

        if ini_file is not None:
            answer = QtWidgets.QMessageBox.question(
                self.app.ui,
                "Create startup profile?",
                f"Create the 'start_up' profile from '{ini_file.name}'?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                try:
                    ini_settings = ini_io.load_settings(ini_file)
                except Exception as error:
                    QtWidgets.QMessageBox.warning(
                        self.app.ui,
                        "Could not read startup settings",
                        f"Could not read '{ini_file.name}': {error}\n"
                        "An empty startup profile will be created.",
                    )
                    self.save_profile("start_up", setting_paths=[])
                    self._set_startup_profile("start_up")
                    return
                setting_values = {
                    path: value
                    for path, value in ini_settings.items()
                    if path in self.app._setting_paths
                    and not self.app._setting_paths[path].ro
                }
                self.save_profile(
                    "start_up",
                    setting_paths=list(setting_values),
                    setting_values=setting_values,
                )
                self._set_startup_profile("start_up")
                self.load_profile("start_up")
                return

        # A blank startup profile also records the user's choice to skip an INI.
        self.save_profile("start_up", setting_paths=[])
        self._set_startup_profile("start_up")

    def setup_menu(self, menu_bar: QtWidgets.QMenuBar) -> None:
        self.profile_menu = menu_bar.addMenu("Profiles")
        background = self.profile_menu.palette().color(QtGui.QPalette.ColorRole.Window)
        blue = "#0057B8" if background.lightness() > 127 else "#70BFFF"
        self.profile_menu.setStyleSheet(f"QMenu::item:checked {{ color: {blue}; }}")
        self.refresh_menu()
        self.history.setup_menu(menu_bar)

    def refresh_menu(self) -> None:
        if self.profile_menu is None:
            return
        self.profile_menu.clear()
        self.profile_action_group = QtGui.QActionGroup(self.profile_menu)
        self.profile_action_group.setExclusive(True)
        for profile_name in self._profile_names():
            action = self.profile_menu.addAction(profile_name)
            action.setCheckable(True)
            action.setChecked(profile_name == self.selected_profile_name)
            action.triggered.connect(
                lambda _checked=False, name=profile_name: self.load_profile(name)
            )
            self.profile_action_group.addAction(action)
        self.profile_menu.addSeparator()
        self.profile_menu.addAction("New from file...", self.new_profile_from_file)
        self.profile_menu.addAction("Edit profiles...", self.edit_profiles_dialog)
        has_selected_profile = bool(
            self.selected_profile_name
            and (
                self.profiles_dir / self.selected_profile_name / "settings.ini"
            ).is_file()
        )
        update_action = self.profile_menu.addAction(
            "Update selected profile with current values", self.update_selected_profile
        )
        update_action.setEnabled(has_selected_profile)

    def _profile_names(self) -> List[str]:
        if not self.profiles_dir.is_dir():
            return []
        return sorted(
            profile_dir.name
            for profile_dir in self.profiles_dir.iterdir()
            if profile_dir.is_dir() and (profile_dir / "settings.ini").is_file()
        )

    def _read_selected_profile(self) -> str:
        marker = self.profiles_dir / ".last_selected_profile"
        try:
            name = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        if (
            name
            and Path(name).name == name
            and name not in (".", "..")
            and (self.profiles_dir / name / "settings.ini").is_file()
        ):
            return name
        return ""

    def _set_selected_profile(self, name: str) -> None:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        marker = self.profiles_dir / ".last_selected_profile"
        if name:
            marker.write_text(name, encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
        self.selected_profile_name = name

    def _read_startup_profile(self) -> str:
        config_path = self._app_implementation_dir() / ".scopefoundry"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            name = config.get("startup_profile", "") if isinstance(config, dict) else ""
        except (OSError, json.JSONDecodeError):
            name = ""
        if not isinstance(name, str):
            return ""
        if (
            name
            and Path(name).name == name
            and name not in (".", "..")
            and (self.profiles_dir / name / "settings.ini").is_file()
        ):
            return name
        return ""

    def _set_startup_profile(self, name: str) -> None:
        config_path = self._app_implementation_dir() / ".scopefoundry"
        if name and (
            Path(name).name != name
            or name in (".", "..")
            or not (self.profiles_dir / name / "settings.ini").is_file()
        ):
            raise ValueError(f"Unknown startup profile: {name}")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
        if not isinstance(config, dict):
            config = {}
        config["startup_profile"] = name
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        self.startup_profile_name = name

    def update_selected_profile(self, checked: bool = False) -> None:
        name = self.selected_profile_name
        settings_path = self.profiles_dir / name / "settings.ini"
        if not name or not settings_path.is_file():
            return
        saved_paths = ini_io.load_settings(settings_path)
        self.save_profile(name, setting_paths=list(saved_paths))

    def new_profile_from_file(self, checked: bool = False) -> None:
        source_file = self.app.settings_select_file_dialog()
        if not source_file:
            return

        source_path = Path(source_file)
        try:
            source_values = self.app.read_settings_file(source_path)
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Could not read settings file",
                f"Could not read '{source_path.name}': {error}",
            )
            return

        setting_values = {}
        invalid_paths = []
        for source_setting_path, value in source_values.items():
            logged_quantity = self.app.get_lq(source_setting_path)
            if (
                logged_quantity is None
                or logged_quantity.ro
                or logged_quantity.protected
            ):
                continue
            try:
                setting_values[logged_quantity.path] = self._profile_value_text(
                    logged_quantity, value
                )
            except Exception:
                invalid_paths.append(logged_quantity.path)

        if not setting_values:
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "No compatible settings found",
                "The selected file does not contain any writable settings for "
                "this app.",
            )
            return

        def hardware_is_connected(path):
            parts = path.split("/", 2)
            if len(parts) < 3 or parts[0] != "hw":
                return True
            connected_path = f"hw/{parts[1]}/connected"
            connected_value = setting_values.get(connected_path)
            connected_lq = self.app.get_lq(connected_path)
            if connected_value is None or connected_lq is None:
                return False
            try:
                return bool(connected_lq.coerce_to_type(connected_value))
            except Exception:
                return False

        initial_selected_paths = {
            path for path in setting_values if hardware_is_connected(path)
        }
        if source_path.suffix.lower() == ".h5":
            measurement_names = h5_io.measurement_names_with_datasets(source_path)
            initial_selected_paths = {
                path
                for path in initial_selected_paths
                if not path.startswith("mm/")
                or path.split("/", 2)[1] in measurement_names
            }

        if invalid_paths:
            paths = "\n".join(invalid_paths[:10])
            more = "\n..." if len(invalid_paths) > 10 else ""
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Some settings were skipped",
                "These settings could not be converted and were not included:\n"
                f"{paths}{more}",
            )

        self.edit_profiles_dialog(
            initial_values=setting_values,
            initial_name=source_path.stem,
            initial_selected_paths=initial_selected_paths,
        )

    def save_setting_to_profile(self, path: str) -> None:
        logged_quantity = self.app.get_lq(path)
        if logged_quantity is None or logged_quantity.ro or logged_quantity.protected:
            return

        profile_names = self._profile_names()
        if not profile_names:
            QtWidgets.QMessageBox.information(
                self.app.ui,
                "No profiles available",
                "Create a profile before saving a setting to it.",
            )
            return

        current_index = (
            profile_names.index(self.selected_profile_name)
            if self.selected_profile_name in profile_names
            else 0
        )
        profile_name, accepted = QtWidgets.QInputDialog.getItem(
            self.app.ui,
            "Save setting to profile",
            f"Save the current value of '{path}' to:",
            profile_names,
            current_index,
            False,
        )
        if not accepted:
            return

        settings_path = self.profiles_dir / profile_name / "settings.ini"
        try:
            settings = ini_io.load_settings(settings_path)
            settings[path] = logged_quantity.ini_string_value()
            ini_io.save_settings(settings_path, settings)
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Could not save setting",
                f"Could not save '{path}' to profile '{profile_name}': {error}",
            )

    def remove_setting_from_profile(self, path: str) -> None:
        logged_quantity = self.app.get_lq(path)
        if logged_quantity is None or logged_quantity.ro or logged_quantity.protected:
            return

        profiles_with_setting = []
        try:
            for profile_name in self._profile_names():
                settings_path = self.profiles_dir / profile_name / "settings.ini"
                if path in ini_io.load_settings(settings_path):
                    profiles_with_setting.append(profile_name)
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Could not read profiles",
                f"Could not check saved profile settings: {error}",
            )
            return

        if not profiles_with_setting:
            QtWidgets.QMessageBox.information(
                self.app.ui,
                "No saved value",
                f"'{path}' is not saved in any profile.",
            )
            return

        current_index = (
            profiles_with_setting.index(self.selected_profile_name)
            if self.selected_profile_name in profiles_with_setting
            else 0
        )
        profile_name, accepted = QtWidgets.QInputDialog.getItem(
            self.app.ui,
            "Remove saved value from profile",
            f"Choose a profile to remove '{path}' from:",
            profiles_with_setting,
            current_index,
            False,
        )
        if not accepted:
            return

        answer = QtWidgets.QMessageBox.question(
            self.app.ui,
            "Remove saved value?",
            f"Remove '{path}' from profile '{profile_name}'? The current value"
            " in the app will not change.",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        settings_path = self.profiles_dir / profile_name / "settings.ini"
        try:
            settings = ini_io.load_settings(settings_path)
            settings.pop(path, None)
            ini_io.save_settings(settings_path, settings)
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Could not remove saved value",
                f"Could not remove '{path}' from profile '{profile_name}': {error}",
            )

    def delete_selected_profile(self, checked: bool = False) -> None:
        name = self.selected_profile_name
        profile_dir = self.profiles_dir / name
        if not name or not profile_dir.is_dir():
            return
        answer = QtWidgets.QMessageBox.question(
            self.app.ui,
            "Delete profile?",
            f"Delete profile '{name}' and its saved settings and window layout?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        rmtree(profile_dir)
        self._set_selected_profile("")
        self.refresh_menu()

    def _selected_measurement_name(self) -> str:
        if self.app.mdi:
            active_subwin = self.app.ui.mdiArea.activeSubWindow()
            for name, measurement in self.app.measurements.items():
                if getattr(measurement, "subwin", None) is active_subwin:
                    return name
        else:
            for name, measurement in self.app.measurements.items():
                ui = getattr(measurement, "ui", None)
                if ui is not None and ui.isActiveWindow():
                    return name
        return ""

    @staticmethod
    def _value_texts_equal(logged_quantity, left: str, right: str) -> bool:
        if left == right:
            return True
        try:
            left_value = logged_quantity.coerce_to_type(left)
            right_value = logged_quantity.coerce_to_type(right)
            equal = left_value == right_value
            if hasattr(equal, "all"):
                equal = equal.all()
            return bool(equal)
        except Exception:
            return False

    @staticmethod
    def _display_value(logged_quantity) -> str:
        value_text = logged_quantity.string_value()
        if logged_quantity.unit:
            value_text = f"{value_text} {logged_quantity.unit}"
        return value_text

    @staticmethod
    def _json_compatible_value(value):
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if hasattr(value, "tolist"):
            return ProfileManager._json_compatible_value(value.tolist())
        if hasattr(value, "item"):
            return ProfileManager._json_compatible_value(value.item())
        if isinstance(value, (list, tuple)):
            return [ProfileManager._json_compatible_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): ProfileManager._json_compatible_value(item)
                for key, item in value.items()
            }
        return value

    @classmethod
    def _profile_value_text(cls, logged_quantity, value) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        typed_value = logged_quantity.coerce_to_type(value)
        if getattr(logged_quantity, "is_array", False):
            return json.dumps(cls._json_compatible_value(typed_value))
        if hasattr(typed_value, "item"):
            typed_value = typed_value.item()
        if isinstance(typed_value, bytes):
            typed_value = typed_value.decode("utf-8")
        return logged_quantity.coerce_to_str(typed_value)

    @classmethod
    def _display_saved_value(cls, logged_quantity, value) -> str:
        try:
            value_text = cls._profile_value_text(logged_quantity, value)
        except Exception:
            value_text = str(value)
        if logged_quantity.unit:
            value_text = f"{value_text} {logged_quantity.unit}"
        return value_text

    def _update_proposed_value_style(self, item, logged_quantity) -> None:
        proposed_value = item.text(2)
        saved_value = item.data(1, QtCore.Qt.ItemDataRole.UserRole)
        baseline_value = item.data(2, QtCore.Qt.ItemDataRole.UserRole)
        differs_from_saved = not self._value_texts_equal(
            logged_quantity, proposed_value, saved_value
        )
        is_unsaved = not self._value_texts_equal(
            logged_quantity, proposed_value, baseline_value
        )
        is_highlighted = differs_from_saved or is_unsaved

        tree = item.treeWidget()
        signals_were_blocked = tree.blockSignals(True)
        try:
            font = item.font(2)
            font.setBold(is_highlighted)
            font.setItalic(differs_from_saved)
            item.setFont(2, font)
            item.setForeground(
                2,
                (
                    QtGui.QBrush(QtGui.QColor("darkorange"))
                    if is_highlighted
                    else QtGui.QBrush()
                ),
            )
            if is_unsaved:
                item.setToolTip(2, "Unsaved profile value")
            elif differs_from_saved:
                item.setToolTip(2, "Differs from the currently saved value")
            else:
                item.setToolTip(2, "Matches the currently saved value")
        finally:
            tree.blockSignals(signals_were_blocked)

    def _make_settings_tree(
        self,
        selected_measurement: str,
        selected_paths=None,
        proposed_values=None,
        show_saved_values=True,
        take_current_values_callback=None,
        load_values_from_file_callback=None,
    ):
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(3)
        header = _ProfileTreeHeader(
            tree,
            take_current_values_callback,
            load_values_from_file_callback,
        )
        tree.setHeader(header)
        tree.setHeaderLabels(["Logged quantity", "Currently saved", ""])
        header._position_controls()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        tree.setItemDelegate(_ProposedValueDelegate(tree))
        tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        tree.setColumnWidth(0, 260)
        tree.setColumnWidth(1, 180)
        tree.setColumnWidth(2, 240)
        tree.setColumnHidden(1, not show_saved_values)
        tree.setMinimumWidth(700)
        categories = {}
        category_components = {}
        component_items = {}
        setting_items = {}
        component_settings = {}

        for path in self.app.get_setting_paths():
            parts = path.split("/")
            if parts[0] == "app":
                category_name = "App"
                component_key = "app"
                component_name = "App settings"
                setting_name = "/".join(parts[1:])
                is_checked = False
            elif parts[0] == "hw":
                category_name = "Hardware"
                component_key = f"hw/{parts[1]}"
                component_name = parts[1]
                setting_name = "/".join(parts[2:])
                is_checked = bool(self.app.hardware[parts[1]].settings["connected"])
            elif parts[0] == "mm":
                category_name = "Measurements"
                component_key = f"mm/{parts[1]}"
                component_name = parts[1]
                setting_name = "/".join(parts[2:])
                is_checked = parts[1] == selected_measurement
            else:
                continue

            if selected_paths is not None:
                is_checked = path in selected_paths

            if category_name not in categories:
                category_item = QtWidgets.QTreeWidgetItem(tree, [category_name])
                category_item.setFlags(
                    category_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                )
                categories[category_name] = category_item
                category_components[category_name] = []
            if component_key not in component_items:
                component_item = QtWidgets.QTreeWidgetItem(
                    categories[category_name], [component_name]
                )
                component_item.setFlags(
                    component_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                )
                component_items[component_key] = component_item
                component_settings[component_key] = []
                category_components[category_name].append(component_key)

            logged_quantity = self.app.get_lq(path)
            is_read_only = logged_quantity.ro
            current_value = logged_quantity.ini_string_value()
            saved_value = (
                proposed_values.get(path)
                if show_saved_values and proposed_values is not None
                else None
            )
            if show_saved_values:
                value_text = (
                    self._display_saved_value(logged_quantity, saved_value)
                    if saved_value is not None
                    else ""
                )
            else:
                value_text = self._display_value(logged_quantity)
            comparison_value = (
                str(saved_value) if saved_value is not None else current_value
            )
            proposed_value = (
                proposed_values.get(path, current_value)
                if proposed_values is not None
                else current_value
            )
            proposed_value = str(proposed_value)
            setting_item = QtWidgets.QTreeWidgetItem(
                component_items[component_key],
                [setting_name, value_text, proposed_value],
            )
            setting_item.setFlags(
                setting_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            )
            if not is_read_only:
                setting_item.setFlags(
                    setting_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable
                )
            setting_item.setCheckState(
                0,
                (
                    QtCore.Qt.CheckState.Checked
                    if is_checked and not is_read_only
                    else QtCore.Qt.CheckState.Unchecked
                ),
            )
            setting_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, path)
            setting_item.setData(1, QtCore.Qt.ItemDataRole.UserRole, comparison_value)
            setting_item.setData(2, QtCore.Qt.ItemDataRole.UserRole, proposed_value)
            setting_item.setToolTip(2, "Click to edit this profile value")
            self._update_proposed_value_style(setting_item, logged_quantity)
            if is_read_only:
                setting_item.setDisabled(True)
            setting_items[path] = setting_item
            component_settings[component_key].append(setting_item)

        def editable_settings(component_key):
            return [
                child
                for child in component_settings[component_key]
                if not child.isDisabled()
            ]

        def set_aggregate_state(item, setting_items_for_group):
            if not setting_items_for_group:
                item.setDisabled(True)
                item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
                return
            item.setDisabled(False)
            selected_count = sum(
                child.checkState(0) == QtCore.Qt.CheckState.Checked
                for child in setting_items_for_group
            )
            if selected_count == 0:
                state = QtCore.Qt.CheckState.Unchecked
            elif selected_count == len(setting_items_for_group):
                state = QtCore.Qt.CheckState.Checked
            else:
                state = QtCore.Qt.CheckState.PartiallyChecked
            item.setCheckState(0, state)

        def category_settings(category_name):
            return [
                child
                for component_key in category_components[category_name]
                for child in editable_settings(component_key)
            ]

        def update_checks(item, column):
            if column != 0:
                return

            signals_were_blocked = tree.blockSignals(True)
            try:
                if item in categories.values():
                    category_name = next(
                        name
                        for name, candidate in categories.items()
                        if candidate is item
                    )
                    state = item.checkState(column)
                    for component_key in category_components[category_name]:
                        children = editable_settings(component_key)
                        for child in children:
                            child.setCheckState(column, state)
                        set_aggregate_state(component_items[component_key], children)
                    set_aggregate_state(item, category_settings(category_name))
                    return

                if item in component_items.values():
                    component_key = next(
                        key
                        for key, candidate in component_items.items()
                        if candidate is item
                    )
                    state = item.checkState(column)
                    children = editable_settings(component_key)
                    for child in children:
                        child.setCheckState(column, state)
                    set_aggregate_state(item, children)
                    category_name = item.parent().text(0)
                    set_aggregate_state(
                        categories[category_name], category_settings(category_name)
                    )
                    return

                component_item = item.parent()
                if component_item not in component_items.values():
                    return
                component_key = next(
                    key
                    for key, candidate in component_items.items()
                    if candidate is component_item
                )
                set_aggregate_state(component_item, editable_settings(component_key))
                category_name = component_item.parent().text(0)
                set_aggregate_state(
                    categories[category_name], category_settings(category_name)
                )
            finally:
                tree.blockSignals(signals_were_blocked)

        for component_key, component_item in component_items.items():
            children = editable_settings(component_key)
            set_aggregate_state(component_item, children)
            is_preselected = any(
                child.checkState(0) == QtCore.Qt.CheckState.Checked
                for child in children
            )
            component_item.setExpanded(is_preselected)
            if is_preselected:
                component_item.parent().setExpanded(True)

        for category_name, category_item in categories.items():
            children = category_settings(category_name)
            set_aggregate_state(category_item, children)
            category_item.setExpanded(
                any(
                    child.checkState(0) == QtCore.Qt.CheckState.Checked
                    for child in children
                )
            )

        def update_proposed_value(item, column):
            if column != 2:
                return
            path = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            if path not in setting_items:
                return
            if item.checkState(0) != QtCore.Qt.CheckState.Checked:
                item.setCheckState(0, QtCore.Qt.CheckState.Checked)
            self._update_proposed_value_style(item, self.app.get_lq(path))

        tree.itemChanged.connect(update_checks)
        tree.itemChanged.connect(update_proposed_value)

        def edit_proposed_value_on_click(item, column):
            if column == 2 and item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable:
                tree.editItem(item, column)

        tree.itemClicked.connect(edit_proposed_value_on_click)
        return tree, component_items, setting_items

    def edit_profiles_dialog(
        self,
        checked: bool = False,
        initial_values=None,
        initial_name=None,
        initial_selected_paths=None,
    ) -> None:
        selected_measurement = self._selected_measurement_name()
        default_name = f"{datetime.date.today():%Y%m%d}"
        if selected_measurement:
            default_name += f"_{selected_measurement}"

        class ProfileEditorDialog(QtWidgets.QDialog):
            def __init__(self, parent):
                super().__init__(parent)
                self.can_close = lambda: True
                self._close_approved = False

            def closeEvent(self, event):
                if self.can_close():
                    self._close_approved = True
                    super().closeEvent(event)
                else:
                    event.ignore()

            def reject(self):
                if self._close_approved or self.can_close():
                    self._close_approved = False
                    super().reject()

        dialog = ProfileEditorDialog(self.app.ui)
        dialog.setWindowTitle("Edit profiles")
        layout = QtWidgets.QVBoxLayout(dialog)

        form = QtWidgets.QFormLayout()
        profile_selector = QtWidgets.QComboBox()
        profile_selector.addItems(self._profile_names())
        form.addRow("Existing profile:", profile_selector)
        startup_profile_selector = QtWidgets.QComboBox()
        layout.addLayout(form)

        tree_layout = QtWidgets.QVBoxLayout()
        layout.addLayout(tree_layout, 1)
        current_tree = {"widget": None, "settings": {}}
        current_profile = {"name": None, "pending_import": False}
        suggested_profile_name = {"value": initial_name or default_name}
        baseline = {"paths": set(), "values": {}}

        def show_tree(selected_paths=None, proposed_values=None):
            tree, _, setting_items = self._make_settings_tree(
                selected_measurement,
                selected_paths=selected_paths,
                proposed_values=proposed_values,
                show_saved_values=current_profile["name"] is not None,
                take_current_values_callback=load_current_values,
                load_values_from_file_callback=load_values_from_file,
            )
            tree.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
            tree.setMinimumHeight(300)
            if current_tree["widget"] is not None:
                tree_layout.removeWidget(current_tree["widget"])
                current_tree["widget"].deleteLater()
            tree_layout.addWidget(tree)
            current_tree["widget"] = tree
            current_tree["settings"] = setting_items

        def checked_paths():
            return {
                path
                for path, item in current_tree["settings"].items()
                if item.checkState(0) == QtCore.Qt.CheckState.Checked
            }

        def capture_baseline():
            baseline["paths"] = checked_paths()
            baseline["values"] = {}
            tree = current_tree["widget"]
            signals_were_blocked = tree.blockSignals(True)
            try:
                for path, item in current_tree["settings"].items():
                    value_text = item.text(2)
                    baseline["values"][path] = value_text
                    item.setData(2, QtCore.Qt.ItemDataRole.UserRole, value_text)
                    self._update_proposed_value_style(item, self.app.get_lq(path))
            finally:
                tree.blockSignals(signals_were_blocked)

        def has_unsaved_changes():
            if current_tree["widget"] is None:
                return False
            if current_profile["pending_import"]:
                return True
            selected = checked_paths()
            if selected != baseline["paths"]:
                return True
            for path, item in current_tree["settings"].items():
                if not self._value_texts_equal(
                    self.app.get_lq(path),
                    item.text(2),
                    baseline["values"].get(path, item.text(2)),
                ):
                    return True
            return False

        def save_current_profile(name_override=None, as_copy=False):
            name = name_override if name_override is not None else current_profile["name"]
            if name is None:
                return save_profile_as()
            name = name.strip()
            if not name or Path(name).name != name or name in (".", ".."):
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Invalid profile name",
                    "Enter a valid profile name.",
                )
                return False

            old_name = current_profile["name"]
            old_dir = self.profiles_dir / old_name if old_name else None
            new_dir = self.profiles_dir / name
            if new_dir.exists() and (name != old_name or as_copy):
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Profile already exists",
                    f"A profile named '{name}' already exists. Select it to edit it.",
                )
                return False

            setting_paths = sorted(checked_paths())
            proposed_values = {
                path: current_tree["settings"][path].text(2) for path in setting_paths
            }
            for path, value in proposed_values.items():
                try:
                    self.app.get_lq(path).coerce_to_type(value)
                except Exception as error:
                    QtWidgets.QMessageBox.warning(
                        dialog,
                        "Invalid logged quantity value",
                        f"The value for '{path}' is invalid: {error}",
                    )
                    return False

            self.save_profile(
                name,
                setting_paths=setting_paths,
                setting_values=proposed_values,
                select_profile=(
                    old_name is None or old_name == self.selected_profile_name
                ),
            )
            if (
                not as_copy
                and old_name != name
                and old_name == self.startup_profile_name
            ):
                self._set_startup_profile(name)
            if not as_copy and old_dir is not None and old_name != name:
                rmtree(old_dir)
                self.refresh_menu()

            current_profile["name"] = name
            current_profile["pending_import"] = False
            suggested_profile_name["value"] = name
            tree = current_tree["widget"]
            saved_values = ini_io.load_settings(new_dir / "settings.ini")
            tree.setColumnHidden(1, False)
            signals_were_blocked = tree.blockSignals(True)
            try:
                for path, item in current_tree["settings"].items():
                    logged_quantity = self.app.get_lq(path)
                    if path in saved_values:
                        saved_value = saved_values[path]
                        item.setText(
                            1, self._display_saved_value(logged_quantity, saved_value)
                        )
                        item.setData(1, QtCore.Qt.ItemDataRole.UserRole, saved_value)
                    else:
                        current_value = logged_quantity.ini_string_value()
                        item.setText(1, "")
                        item.setData(1, QtCore.Qt.ItemDataRole.UserRole, current_value)
                        item.setText(2, current_value)
            finally:
                tree.blockSignals(signals_were_blocked)
            for path, item in current_tree["settings"].items():
                self._update_proposed_value_style(item, self.app.get_lq(path))

            refresh_profile_selector(name)
            delete_button.setEnabled(True)
            capture_baseline()
            return True

        def save_profile_as():
            source_name = current_profile["name"]
            suggested_name = (
                f"{source_name} copy"
                if source_name
                else suggested_profile_name["value"]
            )
            new_name, accepted = QtWidgets.QInputDialog.getText(
                dialog,
                "Save profile as",
                "New profile name:",
                QtWidgets.QLineEdit.EchoMode.Normal,
                suggested_name,
            )
            if not accepted:
                return
            save_current_profile(new_name, as_copy=True)

        def ask_to_save_changes(prompt):
            if not has_unsaved_changes():
                return True
            answer = QtWidgets.QMessageBox.question(
                dialog,
                "Unsaved changes",
                prompt,
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Yes,
            )
            if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                return save_current_profile()
            return answer == QtWidgets.QMessageBox.StandardButton.No

        def restore_profile_selector():
            profile_selector.blockSignals(True)
            profile_name = current_profile["name"]
            profile_selector.setCurrentIndex(
                profile_selector.findText(profile_name) if profile_name else -1
            )
            profile_selector.blockSignals(False)

        def set_new_profile(
            confirm=True,
            selected_paths=None,
            proposed_values=None,
            display_name=None,
            load_current=True,
        ):
            if confirm and not ask_to_save_changes(
                "Save changes to this profile before starting a new one?"
            ):
                restore_profile_selector()
                return
            profile_selector.blockSignals(True)
            profile_selector.setCurrentIndex(-1)
            profile_selector.blockSignals(False)
            current_profile["name"] = None
            current_profile["pending_import"] = proposed_values is not None
            suggested_profile_name["value"] = display_name or default_name
            delete_button.setEnabled(False)
            show_tree(selected_paths, proposed_values)
            if load_current:
                load_current_values()
            capture_baseline()

        def select_profile(name, confirm=True):
            if not name:
                return
            if confirm and not ask_to_save_changes(
                "Save changes to this profile before switching profiles?"
            ):
                restore_profile_selector()
                return
            settings_path = self.profiles_dir / name / "settings.ini"
            saved_values = (
                ini_io.load_settings(settings_path) if settings_path.is_file() else {}
            )
            selected_paths = set(saved_values)
            current_profile["name"] = name
            current_profile["pending_import"] = False
            delete_button.setEnabled(settings_path.is_file())
            show_tree(selected_paths, saved_values)
            capture_baseline()

        def refresh_profile_selector(select_name=None):
            profile_selector.blockSignals(True)
            profile_selector.clear()
            profile_selector.addItems(self._profile_names())
            index = profile_selector.findText(select_name) if select_name else -1
            profile_selector.setCurrentIndex(index)
            profile_selector.blockSignals(False)
            refresh_startup_profile_selector()

        def refresh_startup_profile_selector():
            startup_profile_selector.blockSignals(True)
            startup_profile_selector.clear()
            startup_profile_selector.addItem("(None)", "")
            for profile_name in self._profile_names():
                startup_profile_selector.addItem(profile_name, profile_name)
            index = startup_profile_selector.findData(self.startup_profile_name)
            startup_profile_selector.setCurrentIndex(max(index, 0))
            startup_profile_selector.blockSignals(False)

        def set_startup_profile_from_editor(index):
            name = startup_profile_selector.itemData(index) or ""
            self._set_startup_profile(name)

        def load_current_values():
            tree = current_tree["widget"]
            tree.blockSignals(True)
            for path, item in current_tree["settings"].items():
                logged_quantity = self.app.get_lq(path)
                current_value = logged_quantity.ini_string_value()
                if not item.isDisabled():
                    item.setText(2, current_value)
            tree.blockSignals(False)
            for path, item in current_tree["settings"].items():
                self._update_proposed_value_style(item, self.app.get_lq(path))

        def load_values_from_file():
            source_file = self.app.settings_select_file_dialog()
            if not source_file:
                return
            try:
                source_values = self.app.read_settings_file(source_file)
            except Exception as error:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Could not read settings file",
                    f"Could not read '{Path(source_file).name}': {error}",
                )
                return

            loaded_count = 0
            invalid_paths = []
            for source_path, value in source_values.items():
                logged_quantity = self.app.get_lq(source_path)
                if (
                    logged_quantity is None
                    or logged_quantity.ro
                    or logged_quantity.protected
                ):
                    continue
                path = logged_quantity.path
                item = current_tree["settings"].get(path)
                if item is None:
                    continue
                try:
                    value_text = self._profile_value_text(logged_quantity, value)
                except Exception:
                    invalid_paths.append(path)
                    continue

                item.setText(2, value_text)
                if item.checkState(0) != QtCore.Qt.CheckState.Checked:
                    item.setCheckState(0, QtCore.Qt.CheckState.Checked)
                loaded_count += 1

            if loaded_count == 0:
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "No compatible settings found",
                    "The selected file does not contain any writable settings "
                    "shown in this profile tree.",
                )
            elif invalid_paths:
                paths = "\n".join(invalid_paths[:10])
                more = "\n..." if len(invalid_paths) > 10 else ""
                QtWidgets.QMessageBox.warning(
                    dialog,
                    "Some settings were skipped",
                    "These settings could not be converted and were not included:\n"
                    f"{paths}{more}",
                )

        def confirm_close():
            return ask_to_save_changes("Save changes to this profile before closing?")

        dialog.can_close = confirm_close
        refresh_startup_profile_selector()

        def delete_current_profile():
            name = current_profile["name"]
            if not name:
                return
            answer = QtWidgets.QMessageBox.question(
                dialog,
                "Delete profile?",
                f"Delete profile '{name}' and its saved settings and window layout?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            rmtree(self.profiles_dir / name)
            if self.selected_profile_name == name:
                self._set_selected_profile("")
            if self.startup_profile_name == name:
                self._set_startup_profile("")
            self.refresh_menu()
            remaining = self._profile_names()
            refresh_profile_selector(remaining[0] if remaining else None)
            current_profile["name"] = None
            current_profile["pending_import"] = False
            if remaining:
                select_profile(remaining[0], confirm=False)
            else:
                set_new_profile(confirm=False)

        profile_selector.currentTextChanged.connect(select_profile)
        startup_profile_selector.currentIndexChanged.connect(
            set_startup_profile_from_editor
        )

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(QtWidgets.QLabel("Run at startup:"))
        buttons.addWidget(startup_profile_selector)
        buttons.addStretch(1)
        new_button = QtWidgets.QPushButton("New profile")
        new_button.clicked.connect(lambda: set_new_profile())
        buttons.addWidget(new_button)
        save_button = QtWidgets.QPushButton("Save")
        save_button.clicked.connect(lambda: save_current_profile())
        buttons.addWidget(save_button)
        save_as_button = QtWidgets.QPushButton("Save as...")
        save_as_button.clicked.connect(lambda: save_profile_as())
        buttons.addWidget(save_as_button)
        delete_button = QtWidgets.QPushButton("Delete")
        delete_button.clicked.connect(lambda: delete_current_profile())
        buttons.addWidget(delete_button)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        if initial_values is not None:
            set_new_profile(
                confirm=False,
                selected_paths=(
                    initial_selected_paths
                    if initial_selected_paths is not None
                    else set(initial_values)
                ),
                proposed_values=initial_values,
                display_name=initial_name,
                load_current=False,
            )
        else:
            initial_profile = self.selected_profile_name
            if initial_profile not in self._profile_names():
                profile_names = self._profile_names()
                initial_profile = profile_names[0] if profile_names else None
            if initial_profile:
                refresh_profile_selector(initial_profile)
                select_profile(initial_profile, confirm=False)
            else:
                set_new_profile(confirm=False)

        dialog.exec()

    def save_profile(
        self,
        name: str,
        include_app: bool = True,
        hardware_names=(),
        measurement_names=(),
        setting_paths: List[str] = None,
        select_profile: bool = True,
        setting_values=None,
    ) -> None:
        profile_dir = self.profiles_dir / name
        profile_dir.mkdir(parents=True, exist_ok=True)

        if setting_paths is None:
            prefixes = []
            if include_app:
                prefixes.append("app/")
            prefixes.extend(
                f"hw/{component_name}/" for component_name in hardware_names
            )
            prefixes.extend(
                f"mm/{component_name}/" for component_name in measurement_names
            )
            paths = [
                path
                for path in self.app.get_setting_paths()
                if any(path.startswith(prefix) for prefix in prefixes)
                and not self.app._setting_paths[path].ro
            ]
        else:
            paths = [
                path
                for path in setting_paths
                if path in self.app._setting_paths
                and not self.app._setting_paths[path].ro
            ]
        if setting_values is None:
            settings = self.app.read_settings(paths, ini_string_value=True)
        else:
            settings = {
                path: setting_values[path] for path in paths if path in setting_values
            }
        ini_io.save_settings(profile_dir / "settings.ini", settings)

        self.app.save_window_positions_json(profile_dir / "window_positions.json")
        if select_profile:
            self._set_selected_profile(name)
        self.refresh_menu()

    def load_profile(self, name: str, checked: bool = False) -> None:
        profile_dir = self.profiles_dir / name
        settings_path = profile_dir / "settings.ini"
        if not settings_path.is_file():
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Profile settings not found",
                f"Could not find the settings file for profile '{name}':\n"
                f"{settings_path}",
            )
            return
        self.app.log.info(f"Loading profile '{name}' from {settings_path}")
        try:
            self.app.settings_load_ini(settings_path)
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self.app.ui,
                "Could not load profile",
                f"Could not load profile '{name}' from:\n{settings_path}\n\n"
                f"{error}",
            )
            return
        self._set_selected_profile(name)
        self.refresh_menu()

        positions_path = profile_dir / "window_positions.json"
        if positions_path.is_file():
            self.app.load_window_positions_json(positions_path)
