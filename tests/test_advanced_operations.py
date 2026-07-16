from __future__ import annotations

from civ5studio.application.advanced_operations import (
    AdvancedOperationResult,
    format_compatibility_report,
    scan_compatibility,
)
from civ5studio.compatibility import CompatibilityReport, ScanIssue
from civ5studio.ui.worker import BackgroundTask


def test_compatibility_summary_keeps_runtime_boundary(tmp_path) -> None:
    report = CompatibilityReport(
        tmp_path,
        (),
        (
            ScanIssue(
                "WARNING", "CUSTOM_TYPE_CONFLICT", "Overlapping Type", "UNIT_X"
            ),
        ),
    )
    text = format_compatibility_report(report)
    assert "0 installed .modinfo" in text
    assert "CUSTOM_TYPE_CONFLICT" in text
    assert "cannot prove" in text


def test_advanced_operation_accepts_background_worker_callbacks(tmp_path) -> None:
    results: list[object] = []
    failures: list[tuple[str, str]] = []
    task = BackgroundTask(scan_compatibility, tmp_path)
    task.signals.result.connect(results.append)
    task.signals.failed.connect(lambda message, detail: failures.append((message, detail)))

    task.run()

    assert failures == []
    assert len(results) == 1
    assert isinstance(results[0], AdvancedOperationResult)
