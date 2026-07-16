"""Read-only installed-mod compatibility inspection."""

from .scanner import (
    CompatibilityReport,
    Confidence,
    EcosystemPresence,
    InstalledMod,
    ModRelation,
    ScanIssue,
    TypeConflict,
    TypeDeclaration,
    scan_installed_mods,
)

__all__ = [
    "CompatibilityReport",
    "Confidence",
    "EcosystemPresence",
    "InstalledMod",
    "ModRelation",
    "ScanIssue",
    "TypeConflict",
    "TypeDeclaration",
    "scan_installed_mods",
]
