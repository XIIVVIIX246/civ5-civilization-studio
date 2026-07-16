"""Adapt portable project art roles to the SMP-standard art pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civ5studio.art import (
    PORTRAIT_ATLAS,
    STATIC_SCREEN_OPAQUE,
    STRATEGIC_VIEW,
    ArtProcessingRole,
    ArtProjectSpec,
    AtlasItem,
    AtlasSpec,
    IndividualArtSpec,
    RenderProfile,
    alpha_icon_atlas_spec,
    art_role_profile,
    unit_flag_atlas_spec,
)
from civ5studio.domain import ArtAssetSpec, ArtRole, CivProject

from .image_prep import ImageTransform, prepare_role_source_image


@dataclass(frozen=True, slots=True)
class PreparedArtProject:
    spec: ArtProjectSpec
    input_root: Path


def prepare_art_project(
    project: CivProject,
    *,
    project_root: str | Path,
    working_root: str | Path,
) -> PreparedArtProject:
    """Create normalized working PNGs and a complete stable-slot art spec."""

    source_root = Path(project_root).resolve()
    input_root = Path(working_root).resolve()
    input_root.mkdir(parents=True, exist_ok=True)
    assets = {(item.role, item.subject_key): item for item in project.art.assets}
    transforms = _transform_map(project)

    def prepare(
        key: str,
        role: ArtRole,
        subject: str,
        processing_role: ArtProcessingRole,
        *,
        transform_role: str | None = None,
    ) -> Path:
        relative = Path("Normalized") / f"{key}.png"
        asset = assets.get((role, subject))
        if asset is None:
            return Path("Missing") / f"{key}.png"
        source = (source_root / asset.source_png).resolve()
        if source != source_root and source_root not in source.parents:
            return Path("Missing") / f"{key}.png"
        transform = _transform_for(
            transforms,
            transform_role or role.value,
            asset,
        )
        if source.is_file():
            prepare_role_source_image(
                source,
                input_root / relative,
                role=processing_role,
                transform=transform,
                crop_mode=asset.crop_mode,
            )
        return relative

    ids = project.ids()
    main_items: list[AtlasItem] = []
    main_roles: list[tuple[str, ArtRole, str, ArtProcessingRole, str]] = [
        (
            "civilization",
            ArtRole.CIVILIZATION_ICON,
            "civilization",
            ArtProcessingRole.CIVILIZATION_ICON,
            "civilization_icon",
        ),
        (
            "leader",
            ArtRole.LEADER_PORTRAIT,
            "leader",
            ArtProcessingRole.LEADER_PORTRAIT,
            "leader_portrait",
        ),
    ]
    main_roles.extend(
        (
            f"unit_{item.key}",
            ArtRole.UNIQUE_UNIT_ICON,
            f"unit:{item.key}",
            ArtProcessingRole.UNIQUE_UNIT_ICON,
            "unique_unit_icon",
        )
        for item in project.units
    )
    main_roles.extend(
        (
            f"building_{item.key}",
            ArtRole.UNIQUE_BUILDING_ICON,
            f"building:{item.key}",
            ArtProcessingRole.UNIQUE_BUILDING_ICON,
            "unique_building_icon",
        )
        for item in project.buildings
    )
    main_roles.extend(
        (
            f"improvement_{item.key}",
            ArtRole.UNIQUE_IMPROVEMENT_ICON,
            f"improvement:{item.key}",
            ArtProcessingRole.UNIQUE_IMPROVEMENT_ICON,
            "unique_improvement_icon",
        )
        for item in project.improvements
    )
    for index, (key, role, subject, processing_role, transform_role) in enumerate(
        main_roles
    ):
        main_items.append(
            AtlasItem(
                key=key,
                source_path=prepare(
                    f"main_{key}",
                    role,
                    subject,
                    processing_role,
                    transform_role=transform_role,
                ),
                index=index,
                required=True,
                label=key,
                processing_role=processing_role,
            )
        )
    main_atlas = AtlasSpec(
        category="main-portraits",
        atlas_name=ids.main_atlas,
        filename_stem=f"{project.internal_prefix}_Atlas",
        items=tuple(main_items),
        render_profile=RenderProfile.PORTRAIT_CIRCLE,
        dds_profile=PORTRAIT_ATLAS,
    )

    alpha_atlas = alpha_icon_atlas_spec(
        category="civilization-alpha",
        atlas_name=ids.alpha_atlas,
        filename_stem=f"{project.internal_prefix}_Alpha",
        items=(
            AtlasItem(
                key="civilization_alpha",
                source_path=prepare(
                    "civilization_alpha",
                    ArtRole.CIVILIZATION_ALPHA,
                    "civilization",
                    ArtProcessingRole.CIVILIZATION_ALPHA,
                    transform_role="civilization_alpha",
                ),
                index=0,
                required=True,
            ),
        ),
    )

    flag_atlases: list[AtlasSpec] = []
    for unit in project.units:
        flag_atlases.append(
            unit_flag_atlas_spec(
                category=f"unit-flag-{unit.key}",
                atlas_name=ids.unit_flag_atlases[unit.key],
                filename_stem=f"{project.internal_prefix}_Flag_{unit.key}",
                items=(
                    AtlasItem(
                        key=f"flag_{unit.key}",
                        source_path=prepare(
                            f"flag_{unit.key}",
                            ArtRole.UNIT_FLAG,
                            f"unit:{unit.key}",
                            ArtProcessingRole.UNIT_FLAG,
                            transform_role="unit_flag",
                        ),
                        index=0,
                        required=True,
                    ),
                ),
            )
        )

    individual_specs = [
        IndividualArtSpec(
            key="leader_scene",
            category="leader-scene",
            source_path=prepare(
                "leader_scene",
                ArtRole.LEADER_SCENE,
                "leader",
                ArtProcessingRole.LEADER_SCENE,
                transform_role="leader_scene",
            ),
            output_path=Path(f"Art/Leaders/{project.internal_prefix}_scene.dds"),
            output_size=(1600, 900),
            dds_profile=STATIC_SCREEN_OPAQUE,
            preferred_source_size=(1600, 900),
            processing_role=ArtProcessingRole.LEADER_SCENE,
        ),
        IndividualArtSpec(
            key="leader_fallback",
            category="leader-fallback",
            source_path=prepare(
                "leader_fallback",
                ArtRole.LEADER_PORTRAIT,
                "leader",
                ArtProcessingRole.LEADER_FALLBACK,
                transform_role="leader_portrait",
            ),
            output_path=Path(f"Art/Leaders/{project.internal_prefix}_fallback.dds"),
            output_size=(825, 1024),
            dds_profile=STATIC_SCREEN_OPAQUE,
            preferred_source_size=(825, 1024),
            processing_role=ArtProcessingRole.LEADER_FALLBACK,
        ),
        IndividualArtSpec(
            key="dawn_of_man",
            category="dawn-of-man",
            source_path=prepare(
                "dawn_of_man",
                ArtRole.DAWN_OF_MAN,
                "civilization",
                ArtProcessingRole.DAWN_OF_MAN,
                transform_role="dawn_of_man",
            ),
            output_path=Path(f"Art/DOM/{project.internal_prefix}_DOM.dds"),
            output_size=(1024, 768),
            dds_profile=STATIC_SCREEN_OPAQUE,
            preferred_source_size=(1024, 768),
            processing_role=ArtProcessingRole.DAWN_OF_MAN,
        ),
        IndividualArtSpec(
            key="civilization_map",
            category="civilization-map",
            source_path=prepare(
                "civilization_map",
                ArtRole.MAP_IMAGE,
                "civilization",
                ArtProcessingRole.MAP_IMAGE,
                transform_role="map_image",
            ),
            output_path=Path(f"Art/Maps/{project.internal_prefix}_map.dds"),
            output_size=(360, 412),
            dds_profile=STATIC_SCREEN_OPAQUE,
            preferred_source_size=(360, 412),
            processing_role=ArtProcessingRole.MAP_IMAGE,
        ),
    ]
    strategic_profile = art_role_profile(ArtProcessingRole.STRATEGIC_VIEW)
    for unit in project.units:
        subject = f"unit:{unit.key}"
        asset = assets.get((ArtRole.STRATEGIC_VIEW, subject))
        if asset is None:
            continue
        individual_specs.append(
            IndividualArtSpec(
                key=f"strategic_{unit.key}",
                category=f"strategic-view-{unit.key}",
                source_path=prepare(
                    f"strategic_{unit.key}",
                    ArtRole.STRATEGIC_VIEW,
                    subject,
                    ArtProcessingRole.STRATEGIC_VIEW,
                    transform_role="strategic_view",
                ),
                output_path=Path(
                    f"Art/StrategicView/SV_{project.internal_prefix}_{unit.key}.dds"
                ),
                output_size=strategic_profile.output_size or (64, 64),
                dds_profile=STRATEGIC_VIEW,
                required=asset.required,
                requires_square_source=True,
                preferred_source_size=strategic_profile.working_size,
                render_profile=RenderProfile.PASSTHROUGH_ALPHA,
                stretch_to_output=False,
                type_name=ids.units[unit.key],
                processing_role=ArtProcessingRole.STRATEGIC_VIEW,
            )
        )
    return PreparedArtProject(
        ArtProjectSpec(
            project_id=project.project_id,
            atlases=(main_atlas, alpha_atlas, *flag_atlases),
            individuals=tuple(individual_specs),
        ),
        input_root,
    )


def _transform_map(project: CivProject) -> dict[str, Any]:
    ui = project.extensions.get("ui", {})
    if not isinstance(ui, dict):
        return {}
    value = ui.get("art_transforms", {})
    return dict(value) if isinstance(value, dict) else {}


def _transform_for(
    transforms: dict[str, Any], role: str, asset: ArtAssetSpec
) -> ImageTransform:
    raw = transforms.get(role, {})
    if not isinstance(raw, dict):
        raw = {}
    return ImageTransform(
        zoom=_bounded_int(raw.get("zoom"), 100, 60, 160),
        offset_x=_bounded_int(
            raw.get("offset_x"),
            round((asset.focal_x - 0.5) * 200),
            -100,
            100,
        ),
        offset_y=_bounded_int(
            raw.get("offset_y"),
            round((asset.focal_y - 0.5) * 200),
            -100,
            100,
        ),
    )


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
