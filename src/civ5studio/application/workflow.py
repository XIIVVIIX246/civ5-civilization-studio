"""End-to-end audit, validation, art rendering, and mod publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import tempfile
from typing import Callable

from civ5studio.art import (
    IssueSeverity,
    PipelineMode,
    PipelineResult,
    run_art_pipeline,
)
from civ5studio.build import BuildBlocked, BuildMode, BuildResult, BuildService, UnsafeBuildPath
from civ5studio.domain import CivProject, Severity, ValidationReport

from .art_project import prepare_art_project


ProgressCallback = Callable[[int, str], None]
LogCallback = Callable[[str], None]


class WorkflowMode(StrEnum):
    AUDIT = "audit"
    VALIDATE = "validate"
    BUILD = "build"


@dataclass(frozen=True, slots=True)
class OperationIssue:
    severity: str
    location: str
    message: str
    code: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "location": self.location,
            "message": self.message,
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    mode: WorkflowMode
    status: str
    summary: str
    issues: tuple[OperationIssue, ...]
    build_path: Path | None = None
    package_path: Path | None = None
    backup_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "PASS"

    @property
    def can_install(self) -> bool:
        return self.succeeded and self.build_path is not None


class ProjectWorkflowService:
    def __init__(self, build_service: BuildService | None = None) -> None:
        self.build_service = build_service or BuildService()

    def run(
        self,
        project: CivProject,
        *,
        source_root: str | Path,
        output_root: str | Path,
        mode: WorkflowMode,
        progress: ProgressCallback = lambda _percent, _message="": None,
        log: LogCallback = lambda _message: None,
    ) -> WorkflowResult:
        mode = WorkflowMode(mode)
        source = Path(source_root).resolve()
        output = Path(output_root).resolve()
        progress(5, "Validating project data")
        strict = mode in {WorkflowMode.VALIDATE, WorkflowMode.BUILD}
        domain_report = self.build_service.validate(
            project,
            source,
            strict_release=strict,
        )
        log(_report_log_line("Project", domain_report))

        with tempfile.TemporaryDirectory(prefix="civ5studio-operation-") as temp_name:
            temporary = Path(temp_name)
            progress(20, "Preparing read-only source copies")
            try:
                prepared = prepare_art_project(
                    project,
                    project_root=source,
                    working_root=temporary / "WorkingSources",
                )
            except Exception as exc:
                issues = [*_domain_issues(domain_report)]
                issues.append(
                    OperationIssue(
                        "ERROR",
                        "art.sources",
                        f"Could not prepare source art: {exc}",
                        "ART_PREPARATION_FAILED",
                    )
                )
                return _result(mode, issues)

            art_mode = {
                WorkflowMode.AUDIT: PipelineMode.DRAFT,
                WorkflowMode.VALIDATE: PipelineMode.VALIDATE,
                WorkflowMode.BUILD: PipelineMode.STRICT_RELEASE,
            }[mode]
            progress(35, "Auditing art sources" if mode is not WorkflowMode.BUILD else "Rendering Civ V art")
            art_result = run_art_pipeline(
                prepared.spec,
                input_root=prepared.input_root,
                staging_root=temporary / "Rendered",
                mode=art_mode,
            )
            log(
                f"Art pipeline: {art_result.status.value}; "
                f"{len(art_result.output_manifest)} DDS outputs."
            )
            issues = [
                *_domain_issues(domain_report),
                *_art_issues(art_result, draft=mode is WorkflowMode.AUDIT),
            ]
            if mode is not WorkflowMode.BUILD:
                progress(100, "Audit complete" if mode is WorkflowMode.AUDIT else "Validation complete")
                return _result(mode, issues)
            if any(item.severity == "ERROR" for item in issues):
                progress(100, "Build blocked")
                return _result(mode, issues)

            progress(72, "Compiling SQL, XML, Lua, and mod metadata")
            workspace = output / f"{project.internal_prefix}_StudioProject"
            try:
                build = self.build_service.build(
                    project,
                    workspace,
                    source_root=source,
                    mode=BuildMode.STRICT_RELEASE,
                    rendered_art_root=temporary / "Rendered",
                    create_zip=True,
                )
            except BuildBlocked as exc:
                combined = [*issues, *_domain_issues(exc.report)]
                progress(100, "Build blocked")
                return _result(mode, _deduplicate(combined))
            except UnsafeBuildPath as exc:
                issues.append(
                    OperationIssue("ERROR", "build.output", str(exc), "UNSAFE_BUILD_PATH")
                )
                progress(100, "Build blocked")
                return _result(mode, issues)
            log(f"Published validated mod: {build.published_path}")
            if build.package_path:
                log(f"Created player ZIP: {build.package_path}")
            progress(100, "Build complete")
            return _result(mode, issues, build)


def _result(
    mode: WorkflowMode,
    issues: list[OperationIssue],
    build: BuildResult | None = None,
) -> WorkflowResult:
    issues = _deduplicate(issues)
    errors = sum(item.severity == "ERROR" for item in issues)
    warnings = sum(item.severity == "WARNING" for item in issues)
    if errors:
        status = "FAIL"
        summary = f"Blocked by {errors} error(s); {warnings} warning(s) also reported."
    elif mode is WorkflowMode.BUILD and build is not None:
        status = "PASS"
        summary = f"Strict release built successfully with {warnings} warning(s)."
    elif mode is WorkflowMode.VALIDATE:
        status = "PASS"
        summary = f"Release inputs are ready for a strict build; {warnings} warning(s)."
    else:
        status = "WARN" if warnings else "PASS"
        summary = f"Draft audit complete: no errors and {warnings} warning(s)."
    return WorkflowResult(
        mode,
        status,
        summary,
        tuple(issues),
        build.published_path if build else None,
        build.package_path if build else None,
        build.backup_path if build else None,
    )


def _domain_issues(report: ValidationReport) -> list[OperationIssue]:
    severity = {
        Severity.ERROR: "ERROR",
        Severity.WARNING: "WARNING",
        Severity.INFO: "INFO",
    }
    return [
        OperationIssue(
            severity[item.severity],
            item.path,
            f"{item.message}{' ' + item.hint if item.hint else ''}",
            item.code,
        )
        for item in report.issues
    ]


def _art_issues(result: PipelineResult, *, draft: bool) -> list[OperationIssue]:
    values: list[OperationIssue] = []
    for item in result.issues:
        if item.severity is IssueSeverity.BLOCKER:
            severity = "WARNING" if draft else "ERROR"
        elif item.severity is IssueSeverity.WARNING:
            severity = "WARNING"
        else:
            severity = "INFO"
        location = ".".join(value for value in (item.category, item.item_key) if value)
        values.append(OperationIssue(severity, location or "art", item.message, item.code))
    return values


def _deduplicate(issues: list[OperationIssue]) -> list[OperationIssue]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[OperationIssue] = []
    for item in issues:
        key = (item.severity, item.location, item.message, item.code)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _report_log_line(label: str, report: ValidationReport) -> str:
    return f"{label}: {len(report.errors)} error(s), {len(report.warnings)} warning(s)."
