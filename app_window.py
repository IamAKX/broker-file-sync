from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QApplication
from PySide6.QtCore import Qt
from components.sidebar import Sidebar
from components.topbar import TopBar


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._navigation_locked = False
        self.setWindowTitle("Broker Sync")
        self.resize(1280, 800)
        self.setMinimumSize(1100, 700)
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._topbar = TopBar(self._controller.theme)
        self._topbar.theme_toggled.connect(self._on_theme_toggled)
        self._topbar.restart_requested.connect(lambda: self.navigate("dashboard"))
        self._topbar.navigate.connect(self.navigate)
        self._topbar.quit_requested.connect(self._controller.request_quit)
        self._topbar.logout_requested.connect(self._controller.show_login)
        self._topbar.fullscreen_requested.connect(self._toggle_fullscreen)
        self._topbar.check_for_update_requested.connect(self._open_update_dialog)
        self._topbar.export_strategies_requested.connect(self._export_all_data)
        self._topbar.import_strategies_requested.connect(self._import_all_data)
        self._topbar.manage_categories_requested.connect(self._open_manage_categories)
        self._topbar.manage_variables_requested.connect(self._open_manage_variables)
        self._topbar.clear_cache_requested.connect(self._clear_cache)
        root.addWidget(self._topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar(self._controller.theme)
        self._sidebar.navigate.connect(self.navigate)
        body.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)

        root.addLayout(body)

        self._screens: dict = {}
        self._register_screens()

    def _register_screens(self):
        from screens.dashboard import DashboardScreen
        from screens.data_import import DataImportScreen
        from screens.config_editor import ConfigEditorScreen
        from screens.notifications import NotificationsScreen
        from screens.live_alerts import LiveAlertsScreen
        from screens.profile import ProfileScreen
        from screens.strategy_builder import StrategyBuilderScreen
        from screens.historic_upload import HistoricUploadScreen
        from screens.formula_builder import FormulaBuilderScreen
        from screens.holidays import HolidaysScreen
        from screens.lmv_upload import LmvUploadScreen
        from screens.jobs import JobsScreen
        from screens.formula_stats import FormulaStatsScreen
        from screens.inception_view_by_date import InceptionViewByDateScreen
        from screens.inception_strategy_builder import InceptionStrategyBuilderScreen
        from screens.inception_hmv import InceptionHmvScreen
        from screens.inception_formula_stats import InceptionFormulaStatsScreen
        from screens.inception_settings import InceptionSettingsScreen
        from screens.inception_admin_sync import InceptionAdminSyncScreen

        dashboard        = DashboardScreen(self._controller)
        data_import      = DataImportScreen(self._controller)
        strategy_builder = StrategyBuilderScreen(self._controller)

        data_import.broker_imported.connect(
            lambda name, rows: self._sidebar.set_broker_active(name, True)
        )
        data_import.broker_reset.connect(
            lambda name: self._sidebar.set_broker_active(name, False)
        )
        data_import.broker_imported.connect(dashboard.on_broker_imported)
        data_import.broker_reset.connect(dashboard.on_broker_reset)

        data_import.broker_source_active.connect(
            lambda name, active, rows: self._sidebar.set_broker_active(name, active)
        )
        data_import.broker_source_active.connect(dashboard.on_broker_source_active)

        # When LMV opens: push headers to strategy builder, push strategies to LMV
        def _on_lmv_ready(headers):
            strategy_builder.set_lmv_headers(headers)
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None:
                # Only strategies marked Active in Strategy Builder are even
                # offered in the picker — one disabled there shouldn't clutter
                # LMV's list. None is auto-applied on open, though: activating
                # every one of them at once meant a large batch of row filters
                # (each strategy's own) all had to match for a row to survive
                # the union, which can empty the whole table the instant LMV
                # loads. Users opt specific ones in per session.
                all_strats = [dict(s, active=False)
                              for s in strategy_builder.get_active_strategies()]
                viewer.set_strategies(all_strats)

        data_import.lmv_headers_ready.connect(_on_lmv_ready)
        data_import.lmv_data_ready.connect(strategy_builder.set_lmv_data)
        data_import.lmv_day_history_ready.connect(strategy_builder.set_day_history)

        screens = [
            ("dashboard",        dashboard),
            ("data_import",      data_import),
            ("config_editor",    ConfigEditorScreen(self._controller)),
            ("strategy_builder", strategy_builder),
            ("notifications",    NotificationsScreen(self._controller)),
            ("live_alerts",      LiveAlertsScreen(self._controller)),
            ("profile",          ProfileScreen(self._controller)),
            ("historic_upload",  HistoricUploadScreen(self._controller)),
            ("formula_builder",  FormulaBuilderScreen(self._controller)),
            ("holidays",         HolidaysScreen(self._controller)),
            ("lmv_upload",       LmvUploadScreen(self._controller)),
            ("jobs",             JobsScreen(self._controller)),
            ("formula_stats",    FormulaStatsScreen(self._controller)),
            ("inception_view_by_date",     InceptionViewByDateScreen(self._controller)),
            ("inception_strategy_builder", InceptionStrategyBuilderScreen(self._controller)),
            ("inception_hmv",              InceptionHmvScreen(self._controller)),
            ("inception_formula_stats",    InceptionFormulaStatsScreen(self._controller)),
            ("inception_settings",         InceptionSettingsScreen(self._controller)),
            ("inception_admin_sync",       InceptionAdminSyncScreen(self._controller)),
        ]
        for name, widget in screens:
            self._screens[name] = widget
            self._stack.addWidget(widget)

    def refresh_user(self):
        self._sidebar.refresh_user()
        # Admin Controls (components.topbar) is gated to one specific
        # account — must be re-evaluated on every re-login too, not just
        # at TopBar's own construction, since MainWindow/TopBar are reused
        # across a logout/login cycle within the same process.
        self._topbar.refresh_user()

    def navigate(self, screen_name: str):
        if self._navigation_locked and screen_name != "holidays":
            return
        if screen_name in self._screens:
            self._stack.setCurrentWidget(self._screens[screen_name])
            self._sidebar.set_active(screen_name)

    # ── Current-year holiday gate ───────────────────────────────────────────
    # On every login/session start, and again whenever the holidays screen
    # saves or deletes a row, verify the current year has at least one
    # holiday on file. If not, force the user onto Market Holidays and lock
    # the rest of the app (sidebar + topbar disabled) until it does.

    def check_holiday_gate(self, initial: bool = False):
        from datetime import date
        from api import holidays_api
        from api.exceptions import ApiError, NetworkError
        try:
            holidays = holidays_api.list_holidays(date.today().year)
        except (ApiError, NetworkError):
            # Can't verify right now — don't lock the user out over a
            # transient network issue.
            self._set_navigation_locked(False)
            if initial:
                self.navigate("dashboard")
            return
        if holidays:
            self._set_navigation_locked(False)
            if initial:
                self.navigate("dashboard")
        else:
            self._set_navigation_locked(True)
            self.navigate("holidays")

    def _set_navigation_locked(self, locked: bool):
        self._navigation_locked = locked
        self._sidebar.setEnabled(not locked)
        self._topbar.setEnabled(not locked)

    def closeEvent(self, event):
        if not self._controller.is_quitting:
            # Tray-resident: closing the window (X button) hides it instead
            # of quitting, so the background scheduler keeps running. Real
            # exit only happens via AppController.request_quit() (tray
            # menu's Quit, or File > Quit).
            event.ignore()
            self.hide()
            return

        self._controller.watcher.stop()
        # Close live viewer if open
        data_import = self._screens.get("data_import")
        if data_import is not None:
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None:
                viewer.close()
        # Close any historic-data viewer popups
        historic_upload = self._screens.get("historic_upload")
        if historic_upload is not None:
            for viewer in getattr(historic_upload, "_viewers", []):
                viewer.close()
        super().closeEvent(event)
        QApplication.quit()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _open_update_dialog(self):
        from components.update_dialog import UpdateDialog
        dlg = UpdateDialog(self._controller, theme=self._controller.theme, parent=self)
        dlg.exec()

    # Section key -> (label, load_all-style getter). Getters take no args;
    # "settings" is the one non-list section (a flat {key: value} dict) and
    # is handled separately in both methods below since it doesn't have a
    # name/overwrite-by-name concept the way every list section does.
    _EXPORT_SECTIONS = [
        ("strategies", "LMV strategies"),
        ("inception_strategies", "HMV/Inception strategies"),
        ("formula_variables", "LMV formula variables"),
        ("inception_formula_variables", "Inception formula variables"),
    ]

    def _export_all_data(self):
        """File > Export All Data: bundles every piece of a user's own
        account-level config into one JSON file — LMV + HMV/Inception
        strategies, both apps' formula variables, and every settings key
        (Config Editor tabs, highlight colors, both apps' custom
        categories, Formula Builder fields, notification/trigger config —
        see services.config_store.export_all_settings). Superset of the
        old "Export All Strategies" (LMV strategies only); a file this
        produces is also still readable by that old feature's shape (a
        bare list) is NOT produced here, but _import_all_data below still
        reads an old bare-list file from before this change.
        """
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services import config_store, formula_variable_store, inception_formula_variable_store, inception_strategy_store, strategy_store

        getters = {
            "strategies": strategy_store.load_all,
            "inception_strategies": inception_strategy_store.load_all,
            "formula_variables": formula_variable_store.load_all,
            "inception_formula_variables": inception_formula_variable_store.load_all,
        }
        try:
            bundle = {key: getters[key]() for key, _ in self._EXPORT_SECTIONS}
            bundle["settings"] = config_store.export_all_settings()
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not read data to export:\n\n{exc}")
            return

        if not any(bundle.values()):
            QMessageBox.information(self, "Export All Data", "Nothing to export.")
            return

        path, _unused = QFileDialog.getSaveFileName(
            self, "Export All Data", "data_export.json", "JSON Files (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(bundle, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not export:\n\n{exc}")
            return

        summary = "\n".join(
            f"  {label}: {len(bundle[key])}" for key, label in self._EXPORT_SECTIONS
        )
        QMessageBox.information(
            self, "Export All Data",
            f"Exported to:\n{path}\n\n{summary}\n  Settings: {len(bundle['settings'])} key(s)",
        )

    def _import_all_data(self):
        """File > Import All Data: the counterpart to _export_all_data
        above. Reads either the new bundled shape ({"strategies": [...],
        "inception_strategies": [...], "formula_variables": [...],
        "inception_formula_variables": [...], "settings": {...}}, any
        subset of keys) or the OLD "Export All Strategies" shape (a bare
        list of strategy dicts) for backward compatibility with files
        exported before this change.

        Every present section is pushed to the server via that store's own
        import_all/import_all_settings — each of those already syncs to
        the server first and raises on failure (an explicit, deliberate
        user action, so it fails loudly rather than silently importing
        local-only) — so importing always updates the database, not just
        the local cache.
        """
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services import config_store, formula_variable_store, inception_formula_variable_store, inception_strategy_store, strategy_store

        path, _unused = QFileDialog.getOpenFileName(
            self, "Import All Data", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                raw = {"strategies": raw}   # old Export All Strategies shape
            if not isinstance(raw, dict):
                raise ValueError("File does not contain a valid data export.")
            for key, _label in self._EXPORT_SECTIONS:
                section = raw.get(key)
                if section is None:
                    continue
                if not isinstance(section, list) or not all(
                    isinstance(item, dict) and "id" in item and "name" in item for item in section
                ):
                    raise ValueError(f"'{key}' in the file is not a valid list of items.")
            settings = raw.get("settings")
            if settings is not None and not isinstance(settings, dict):
                raise ValueError("'settings' in the file is not a valid key/value object.")
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", f"Could not import:\n\n{exc}")
            return

        present = [(key, label, raw[key]) for key, label in self._EXPORT_SECTIONS if raw.get(key)]
        settings = raw.get("settings") or {}
        if not present and not settings:
            QMessageBox.information(self, "Import All Data", "Nothing to import — the file is empty.")
            return

        lines = [f"  {label}: {len(items)}" for _key, label, items in present]
        if settings:
            lines.append(f"  Settings: {len(settings)} key(s)")
        reply = QMessageBox.question(
            self, "Import All Data",
            "This will import:\n" + "\n".join(lines) +
            "\n\nAn item whose name matches an existing one is overwritten; a new "
            "name is added. Every other existing item is left untouched. This "
            "updates your account on the server, not just this device. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        importers = {
            "strategies": strategy_store.import_all,
            "inception_strategies": inception_strategy_store.import_all,
            "formula_variables": formula_variable_store.import_all,
            "inception_formula_variables": inception_formula_variable_store.import_all,
        }
        results = []
        try:
            for key, label, items in present:
                overwritten, added = importers[key](items)
                results.append(f"  {label}: {overwritten} overwritten, {added} added")
            if settings:
                count = config_store.import_all_settings(settings)
                results.append(f"  Settings: {count} key(s) imported")
        except Exception as exc:
            done = "\n".join(results) if results else "  (nothing yet)"
            QMessageBox.warning(
                self, "Import Failed",
                f"Stopped after an error:\n\n{exc}\n\nAlready imported before the error:\n{done}",
            )
            return

        strategy_builder = self._screens.get("strategy_builder")
        if strategy_builder is not None:
            strategy_builder.reload_strategies()
        formula_builder = self._screens.get("formula_builder")
        if formula_builder is not None:
            formula_builder.reload_formulas()

        QMessageBox.information(self, "Import All Data", "Imported:\n" + "\n".join(results))

    def _open_manage_categories(self):
        from screens.strategy_builder import ManageCategoriesDialog

        dlg = ManageCategoriesDialog(self._controller.theme, parent=self)
        dlg.exec()
        # Renaming/deleting a category writes strategies.json directly (see
        # services.strategy_store), bypassing the Strategy Builder screen's
        # own in-memory list — reload it the same way Import All Strategies
        # does, so its sidebar regroups under any renamed/deleted category.
        strategy_builder = self._screens.get("strategy_builder")
        if strategy_builder is not None:
            strategy_builder.reload_strategies()

    def _open_manage_variables(self):
        """Data > Manage Variables: the same VariablesManagerDialog the
        Strategy Builder "Variables" button opens, but reachable without
        going into Strategy Builder first. Its "⟳ Sync" button re-pulls
        formula variables from the server AND clears the compiled-formula
        cache, so a variable created/edited elsewhere starts resolving in
        an open Live Master View without needing a builder round trip (a
        strategy formula that references a not-yet-synced "{Name}" variable
        otherwise silently drops the token — see services.strategy_engine.
        _expand_var_tokens).

        Column catalogue for any formula edited from here: the loaded LMV's
        real columns when a Strategy Builder screen already has them, else
        just the Formula Builder / Inception field codes — same fallback
        Strategy Builder itself shows before an LMV sheet is loaded.
        """
        from screens.formula_editor import VariablesManagerDialog
        from services.formula_tokens import all_field_codes
        from services.lmv_inception_fields import FIELD_CODES as _inception_codes

        headers = list(all_field_codes())
        headers += [c for c in _inception_codes if c not in headers]
        first_row: dict = {}
        all_data: list = []
        sb = self._screens.get("strategy_builder")
        if sb is not None and getattr(sb, "_lmv_headers", None):
            headers = list(sb._lmv_headers) + [
                c for c in headers if c not in sb._lmv_headers
            ]
            first_row = getattr(sb, "_lmv_first_row", {}) or {}
            all_data = getattr(sb, "_all_lmv_data", []) or []

        dlg = VariablesManagerDialog(
            headers, first_row, all_data,
            theme=self._controller.theme, parent=self,
        )
        dlg.exec()

    def _clear_cache(self):
        """File > Clear Cache: deletes the local read-cache files that
        mirror server data (services.config_store's config_data.json —
        Formula Builder formulas, Config Editor tabs, highlight colors,
        theme; services.strategy_store's strategies.json — Strategy
        Builder strategies; services.formula_variable_store's
        formula_variables.json — reusable {Name} formula variables), drops
        strategy_engine's compiled-formula cache (which a "{Name}" edit
        can't invalidate on its own — see strategy_engine.
        clear_compile_cache), then re-pulls everything fresh into every
        currently open screen — the same reload reload_per_user_data() does
        on login, plus an open Live Master View window, whose own strategy
        list is a separate in-memory snapshot with the exact same
        staleness issue (see screens.live_viewer.LiveViewerWindow.
        set_strategies' docstring).

        Both files are pure read-caches — load_json()/load_all() always try
        the server first regardless of whether either file exists, so this
        mainly matters for whatever a stale/corrupted local copy would
        otherwise serve the next time the app is offline; deleting them
        loses nothing server-side.

        Deliberately leaves alone:
          - auth_session.json (api.token_store) — the login session, not a
            data cache; clearing it would silently log the user out.
          - strategy_alert_state_<email>.json (services.strategy_alerts.
            state_store) — local-only alert/cooldown history with no
            server copy; deleting it would be real data loss, not a
            cache refresh.
        """
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self, "Clear Cache",
            "This clears locally cached Strategy Builder, Formula "
            "Builder/Config and formula-variable data, then re-fetches "
            "everything fresh from the server. Your login session and "
            "notification alert history are not affected. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from services import config_store, strategy_store, formula_variable_store, strategy_engine
        try:
            config_store.clear_local_cache()
            strategy_store.clear_local_cache()
            formula_variable_store.clear_local_cache()
        except OSError as exc:
            QMessageBox.warning(self, "Clear Cache", f"Could not remove a cache file:\n\n{exc}")
            return

        # A cached compiled formula keeps its pre-edit "{Name}" expansion
        # until this is dropped — the same reason formula_variable_store's
        # own save/delete calls it (see strategy_engine.clear_compile_cache).
        strategy_engine.clear_compile_cache()

        self.reload_per_user_data()

        data_import = self._screens.get("data_import")
        viewer = getattr(data_import, "_live_viewer", None) if data_import is not None else None
        if viewer is not None and not viewer.isHidden():
            viewer._refresh_day_history_from_store()

        QMessageBox.information(
            self, "Clear Cache", "Cache cleared — data refreshed from the server.")

    def reload_per_user_data(self):
        """Re-pulls every eagerly-loaded, now-per-user store — called on
        every successful login (see AppController.show_main_window), not
        just the first. MainWindow itself is reused across a logout/login
        cycle within the same running process (rebuilding it would lose the
        scheduler/tray/notifier state, which must survive — see
        _ensure_scheduler's own comment on that), but each screen's
        in-memory copy of what used to be purely local, device-scoped data
        is now per-user: without this, a second user logging in on the same
        device/process would keep seeing the first user's strategies,
        config, and formulas instead of their own.
        """
        strategy_builder = self._screens.get("strategy_builder")
        if strategy_builder is not None:
            strategy_builder.reload_strategies()

        from services.strategy_alerts import alert_schedule
        from services.strategy_alerts import config_store as alerts_config_store
        from services.strategy_alerts import state_store as alerts_state_store
        alerts_config_store.reload_cache()
        alert_schedule.reload_cache()
        alerts_state_store.reset_for_user_switch()

        notifications = self._screens.get("notifications")
        if notifications is not None:
            notifications.reload_configs()

        live_alerts = self._screens.get("live_alerts")
        if live_alerts is not None:
            live_alerts.reload_alerts()

        formula_builder = self._screens.get("formula_builder")
        if formula_builder is not None:
            formula_builder.reload_formulas()

        formula_stats = self._screens.get("formula_stats")
        if formula_stats is not None:
            formula_stats.reload_strategies()

        self._reload_config_editor()

    def _reload_config_editor(self):
        """ConfigEditorScreen's 4 tabs each load their rows once, inside
        their own __init__ (see screens/config_editor.py::ConfigTabWidget) —
        rather than teaching each one how to repopulate its QTableWidget in
        place, just rebuild the whole screen and swap it into the stack;
        config editor isn't performance-sensitive enough for a full rebuild
        on login to matter."""
        from screens.config_editor import ConfigEditorScreen

        old = self._screens.get("config_editor")
        if old is None:
            return
        was_current = self._stack.currentWidget() is old
        new_screen = ConfigEditorScreen(self._controller)
        idx = self._stack.indexOf(old)
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(idx, new_screen)
        self._screens["config_editor"] = new_screen
        if was_current:
            self._stack.setCurrentWidget(new_screen)

    def _on_theme_toggled(self):
        self._controller.theme.apply()
        self._sidebar.repaint()
        self._topbar.repaint()
        for w in self._screens.values():
            w.repaint()
        self._sidebar.refresh_theme()
        data_import = self._screens.get("data_import")
        if data_import is not None:
            data_import.refresh_theme()
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None and viewer.isVisible():
                viewer.refresh_theme()
        strategy_builder = self._screens.get("strategy_builder")
        if strategy_builder is not None:
            strategy_builder.refresh_theme()
        historic_upload = self._screens.get("historic_upload")
        if historic_upload is not None:
            historic_upload.refresh_theme()
        formula_builder = self._screens.get("formula_builder")
        if formula_builder is not None:
            formula_builder.refresh_theme()
        holidays = self._screens.get("holidays")
        if holidays is not None:
            holidays.refresh_theme()
        jobs = self._screens.get("jobs")
        if jobs is not None:
            jobs.refresh_theme()
        formula_stats = self._screens.get("formula_stats")
        if formula_stats is not None:
            formula_stats.refresh_theme()
        for key in ("inception_view_by_date", "inception_strategy_builder", "inception_hmv",
                    "inception_formula_stats"):
            screen = self._screens.get(key)
            if screen is not None:
                screen.refresh_theme()
