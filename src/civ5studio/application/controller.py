"""Qt controller that binds the presentation shell to application services."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
import re
from typing import Any

from PySide6.QtCore import QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain import (
    CivProject,
    RecipeScope,
    iter_lua_effects,
    load_project,
    lua_effects_compatible,
    recipes_for_scope,
)
from civ5studio.integrations import PromotionsExpansionPackCatalog
from civ5studio.ui.main_window import MainWindow
from civ5studio.ui.history_dialog import ProjectHistoryDialog
from civ5studio.ui.worker import BackgroundTask
from civ5studio.domain.history import (
    HistoryBoundaryError,
    ProjectHistory,
    ProjectHistoryError,
)

from .install import InstallResult, InstallService, default_civ5_mods_path
from .advanced_content import materialize_advanced_sources
from .advanced_operations import (
    AdvancedOperationResult,
    analyze_runtime_logs,
    export_runtime_diagnostics,
    import_existing_mod,
    scan_compatibility,
)
from .localization import load_localization_csv, save_localization_csv
from .mod_importer import IMPORT_EXTENSION_KEY, copy_imported_snapshot
from .project_adapter import project_from_ui, project_to_ui, save_ui_project
from .project_history import ProjectHistoryPersistenceError, ProjectHistoryStore
from .workflow import ProjectWorkflowService, WorkflowMode, WorkflowResult
from .workspace import ProjectWorkspace, RecoveryError, WorkspaceError


PROJECT_FILTER = "Civilization Studio projects (*.civ5project.json);;JSON files (*.json)"
HISTORY_WORKSPACE_PREFIX = "civ5studio-workspace://"


class ApplicationController:
    def __init__(
        self,
        window: MainWindow,
        *,
        workflow: ProjectWorkflowService | None = None,
        installer: InstallService | None = None,
    ) -> None:
        self.window = window
        self.workflow = workflow or ProjectWorkflowService()
        self.installer = installer or InstallService()
        self.thread_pool = QThreadPool.globalInstance()
        self.project: CivProject | None = None
        self.workspace: ProjectWorkspace | None = None
        self.last_build_path: Path | None = None
        self._tasks: set[BackgroundTask] = set()
        self._project_revision = 0
        self._active_pipeline_stage: str | None = None
        self.history = ProjectHistory(max_entries=200, max_snapshots=100)
        self.history_store: ProjectHistoryStore | None = None
        self._history_persistence_blocked = False
        self._live_validation_timer = QTimer(self.window)
        self._live_validation_timer.setSingleShot(True)
        self._live_validation_timer.setInterval(450)
        self._live_validation_timer.timeout.connect(self._run_live_validation)
        self._autosave_timer = QTimer(self.window)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1500)
        self._autosave_timer.timeout.connect(self._autosave_workspace)
        self._history_timer = QTimer(self.window)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(500)
        self._history_timer.timeout.connect(self._record_history)
        self._populate_references()
        self._blank_data = deepcopy(self.window.collect_values())
        self.history.reset(self._to_history_state(self._blank_data), label="New project")
        self.window.mark_clean()
        self._connect()
        self._update_history_actions()

    def _connect(self) -> None:
        self.window.newRequested.connect(self.new_project)
        self.window.openRequested.connect(self.open_project)
        self.window.saveRequested.connect(self.save_project)
        self.window.auditRequested.connect(
            lambda data: self.start_operation(WorkflowMode.AUDIT, data)
        )
        self.window.validateRequested.connect(
            lambda data: self.start_operation(WorkflowMode.VALIDATE, data)
        )
        self.window.buildRequested.connect(
            lambda data: self.start_operation(WorkflowMode.BUILD, data)
        )
        self.window.installRequested.connect(self.install_last_build)
        self.window.launchRequested.connect(self.launch_civilization_v)
        self.window.analyzeLogsRequested.connect(self.analyze_game_logs)
        self.window.undoRequested.connect(self.undo)
        self.window.redoRequested.connect(self.redo)
        self.window.snapshotRequested.connect(self.create_snapshot)
        self.window.historyRequested.connect(self.show_history)
        self.window.openArtifactRequested.connect(self.open_artifact)
        advanced = self.window.advanced_page
        advanced.importModRequested.connect(self.import_existing_mod)
        advanced.analyzeLogsRequested.connect(self.analyze_game_logs)
        advanced.exportDiagnosticsRequested.connect(self.export_diagnostics)
        advanced.scanCompatibilityRequested.connect(self.scan_compatibility)
        advanced.importLocalizationCsvRequested.connect(
            self.import_localization_csv
        )
        advanced.exportLocalizationCsvRequested.connect(
            self.export_localization_csv
        )
        for page in self.window.pages[:-1]:
            page.changed.connect(self._project_changed)

    def _populate_references(self) -> None:
        catalog = ReferenceCatalog.bundled()
        pep_catalog = PromotionsExpansionPackCatalog.bundled()
        lua_definitions = list(iter_lua_effects())
        self.window.set_reference_catalog(
            civilizations=sorted(catalog.values("civilizations")),
            unit_templates=sorted(catalog.unit_class_to_base_unit.items()),
            building_templates=sorted(catalog.building_class_to_base_building.items()),
            improvement_templates=sorted(catalog.improvements),
            yields=sorted(catalog.values("yields")),
            technologies=sorted(catalog.values("technologies")),
            promotions=sorted(catalog.values("promotions")),
            domains=sorted(catalog.values("domains")),
            trait_recipes=[
                {
                    "recipe_id": recipe.recipe_id,
                    "label": recipe.label,
                    "summary": recipe.summary,
                    "storage_path": recipe.storage_path,
                }
                for recipe in recipes_for_scope(RecipeScope.TRAIT)
                if recipe.is_compiled
            ],
            lua_effects=[
                {
                    "effect_id": effect.effect_id,
                    "version": effect.version,
                    "label": effect.label,
                    "category": effect.category,
                    "description": effect.description,
                    "primitive_id": effect.primitive_id,
                    "trigger": effect.trigger,
                    "default_parameters": effect.parameter_defaults(),
                    "parameters": [
                        {
                            "key": parameter.key,
                            "label": parameter.label,
                            "kind": parameter.kind.value,
                            "default": parameter.default,
                            "minimum": parameter.minimum,
                            "maximum": parameter.maximum,
                            "choices": list(parameter.choices),
                            "description": parameter.description,
                        }
                        for parameter in effect.parameters
                    ],
                    "origin": effect.origin.value,
                    "inspiration": effect.inspiration,
                    "tags": sorted(effect.tags),
                    "pure_bnw": effect.pure_bnw,
                    "supports_multiplayer": effect.supports_multiplayer,
                    "supports_hotseat": effect.supports_hotseat,
                    "runtime_notes": effect.runtime_notes,
                    "incompatible_effect_ids": [
                        other.effect_id
                        for other in lua_definitions
                        if other.effect_id != effect.effect_id
                        and not lua_effects_compatible(effect, other)
                    ],
                }
                for effect in lua_definitions
            ],
            promotions_expansion_pack=pep_catalog.ui_entries(),
            diplomacy_responses=sorted(catalog.values("diplomacy_responses")),
        )
        default_mods = default_civ5_mods_path()
        advanced = self.window.advanced_page
        advanced.compatibility_mods_root.setText(str(default_mods))
        advanced.test_civ5_root.setText(str(default_mods.parent))

    def new_project(self) -> None:
        if self._reject_while_busy("create a new project"):
            return
        if not self._confirm_abandon():
            return
        self.project = None
        self.workspace = None
        self.last_build_path = None
        self._autosave_timer.stop()
        self._live_validation_timer.stop()
        self._history_timer.stop()
        self.window.load_values(deepcopy(self._blank_data), None)
        self.history_store = None
        self._history_persistence_blocked = False
        self.history = ProjectHistory(max_entries=200, max_snapshots=100)
        self.history.reset(
            self._to_history_state(self.window.collect_values()),
            label="New project",
        )
        self.window.review_page.reset_pipeline()
        self._update_history_actions()
        self._project_revision += 1
        self.window.statusBar().showMessage("New project ready")

    def open_project(self) -> None:
        if self._reject_while_busy("open another project"):
            return
        if not self._confirm_abandon():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self.window,
            "Open Civilization Studio project",
            str(self.window.project_path.parent if self.window.project_path else Path.home() / "Documents"),
            PROJECT_FILTER,
        )
        if filename:
            self.open_path(filename)

    def open_path(self, path: str | Path) -> bool:
        source = Path(path).resolve()
        try:
            workspace = None
            marker = source.parent / ".civ5studio" / "workspace.json"
            if marker.is_file():
                workspace = ProjectWorkspace.open_project_file(source)
                if not self._resolve_recovery(workspace):
                    return False
                project = workspace.load()
            else:
                project = load_project(source)
            values = project_to_ui(project, source.parent)
        except Exception as exc:
            QMessageBox.critical(self.window, "Could not open project", str(exc))
            return False
        self.project = project
        self.workspace = workspace
        self.last_build_path = None
        self.window.load_values(values, source)
        self._attach_history(workspace, values, label="Opened saved project")
        self.window.review_page.reset_pipeline()
        self._project_revision += 1
        suffix = " (portable workspace)" if workspace else " (legacy loose project)"
        if self._history_persistence_blocked:
            suffix += " · history disabled; the unreadable history file was left untouched"
        self.window.statusBar().showMessage(f"Opened {source}{suffix}")
        self._run_live_validation()
        return True

    def save_project(self, force_as: bool = False) -> bool:
        if self._reject_while_busy("save the project"):
            return False
        self._record_history(label="Before save")
        return self._save_values(self.window.collect_values(), force_as)

    def _save_values(
        self,
        values: dict[str, Any],
        force_as: bool,
        *,
        preserve_review: bool = False,
    ) -> bool:
        creating_workspace = force_as or self.window.project_path is None
        if creating_workspace:
            mod_name = str(values.get("project", {}).get("mod_name", "")).strip()
            stem = re.sub(r"[^A-Za-z0-9 _-]+", "", mod_name).strip() or "New Civilization"
            parent = QFileDialog.getExistingDirectory(
                self.window,
                "Choose a parent folder for the self-contained project workspace",
                str(
                    self.window.project_path.parent
                    if self.window.project_path
                    else Path.home() / "Documents"
                ),
            )
            if not parent:
                return False
            workspace_root = Path(parent).resolve() / f"{stem} Civilization Studio Project"
            project_file = f"{stem}.civ5project.json"
            source_base = (
                self.window.project_path.parent if self.window.project_path else None
            )
            source_workspace = self.workspace
            try:
                draft = project_from_ui(values, existing=self.project)
                if (
                    IMPORT_EXTENSION_KEY in draft.extensions
                    and source_workspace is None
                ):
                    raise WorkspaceError(
                        "This imported-mod inspection project is no longer attached "
                        "to its marked source workspace, so its immutable snapshot "
                        "cannot be verified or copied. Open the project from its "
                        "original Civilization Studio workspace and try Save As again."
                    )
                workspace = ProjectWorkspace.create(
                    workspace_root,
                    draft,
                    project_file=project_file,
                    source_root=source_base,
                )
                if source_workspace is not None:
                    copy_imported_snapshot(draft, source_workspace, workspace)
                portable = materialize_advanced_sources(
                    workspace.load(), workspace.root, source_root=source_base
                )
                workspace.save(portable, require_assets=False)
                project = workspace.load()
            except Exception as exc:
                QMessageBox.critical(
                    self.window, "Could not create project workspace", str(exc)
                )
                return False
            destination = workspace.project_path
            self.workspace = workspace
            self._history_persistence_blocked = False
        else:
            destination = Path(self.window.project_path).resolve()
            source_base = destination.parent
            try:
                if self.workspace is not None:
                    draft = project_from_ui(values, existing=self.project)
                    portable = self.workspace.materialize_sources(
                        draft, source_root=source_base
                    )
                    portable = materialize_advanced_sources(
                        portable, self.workspace.root, source_root=source_base
                    )
                    self.workspace.save(portable, require_assets=False)
                    project = self.workspace.load()
                else:
                    project, _portable = save_ui_project(
                        destination,
                        values,
                        existing=self.project,
                        source_base=source_base,
                    )
            except Exception as exc:
                QMessageBox.critical(self.window, "Could not save project", str(exc))
                return False
        self.project = project
        if not preserve_review:
            self.last_build_path = None
        self._autosave_timer.stop()
        saved_values = project_to_ui(project, destination.parent)
        self.window.load_values(
            saved_values,
            destination,
            reset_review=not preserve_review,
        )
        self.history.record(
            self._to_history_state(saved_values), label="Saved project"
        )
        self.history_store = (
            ProjectHistoryStore(self.workspace)
            if self.workspace is not None
            and not self._history_persistence_blocked
            else None
        )
        history_persisted = self._persist_history()
        self._update_history_actions()
        if self._history_persistence_blocked:
            self.window.statusBar().showMessage(
                f"Saved {destination} · unreadable history was left untouched; use Save As for a clean workspace"
            )
        elif self.history_store is not None and not history_persisted:
            self.window.statusBar().showMessage(
                f"Saved {destination} · project history could not be persisted"
            )
        else:
            self.window.statusBar().showMessage(f"Saved {destination}")
        return True

    def _project_changed(self) -> None:
        if self.window.is_loading:
            return
        self._project_revision += 1
        self.last_build_path = None
        self._live_validation_timer.start()
        self._history_timer.start()
        if self.workspace is not None:
            self._autosave_timer.start()

    def _draft_project(self) -> CivProject:
        return project_from_ui(self.window.collect_values(), existing=self.project)

    def _run_live_validation(self) -> None:
        if self._tasks:
            return
        try:
            draft = self._draft_project()
            root = self.window.project_path.parent if self.window.project_path else None
            report = self.workflow.build_service.audit(draft, root)
        except Exception as exc:
            issues = [
                {
                    "severity": "ERROR",
                    "location": "project",
                    "message": f"Live validation could not read the draft: {exc}",
                    "code": "live.draft",
                }
            ]
            summary = "Live check: the current draft could not be interpreted."
        else:
            issues = [
                {
                    "severity": item.severity.value.upper(),
                    "location": item.path,
                    "message": item.message,
                    "code": item.code,
                    "hint": item.hint,
                }
                for item in report.issues
            ]
            summary = (
                f"Live check: {len(report.errors)} error(s), "
                f"{len(report.warnings)} warning(s). "
                "Use Validate release for the complete art and package gate."
            )
        self.window.set_live_issues(issues, summary, can_install=False)

    def _autosave_workspace(self) -> None:
        if self.workspace is None or not self.window.is_dirty or self._tasks:
            return
        try:
            draft = self._draft_project()
            portable = self.workspace.materialize_sources(
                draft, source_root=self.workspace.root
            )
            portable = materialize_advanced_sources(
                portable, self.workspace.root, source_root=self.workspace.root
            )
            self.workspace.autosave(portable)
        except WorkspaceError as exc:
            self.window.statusBar().showMessage(f"Autosave paused: {exc}")
        except Exception as exc:
            self.window.statusBar().showMessage(f"Autosave could not complete: {exc}")
        else:
            self.window.statusBar().showMessage("Recovery autosave updated")

    def _resolve_recovery(self, workspace: ProjectWorkspace) -> bool:
        try:
            status = workspace.recovery_status()
        except RecoveryError as exc:
            QMessageBox.critical(self.window, "Recovery data is invalid", str(exc))
            return False
        if not status.available:
            return True
        box = QMessageBox(self.window)
        box.setWindowTitle("Recover unsaved project changes")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("A newer crash-recovery autosave is available for this project.")
        detail = f"Autosave: {status.updated_utc or status.autosave_path}"
        if status.base_matches_current is False:
            detail += (
                "\nThe project file changed after the autosave was created; "
                "recovering will retain the current file as a backup."
            )
        box.setInformativeText(detail)
        recover_button = box.addButton("Recover autosave", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard autosave", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        try:
            if clicked is recover_button:
                workspace.recover()
                return True
            if clicked is discard_button:
                workspace.discard_recovery()
                return True
        except WorkspaceError as exc:
            QMessageBox.critical(self.window, "Recovery failed", str(exc))
        return False

    def start_operation(self, mode: WorkflowMode, values: dict[str, Any]) -> None:
        if self._reject_while_busy(f"start {mode.value}"):
            return
        history_values = self._to_history_state(values)
        self.history.record(history_values, label="Current edit")
        self._persist_history()
        self._update_history_actions()
        if not self._save_values(values, False, preserve_review=True):
            return
        if mode is WorkflowMode.BUILD:
            saved_history_values = self._to_history_state(
                self.window.collect_values()
            )
            self.history.snapshot_before_build(
                state=saved_history_values,
                detail=str(
                    values.get("project", {}).get(
                        "mod_name", "release candidate"
                    )
                ),
            )
            self._persist_history()
            self._update_history_actions()
        assert self.project is not None and self.window.project_path is not None
        project_id = self.project.project_id
        project_revision = self._project_revision
        source_root = self.window.project_path.parent
        ui_options = self.project.extensions.get("ui", {})
        configured_output = (
            ui_options.get("project_root", "") if isinstance(ui_options, dict) else ""
        )
        output_root = Path(str(configured_output)) if configured_output else source_root / "Build Output"
        if not output_root.is_absolute():
            output_root = source_root / output_root
        self.window.review_page.log.clear()
        self._active_pipeline_stage = mode.value
        self.window.review_page.set_pipeline_stage(
            mode.value,
            "RUNNING",
            f"{mode.value.title()} is running for the saved current project revision.",
        )
        self.window.set_busy(True, f"Starting {mode.value}…")
        task = BackgroundTask(
            self.workflow.run,
            self.project,
            source_root=source_root,
            output_root=output_root,
            mode=mode,
        )
        task.signals.progress.connect(self._on_progress)
        task.signals.log.connect(self.window.append_log)
        task.signals.result.connect(
            lambda value, pid=project_id, revision=project_revision: (
                self._operation_finished(value, pid, revision)
            )
        )
        task.signals.failed.connect(
            lambda message, detail, pid=project_id, revision=project_revision: (
                self._operation_failed_for_project(
                    message, detail, pid, revision
                )
            )
        )
        task.signals.finished.connect(lambda: self._task_finished(task))
        self._tasks.add(task)
        self.thread_pool.start(task)

    def _on_progress(self, value: int, message: str) -> None:
        self.window.review_page.progress.setRange(0, 100)
        self.window.review_page.progress.setValue(value)
        if message:
            self.window.append_log(f"[{value:3d}%] {message}")

    def _operation_finished(
        self, value: object, project_id: str, project_revision: int
    ) -> None:
        if not self._operation_matches(project_id, project_revision):
            self.last_build_path = None
            build_path = (
                value.build_path
                if isinstance(value, WorkflowResult)
                else None
            )
            message = (
                "An operation finished for an older project revision. Its result "
                "was not attached to the current project and cannot be installed."
            )
            if build_path:
                message += f" Output remains at {build_path}."
            self.window.append_log(message)
            self.window.statusBar().showMessage(message)
            if isinstance(value, WorkflowResult):
                self.window.review_page.set_pipeline_stage(
                    value.mode.value,
                    "STALE",
                    message,
                    artifact_path=str(build_path) if build_path else None,
                )
            return
        if not isinstance(value, WorkflowResult):
            self._operation_failed("Service returned an unknown result.", "")
            return
        self.last_build_path = value.build_path if value.can_install else None
        detail_parts = [value.summary]
        if value.build_path:
            detail_parts.append(f"Build: {value.build_path}")
        if value.package_path:
            detail_parts.append(f"ZIP: {value.package_path}")
        self.window.review_page.set_pipeline_stage(
            value.mode.value,
            "PASS" if value.succeeded else "BLOCKED",
            "\n".join(detail_parts),
            artifact_path=(
                str(value.build_path or value.package_path)
                if value.build_path or value.package_path
                else None
            ),
        )
        if value.build_path:
            self.window.advanced_page.test_generated_mod_root.setText(
                str(value.build_path)
            )
        self.window.show_issues(
            [item.to_dict() for item in value.issues],
            value.summary,
            can_install=value.can_install,
        )
        if value.build_path:
            self.window.append_log(f"Build folder: {value.build_path}")
        if value.package_path:
            self.window.append_log(f"Player ZIP: {value.package_path}")
        self.window.statusBar().showMessage(value.summary)

    def _operation_failed(self, message: str, detail: str) -> None:
        self.last_build_path = None
        if self._active_pipeline_stage:
            self.window.review_page.set_pipeline_stage(
                self._active_pipeline_stage,
                "ERROR",
                message,
            )
        if detail:
            self.window.append_log(detail)
        self.window.show_issues(
            [{"severity": "ERROR", "location": "application", "message": message}],
            "The operation stopped unexpectedly.",
            can_install=False,
        )
        QMessageBox.critical(self.window, "Operation failed", message)

    def _operation_failed_for_project(
        self,
        message: str,
        detail: str,
        project_id: str,
        project_revision: int,
    ) -> None:
        if not self._operation_matches(project_id, project_revision):
            self.last_build_path = None
            self.window.append_log(detail or message)
            self.window.statusBar().showMessage(
                "An operation for an older project revision failed; the current "
                "project was not changed."
            )
            return
        self._operation_failed(message, detail)

    def _task_finished(self, task: BackgroundTask) -> None:
        self._tasks.discard(task)
        self.window.set_busy(False)
        self._active_pipeline_stage = None
        if self.window.is_dirty:
            self._live_validation_timer.start()

    def install_last_build(self) -> None:
        if self._reject_while_busy("install a build"):
            return
        if self.last_build_path is None or not self.last_build_path.is_dir():
            QMessageBox.warning(
                self.window,
                "No validated build",
                "Run a successful strict build before installing.",
            )
            return
        default = default_civ5_mods_path()
        box = QMessageBox(self.window)
        box.setWindowTitle("Install validated mod")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"Install this build into the default Civ V MODS folder?\n\n{default}")
        box.setInformativeText(
            "An existing folder with the same name will be moved to a timestamped backup."
        )
        default_button = box.addButton("Install to default", QMessageBox.ButtonRole.AcceptRole)
        browse_button = box.addButton("Choose MODS folder…", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is default_button:
            mods_root = default
        elif clicked is browse_button:
            selected = QFileDialog.getExistingDirectory(
                self.window,
                "Choose Civilization V MODS folder",
                str(default if default.exists() else default.parent),
            )
            if not selected:
                return
            mods_root = Path(selected)
        else:
            return

        self._active_pipeline_stage = "install"
        self.window.review_page.set_pipeline_stage(
            "install", "RUNNING", f"Installing validated build to {mods_root}."
        )
        self.window.set_busy(True, "Installing validated build…")
        task = BackgroundTask(self.installer.install, self.last_build_path, mods_root)
        install_revision = self._project_revision
        task.signals.progress.connect(self._on_progress)
        task.signals.log.connect(self.window.append_log)
        task.signals.result.connect(
            lambda value, revision=install_revision: self._install_finished(
                value, revision
            )
        )
        task.signals.failed.connect(self._operation_failed)
        task.signals.finished.connect(lambda: self._task_finished(task))
        self._tasks.add(task)
        self.thread_pool.start(task)

    def _install_finished(self, value: object, project_revision: int) -> None:
        if not isinstance(value, InstallResult):
            self._operation_failed("Installer returned an unknown result.", "")
            return
        message = f"Installed to:\n{value.destination}"
        if value.backup_path:
            message += f"\n\nPrevious install retained at:\n{value.backup_path}"
        if project_revision == self._project_revision:
            self.window.review_page.set_pipeline_stage(
                "install",
                "PASS",
                f"Installed to {value.destination}",
                artifact_path=str(value.destination),
            )
        else:
            self.window.review_page.set_pipeline_stage(
                "install",
                "STALE",
                "The install completed, but the project changed while it ran. Rebuild and reinstall the current revision.",
                artifact_path=str(value.destination),
            )
            message += (
                "\n\nThe project changed while installation ran. This installed copy "
                "is not the current editor revision."
            )
        self.window.statusBar().showMessage(f"Installed {value.destination.name}")
        QMessageBox.information(self.window, "Install complete", message)

    def launch_civilization_v(self) -> None:
        """Request a normal Steam launch while preserving the runtime boundary."""

        if self._reject_while_busy("launch Civilization V"):
            return
        install_ready = self.window.review_page.pipeline.status("install") == "PASS"
        readiness = (
            "The command center records a validated install for this revision."
            if install_ready
            else "No validated install is recorded for this revision; the custom civilization may not be available."
        )
        result = QMessageBox.question(
            self.window,
            "Launch Civilization V",
            f"{readiness}\n\nOpen Civilization V through Steam now?\n\n"
            "Launching is not a test result. The runtime gate remains NOT RUN until you "
            "exercise the exact mod in BNW and explicitly record PASS or FAIL.",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result != QMessageBox.StandardButton.Open:
            return
        launched = QDesktopServices.openUrl(QUrl("steam://rungameid/8930"))
        if launched:
            self.window.review_page.runtime_status.setCurrentText("NOT RUN")
            self.window.review_page.set_pipeline_stage(
                "launch",
                "REQUESTED",
                "Steam accepted the Civ V launch request. Runtime result remains NOT RUN.",
            )
            self.window.statusBar().showMessage(
                "Civilization V launch requested · runtime testing is still NOT RUN"
            )
        else:
            self.window.review_page.set_pipeline_stage(
                "launch",
                "ERROR",
                "Windows could not hand the Civilization V request to Steam.",
            )
            QMessageBox.warning(
                self.window,
                "Could not launch Civilization V",
                "Steam did not accept the Civ V launch request. Start the game normally, then return to analyze fresh logs.",
            )

    def open_artifact(self, path: str) -> None:
        """Open an explicitly displayed local output after a user click."""

        candidate = Path(str(path)).expanduser()
        if not candidate.exists():
            QMessageBox.warning(
                self.window,
                "Artifact is unavailable",
                f"The recorded output no longer exists:\n\n{candidate}",
            )
            return
        resolved = candidate.resolve()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
            QMessageBox.warning(
                self.window,
                "Could not open artifact",
                f"Windows could not open:\n\n{resolved}",
            )
            return
        self.window.statusBar().showMessage(f"Opened artifact {resolved}")

    def import_existing_mod(self, source: str, destination_parent: str) -> None:
        if self._reject_while_busy("import a mod"):
            return
        if not self._confirm_abandon():
            return
        self._record_history(label="Before import")
        self.history.snapshot_before_import(
            state=self._to_history_state(self.window.collect_values()),
            detail=Path(source).name,
        )
        self._persist_history()
        self._update_history_actions()
        project_revision = self._project_revision
        project_id = self.project.project_id if self.project is not None else None
        self._start_advanced_task(
            import_existing_mod,
            (source, destination_parent),
            lambda value, revision=project_revision, pid=project_id: (
                self._import_finished(value, revision, pid)
            ),
            self.window.advanced_page.set_import_result,
            "Importing an immutable source snapshot...",
        )

    def analyze_game_logs(self, civ5_root: str, generated_mod_root: str) -> None:
        if self._tasks:
            self.window.review_page.set_pipeline_stage(
                "analyze", "WARNING", "Another application operation is already running."
            )
            return
        self._active_pipeline_stage = "analyze"
        self.window.review_page.set_pipeline_stage(
            "analyze",
            "RUNNING",
            "Reading fresh Civ V logs and attributing findings without modifying game data.",
        )
        self._start_advanced_task(
            analyze_runtime_logs,
            (civ5_root, generated_mod_root),
            lambda value, revision=self._project_revision, logs_path=str(
                Path(civ5_root).expanduser() / "Logs"
            ): self._diagnostics_finished(
                value, revision, logs_path
            ),
            self.window.advanced_page.set_diagnostics_result,
            "Reading Civ V logs without changing the game folder...",
        )

    def export_diagnostics(
        self, civ5_root: str, generated_mod_root: str, destination_zip: str
    ) -> None:
        self._start_advanced_task(
            export_runtime_diagnostics,
            (civ5_root, generated_mod_root, destination_zip),
            self._diagnostics_export_finished,
            self.window.advanced_page.set_diagnostics_result,
            "Creating a redacted diagnostics bundle...",
        )

    def scan_compatibility(self, mods_root: str) -> None:
        self._start_advanced_task(
            scan_compatibility,
            (mods_root,),
            self._compatibility_finished,
            self.window.advanced_page.set_compatibility_result,
            "Scanning installed mod metadata read-only...",
        )

    def import_localization_csv(self, path: str) -> None:
        try:
            result = load_localization_csv(path)
        except Exception as exc:
            self.window.advanced_page.set_localization_result(str(exc), True)
            return
        if not result.is_valid:
            summary = "\n".join(
                f"Row {item.row}: {item.message}" for item in result.issues
            )
            self.window.advanced_page.set_localization_result(summary, True)
            return
        self.window.advanced_page.set_localization_entries(result.entries)
        count = sum(len(values) for values in result.entries.values())
        self.window.advanced_page.set_localization_result(
            f"Imported {count} localization row(s) from {path}."
        )

    def export_localization_csv(self, path: str) -> None:
        entries = self.window.advanced_page.values()["localization"]["entries"]
        try:
            destination = save_localization_csv(path, entries)
        except Exception as exc:
            self.window.advanced_page.set_localization_result(str(exc), True)
            return
        self.window.advanced_page.set_localization_result(
            f"Exported localization CSV without overwriting another file:\n{destination}"
        )

    def _start_advanced_task(
        self,
        function,
        args: tuple,
        on_result,
        result_setter,
        message: str,
    ) -> None:
        if self._tasks:
            result_setter("Another application operation is already running.", True)
            return
        result_setter(message, False)
        task = BackgroundTask(function, *args)
        task.signals.result.connect(on_result)
        task.signals.failed.connect(
            lambda error, detail: self._advanced_operation_failed(
                result_setter, error, detail
            )
        )
        task.signals.finished.connect(lambda: self._advanced_task_finished(task))
        self._tasks.add(task)
        self.thread_pool.start(task)

    def _advanced_operation_failed(self, result_setter, error: str, detail: str) -> None:
        result_setter(
            (error + ("\n\n" + detail if detail else "")).strip(), True
        )
        if self._active_pipeline_stage == "analyze":
            self.window.review_page.set_pipeline_stage(
                "analyze", "ERROR", error
            )

    def _advanced_task_finished(self, task: BackgroundTask) -> None:
        self._tasks.discard(task)
        if self._active_pipeline_stage == "analyze":
            self._active_pipeline_stage = None
        if self.window.is_dirty:
            self._live_validation_timer.start()

    def _import_finished(
        self,
        value: object,
        project_revision: int,
        project_id: str | None,
    ) -> None:
        if not isinstance(value, AdvancedOperationResult) or value.imported is None:
            self.window.advanced_page.set_import_result(
                "Importer returned an unknown result.", True
            )
            return
        current_id = self.project.project_id if self.project is not None else None
        if self._project_revision != project_revision or current_id != project_id:
            self.window.advanced_page.set_import_result(
                value.summary
                + "\n\nThe current project changed while the import ran, so the "
                "new workspace was not opened automatically. Save your current "
                "work, then open:\n"
                + str(value.imported.workspace.project_path)
            )
            return
        self.window.advanced_page.set_import_result(value.summary)
        self.open_path(value.imported.workspace.project_path)

    def _diagnostics_finished(
        self,
        value: object,
        project_revision: int | None = None,
        logs_path: str | None = None,
    ) -> None:
        if not isinstance(value, AdvancedOperationResult):
            self.window.advanced_page.set_diagnostics_result(
                "Diagnostics returned an unknown result.", True
            )
            self.window.review_page.set_pipeline_stage(
                "analyze", "ERROR", "Diagnostics returned an unknown result."
            )
            return
        self.window.advanced_page.set_diagnostics_result(value.summary)
        if project_revision is None or project_revision == self._project_revision:
            self.window.review_page.set_pipeline_stage(
                "analyze",
                "COMPLETE",
                "Log attribution completed. This is evidence collection, not an in-game PASS.",
                artifact_path=logs_path,
            )
        else:
            self.window.review_page.set_pipeline_stage(
                "analyze",
                "STALE",
                "Log analysis completed for an older editor revision. Review the evidence, then retest the current build.",
                artifact_path=logs_path,
            )

    def _diagnostics_export_finished(self, value: object) -> None:
        if not isinstance(value, AdvancedOperationResult):
            self.window.advanced_page.set_diagnostics_result(
                "Diagnostics export returned an unknown result.", True
            )
            return
        self.window.advanced_page.set_diagnostics_result(value.summary)

    def _compatibility_finished(self, value: object) -> None:
        if not isinstance(value, AdvancedOperationResult):
            self.window.advanced_page.set_compatibility_result(
                "Compatibility scan returned an unknown result.", True
            )
            return
        self.window.advanced_page.set_compatibility_result(value.summary)

    # ------------------------------------------------------------------
    # Bounded undo, redo, and project-owned named snapshots

    def _to_history_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Tokenize only paths demonstrably inside the current workspace."""

        root = self.workspace.root.resolve() if self.workspace is not None else None

        def portable(value):
            if isinstance(value, dict):
                return {str(key): portable(item) for key, item in value.items()}
            if isinstance(value, list):
                return [portable(item) for item in value]
            if not isinstance(value, str) or root is None or not value:
                return value
            try:
                candidate = Path(value)
                if not candidate.is_absolute():
                    return value
                resolved = candidate.resolve(strict=False)
                if not resolved.is_relative_to(root):
                    return value
                relative = resolved.relative_to(root).as_posix()
            except (OSError, ValueError):
                return value
            return HISTORY_WORKSPACE_PREFIX + relative

        return portable(state)

    def _from_history_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Expand validated workspace tokens for the current UI session."""

        root = self.workspace.root.resolve() if self.workspace is not None else None

        def expand(value):
            if isinstance(value, dict):
                return {str(key): expand(item) for key, item in value.items()}
            if isinstance(value, list):
                return [expand(item) for item in value]
            if (
                not isinstance(value, str)
                or root is None
                or not value.startswith(HISTORY_WORKSPACE_PREFIX)
            ):
                return value
            relative = PurePosixPath(value[len(HISTORY_WORKSPACE_PREFIX) :])
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ProjectHistoryError("Project history contains an unsafe workspace path.")
            candidate = root.joinpath(*relative.parts).resolve(strict=False)
            if not candidate.is_relative_to(root):
                raise ProjectHistoryError("Project history path escapes the workspace.")
            return str(candidate)

        return expand(state)

    def _attach_history(
        self,
        workspace: ProjectWorkspace | None,
        state: dict[str, Any],
        *,
        label: str,
    ) -> None:
        self._history_timer.stop()
        self._history_persistence_blocked = False
        self.history_store = ProjectHistoryStore(workspace) if workspace else None
        if self.history_store is None:
            self.history = ProjectHistory(max_entries=200, max_snapshots=100)
        else:
            try:
                self.history = self.history_store.load()
            except ProjectHistoryPersistenceError as exc:
                self.history = ProjectHistory(max_entries=200, max_snapshots=100)
                self.history_store = None
                self._history_persistence_blocked = True
                self.window.statusBar().showMessage(
                    "Project history could not be loaded. The unreadable file was "
                    f"left untouched and history is session-only: {exc}"
                )
        self.history.reset(
            self._to_history_state(state),
            label=label,
            clear_snapshots=self.history_store is None,
        )
        self._persist_history()
        self._update_history_actions()

    def _record_history(self, label: str = "Edit") -> None:
        if self.window.is_loading:
            return
        try:
            self.history.record(
                self._to_history_state(self.window.collect_values()), label=label
            )
        except ProjectHistoryError as exc:
            self.window.statusBar().showMessage(f"Project history skipped an edit: {exc}")
            return
        self._persist_history()
        self._update_history_actions()

    def _persist_history(self) -> bool:
        if self.history_store is None:
            return False
        try:
            self.history_store.save(self.history)
        except ProjectHistoryPersistenceError as exc:
            self.window.statusBar().showMessage(
                f"Project history could not be persisted: {exc}"
            )
            return False
        return True

    def _update_history_actions(self) -> None:
        entries = self.history.entries
        cursor = self.history.cursor
        undo_label = entries[cursor].label if self.history.can_undo and cursor >= 0 else ""
        redo_label = (
            entries[cursor + 1].label
            if self.history.can_redo and cursor + 1 < len(entries)
            else ""
        )
        self.window.set_history_state(
            can_undo=self.history.can_undo,
            can_redo=self.history.can_redo,
            undo_label=undo_label,
            redo_label=redo_label,
        )

    def undo(self) -> None:
        if self._reject_while_busy("undo an edit"):
            return
        self._history_timer.stop()
        self._record_history(label="Current edit")
        try:
            state = self.history.undo()
        except HistoryBoundaryError:
            self._update_history_actions()
            return
        self._apply_history_state(state, "Undo restored the previous project revision")

    def redo(self) -> None:
        if self._reject_while_busy("redo an edit"):
            return
        self._history_timer.stop()
        try:
            state = self.history.redo()
        except HistoryBoundaryError:
            self._update_history_actions()
            return
        self._apply_history_state(state, "Redo restored the next project revision")

    def create_snapshot(self, label: str) -> None:
        if self._reject_while_busy("create a snapshot"):
            return
        self._history_timer.stop()
        self._record_history(label="Snapshot source")
        try:
            snapshot = self.history.create_snapshot(
                label,
                state=self._to_history_state(self.window.collect_values()),
            )
        except ProjectHistoryError as exc:
            QMessageBox.warning(self.window, "Snapshot not created", str(exc))
            return
        persisted = self._persist_history()
        self._update_history_actions()
        if self.history_store is not None and persisted:
            self.window.statusBar().showMessage(
                f"Created snapshot '{snapshot.label}' in {self.history_store.path}"
            )
        elif self.history_store is not None:
            self.window.statusBar().showMessage(
                f"Created snapshot '{snapshot.label}' in memory only; workspace history could not be persisted"
            )
        elif self._history_persistence_blocked:
            self.window.statusBar().showMessage(
                f"Created snapshot '{snapshot.label}' for this session only; unreadable workspace history remains untouched"
            )
        else:
            self.window.statusBar().showMessage(
                f"Created snapshot '{snapshot.label}' in this application session (save into a Studio workspace to persist it)"
            )

    def show_history(self) -> None:
        self._history_timer.stop()
        self._record_history(label="Current edit")
        current_state = self._to_history_state(self.window.collect_values())
        entries = [
            {
                "label": entry.label,
                "created_utc": entry.created_utc,
                "digest": entry.digest,
                "current": index == self.history.cursor,
            }
            for index, entry in enumerate(self.history.entries)
        ]
        snapshots = []
        for snapshot in self.history.snapshots:
            comparison = self.history.compare_snapshot(
                snapshot.snapshot_id, state=current_state, max_paths=12
            )
            snapshots.append(
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "label": snapshot.label,
                    "created_utc": snapshot.created_utc,
                    "reason": snapshot.reason.value,
                    "comparison": {
                        "total_changes": comparison.total_changes,
                        "modified_sections": list(comparison.modified_sections),
                        "changed_paths": list(comparison.changed_paths),
                    },
                }
            )
        dialog = ProjectHistoryDialog(
            entries=entries,
            snapshots=snapshots,
            parent=self.window,
        )
        if not dialog.exec() or not dialog.selected_snapshot_id:
            return
        try:
            if dialog.selected_section:
                state = self.history.restore_section(
                    dialog.selected_snapshot_id,
                    dialog.selected_section,
                    base_state=current_state,
                )
                detail = f"Restored snapshot section {dialog.selected_section}"
            else:
                state = self.history.restore_snapshot(dialog.selected_snapshot_id)
                detail = "Restored complete project snapshot"
        except ProjectHistoryError as exc:
            QMessageBox.warning(self.window, "Snapshot could not be restored", str(exc))
            return
        self._apply_history_state(state, detail)

    def _apply_history_state(self, state: dict[str, Any], message: str) -> None:
        path = self.window.project_path
        self.window.load_values(self._from_history_state(state), path)
        self.window.mark_dirty()
        self.last_build_path = None
        self._project_revision += 1
        self._live_validation_timer.start()
        if self.workspace is not None:
            self._autosave_timer.start()
        self._persist_history()
        self._update_history_actions()
        self.window.statusBar().showMessage(message)

    def _operation_matches(self, project_id: str, project_revision: int) -> bool:
        return (
            self.project is not None
            and self.project.project_id == project_id
            and self._project_revision == project_revision
        )

    def _reject_while_busy(self, action: str) -> bool:
        if not self._tasks:
            return False
        self.window.statusBar().showMessage(
            f"Wait for the current operation before trying to {action}."
        )
        return True

    def _confirm_abandon(self) -> bool:
        if not self.window.is_dirty:
            return True
        result = QMessageBox.question(
            self.window,
            "Unsaved project",
            "Save changes before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return self.save_project(False)
        return result == QMessageBox.StandardButton.Discard
