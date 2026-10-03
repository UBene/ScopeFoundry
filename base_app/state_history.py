import datetime
import json
import re
import shutil
from pathlib import Path

from functools import partial

from qtpy import QtWidgets

from ScopeFoundry import ini_io


class StateHistory:
    max_entries = 40
    _activation_reason_pattern = re.compile(
        r"^mm/(?P<measurement>[^/]+)/activation\s+"
        r"(?P<old>True|False)\s*-+>\s*(?P<new>True|False)$"
    )

    def __init__(self, app, history_dir: Path):
        self.app = app
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._prune()
        self.history_menu = None
        self.undo_action = None

    def setup_menu(self, menu_bar: QtWidgets.QMenuBar) -> None:
        self.history_menu = menu_bar.addMenu("History")
        self.history_menu.aboutToShow.connect(self.refresh_menu)
        self.undo_action = menu_bar.addAction("Undo")
        self.undo_action.setIcon(
            self.app.ui.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_ArrowBack
            )
        )
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.triggered.connect(self.undo_latest)
        self.refresh_menu()

    def _entry_paths(self):
        entries = []
        if not self.history_dir.is_dir():
            return entries
        for entry_dir in self.history_dir.iterdir():
            metadata_path = entry_dir / "metadata.json"
            if not entry_dir.is_dir() or not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            entries.append((metadata.get("timestamp", entry_dir.name), entry_dir))
        return sorted(entries)

    def _prune(self) -> None:
        entries = self._entry_paths()
        for _, entry_dir in entries[: -self.max_entries]:
            shutil.rmtree(entry_dir, ignore_errors=True)

    def save_snapshot(self, reason: str) -> Path | None:
        try:
            return self._save_snapshot(self._normalize_reason(reason))
        except Exception:
            self.app.log.exception("Could not save app history snapshot")
            return None

    @classmethod
    def _normalize_reason(cls, reason: str) -> str:
        match = cls._activation_reason_pattern.fullmatch(reason)
        if match is None:
            return reason

        measurement = match.group("measurement")
        old_value = match.group("old")
        new_value = match.group("new")
        if old_value == "False" and new_value == "True":
            return f"{measurement} started"
        if old_value == "True" and new_value == "False":
            return f"{measurement} stopped"
        return reason

    def _save_snapshot(self, reason: str) -> Path:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().astimezone()
        entry_name = timestamp.strftime("%Y%m%d_%H%M%S_%f")
        entry_dir = self.history_dir / entry_name
        entry_dir.mkdir()

        setting_paths = [
            path
            for path in self.app.get_setting_paths()
            if not self.app.get_lq(path).ro
        ]
        settings = self.app.read_settings(setting_paths, ini_string_value=True)
        ini_io.save_settings(entry_dir / "settings.ini", settings)

        positions = (
            self.app.get_window_positions()
            if self.app.mdi
            else {"main": {"geometry": self.app.ui.geometry().getRect()}}
        )
        with open(entry_dir / "window_positions.json", "w") as outfile:
            json.dump(positions, outfile, indent=4)
        metadata = {"timestamp": timestamp.isoformat(), "reason": reason}
        with open(entry_dir / "metadata.json", "w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile, indent=2)

        self._prune()
        self.refresh_menu()
        return entry_dir

    def refresh_menu(self) -> None:
        if self.history_menu is None:
            return
        self.history_menu.clear()
        entries = self._entry_paths()
        if self.undo_action is not None:
            self.undo_action.setEnabled(bool(entries))
            hint = self._history_item_text(entries[-1][1]) if entries else ""
            self.undo_action.setToolTip(hint)
            self.undo_action.setStatusTip(hint)
        for _, entry_dir in reversed(entries):
            action = self.history_menu.addAction(self._history_item_text(entry_dir))
            action.setData(entry_dir.name)
            action.triggered.connect(partial(self.restore_snapshot, entry_dir.name))
        if not entries:
            self.history_menu.addAction("No history yet").setEnabled(False)

    def _history_item_text(self, entry_dir: Path) -> str:
        metadata = json.loads((entry_dir / "metadata.json").read_text(encoding="utf-8"))
        timestamp = datetime.datetime.fromisoformat(metadata["timestamp"])
        return f"{timestamp:%Y-%m-%d %H:%M:%S}  {metadata['reason']}"

    def undo_latest(self, checked: bool = False) -> None:
        entries = self._entry_paths()
        if not entries:
            return
        self.restore_snapshot(entries[-1][1].name)

    def restore_snapshot(self, entry_name: str) -> None:
        entry_dir = self.history_dir / entry_name
        settings_path = entry_dir / "settings.ini"
        if not settings_path.is_file():
            return
        self.app.settings_load_ini(
            settings_path, ignore_hw_connect=True, show_report=False
        )
        positions_path = entry_dir / "window_positions.json"
        if not positions_path.is_file():
            return
        if self.app.mdi:
            self.app.load_window_positions_json(positions_path)
            return
        with open(positions_path, "r") as infile:
            positions = json.load(infile)
        geometry = positions.get("main", {}).get("geometry")
        if geometry:
            self.app.ui.setGeometry(*geometry)
