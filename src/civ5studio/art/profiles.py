"""Civ V art constants and DDS/render profiles.

The values in this module are the generic form of the Strategic Missile
Project's current BNW art contract.  Nothing here is tied to an SMP filename,
SQL type, or output directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


PREFERRED_SOURCE_SIZE = (1024, 1024)
STANDARD_ICON_SIZES = (256, 128, 80, 64, 45, 32)
# Civilization alpha/emblem atlases use a different Firaxis size ladder than
# normal portrait atlases.  Keep it explicit so callers never approximate a
# requested 48px or 24px entry with a normal icon size.
ALPHA_ICON_SIZES = (128, 80, 64, 48, 32, 24, 16)
ATLAS_COLUMNS = 8
ATLAS_ROWS = 8
ATLAS_CAPACITY = ATLAS_COLUMNS * ATLAS_ROWS
PORTRAIT_DIAMETER_RATIO = 172 / 256
UNIT_FLAG_SUBJECT_SCALE = 0.78


class DdsFormat(StrEnum):
    """Legacy DirectDraw surface formats used by Civ V BNW."""

    DXT1 = "DXT1"
    DXT5 = "DXT5"
    A8R8G8B8 = "A8R8G8B8"


class AlphaMode(StrEnum):
    PRESERVE = "preserve"
    REQUIRED = "required"
    OPAQUE = "opaque"


class RenderProfile(StrEnum):
    """Image geometry applied before an image enters a DDS or atlas."""

    PORTRAIT_CIRCLE = "portrait_circle"
    ALPHA_GLYPH = "alpha_glyph"
    PASSTHROUGH_ALPHA = "passthrough_alpha"
    UNIT_FLAG = "unit_flag"


class ImageFitMode(StrEnum):
    """Deterministic source fitting used before render/DDS processing."""

    COVER = "cover"
    CONTAIN = "contain"


class SourceValidationProfile(StrEnum):
    """Source checks that differ by the image's job in Civ V."""

    GENERIC = "generic"
    PORTRAIT_NO_FRAME = "portrait_no_frame"
    ALPHA_GLYPH = "alpha_glyph"
    UNIT_FLAG = "unit_flag"
    FULL_FRAME_OPAQUE = "full_frame_opaque"
    STRATEGIC_VIEW = "strategic_view"


class ArtProcessingRole(StrEnum):
    """Concrete Civ V art purposes understood by the processing backend.

    These values deliberately mirror portable project roles where possible,
    while ``leader_fallback`` remains a separate output purpose because the
    same leader source also feeds the circular portrait atlas.
    """

    GENERIC = "generic"
    CIVILIZATION_ICON = "civilization_icon"
    CIVILIZATION_ALPHA = "civilization_alpha"
    LEADER_PORTRAIT = "leader_portrait"
    LEADER_FALLBACK = "leader_fallback"
    LEADER_SCENE = "leader_scene"
    DAWN_OF_MAN = "dawn_of_man"
    MAP_IMAGE = "map_image"
    UNIQUE_UNIT_ICON = "unique_unit_icon"
    UNIQUE_BUILDING_ICON = "unique_building_icon"
    UNIQUE_IMPROVEMENT_ICON = "unique_improvement_icon"
    UNIT_FLAG = "unit_flag"
    STRATEGIC_VIEW = "strategic_view"


@dataclass(frozen=True, slots=True)
class DdsProfile:
    name: str
    format: DdsFormat
    alpha: AlphaMode
    mipmaps: bool = False
    default_size: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class ArtRoleProfile:
    """Locked preprocessing and output contract for one Civ V art purpose."""

    role: ArtProcessingRole
    working_size: tuple[int, int] | None
    output_size: tuple[int, int] | None
    fit_mode: ImageFitMode
    canvas_rgba: tuple[int, int, int, int]
    ensure_coverage: bool
    binary_black_white: bool
    requires_square_source: bool
    render_profile: RenderProfile
    validation_profile: SourceValidationProfile
    dds_profile: DdsProfile | None
    atlas_role: bool


PORTRAIT_ATLAS = DdsProfile(
    "portrait-atlas", DdsFormat.DXT5, AlphaMode.PRESERVE
)
ALPHA_ICON_ATLAS = DdsProfile(
    "alpha-icon-atlas", DdsFormat.DXT5, AlphaMode.REQUIRED
)
UNIT_FLAG_ATLAS = DdsProfile(
    "unit-flag-atlas", DdsFormat.DXT5, AlphaMode.REQUIRED
)
STRATEGIC_VIEW = DdsProfile(
    "strategic-view", DdsFormat.A8R8G8B8, AlphaMode.PRESERVE, default_size=(64, 64)
)
STATIC_SCREEN_OPAQUE = DdsProfile(
    "static-screen-opaque", DdsFormat.DXT1, AlphaMode.OPAQUE
)


PROFILES: dict[str, DdsProfile] = {
    profile.name: profile
    for profile in (
        PORTRAIT_ATLAS,
        ALPHA_ICON_ATLAS,
        UNIT_FLAG_ATLAS,
        STRATEGIC_VIEW,
        STATIC_SCREEN_OPAQUE,
    )
}


def _role_profile(
    role: ArtProcessingRole,
    *,
    working_size: tuple[int, int],
    output_size: tuple[int, int] | None,
    fit_mode: ImageFitMode,
    canvas_rgba: tuple[int, int, int, int],
    ensure_coverage: bool,
    binary_black_white: bool,
    requires_square_source: bool,
    render_profile: RenderProfile,
    validation_profile: SourceValidationProfile,
    dds_profile: DdsProfile,
    atlas_role: bool,
) -> ArtRoleProfile:
    return ArtRoleProfile(
        role=role,
        working_size=working_size,
        output_size=output_size,
        fit_mode=fit_mode,
        canvas_rgba=canvas_rgba,
        ensure_coverage=ensure_coverage,
        binary_black_white=binary_black_white,
        requires_square_source=requires_square_source,
        render_profile=render_profile,
        validation_profile=validation_profile,
        dds_profile=dds_profile,
        atlas_role=atlas_role,
    )


_PORTRAIT_ROLE_DEFAULTS = {
    "working_size": PREFERRED_SOURCE_SIZE,
    "output_size": None,
    "fit_mode": ImageFitMode.COVER,
    "canvas_rgba": (0, 0, 0, 0),
    "ensure_coverage": True,
    "binary_black_white": False,
    "requires_square_source": True,
    "render_profile": RenderProfile.PORTRAIT_CIRCLE,
    "validation_profile": SourceValidationProfile.PORTRAIT_NO_FRAME,
    "dds_profile": PORTRAIT_ATLAS,
    "atlas_role": True,
}


ART_ROLE_PROFILES: dict[ArtProcessingRole, ArtRoleProfile] = {
    ArtProcessingRole.GENERIC: ArtRoleProfile(
        role=ArtProcessingRole.GENERIC,
        working_size=None,
        output_size=None,
        fit_mode=ImageFitMode.COVER,
        canvas_rgba=(0, 0, 0, 0),
        ensure_coverage=False,
        binary_black_white=False,
        requires_square_source=False,
        render_profile=RenderProfile.PASSTHROUGH_ALPHA,
        validation_profile=SourceValidationProfile.GENERIC,
        dds_profile=None,
        atlas_role=False,
    ),
    ArtProcessingRole.CIVILIZATION_ICON: _role_profile(
        ArtProcessingRole.CIVILIZATION_ICON, **_PORTRAIT_ROLE_DEFAULTS
    ),
    ArtProcessingRole.LEADER_PORTRAIT: _role_profile(
        ArtProcessingRole.LEADER_PORTRAIT, **_PORTRAIT_ROLE_DEFAULTS
    ),
    ArtProcessingRole.UNIQUE_UNIT_ICON: _role_profile(
        ArtProcessingRole.UNIQUE_UNIT_ICON, **_PORTRAIT_ROLE_DEFAULTS
    ),
    ArtProcessingRole.UNIQUE_BUILDING_ICON: _role_profile(
        ArtProcessingRole.UNIQUE_BUILDING_ICON, **_PORTRAIT_ROLE_DEFAULTS
    ),
    ArtProcessingRole.UNIQUE_IMPROVEMENT_ICON: _role_profile(
        ArtProcessingRole.UNIQUE_IMPROVEMENT_ICON, **_PORTRAIT_ROLE_DEFAULTS
    ),
    ArtProcessingRole.CIVILIZATION_ALPHA: _role_profile(
        ArtProcessingRole.CIVILIZATION_ALPHA,
        working_size=PREFERRED_SOURCE_SIZE,
        output_size=None,
        fit_mode=ImageFitMode.CONTAIN,
        canvas_rgba=(0, 0, 0, 255),
        ensure_coverage=False,
        binary_black_white=True,
        requires_square_source=True,
        render_profile=RenderProfile.ALPHA_GLYPH,
        validation_profile=SourceValidationProfile.ALPHA_GLYPH,
        dds_profile=ALPHA_ICON_ATLAS,
        atlas_role=True,
    ),
    ArtProcessingRole.UNIT_FLAG: _role_profile(
        ArtProcessingRole.UNIT_FLAG,
        working_size=PREFERRED_SOURCE_SIZE,
        output_size=None,
        fit_mode=ImageFitMode.CONTAIN,
        canvas_rgba=(0, 0, 0, 255),
        ensure_coverage=False,
        binary_black_white=True,
        requires_square_source=True,
        render_profile=RenderProfile.UNIT_FLAG,
        validation_profile=SourceValidationProfile.UNIT_FLAG,
        dds_profile=UNIT_FLAG_ATLAS,
        atlas_role=True,
    ),
    ArtProcessingRole.LEADER_FALLBACK: _role_profile(
        ArtProcessingRole.LEADER_FALLBACK,
        working_size=(825, 1024),
        output_size=(825, 1024),
        fit_mode=ImageFitMode.COVER,
        canvas_rgba=(0, 0, 0, 255),
        ensure_coverage=True,
        binary_black_white=False,
        requires_square_source=False,
        render_profile=RenderProfile.PASSTHROUGH_ALPHA,
        validation_profile=SourceValidationProfile.FULL_FRAME_OPAQUE,
        dds_profile=STATIC_SCREEN_OPAQUE,
        atlas_role=False,
    ),
    ArtProcessingRole.LEADER_SCENE: _role_profile(
        ArtProcessingRole.LEADER_SCENE,
        working_size=(1600, 900),
        output_size=(1600, 900),
        fit_mode=ImageFitMode.COVER,
        canvas_rgba=(0, 0, 0, 255),
        ensure_coverage=True,
        binary_black_white=False,
        requires_square_source=False,
        render_profile=RenderProfile.PASSTHROUGH_ALPHA,
        validation_profile=SourceValidationProfile.FULL_FRAME_OPAQUE,
        dds_profile=STATIC_SCREEN_OPAQUE,
        atlas_role=False,
    ),
    ArtProcessingRole.DAWN_OF_MAN: _role_profile(
        ArtProcessingRole.DAWN_OF_MAN,
        working_size=(1024, 768),
        output_size=(1024, 768),
        fit_mode=ImageFitMode.COVER,
        canvas_rgba=(0, 0, 0, 255),
        ensure_coverage=True,
        binary_black_white=False,
        requires_square_source=False,
        render_profile=RenderProfile.PASSTHROUGH_ALPHA,
        validation_profile=SourceValidationProfile.FULL_FRAME_OPAQUE,
        dds_profile=STATIC_SCREEN_OPAQUE,
        atlas_role=False,
    ),
    ArtProcessingRole.MAP_IMAGE: _role_profile(
        ArtProcessingRole.MAP_IMAGE,
        working_size=(360, 412),
        output_size=(360, 412),
        fit_mode=ImageFitMode.COVER,
        canvas_rgba=(0, 0, 0, 255),
        ensure_coverage=True,
        binary_black_white=False,
        requires_square_source=False,
        render_profile=RenderProfile.PASSTHROUGH_ALPHA,
        validation_profile=SourceValidationProfile.FULL_FRAME_OPAQUE,
        dds_profile=STATIC_SCREEN_OPAQUE,
        atlas_role=False,
    ),
    ArtProcessingRole.STRATEGIC_VIEW: _role_profile(
        ArtProcessingRole.STRATEGIC_VIEW,
        working_size=PREFERRED_SOURCE_SIZE,
        output_size=(64, 64),
        fit_mode=ImageFitMode.CONTAIN,
        canvas_rgba=(0, 0, 0, 0),
        ensure_coverage=False,
        binary_black_white=False,
        requires_square_source=True,
        render_profile=RenderProfile.PASSTHROUGH_ALPHA,
        validation_profile=SourceValidationProfile.STRATEGIC_VIEW,
        dds_profile=STRATEGIC_VIEW,
        atlas_role=False,
    ),
}


def profile_by_name(name: str) -> DdsProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown DDS profile {name!r}; expected one of: {choices}") from exc


def art_role_profile(role: ArtProcessingRole | str) -> ArtRoleProfile:
    """Return the locked role contract, accepting serialized enum values."""

    try:
        return ART_ROLE_PROFILES[ArtProcessingRole(role)]
    except (KeyError, ValueError) as exc:
        choices = ", ".join(item.value for item in ArtProcessingRole)
        raise ValueError(
            f"unknown art processing role {role!r}; expected one of: {choices}"
        ) from exc
