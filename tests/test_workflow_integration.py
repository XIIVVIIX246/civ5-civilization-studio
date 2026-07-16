from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw

from civ5studio.application import ProjectWorkflowService, WorkflowMode
from civ5studio.domain import ArtAssetSpec, ArtRole
from tools.verify_generated_mod import verify


def _write_sources(project, root: Path) -> None:
    for asset in project.art.assets:
        path = root / asset.source_png
        path.parent.mkdir(parents=True, exist_ok=True)
        if asset.role.value in {"civilization_alpha", "unit_flag"}:
            image = Image.new("RGB", (256, 256), "black")
            ImageDraw.Draw(image).ellipse((72, 48, 184, 208), fill="white")
        elif asset.role.value in {"leader_scene", "dawn_of_man", "map_image"}:
            image = Image.new("RGB", (400, 300), (80, 100, 120))
        else:
            image = Image.new("RGB", (256, 256), (80, 120, 160))
        image.save(path)


def test_strict_workflow_renders_compiles_validates_and_packages(
    sample_project, tmp_path: Path
) -> None:
    project = deepcopy(sample_project)
    source_root = tmp_path / "project"
    _write_sources(project, source_root)
    service = ProjectWorkflowService()
    progress: list[int] = []
    logs: list[str] = []
    result = service.run(
        project,
        source_root=source_root,
        output_root=tmp_path / "output",
        mode=WorkflowMode.BUILD,
        progress=lambda value, _message="": progress.append(value),
        log=logs.append,
    )
    assert result.succeeded, [item.to_dict() for item in result.issues]
    assert result.can_install
    assert result.build_path and result.build_path.is_dir()
    assert result.package_path and result.package_path.is_file()
    assert list(result.build_path.glob("*.modinfo"))
    assert (result.build_path / "Core" / "Civilization.sql").is_file()
    assert len(list((result.build_path / "Art").rglob("*.dds"))) == 18
    verification = verify(result.build_path)
    assert verification["status"] == "PASS", verification["errors"]
    assert verification["portrait_outer_annulus_alpha_max"] == 0
    with zipfile.ZipFile(result.package_path) as archive:
        assert any(name.endswith(".modinfo") for name in archive.namelist())
    assert progress[-1] == 100
    assert any("Published validated mod" in line for line in logs)
    capability = json.loads(
        (result.build_path / "Documentation/CAPABILITY_REPORT.json").read_text(
            encoding="utf-8"
        )
    )
    assert capability["release_gates"]["strict_static_release"] == "PASS"
    assert capability["release_gates"]["install_eligibility"] == "PASS"
    assert capability["release_gates"]["bnw_in_game"] == "REQUIRED_NOT_RUN"


def test_validate_reports_missing_art_without_publishing(sample_project, tmp_path: Path) -> None:
    result = ProjectWorkflowService().run(
        deepcopy(sample_project),
        source_root=tmp_path,
        output_root=tmp_path / "output",
        mode=WorkflowMode.VALIDATE,
    )
    assert not result.succeeded
    assert result.build_path is None
    assert any(item.code == "art.source-missing" for item in result.issues)


def test_strict_workflow_packages_optional_strategic_view_binding(
    sample_project, tmp_path: Path
) -> None:
    project = deepcopy(sample_project)
    project.art.assets.append(
        ArtAssetSpec(
            asset_id="winged_hussar_strategic",
            role=ArtRole.STRATEGIC_VIEW,
            source_png="Assets/Source/winged-hussar-sv.png",
            subject_key="unit:WINGED_HUSSAR",
            required=True,
            crop_mode="contain",
        )
    )
    source_root = tmp_path / "project"
    _write_sources(project, source_root)
    strategic_source = source_root / "Assets/Source/winged-hussar-sv.png"
    strategic = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    ImageDraw.Draw(strategic).polygon(
        ((512, 180), (820, 820), (512, 680), (204, 820)),
        fill=(255, 255, 255, 255),
    )
    strategic.save(strategic_source)

    result = ProjectWorkflowService().run(
        project,
        source_root=source_root,
        output_root=tmp_path / "output",
        mode=WorkflowMode.BUILD,
    )
    assert result.succeeded, [item.to_dict() for item in result.issues]
    assert result.build_path is not None
    relative = Path(
        "Art/StrategicView/SV_LITHUANIA_CUSTOM_WINGED_HUSSAR.dds"
    )
    assert (result.build_path / relative).is_file()
    units_sql = (result.build_path / "Core/Units.sql").read_text(encoding="utf-8")
    assert "INSERT INTO ArtDefine_StrategicView" in units_sql
    assert relative.name in units_sql
    modinfo = next(result.build_path.glob("*.modinfo")).read_text(encoding="utf-8")
    assert relative.as_posix() in modinfo
