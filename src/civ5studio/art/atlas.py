"""Stable fixed-grid atlas planning and construction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from PIL import Image

from .dds import DdsWriteResult, write_dds
from .profiles import (
    ALPHA_ICON_ATLAS,
    ALPHA_ICON_SIZES,
    ATLAS_CAPACITY,
    ATLAS_COLUMNS,
    ATLAS_ROWS,
    PORTRAIT_ATLAS,
    STANDARD_ICON_SIZES,
    UNIT_FLAG_ATLAS,
    ArtProcessingRole,
    DdsFormat,
    DdsProfile,
    RenderProfile,
    art_role_profile,
)
from .rendering import render_image, render_metrics


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class AtlasItem:
    """One explicitly assigned atlas slot.

    ``source_path`` is relative to the pipeline input root.  Explicit paths
    avoid fuzzy matching one image into multiple slots.
    """

    key: str
    source_path: Path
    index: int
    required: bool = True
    label: str = ""
    type_name: str = ""
    processing_role: ArtProcessingRole = ArtProcessingRole.GENERIC


@dataclass(frozen=True, slots=True)
class AtlasSpec:
    category: str
    atlas_name: str
    filename_stem: str
    items: tuple[AtlasItem, ...]
    render_profile: RenderProfile = RenderProfile.PORTRAIT_CIRCLE
    dds_profile: DdsProfile = PORTRAIT_ATLAS
    output_sizes: tuple[int, ...] = STANDARD_ICON_SIZES
    release_blocking: bool = True
    requires_square_source: bool = True
    preferred_source_size: tuple[int, int] | None = (1024, 1024)

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("atlas category cannot be empty")
        if not _SAFE_NAME.fullmatch(self.atlas_name):
            raise ValueError(f"unsafe atlas name: {self.atlas_name!r}")
        if not _SAFE_NAME.fullmatch(self.filename_stem):
            raise ValueError(f"unsafe atlas filename stem: {self.filename_stem!r}")
        if self.dds_profile.format is not DdsFormat.DXT5 or self.dds_profile.mipmaps:
            raise ValueError("Civ V icon atlases must use one-surface DXT5")
        if not self.output_sizes:
            raise ValueError("an atlas must declare at least one output size")
        if len(set(self.output_sizes)) != len(self.output_sizes):
            raise ValueError("atlas output sizes must be unique")
        supported_sizes = (
            set(STANDARD_ICON_SIZES) | set(ALPHA_ICON_SIZES)
            if self.dds_profile == ALPHA_ICON_ATLAS
            else set(STANDARD_ICON_SIZES)
        )
        unsupported = set(self.output_sizes) - supported_sizes
        if unsupported:
            raise ValueError(f"non-standard Civ V atlas sizes: {sorted(unsupported)}")
        keys = [item.key for item in self.items]
        indexes = [item.index for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate item keys in {self.category}")
        if len(indexes) != len(set(indexes)):
            raise ValueError(f"duplicate atlas indexes in {self.category}")
        if any(index < 0 for index in indexes):
            raise ValueError("atlas indexes cannot be negative")
        for item in self.items:
            role = ArtProcessingRole(item.processing_role)
            if role is ArtProcessingRole.GENERIC:
                continue
            profile = art_role_profile(role)
            if not profile.atlas_role:
                raise ValueError(f"{role.value} is not an atlas art role")
            if profile.render_profile is not self.render_profile:
                raise ValueError(
                    f"{role.value} requires {profile.render_profile.value} rendering"
                )
            if profile.dds_profile != self.dds_profile:
                raise ValueError(
                    f"{role.value} requires the {profile.dds_profile.name} DDS profile"
                )
        if self.render_profile is RenderProfile.UNIT_FLAG:
            if self.dds_profile != UNIT_FLAG_ATLAS:
                raise ValueError("unit-flag rendering requires the unit-flag DDS profile")
            if self.output_sizes != (32,):
                raise ValueError("Civ V unit-flag atlases must contain only the 32px size")


@dataclass(frozen=True, slots=True)
class AtlasPlacement:
    global_index: int
    page: int
    local_index: int
    row: int
    column: int
    atlas_name: str


@dataclass(frozen=True, slots=True)
class AtlasPageResult:
    category: str
    atlas_name: str
    atlas_page: int
    icon_size: int
    output_path: Path
    width: int
    height: int
    dds_profile: str
    dds_format: str
    mipmap_count: int
    output_sha256: str
    encoder: str
    built_item_keys: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AtlasShapeResult:
    item_key: str
    icon_size: int
    atlas_page: int
    corner_alpha_max: int
    center_alpha: int
    transparent_fraction: float
    visible_fraction: float


def atlas_page(index: int) -> int:
    if index < 0:
        raise ValueError("atlas index cannot be negative")
    return index // ATLAS_CAPACITY


def local_atlas_index(index: int) -> int:
    if index < 0:
        raise ValueError("atlas index cannot be negative")
    return index % ATLAS_CAPACITY


def paged_name(base_name: str, page: int) -> str:
    if page < 0:
        raise ValueError("atlas page cannot be negative")
    return base_name if page == 0 else f"{base_name}_{page + 1}"


def placement_for(index: int, base_name: str) -> AtlasPlacement:
    page = atlas_page(index)
    local = local_atlas_index(index)
    return AtlasPlacement(
        global_index=index,
        page=page,
        local_index=local,
        row=local // ATLAS_COLUMNS,
        column=local % ATLAS_COLUMNS,
        atlas_name=paged_name(base_name, page),
    )


def planned_placements(spec: AtlasSpec) -> dict[str, AtlasPlacement]:
    return {item.key: placement_for(item.index, spec.atlas_name) for item in spec.items}


def page_filename(stem: str, page: int, size: int) -> str:
    return f"{paged_name(stem, page)}_{size}.dds"


def expected_page_matrix(spec: AtlasSpec) -> set[tuple[int, int]]:
    """Return every page/size pair implied by configured stable indexes."""

    if not spec.items:
        return set()
    page_count = atlas_page(max(item.index for item in spec.items)) + 1
    return {(page, size) for size in spec.output_sizes for page in range(page_count)}


def build_atlas(
    spec: AtlasSpec,
    available_sources: Mapping[str, Path],
    output_directory: Path,
    *,
    preview_directory: Path | None = None,
    texconv_path: Path | None = None,
) -> tuple[list[AtlasPageResult], list[AtlasShapeResult]]:
    """Build all configured pages while leaving missing slots transparent."""

    if not available_sources:
        return [], []
    known_keys = {item.key for item in spec.items}
    unknown = set(available_sources) - known_keys
    if unknown:
        raise ValueError(f"sources do not belong to atlas {spec.category}: {sorted(unknown)}")
    page_matrix = expected_page_matrix(spec)
    pages: list[AtlasPageResult] = []
    shapes: list[AtlasShapeResult] = []
    by_key = {item.key: item for item in spec.items}
    output_directory.mkdir(parents=True, exist_ok=True)

    for size in spec.output_sizes:
        for page in sorted(page for page, page_size in page_matrix if page_size == size):
            atlas = Image.new(
                "RGBA",
                (ATLAS_COLUMNS * size, ATLAS_ROWS * size),
                (0, 0, 0, 0),
            )
            built_keys: list[str] = []
            for key, source_path in available_sources.items():
                item = by_key[key]
                placement = placement_for(item.index, spec.atlas_name)
                if placement.page != page:
                    continue
                with Image.open(source_path) as opened:
                    tile = render_image(opened, size, spec.render_profile)
                metrics = render_metrics(tile, spec.render_profile)
                shapes.append(
                    AtlasShapeResult(
                        item_key=key,
                        icon_size=size,
                        atlas_page=page,
                        corner_alpha_max=metrics.corner_alpha_max,
                        center_alpha=metrics.center_alpha,
                        transparent_fraction=metrics.transparent_fraction,
                        visible_fraction=metrics.visible_fraction,
                    )
                )
                atlas.alpha_composite(
                    tile, (placement.column * size, placement.row * size)
                )
                built_keys.append(key)

            output_path = output_directory / page_filename(spec.filename_stem, page, size)
            write_result: DdsWriteResult = write_dds(
                atlas, output_path, spec.dds_profile, texconv_path=texconv_path
            )
            if preview_directory is not None and size == min(spec.output_sizes):
                preview_directory.mkdir(parents=True, exist_ok=True)
                atlas.save(
                    preview_directory
                    / f"{paged_name(spec.filename_stem, page)}_{size}.png"
                )
            pages.append(
                AtlasPageResult(
                    category=spec.category,
                    atlas_name=paged_name(spec.atlas_name, page),
                    atlas_page=page,
                    icon_size=size,
                    output_path=output_path,
                    width=atlas.width,
                    height=atlas.height,
                    dds_profile=spec.dds_profile.name,
                    dds_format=write_result.header.fourcc,
                    mipmap_count=write_result.header.mipmap_count,
                    output_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
                    encoder=write_result.encoder,
                    built_item_keys=tuple(sorted(built_keys)),
                )
            )
    return pages, shapes


def unit_flag_atlas_spec(
    *,
    category: str,
    atlas_name: str,
    filename_stem: str,
    items: tuple[AtlasItem, ...],
    release_blocking: bool = True,
) -> AtlasSpec:
    role_items = tuple(
        replace(item, processing_role=ArtProcessingRole.UNIT_FLAG)
        if ArtProcessingRole(item.processing_role) is ArtProcessingRole.GENERIC
        else item
        for item in items
    )
    return AtlasSpec(
        category=category,
        atlas_name=atlas_name,
        filename_stem=filename_stem,
        items=role_items,
        render_profile=RenderProfile.UNIT_FLAG,
        dds_profile=UNIT_FLAG_ATLAS,
        output_sizes=(32,),
        release_blocking=release_blocking,
    )


def alpha_icon_atlas_spec(
    *,
    category: str,
    atlas_name: str,
    filename_stem: str,
    items: tuple[AtlasItem, ...],
    release_blocking: bool = True,
    output_sizes: tuple[int, ...] = ALPHA_ICON_SIZES,
) -> AtlasSpec:
    """Create a no-frame civilization alpha/emblem atlas specification."""

    role_items = tuple(
        replace(item, processing_role=ArtProcessingRole.CIVILIZATION_ALPHA)
        if ArtProcessingRole(item.processing_role) is ArtProcessingRole.GENERIC
        else item
        for item in items
    )
    return AtlasSpec(
        category=category,
        atlas_name=atlas_name,
        filename_stem=filename_stem,
        items=role_items,
        render_profile=RenderProfile.ALPHA_GLYPH,
        dds_profile=ALPHA_ICON_ATLAS,
        output_sizes=output_sizes,
        release_blocking=release_blocking,
    )
