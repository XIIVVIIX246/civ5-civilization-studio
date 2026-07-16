"""Portable JSON/CSV/Markdown manifests for the art pipeline."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .validation import ValidationIssue


REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SourceManifestEntry:
    item_key: str
    category: str
    output_kind: str
    required: bool
    source_path: str
    source_sha256: str
    exists: bool
    valid: bool
    validation_status: str
    validation_codes: tuple[str, ...] = field(default_factory=tuple)
    width: int | None = None
    height: int | None = None
    atlas_name: str = ""
    atlas_page: int | None = None
    global_index: int | None = None
    local_index: int | None = None
    row: int | None = None
    column: int | None = None
    expected_output_path: str = ""


@dataclass(frozen=True, slots=True)
class OutputManifestEntry:
    output_kind: str
    category: str
    item_key: str
    output_path: str
    dds_profile: str
    dds_format: str
    width: int
    height: int
    mipmap_count: int
    output_sha256: str
    encoder: str
    atlas_name: str = ""
    atlas_page: int | None = None
    icon_size: int | None = None
    built_item_keys: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RunReport:
    project_id: str
    mode: str
    status: str
    configured_items: int
    existing_sources: int
    valid_sources: int
    blocker_count: int
    warning_count: int
    expected_outputs: int
    built_outputs: int
    build_performed: bool
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _rows(entries: Iterable[Any]) -> list[dict[str, Any]]:
    return [_json_safe(asdict(entry)) for entry in entries]


def _write_json(path: Path, *, kind: str, rows: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "kind": kind,
        "rows": rows,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    if value is None:
        return ""
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


def _write_run_report(path: Path, report: RunReport) -> None:
    issues = [_json_safe(asdict(issue)) for issue in report.issues]
    payload = _json_safe(asdict(report))
    payload["schema_version"] = REPORT_SCHEMA_VERSION
    payload["issues"] = issues
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_run_markdown(path: Path, report: RunReport) -> None:
    lines = [
        f"# Art pipeline report: {report.project_id}",
        "",
        f"- Mode: {report.mode}",
        f"- Status: {report.status}",
        f"- Configured items: {report.configured_items}",
        f"- Existing sources: {report.existing_sources}",
        f"- Valid sources: {report.valid_sources}",
        f"- Release blockers: {report.blocker_count}",
        f"- Warnings: {report.warning_count}",
        f"- Expected outputs: {report.expected_outputs}",
        f"- Built outputs: {report.built_outputs}",
        "",
        "Missing required art is structured blocker data, not a script error.",
    ]
    if report.issues:
        lines.extend(("", "## Issues", ""))
        for issue in report.issues:
            lines.append(
                f"- [{issue.severity.value.upper()}] `{issue.code}` "
                f"{issue.category}/{issue.item_key}: {issue.message}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report_bundle(
    report_directory: Path,
    *,
    source_entries: list[SourceManifestEntry],
    output_entries: list[OutputManifestEntry],
    run_report: RunReport,
    write_output_manifest: bool,
) -> dict[str, Path]:
    """Write reports without erasing previous build evidence in scan-only modes."""

    report_directory.mkdir(parents=True, exist_ok=True)
    source_rows = _rows(source_entries)
    source_json = report_directory / "art-source-manifest.json"
    source_csv = report_directory / "art-source-manifest.csv"
    _write_json(source_json, kind="source-manifest", rows=source_rows)
    _write_csv(source_csv, source_rows, list(SourceManifestEntry.__dataclass_fields__))

    mode_slug = run_report.mode.replace("_", "-")
    run_json = report_directory / f"art-run-report-{mode_slug}.json"
    run_markdown = report_directory / f"art-run-report-{mode_slug}.md"
    _write_run_report(run_json, run_report)
    _write_run_markdown(run_markdown, run_report)
    paths = {
        "source_json": source_json,
        "source_csv": source_csv,
        "run_json": run_json,
        "run_markdown": run_markdown,
    }
    if write_output_manifest:
        output_rows = _rows(output_entries)
        output_json = report_directory / "art-output-manifest.json"
        output_csv = report_directory / "art-output-manifest.csv"
        _write_json(output_json, kind="output-manifest", rows=output_rows)
        _write_csv(output_csv, output_rows, list(OutputManifestEntry.__dataclass_fields__))
        paths.update(output_json=output_json, output_csv=output_csv)
    return paths
