from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from civ5studio.application.mod_importer import (
    IMPORT_EXTENSION_KEY,
    ExistingModImporter,
    ImportedSnapshotError,
    ModSourceChangedError,
    UnsafeModSourceError,
    copy_imported_snapshot,
)
from civ5studio.application.workspace import ProjectWorkspace


MOD_ID = "7cc9ebbf-5bea-4bc4-b925-c0a00e8b96f9"


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_mod(root: Path) -> Path:
    _write(
        root / "Database" / "Identity.xml",
        """<?xml version="1.0" encoding="utf-8"?>
<GameData>
  <Civilizations><Row><Type>CIVILIZATION_TEST_NATION</Type></Row></Civilizations>
  <Leaders><Row Type="LEADER_TEST_RULER" /></Leaders>
  <Traits><Row><Type>TRAIT_TEST_IDEA</Type></Row></Traits>
</GameData>
""",
    )
    _write(
        root / "Database" / "Uniques.sql",
        """-- Candidate declarations are inspected but the SQL remains pass-through.
INSERT INTO Units (Type, Class, Description)
VALUES ('UNIT_TEST_GUARD', 'UNITCLASS_SPEARMAN', 'TXT_KEY_UNIT_TEST_GUARD');
INSERT INTO Buildings (Type, BuildingClass, Description)
VALUES ('BUILDING_TEST_HALL', 'BUILDINGCLASS_MONUMENT', 'TXT_KEY_BUILDING_TEST_HALL');
""",
    )
    _write(root / "Text" / "English.xml", "<GameData><Language_en_US /></GameData>\n")
    _write(root / "Art" / "Atlases.xml", "<GameData><IconTextureAtlases /></GameData>\n")
    _write(root / "UI" / "Panel.lua", "print('preserved')\n")
    _write(root / "Unlisted.bin", b"\x00\x01\x02read-only")
    return _write(
        root / "Synthetic.modinfo",
        f"""<?xml version="1.0" encoding="utf-8"?>
<Mod id="{MOD_ID}" version="9">
  <Properties>
    <Name>Synthetic Nation</Name>
    <Authors>Importer Test</Authors>
    <Teaser>Safe import</Teaser>
    <Description>Lossless source snapshot</Description>
  </Properties>
  <Files>
    <File md5="unused" import="0">Database/Identity.xml</File>
    <File md5="unused" import="0">Database/Uniques.sql</File>
    <File md5="unused" import="0">Text/English.xml</File>
    <File md5="unused" import="0">Art/Atlases.xml</File>
    <File md5="unused" import="1">UI/Panel.lua</File>
  </Files>
  <Actions>
    <OnModActivated>
      <UpdateDatabase>Database/Identity.xml</UpdateDatabase>
      <UpdateDatabase>Database/Uniques.sql</UpdateDatabase>
      <UpdateText>Text/English.xml</UpdateText>
      <UpdateArt>Art/Atlases.xml</UpdateArt>
      <Custom>UI/Panel.lua</Custom>
    </OnModActivated>
  </Actions>
</Mod>
""",
    )


def test_inspect_inventories_actions_vfs_types_and_truthful_editability(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Synthetic Mod"
    _synthetic_mod(source)

    plan = ExistingModImporter().inspect(source)
    report = plan.report

    assert report.mod_name == "Synthetic Nation"
    assert report.original_mod_id == MOD_ID
    assert report.mod_version == 9
    assert report.action_files("UpdateDatabase") == (
        "Database/Identity.xml",
        "Database/Uniques.sql",
    )
    assert report.action_files("UpdateText") == ("Text/English.xml",)
    assert report.action_files("UpdateArt") == ("Art/Atlases.xml",)
    assert report.vfs_files == ("UI/Panel.lua",)
    assert report.types_for("civilizations") == ("CIVILIZATION_TEST_NATION",)
    assert report.types_for("leaders") == ("LEADER_TEST_RULER",)
    assert report.types_for("traits") == ("TRAIT_TEST_IDEA",)
    assert report.types_for("units") == ("UNIT_TEST_GUARD",)
    assert report.types_for("buildings") == ("BUILDING_TEST_HALL",)

    extension = plan.project.extensions[IMPORT_EXTENSION_KEY]
    assert extension["import_mode"] == "read_only_inspection_snapshot"
    assert extension["generated_build_inclusion"] == "excluded"
    assert extension["editability"]["status"] == "partial_metadata_only"
    assert extension["editability"]["source_files_editable"] is False
    assert extension["snapshot"]["status"] == "not_created"
    assert len(extension["files"]) == 7
    assert all(item["inspection_evidence"] for item in extension["files"])
    assert not any(item["included_in_generated_build"] for item in extension["files"])
    assert not any(item["editable"] for item in extension["files"])
    assert "unsupported_mod_action" in {item.code for item in report.diagnostics}
    assert "unlisted_source_file" in {item.code for item in report.diagnostics}


def test_create_workspace_copies_every_file_without_altering_source(tmp_path: Path) -> None:
    source = tmp_path / "Source Mod"
    _synthetic_mod(source)
    original = {
        path.relative_to(source).as_posix(): _sha256(path)
        for path in source.rglob("*")
        if path.is_file()
    }
    destination = tmp_path / "Imported Workspace"

    result = ExistingModImporter().create_workspace(source, destination)

    assert result.copied_files == len(original)
    reopened = ProjectWorkspace.open(destination)
    project = reopened.load()
    extension = project.extensions[IMPORT_EXTENSION_KEY]
    assert extension["snapshot"] == {
        "status": "complete",
        "root": "ImportedMod/Source",
        "file_count": len(original),
    }
    for item in extension["files"]:
        copied = destination / item["workspace_path"]
        assert copied.is_file()
        assert _sha256(copied) == item["sha256"]
    assert {
        path.relative_to(source).as_posix(): _sha256(path)
        for path in source.rglob("*")
        if path.is_file()
    } == original
    assert not (source / ".civ5studio").exists()


def test_copy_imported_snapshot_between_workspaces_is_complete_and_verified(
    tmp_path: Path,
) -> None:
    source_mod = tmp_path / "Source Mod"
    _synthetic_mod(source_mod)
    imported = ExistingModImporter().create_workspace(
        source_mod, tmp_path / "Imported Workspace"
    )
    project = imported.workspace.load()
    destination = ProjectWorkspace.create(tmp_path / "Saved As Workspace", project)

    result = copy_imported_snapshot(project, imported.workspace, destination)

    assert result is not None
    assert result.copied_files == len(project.extensions[IMPORT_EXTENSION_KEY]["files"])
    assert result.copied_bytes == sum(
        item["size"] for item in project.extensions[IMPORT_EXTENSION_KEY]["files"]
    )
    for item in project.extensions[IMPORT_EXTENSION_KEY]["files"]:
        source = imported.workspace.root / item["workspace_path"]
        copied = destination.root / item["workspace_path"]
        assert copied.is_file()
        assert copied.read_bytes() == source.read_bytes()
        assert _sha256(copied) == item["sha256"]


def test_copy_imported_snapshot_rejects_changed_or_extra_source_bytes(
    tmp_path: Path,
) -> None:
    source_mod = tmp_path / "Source Mod"
    _synthetic_mod(source_mod)
    imported = ExistingModImporter().create_workspace(
        source_mod, tmp_path / "Imported Workspace"
    )
    project = imported.workspace.load()
    destination = ProjectWorkspace.create(tmp_path / "Saved As Workspace", project)
    snapshot = imported.workspace.root / "ImportedMod" / "Source"
    (snapshot / "Unlisted.bin").write_bytes(b"changed")
    _write(snapshot / "Unexpected.txt", "unexpected")

    with pytest.raises(ModSourceChangedError):
        copy_imported_snapshot(project, imported.workspace, destination)

    assert not (destination.root / "ImportedMod").exists()


def test_copy_imported_snapshot_refuses_occupied_destination(tmp_path: Path) -> None:
    source_mod = tmp_path / "Source Mod"
    _synthetic_mod(source_mod)
    imported = ExistingModImporter().create_workspace(
        source_mod, tmp_path / "Imported Workspace"
    )
    project = imported.workspace.load()
    destination = ProjectWorkspace.create(tmp_path / "Saved As Workspace", project)
    sentinel = _write(destination.root / "ImportedMod" / "keep.txt", "keep")

    with pytest.raises(ImportedSnapshotError, match="overwrite"):
        copy_imported_snapshot(project, imported.workspace, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_copy_imported_snapshot_rejects_manifest_traversal(tmp_path: Path) -> None:
    source_mod = tmp_path / "Source Mod"
    _synthetic_mod(source_mod)
    imported = ExistingModImporter().create_workspace(
        source_mod, tmp_path / "Imported Workspace"
    )
    project = imported.workspace.load()
    project.extensions[IMPORT_EXTENSION_KEY]["files"][0][
        "source_relative_path"
    ] = "../Outside.sql"

    with pytest.raises(UnsafeModSourceError, match="Traversal"):
        copy_imported_snapshot(project, imported.workspace, tmp_path / "unused")


@pytest.mark.parametrize(
    "element",
    [
        '<File import="1">../Outside.lua</File>',
        '<File import="1">C:\\Outside.lua</File>',
    ],
)
def test_inspect_rejects_unsafe_manifest_file_paths(
    tmp_path: Path, element: str
) -> None:
    source = tmp_path / "Unsafe Mod"
    _write(
        source / "Unsafe.modinfo",
        f'<Mod id="{MOD_ID}" version="1"><Files>{element}</Files></Mod>',
    )

    with pytest.raises(UnsafeModSourceError):
        ExistingModImporter().inspect(source)


def test_inspect_rejects_unsafe_action_paths(tmp_path: Path) -> None:
    source = tmp_path / "Unsafe Action Mod"
    _write(
        source / "UnsafeAction.modinfo",
        f"""<Mod id="{MOD_ID}" version="1">
  <Files />
  <Actions><OnModActivated>
    <UpdateDatabase>Database/../../Outside.sql</UpdateDatabase>
  </OnModActivated></Actions>
</Mod>""",
    )

    with pytest.raises(UnsafeModSourceError, match="Traversal"):
        ExistingModImporter().inspect(source)


def test_inspect_reports_missing_files_and_unparseable_xml_without_claiming_success(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Incomplete Mod"
    _write(source / "Database" / "Broken.xml", "<GameData><Units>")
    _write(
        source / "Incomplete.modinfo",
        f"""<Mod id="{MOD_ID}" version="1">
  <Files>
    <File import="0">Database/Broken.xml</File>
    <File import="0">Database/Missing.sql</File>
  </Files>
  <Actions><OnModActivated>
    <UpdateDatabase>Database/Broken.xml</UpdateDatabase>
    <UpdateDatabase>Database/Missing.sql</UpdateDatabase>
  </OnModActivated></Actions>
</Mod>""",
    )

    report = ExistingModImporter().inspect(source).report

    codes = {item.code for item in report.diagnostics}
    assert "missing_declared_file" in codes
    assert "xml_parse_failed" in codes
    broken = next(item for item in report.files if item.relative_path.endswith("Broken.xml"))
    assert broken.parse_status == "error"
    assert report.identified_types == ()


def test_inspect_rejects_source_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "Linked Mod"
    _write(source / "Real.lua", "print('real')\n")
    _write(
        source / "Linked.modinfo",
        f'<Mod id="{MOD_ID}" version="1"><Files /></Mod>',
    )
    try:
        (source / "Alias.lua").symlink_to(source / "Real.lua")
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this Windows host.")

    with pytest.raises(UnsafeModSourceError, match="Links|junctions"):
        ExistingModImporter().inspect(source)
