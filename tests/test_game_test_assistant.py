from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest

from civ5studio.diagnostics import (
    AttributionConfidence,
    EnvironmentStatus,
    analyze_game_logs,
    build_manual_test_checklist,
    collect_diagnostics_bundle,
    discover_civ5_user_environment,
    inspect_generated_mod,
)


def _environment(tmp_path: Path, *, logging_enabled: str = "1") -> Path:
    root = tmp_path / "Sid Meier's Civilization 5"
    for relative in ("MODS", "Logs", "cache"):
        (root / relative).mkdir(parents=True)
    (root / "config.ini").write_text(
        f"[Debug]\nLoggingEnabled = {logging_enabled}\n",
        encoding="utf-8",
    )
    return root


def _generated_mod(tmp_path: Path) -> Path:
    root = tmp_path / "My Test Civilization (v 1)"
    root.mkdir()
    sql_name = "MYTEST_Core.sql"
    (root / sql_name).write_text(
        "INSERT INTO Units (Type, Description) VALUES "
        "('UNIT_MYTEST_RANGER', 'TXT_KEY_UNIT_MYTEST_RANGER');\n",
        encoding="utf-8",
    )
    document = ET.Element("Mod", {"id": "11111111-2222-3333-4444-555555555555", "version": "1"})
    properties = ET.SubElement(document, "Properties")
    ET.SubElement(properties, "Name").text = "My Test Civilization"
    files = ET.SubElement(document, "Files")
    ET.SubElement(files, "File", {"import": "0"}).text = sql_name
    modinfo = root / "My Test Civilization (v 1).modinfo"
    ET.ElementTree(document).write(modinfo, encoding="utf-8", xml_declaration=True)
    (root / ".civ5studio-generated.json").write_text("{}\n", encoding="utf-8")
    return root


def test_environment_discovery_is_read_only_and_reports_logging_state(
    tmp_path: Path,
) -> None:
    root = _environment(tmp_path, logging_enabled="0")
    sentinel = root / "cache" / "do-not-delete.bin"
    sentinel.write_bytes(b"cache")

    environment = discover_civ5_user_environment(root)

    assert environment.status is EnvironmentStatus.READY
    assert environment.mods_path == root / "MODS"
    assert environment.logs_path == root / "Logs"
    assert environment.cache_path == root / "cache"
    assert environment.logging_enabled is False
    assert any(item.code == "CIV5_LOGGING_DISABLED" for item in environment.issues)
    assert sentinel.read_bytes() == b"cache"


def test_missing_environment_is_reported_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "not-present"
    environment = discover_civ5_user_environment(missing)
    assert environment.status is EnvironmentStatus.NOT_FOUND
    assert not missing.exists()


def test_log_doctor_attributes_direct_context_and_unrelated_errors(
    tmp_path: Path,
) -> None:
    user_root = _environment(tmp_path)
    mod_root = _generated_mod(tmp_path)
    logs = user_root / "Logs"
    (logs / "Database.log").write_text(
        "[100] My Test Civilization (v 1) - MYTEST_Core.sql\n"
        "[101] ERROR: no such column: Units.BadColumn\n"
        "[102] Validation complete: 0 errors\n",
        encoding="utf-8",
    )
    (logs / "Lua.log").write_text(
        "Runtime Error: MYTEST_Core.lua:42: attempt to index a nil value for UNIT_MYTEST_RANGER\n",
        encoding="utf-8",
    )
    (logs / "xml.log").write_text(
        "ERROR: unrelated legacy mod malformed XML\n", encoding="utf-8"
    )
    (logs / "Modding.log").write_text("Modding startup succeeded\n", encoding="utf-8")
    environment = discover_civ5_user_environment(user_root)
    identity = inspect_generated_mod(mod_root)

    evidence, findings = analyze_game_logs(environment, identity)

    assert all(item.sha256 for item in evidence)
    assert len(findings) == 3
    by_log = {item.log_name: item for item in findings}
    assert by_log["Database.log"].attribution is AttributionConfidence.MEDIUM
    assert by_log["Lua.log"].attribution is AttributionConfidence.HIGH
    assert by_log["xml.log"].attribution is AttributionConfidence.UNATTRIBUTED
    assert "MYTEST_Core.sql" in identity.tokens
    assert "UNIT_MYTEST_RANGER" in identity.tokens
    assert not any("0 errors" in item.message for item in findings)


def test_manual_checklist_states_all_mutations_and_runtime_work_are_manual(
    tmp_path: Path,
) -> None:
    environment = discover_civ5_user_environment(_environment(tmp_path))
    identity = inspect_generated_mod(_generated_mod(tmp_path))

    checklist = build_manual_test_checklist(environment, identity)
    combined = " ".join(item.instructions for item in checklist).casefold()

    assert "does not delete cache" in combined
    assert "does not launch the game" in combined
    assert "separate ige" in " ".join(item.title for item in checklist).casefold()
    assert "not itself proof of compatibility" in combined


def test_bundle_redacts_paths_hashes_evidence_and_preserves_cache(
    tmp_path: Path,
) -> None:
    user_root = _environment(tmp_path)
    mod_root = _generated_mod(tmp_path)
    cache_sentinel = user_root / "cache" / "cache.db"
    cache_sentinel.write_bytes(b"untouched")
    log_content = (
        f"Loading {mod_root}\\MYTEST_Core.sql\n"
        f"ERROR in {user_root}\\MODS\\My Test Civilization: constraint failed\n"
    )
    (user_root / "Logs" / "Database.log").write_text(log_content, encoding="utf-8")
    for name in ("Lua.log", "xml.log", "Modding.log"):
        (user_root / "Logs" / name).write_text("No errors\n", encoding="utf-8")
    environment = discover_civ5_user_environment(user_root)
    destination = tmp_path / "diagnostics.zip"

    result = collect_diagnostics_bundle(environment, mod_root, destination)

    assert result.path == destination
    assert result.sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert cache_sentinel.read_bytes() == b"untouched"
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {
            "diagnostics.json",
            "diagnostics.md",
            "logs/Database.log",
            "logs/Lua.log",
            "logs/xml.log",
            "logs/Modding.log",
        }
        combined = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
        payload = json.loads(archive.read("diagnostics.json"))
    assert str(user_root) not in combined
    assert str(mod_root) not in combined
    assert "%CIV5_USER_ROOT%" in combined or "%CIV5_LOGS%" in combined
    assert "%GENERATED_MOD_ROOT%" in combined
    assert payload["runtime_gates"] == {
        "bnw_in_game": "NOT_RUN_BY_ASSISTANT",
        "ige_compatibility": "NOT_RUN_BY_ASSISTANT",
    }
    database = next(
        item for item in payload["evidence"] if item["label"].endswith("Database.log")
    )
    assert database["sha256"] == hashlib.sha256(
        (user_root / "Logs" / "Database.log").read_bytes()
    ).hexdigest()


def test_bundle_refuses_overwrite_and_reports_missing_logs(tmp_path: Path) -> None:
    user_root = _environment(tmp_path)
    mod_root = _generated_mod(tmp_path)
    environment = discover_civ5_user_environment(user_root)
    evidence, findings = analyze_game_logs(environment, inspect_generated_mod(mod_root))
    assert not findings
    assert all(not item.exists and not item.captured for item in evidence)

    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"keep")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        collect_diagnostics_bundle(environment, mod_root, destination)
    assert destination.read_bytes() == b"keep"
