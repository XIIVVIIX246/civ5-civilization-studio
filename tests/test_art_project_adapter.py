from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from civ5studio.application.art_project import prepare_art_project
from civ5studio.art import PipelineStatus, read_dds_header, strict_release
from civ5studio.domain import (
    ArtAssetSpec,
    ArtManifestSpec,
    ArtRole,
    CivilizationSpec,
    CivProject,
    LeaderSpec,
    TraitSpec,
    UniqueBuildingSpec,
    UniqueUnitSpec,
)
from civ5studio.generation import generate_art_manifest


def _sample_project(root: Path) -> CivProject:
    art = root / "Assets" / "Source"
    art.mkdir(parents=True)
    portrait = Image.new("RGB", (200, 200), (60, 100, 140))
    portrait.save(art / "portrait.png")
    flag = Image.new("RGB", (200, 200), "black")
    ImageDraw.Draw(flag).rectangle((65, 35, 135, 165), fill="white")
    flag.save(art / "flag.png")
    Image.new("RGB", (320, 180), (80, 40, 20)).save(art / "screen.png")
    unit = UniqueUnitSpec(
        key="GUARD",
        name="Guard",
        replaces_unit_class="UNITCLASS_SWORDSMAN",
        base_unit="UNIT_SWORDSMAN",
    )
    building = UniqueBuildingSpec(
        key="HALL",
        name="Hall",
        replaces_building_class="BUILDINGCLASS_MONUMENT",
        base_building="BUILDING_MONUMENT",
    )
    assets = [
        ArtAssetSpec("civ", ArtRole.CIVILIZATION_ICON, "Assets/Source/portrait.png", "civilization"),
        ArtAssetSpec("alpha", ArtRole.CIVILIZATION_ALPHA, "Assets/Source/flag.png", "civilization"),
        ArtAssetSpec("leader", ArtRole.LEADER_PORTRAIT, "Assets/Source/portrait.png", "leader"),
        ArtAssetSpec("scene", ArtRole.LEADER_SCENE, "Assets/Source/screen.png", "leader"),
        ArtAssetSpec("dom", ArtRole.DAWN_OF_MAN, "Assets/Source/screen.png", "civilization"),
        ArtAssetSpec("map", ArtRole.MAP_IMAGE, "Assets/Source/screen.png", "civilization"),
        ArtAssetSpec("unit", ArtRole.UNIQUE_UNIT_ICON, "Assets/Source/portrait.png", "unit:GUARD"),
        ArtAssetSpec("unit_flag", ArtRole.UNIT_FLAG, "Assets/Source/flag.png", "unit:GUARD"),
        ArtAssetSpec("building", ArtRole.UNIQUE_BUILDING_ICON, "Assets/Source/portrait.png", "building:HALL"),
    ]
    return CivProject(
        project_id="11111111-1111-4111-8111-111111111111",
        mod_name="Adapter Test",
        internal_prefix="ADAPTER_TEST",
        civilization=CivilizationSpec(name="Adapter Test", short_name="Adapter", adjective="Adapter", city_names=["City"]),
        leader=LeaderSpec(key="LEADER", name="Leader"),
        trait=TraitSpec(key="TRAIT", name="Trait", short_description="Trait"),
        units=[unit],
        buildings=[building],
        art=ArtManifestSpec(assets=assets),
    )


def test_project_art_adapter_builds_exact_compiler_contract(tmp_path: Path) -> None:
    project = _sample_project(tmp_path)
    prepared = prepare_art_project(
        project,
        project_root=tmp_path,
        working_root=tmp_path / "working",
    )
    result = strict_release(
        prepared.spec,
        input_root=prepared.input_root,
        staging_root=tmp_path / "rendered",
    )
    assert result.status is PipelineStatus.PASS
    actual = {entry.output_path for entry in result.output_manifest}
    expected = {item["path"] for item in generate_art_manifest(project)["outputs"]}
    assert actual == expected
    assert len(actual) == 18
    for relative in actual:
        header = read_dds_header(tmp_path / "rendered" / relative)
        assert header.mipmap_count == 1


def test_project_art_adapter_processes_optional_strategic_view_role(
    tmp_path: Path,
) -> None:
    project = _sample_project(tmp_path)
    strategic_path = tmp_path / "Assets" / "Source" / "strategic.png"
    strategic = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    ImageDraw.Draw(strategic).polygon(
        ((180, 520), (820, 220), (700, 520), (820, 800)),
        fill=(240, 240, 240, 220),
    )
    strategic.save(strategic_path)
    project.art.assets.append(
        ArtAssetSpec(
            "guard_strategic",
            ArtRole.STRATEGIC_VIEW,
            "Assets/Source/strategic.png",
            "unit:GUARD",
        )
    )
    prepared = prepare_art_project(
        project,
        project_root=tmp_path,
        working_root=tmp_path / "working",
    )
    strategic_spec = next(
        item for item in prepared.spec.individuals if item.key == "strategic_GUARD"
    )
    assert strategic_spec.output_size == (64, 64)
    assert strategic_spec.output_path.as_posix() == (
        "Art/StrategicView/SV_ADAPTER_TEST_GUARD.dds"
    )
    result = strict_release(
        prepared.spec,
        input_root=prepared.input_root,
        staging_root=tmp_path / "rendered",
    )
    assert result.status is PipelineStatus.PASS
    output = next(
        item for item in result.output_manifest if item.item_key == "strategic_GUARD"
    )
    header = read_dds_header(tmp_path / "rendered" / output.output_path)
    assert (header.width, header.height) == (64, 64)
    assert header.fourcc == ""
    assert header.bits_per_pixel == 32
    assert header.mipmap_count == 1
