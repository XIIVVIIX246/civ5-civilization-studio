"""Read-only Civilization V runtime-test assistance and log diagnostics."""

from .game_test import (
    AttributionConfidence,
    BundleResult,
    ChecklistStep,
    Civ5UserEnvironment,
    DiagnosticsReport,
    EnvironmentIssue,
    EnvironmentStatus,
    FileEvidence,
    GeneratedModIdentity,
    LogFinding,
    analyze_game_logs,
    build_manual_test_checklist,
    collect_diagnostics_bundle,
    discover_civ5_user_environment,
    inspect_generated_mod,
)

__all__ = [
    "AttributionConfidence",
    "BundleResult",
    "ChecklistStep",
    "Civ5UserEnvironment",
    "DiagnosticsReport",
    "EnvironmentIssue",
    "EnvironmentStatus",
    "FileEvidence",
    "GeneratedModIdentity",
    "LogFinding",
    "analyze_game_logs",
    "build_manual_test_checklist",
    "collect_diagnostics_bundle",
    "discover_civ5_user_environment",
    "inspect_generated_mod",
]
