"""Create and optionally build the repo's real-art Mississippian sample project."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import tempfile
import zipfile

from PIL import Image

from civ5studio.application import ProjectWorkflowService, WorkflowMode, save_ui_project


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT = REPO_ROOT / "Input" / "Mississippian"


def create_sample(project_path: Path, *, build: bool) -> dict[str, object]:
    project_path = project_path.resolve()
    build_root = project_path.parent / "Builds"
    with tempfile.TemporaryDirectory(prefix="civ5studio-sample-") as temp_name:
        map_png = Path(temp_name) / "Mississippian_Map.png"
        _create_map_source(map_png)
        values = _sample_values(map_png, build_root)
        project, _ = save_ui_project(project_path, values)

    result: dict[str, object] = {
        "project": str(project_path),
        "project_id": project.project_id,
        "mod_id": project.mod_id,
    }
    if build:
        operation = ProjectWorkflowService().run(
            project,
            source_root=project_path.parent,
            output_root=build_root,
            mode=WorkflowMode.BUILD,
        )
        result.update(
            status=operation.status,
            summary=operation.summary,
            build_path=str(operation.build_path or ""),
            package_path=str(operation.package_path or ""),
            issues=[item.to_dict() for item in operation.issues],
        )
        if not operation.succeeded:
            raise RuntimeError(json.dumps(result, indent=2))
    return result


def _create_map_source(destination: Path) -> None:
    archive = REPO_ROOT / "Output" / "Mississippian.zip"
    entry = "Mississippian/Art/Map_Mississippian512.dds"
    if archive.is_file():
        with zipfile.ZipFile(archive) as package:
            with Image.open(io.BytesIO(package.read(entry))) as image:
                image.convert("RGB").save(destination, format="PNG")
        return
    with Image.open(INPUT / "DawnOfMan_Mississippian.png") as image:
        image.convert("RGB").save(destination, format="PNG")


def _sample_values(map_png: Path, build_root: Path) -> dict:
    def art(name: str) -> str:
        return str((INPUT / name).resolve())

    transform = {"zoom": 100, "offset_x": 0, "offset_y": 0}
    flavors = {
        "offense": 6,
        "defense": 6,
        "expansion": 6,
        "growth": 7,
        "science": 4,
        "culture": 8,
        "diplomacy": 5,
        "wonder": 6,
    }
    return {
        "schema_version": 1,
        "project": {
            "mod_name": "Mississippian Studio Demonstration",
            "prefix": "MISSISSIPPIAN_STUDIO",
            "version": 1,
            "author": "Civ V Civilization Studio",
            "description": "End-to-end BNW sample built from the repository's Mississippian source-art set.",
            "affects_saved_games": True,
            "project_root": str(build_root),
        },
        "civilization": {
            "name": "Mississippian Civilization",
            "short_name": "Mississippia",
            "adjective": "Mississippian",
            "base_civilization": "CIVILIZATION_IROQUOIS",
            "dawn_of_man_quote": "Great Sun, the mound cities and river peoples look to your guidance. Build a realm whose memory will endure through the ages.",
            "civilopedia": "A demonstration civilization used to validate the complete Civilization Studio pipeline.",
            "colors": {"primary": "#8e2430", "secondary": "#e0bd5a"},
            "city_names": [
                "Cahokia",
                "Moundville",
                "Etowah",
                "Spiro",
                "Kincaid",
                "Angel Mounds",
                "Aztalan",
                "Emerald Acropolis",
                "Winterville",
                "Toltec Mounds",
                "Parkin",
                "Lake George",
            ],
            "spy_names": ["Morning Star", "Red Horn", "Water Panther", "Thunderbird"],
        },
        "leader": {
            "name": "Great Sun",
            "title": "Keeper of the Sacred Fire",
            "civilopedia": "Great Sun represents the ceremonial leadership of the Mississippian demonstration civilization.",
            "flavors": flavors,
            "art": {
                "leader_scene": art("GreatSun_Scene.png"),
                "leader_fallback": art("GreatSun_LeaderIcon.png"),
            },
        },
        "mechanics": {
            "trait": {
                "name": "Mounds of the Sun",
                "short_description": "Military units are produced 15 percent faster.",
                "implementation_class": "Database-native recipe",
                "recipe": "Military production modifier",
                "modifier_value": 15,
                "effect_description": "Military units are produced 15 percent faster.",
            },
            "uniques": [
                {
                    "kind": "unit",
                    "name": "Chunkey Warrior",
                    "replaces_class": "UNITCLASS_SWORDSMAN",
                    "base_template": "UNIT_SWORDSMAN",
                    "override": "Combat",
                    "value": "16",
                    "help_text": "A stronger Swordsman used to validate safe vanilla-row cloning.",
                },
                {
                    "kind": "building",
                    "name": "Platform Mound",
                    "replaces_class": "BUILDINGCLASS_MONUMENT",
                    "base_template": "BUILDING_MONUMENT",
                    "override": "Yield:YIELD_CULTURE",
                    "value": "1",
                    "help_text": "A Monument replacement that adds one Culture.",
                },
            ],
        },
        "art": {
            "civilization_icon": {"source": art("Mississippian_CivilizationIcon.png"), "transform": transform},
            "civilization_alpha": {"source": art("Mississippian_AlphaIcon_black.png"), "transform": transform},
            "leader_portrait": {"source": art("GreatSun_LeaderIcon.png"), "transform": transform},
            "unique_unit_icon": {"source": art("ChunkeyWarrior_Icon.png"), "transform": transform},
            "unique_building_icon": {"source": art("PlatformMound_Icon.png"), "transform": transform},
            "unit_flag": {"source": art("ChunkeyWarrior_UnitFlag_black.png"), "transform": transform},
            "dawn_of_man": {"source": art("DawnOfMan_Mississippian.png"), "transform": transform},
            "map_image": {"source": str(map_png), "transform": transform},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "projects"
        / "Mississippian Studio Demo"
        / "Mississippian Studio Demo.civ5project.json",
    )
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    result = create_sample(args.output, build=not args.no_build)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
