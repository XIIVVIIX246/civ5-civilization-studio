"""Application-level adapters for the Advanced Tools page."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re

from civ5studio.compatibility import CompatibilityReport, scan_installed_mods
from civ5studio.diagnostics import (
    DiagnosticsReport,
    analyze_game_logs,
    build_manual_test_checklist,
    collect_diagnostics_bundle,
    discover_civ5_user_environment,
    inspect_generated_mod,
)

from .mod_importer import ExistingModImporter, ModImportResult


ProgressCallback = Callable[[int, str], None]
LogCallback = Callable[[str], None]


def _ignore_progress(_percent: int, _message: str = "") -> None:
    return


def _ignore_log(_message: str) -> None:
    return


@dataclass(frozen=True, slots=True)
class AdvancedOperationResult:
    summary: str
    imported: ModImportResult | None = None


def import_existing_mod(
    source: str | Path,
    destination_parent: str | Path,
    *,
    progress: ProgressCallback = _ignore_progress,
    log: LogCallback = _ignore_log,
) -> AdvancedOperationResult:
    progress(0, "Inspecting the selected mod...")
    log(f"Inspecting existing mod read-only: {source}")
    importer = ExistingModImporter()
    plan = importer.inspect(source)
    progress(35, "Verified source inventory; creating the snapshot workspace...")
    parent = Path(destination_parent).expanduser().resolve()
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("Choose an existing, real destination parent folder.")
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", plan.report.mod_name).strip()
    stem = stem or "Imported Civ V Mod"
    destination = parent / f"{stem} Civilization Studio Import"
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(
            f"Refusing to overwrite an existing import workspace: {destination}"
        )
    project_file = f"{stem}.civ5project.json"
    result = importer.create_workspace(
        source, destination, project_file=project_file
    )
    progress(100, "Import snapshot complete.")
    log(f"Created immutable source snapshot: {result.workspace.root}")
    warnings = sum(
        item.severity.casefold() == "warning" for item in result.report.diagnostics
    )
    errors = sum(
        item.severity.casefold() == "error" for item in result.report.diagnostics
    )
    identified = ", ".join(
        f"{category}: {len(result.report.types_for(category))}"
        for category in ("civilizations", "leaders", "traits", "units", "buildings")
    )
    summary = (
        f"Created read-only source snapshot at {result.workspace.root}\n"
        f"Copied {result.copied_files} file(s) byte-for-byte.\n"
        f"Import diagnostics: {errors} error(s), {warnings} warning(s).\n"
        f"Identified custom Types: {identified}.\n\n"
        "Metadata is editable. SQL, XML, Lua, DLL, and art are preserved only as "
        "immutable inspection evidence; they are excluded from generated builds."
    )
    return AdvancedOperationResult(summary, result)


def analyze_runtime_logs(
    civ5_user_root: str | Path,
    generated_mod_root: str | Path,
    *,
    progress: ProgressCallback = _ignore_progress,
    log: LogCallback = _ignore_log,
) -> AdvancedOperationResult:
    progress(0, "Discovering Civ V user data...")
    environment = discover_civ5_user_environment(civ5_user_root)
    generated = inspect_generated_mod(generated_mod_root)
    log(f"Reading Civ V logs from {environment.logs_path}")
    progress(35, "Reading and attributing Civ V log findings...")
    evidence, findings = analyze_game_logs(environment, generated)
    checklist = build_manual_test_checklist(environment, generated)
    report = DiagnosticsReport(environment, generated, evidence, findings, checklist)
    tied = report.generated_mod_findings
    lines = [
        f"Environment: {environment.status.value}",
        f"Generated mod: {generated.name} v{generated.version or '?'} ({generated.mod_id or 'no id'})",
        f"Logs captured: {sum(item.captured for item in evidence)}/{len(evidence)}",
        f"Findings: {len(findings)} total; {len(tied)} tied to this generated mod",
        "",
    ]
    for finding in tied[:20]:
        lines.append(
            f"[{finding.severity}/{finding.attribution.value}] "
            f"{finding.log_name}:{finding.line_number} {finding.message}"
        )
    if not tied:
        lines.append(
            "No error/warning line was tied to this mod by the static token scan. "
            "That is not an in-game pass."
        )
    lines.extend(
        [
            "",
            "Next manual gates:",
            *[f"{step.number}. {step.title}" for step in checklist],
            "",
            report.safety_boundary,
        ]
    )
    progress(100, "Log analysis complete.")
    return AdvancedOperationResult("\n".join(lines))


def export_runtime_diagnostics(
    civ5_user_root: str | Path,
    generated_mod_root: str | Path,
    destination_zip: str | Path,
    *,
    progress: ProgressCallback = _ignore_progress,
    log: LogCallback = _ignore_log,
) -> AdvancedOperationResult:
    progress(0, "Collecting redacted diagnostics...")
    environment = discover_civ5_user_environment(civ5_user_root)
    log(f"Writing diagnostics bundle without changing Civ V data: {destination_zip}")
    result = collect_diagnostics_bundle(
        environment, generated_mod_root, destination_zip
    )
    progress(100, "Diagnostics bundle complete.")
    return AdvancedOperationResult(
        f"Created redacted diagnostics bundle:\n{result.path}\n"
        f"SHA-256: {result.sha256}\n\n{result.report.safety_boundary}"
    )


def scan_compatibility(
    mods_root: str | Path,
    *,
    progress: ProgressCallback = _ignore_progress,
    log: LogCallback = _ignore_log,
) -> AdvancedOperationResult:
    progress(0, "Scanning installed mod metadata read-only...")
    log(f"Scanning Civ V MODS metadata: {mods_root}")
    report = scan_installed_mods(mods_root)
    progress(100, "Compatibility scan complete.")
    return AdvancedOperationResult(format_compatibility_report(report))


def format_compatibility_report(report: CompatibilityReport) -> str:
    lines = [
        f"Scanned {len(report.mods)} installed .modinfo package(s).",
        f"Issues: {len(report.errors)} error(s), {len(report.warnings)} warning(s).",
        f"Duplicate mod IDs: {len(report.duplicate_mod_ids)}.",
        f"Cross-mod Type conflicts: {len(report.type_conflicts)}.",
    ]
    if report.ecosystem_presence:
        lines.append(
            "Detected ecosystems (presence only): "
            + ", ".join(
                sorted({item.product for item in report.ecosystem_presence})
            )
        )
    lines.extend(["", "Highest-priority evidence:"])
    for issue in report.issues[:30]:
        lines.append(
            f"[{issue.severity}] {issue.code}: {issue.message}"
            + (f" ({issue.source})" if issue.source else "")
        )
    if not report.issues:
        lines.append("No static package conflict evidence was found.")
    lines.extend(
        [
            "",
            "This read-only scan cannot prove load order, DLL coexistence, UI "
            "hook interoperability, IGE compatibility, or runtime stability.",
        ]
    )
    return "\n".join(lines)
