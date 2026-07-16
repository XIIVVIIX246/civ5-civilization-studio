"""Structured, non-throwing validation for source and rendered art."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .profiles import (
    PORTRAIT_DIAMETER_RATIO,
    PREFERRED_SOURCE_SIZE,
    ArtProcessingRole,
    RenderProfile,
    SourceValidationProfile,
    art_role_profile,
)
from .rendering import (
    render_alpha_glyph,
    render_metrics,
    render_passthrough,
    render_unit_flag,
)


class IssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: IssueSeverity
    item_key: str
    category: str
    source_path: str
    details: dict[str, int | float | str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceValidation:
    item_key: str
    category: str
    source_path: Path
    exists: bool
    valid: bool
    width: int | None
    height: int | None
    source_sha256: str
    issues: tuple[ValidationIssue, ...]
    metrics: dict[str, int | float | str] = field(default_factory=dict)

    @property
    def blockers(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is IssueSeverity.BLOCKER)

    @property
    def status(self) -> str:
        if not self.exists:
            return "MISSING"
        if not self.valid:
            return "INVALID"
        if self.issues:
            return "WARN"
        return "PASS"


def _issue(
    code: str,
    message: str,
    *,
    blocking: bool,
    item_key: str,
    category: str,
    source_path: Path,
    details: dict[str, int | float | str] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        severity=IssueSeverity.BLOCKER if blocking else IssueSeverity.WARNING,
        item_key=item_key,
        category=category,
        source_path=source_path.as_posix(),
        details=details or {},
    )


def validate_image_source(
    path: Path,
    *,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
    requires_square: bool = True,
    preferred_size: tuple[int, int] | None = PREFERRED_SOURCE_SIZE,
) -> SourceValidation:
    """Validate a normal PNG/image while returning missing art as data."""

    blocking = required and release_blocking
    if not path.is_file():
        missing = _issue(
            "MISSING_REQUIRED_ART" if required else "MISSING_OPTIONAL_ART",
            "required source art is missing" if required else "optional source art is missing",
            blocking=blocking,
            item_key=item_key,
            category=category,
            source_path=path,
        )
        return SourceValidation(
            item_key, category, path, False, False, None, None, "", (missing,)
        )

    issues: list[ValidationIssue] = []
    try:
        with Image.open(path) as opened:
            opened.load()
            width, height = opened.size
    except (OSError, UnidentifiedImageError) as exc:
        unreadable = _issue(
            "UNREADABLE_ART",
            f"source image cannot be decoded: {exc}",
            blocking=blocking,
            item_key=item_key,
            category=category,
            source_path=path,
        )
        return SourceValidation(
            item_key, category, path, True, False, None, None, "", (unreadable,)
        )
    invalid = False
    if requires_square and width != height:
        invalid = True
        issues.append(
            _issue(
                "SOURCE_NOT_SQUARE",
                f"source must be square, got {width}x{height}",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"width": width, "height": height},
            )
        )
    if preferred_size and (width, height) != preferred_size:
        issues.append(
            _issue(
                "NON_PREFERRED_SOURCE_SIZE",
                f"preferred source size is {preferred_size[0]}x{preferred_size[1]}, "
                f"got {width}x{height}",
                blocking=False,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"width": width, "height": height},
            )
        )
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return SourceValidation(
        item_key,
        category,
        path,
        True,
        not invalid,
        width,
        height,
        source_hash,
        tuple(issues),
    )


def _gold_like(red: int, green: int, blue: int) -> bool:
    """Conservative color test used only by the annular frame detector."""

    return (
        red >= 150
        and green >= 80
        and blue <= 125
        and red >= green * 1.08
        and green >= blue * 1.20
        and max(red, green, blue) - min(red, green, blue) >= 65
    )


def _baked_gold_frame_metrics(image: Image.Image) -> dict[str, int | float]:
    """Measure narrow, continuous gold annuli without flagging gold scenes.

    The radial contrast term is important: a mostly gold background is not a
    ring, while a thin Firaxis-like medallion frame has a sharp radial peak.
    Analysis is capped at 256px so validation cost is deterministic.
    """

    side = min(256, image.width, image.height)
    square_side = min(image.width, image.height)
    left = (image.width - square_side) // 2
    top = (image.height - square_side) // 2
    sample = image.convert("RGB").crop(
        (left, top, left + square_side, top + square_side)
    ).resize((side, side), Image.Resampling.LANCZOS)
    center = (side - 1) / 2
    angle_bins = 72
    maximum_radius = int(side * 0.49)
    minimum_radius = max(3, int(side * 0.20))
    totals = [[0] * angle_bins for _ in range(maximum_radius + 1)]
    gold = [[0] * angle_bins for _ in range(maximum_radius + 1)]
    pixels = sample.load()
    for y in range(side):
        dy = y - center
        for x in range(side):
            dx = x - center
            radius = int(round(math.hypot(dx, dy)))
            if radius < minimum_radius or radius > maximum_radius:
                continue
            angle = (math.atan2(dy, dx) + math.pi) / (2 * math.pi)
            angle_bin = min(angle_bins - 1, int(angle * angle_bins))
            totals[radius][angle_bin] += 1
            if _gold_like(*pixels[x, y]):
                gold[radius][angle_bin] += 1

    fractions: dict[int, float] = {}
    coverages: dict[int, float] = {}
    half_band = max(1, round(side / 128))
    for radius in range(minimum_radius + half_band, maximum_radius - half_band):
        band_total = 0
        band_gold = 0
        covered_angles = 0
        for angle_bin in range(angle_bins):
            angle_total = sum(
                totals[band_radius][angle_bin]
                for band_radius in range(radius - half_band, radius + half_band + 1)
            )
            angle_gold = sum(
                gold[band_radius][angle_bin]
                for band_radius in range(radius - half_band, radius + half_band + 1)
            )
            band_total += angle_total
            band_gold += angle_gold
            if angle_total and angle_gold / angle_total >= 0.35:
                covered_angles += 1
        fractions[radius] = band_gold / max(1, band_total)
        coverages[radius] = covered_angles / angle_bins

    best_radius = max(
        fractions,
        key=lambda radius: (fractions[radius] * coverages[radius], fractions[radius]),
        default=0,
    )
    peak_fraction = fractions.get(best_radius, 0.0)
    angular_coverage = coverages.get(best_radius, 0.0)
    baseline_distance = max(8, round(side * 0.07))
    baseline_values = [
        fractions[radius]
        for radius in (best_radius - baseline_distance, best_radius + baseline_distance)
        if radius in fractions
    ]
    baseline = sum(baseline_values) / max(1, len(baseline_values))
    return {
        "gold_ring_radius": best_radius,
        "gold_ring_fraction": round(peak_fraction, 6),
        "gold_ring_angular_coverage": round(angular_coverage, 6),
        "gold_ring_radial_contrast": round(peak_fraction - baseline, 6),
        "gold_ring_sample_size": side,
    }


def validate_portrait_source(
    path: Path,
    *,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
    preferred_size: tuple[int, int] | None = PREFERRED_SOURCE_SIZE,
) -> SourceValidation:
    """Validate portrait inputs and reject a confidently detected baked frame."""

    base = validate_image_source(
        path,
        item_key=item_key,
        category=category,
        required=required,
        release_blocking=release_blocking,
        requires_square=True,
        preferred_size=preferred_size,
    )
    if not base.exists or base.width is None or not base.valid:
        return base
    with Image.open(path) as opened:
        metrics = _baked_gold_frame_metrics(opened)
    issues = list(base.issues)
    detected = (
        float(metrics["gold_ring_fraction"]) >= 0.45
        and float(metrics["gold_ring_angular_coverage"]) >= 0.80
        and float(metrics["gold_ring_radial_contrast"]) >= 0.25
    )
    if detected:
        issues.append(
            _issue(
                "BAKED_GOLD_FRAME_DETECTED",
                "portrait appears to contain a continuous gold medallion frame; "
                "Civ V supplies this frame at runtime",
                blocking=required and release_blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details=metrics,
            )
        )
    return SourceValidation(
        item_key=base.item_key,
        category=base.category,
        source_path=base.source_path,
        exists=True,
        valid=not detected,
        width=base.width,
        height=base.height,
        source_sha256=base.source_sha256,
        issues=tuple(issues),
        metrics=metrics,
    )


def validate_alpha_glyph_source(
    path: Path,
    *,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
) -> SourceValidation:
    """Validate a civilization alpha as a white glyph on black/transparent."""

    base = validate_image_source(
        path,
        item_key=item_key,
        category=category,
        required=required,
        release_blocking=release_blocking,
        requires_square=True,
        preferred_size=PREFERRED_SOURCE_SIZE,
    )
    if not base.exists or base.width is None or not base.valid:
        return base
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    total = image.width * image.height
    white = intermediate = visible = 0
    pixel_data = (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )
    for red, green, blue, alpha in pixel_data:
        if alpha == 0:
            continue
        visible += 1
        if red >= 245 and green >= 245 and blue >= 245:
            white += 1
        elif not (red <= 8 and green <= 8 and blue <= 8):
            intermediate += 1
    white_coverage = white / max(1, total)
    intermediate_ratio = intermediate / max(1, visible)
    metrics: dict[str, int | float | str] = {
        "visible_pixels": visible,
        "white_pixels": white,
        "intermediate_pixels": intermediate,
        "white_coverage": round(white_coverage, 6),
        "intermediate_ratio": round(intermediate_ratio, 6),
    }
    issues = list(base.issues)
    invalid = False
    blocking = required and release_blocking
    if white_coverage < 0.002 or white_coverage > 0.70:
        invalid = True
        issues.append(
            _issue(
                "ALPHA_GLYPH_WHITE_COVERAGE",
                f"white emblem coverage {white_coverage:.2%} is outside 0.2%-70%",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"white_coverage": white_coverage},
            )
        )
    if intermediate_ratio > 0.01:
        invalid = True
        issues.append(
            _issue(
                "ALPHA_GLYPH_INTERMEDIATE_COLORS",
                f"{intermediate_ratio:.2%} of visible pixels are not near black/white",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"intermediate_ratio": intermediate_ratio},
            )
        )
    rendered = render_alpha_glyph(image, 32)
    rendered_alpha = rendered.getchannel("A")
    alpha_data = (
        rendered_alpha.get_flattened_data()
        if hasattr(rendered_alpha, "get_flattened_data")
        else rendered_alpha.getdata()
    )
    legible = sum(1 for alpha in alpha_data if alpha > 24)
    metrics["rendered_32px_visible_pixels"] = legible
    if legible < 4:
        invalid = True
        issues.append(
            _issue(
                "ALPHA_GLYPH_NOT_LEGIBLE_32PX",
                "rendered civilization alpha retains fewer than four visible pixels at 32px",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"visible_pixels": legible},
            )
        )
    return SourceValidation(
        item_key=base.item_key,
        category=base.category,
        source_path=base.source_path,
        exists=True,
        valid=not invalid,
        width=base.width,
        height=base.height,
        source_sha256=base.source_sha256,
        issues=tuple(issues),
        metrics=metrics,
    )


def validate_unit_flag_source(
    path: Path,
    *,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
) -> SourceValidation:
    """Validate the SMP-standard white silhouette on black source contract."""

    base = validate_image_source(
        path,
        item_key=item_key,
        category=category,
        required=required,
        release_blocking=release_blocking,
        requires_square=True,
        preferred_size=PREFERRED_SOURCE_SIZE,
    )
    if not base.exists or base.width is None or not base.valid:
        return base
    blocking = required and release_blocking
    issues = list(base.issues)
    metrics: dict[str, int | float | str] = {}
    invalid = False
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    visible = black = white = intermediate = 0
    min_x, min_y = image.width, image.height
    max_x = max_y = -1
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            visible += 1
            is_black = red <= 8 and green <= 8 and blue <= 8
            is_white = red >= 245 and green >= 245 and blue >= 245
            if is_black:
                black += 1
            elif is_white:
                white += 1
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
            else:
                intermediate += 1

    metrics.update(
        visible_pixels=visible,
        black_pixels=black,
        white_pixels=white,
        intermediate_pixels=intermediate,
    )
    if visible == 0:
        invalid = True
        issues.append(
            _issue(
                "EMPTY_UNIT_FLAG",
                "unit-flag source has no visible pixels",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
            )
        )
    else:
        intermediate_ratio = intermediate / visible
        white_coverage = white / visible
        metrics["intermediate_ratio"] = round(intermediate_ratio, 6)
        metrics["white_coverage"] = round(white_coverage, 6)
        if intermediate_ratio > 0.01:
            invalid = True
            issues.append(
                _issue(
                    "UNIT_FLAG_INTERMEDIATE_COLORS",
                    f"{intermediate_ratio:.2%} of visible pixels are not near black/white",
                    blocking=blocking,
                    item_key=item_key,
                    category=category,
                    source_path=path,
                    details={"intermediate_ratio": intermediate_ratio},
                )
            )
        if white_coverage < 0.02 or white_coverage > 0.70:
            invalid = True
            issues.append(
                _issue(
                    "UNIT_FLAG_WHITE_COVERAGE",
                    f"white glyph coverage {white_coverage:.2%} is outside 2%-70%",
                    blocking=blocking,
                    item_key=item_key,
                    category=category,
                    source_path=path,
                    details={"white_coverage": white_coverage},
                )
            )
        if white and (
            min_x <= 0
            or min_y <= 0
            or max_x >= image.width - 1
            or max_y >= image.height - 1
        ):
            issues.append(
                _issue(
                    "UNIT_FLAG_TOUCHES_EDGE",
                    "white glyph bounding box touches the source edge",
                    blocking=False,
                    item_key=item_key,
                    category=category,
                    source_path=path,
                )
            )

    rendered = render_unit_flag(image, 32)
    rendered_pixels = (
        rendered.get_flattened_data()
        if hasattr(rendered, "get_flattened_data")
        else rendered.getdata()
    )
    bright_pixels = sum(
        1
        for red, green, blue, alpha in rendered_pixels
        if alpha > 0 and red >= 180 and green >= 180 and blue >= 180
    )
    metrics["rendered_32px_bright_pixels"] = bright_pixels
    if bright_pixels < 4:
        invalid = True
        issues.append(
            _issue(
                "UNIT_FLAG_NOT_LEGIBLE_32PX",
                "rendered unit flag retains fewer than four bright pixels at 32px",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"bright_pixels": bright_pixels},
            )
        )
    return SourceValidation(
        item_key=base.item_key,
        category=base.category,
        source_path=base.source_path,
        exists=True,
        valid=not invalid,
        width=base.width,
        height=base.height,
        source_sha256=base.source_sha256,
        issues=tuple(issues),
        metrics=metrics,
    )


def validate_full_frame_source(
    path: Path,
    *,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
    expected_size: tuple[int, int] | None,
) -> SourceValidation:
    """Validate a DXT1 screen/map source as exact-size and fully opaque."""

    base = validate_image_source(
        path,
        item_key=item_key,
        category=category,
        required=required,
        release_blocking=release_blocking,
        requires_square=False,
        preferred_size=expected_size,
    )
    if not base.exists or base.width is None or not base.valid:
        return base
    with Image.open(path) as opened:
        alpha = opened.convert("RGBA").getchannel("A")
    histogram = alpha.histogram()
    total = base.width * base.height
    transparent_pixels = sum(histogram[:250])
    transparent_fraction = transparent_pixels / max(1, total)
    metrics: dict[str, int | float | str] = {
        "transparent_pixels": transparent_pixels,
        "transparent_fraction": round(transparent_fraction, 6),
    }
    issues = list(base.issues)
    invalid = False
    blocking = required and release_blocking
    if expected_size is not None and (base.width, base.height) != expected_size:
        invalid = True
        issues.append(
            _issue(
                "FULL_FRAME_DIMENSIONS",
                f"full-frame art must be {expected_size[0]}x{expected_size[1]}, "
                f"got {base.width}x{base.height}",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"width": base.width, "height": base.height},
            )
        )
    if transparent_fraction > 0.001:
        invalid = True
        issues.append(
            _issue(
                "FULL_FRAME_HAS_TRANSPARENCY",
                f"full-frame art contains {transparent_fraction:.2%} transparent pixels",
                blocking=blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"transparent_fraction": transparent_fraction},
            )
        )
    return SourceValidation(
        item_key=base.item_key,
        category=base.category,
        source_path=base.source_path,
        exists=True,
        valid=not invalid,
        width=base.width,
        height=base.height,
        source_sha256=base.source_sha256,
        issues=tuple(issues),
        metrics=metrics,
    )


def validate_strategic_view_source(
    path: Path,
    *,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
) -> SourceValidation:
    """Validate Strategic View source legibility while preserving color/alpha."""

    base = validate_image_source(
        path,
        item_key=item_key,
        category=category,
        required=required,
        release_blocking=release_blocking,
        requires_square=True,
        preferred_size=PREFERRED_SOURCE_SIZE,
    )
    if not base.exists or base.width is None or not base.valid:
        return base
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    rendered = render_passthrough(image, 64)
    alpha = rendered.getchannel("A")
    histogram = alpha.histogram()
    total = rendered.width * rendered.height
    visible_pixels = sum(histogram[9:])
    opaque_fraction = sum(histogram[250:]) / max(1, total)
    corners = (
        (0, 0),
        (rendered.width - 1, 0),
        (0, rendered.height - 1),
        (rendered.width - 1, rendered.height - 1),
    )
    corner_alpha_max = max(alpha.getpixel(point) for point in corners)
    metrics: dict[str, int | float | str] = {
        "rendered_64px_visible_pixels": visible_pixels,
        "rendered_64px_opaque_fraction": round(opaque_fraction, 6),
        "rendered_64px_corner_alpha_max": corner_alpha_max,
    }
    issues = list(base.issues)
    invalid = visible_pixels < 4
    if invalid:
        issues.append(
            _issue(
                "STRATEGIC_VIEW_NOT_LEGIBLE_64PX",
                "Strategic View art retains fewer than four visible pixels at 64px",
                blocking=required and release_blocking,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"visible_pixels": visible_pixels},
            )
        )
    if opaque_fraction > 0.98 and corner_alpha_max > 240:
        issues.append(
            _issue(
                "STRATEGIC_VIEW_OPAQUE_BACKGROUND",
                "Strategic View art is fully opaque; a transparent background is recommended",
                blocking=False,
                item_key=item_key,
                category=category,
                source_path=path,
                details={"opaque_fraction": opaque_fraction},
            )
        )
    return SourceValidation(
        item_key=base.item_key,
        category=base.category,
        source_path=base.source_path,
        exists=True,
        valid=not invalid,
        width=base.width,
        height=base.height,
        source_sha256=base.source_sha256,
        issues=tuple(issues),
        metrics=metrics,
    )


def validate_art_role_source(
    path: Path,
    *,
    role: ArtProcessingRole | str,
    item_key: str,
    category: str,
    required: bool,
    release_blocking: bool,
    requires_square: bool | None = None,
    preferred_size: tuple[int, int] | None = None,
) -> SourceValidation:
    """Dispatch source checks using the explicit Civ V art-purpose contract."""

    profile = art_role_profile(role)
    source_validation = profile.validation_profile
    if source_validation is SourceValidationProfile.PORTRAIT_NO_FRAME:
        return validate_portrait_source(
            path,
            item_key=item_key,
            category=category,
            required=required,
            release_blocking=release_blocking,
            preferred_size=preferred_size or profile.working_size,
        )
    if source_validation is SourceValidationProfile.ALPHA_GLYPH:
        return validate_alpha_glyph_source(
            path,
            item_key=item_key,
            category=category,
            required=required,
            release_blocking=release_blocking,
        )
    if source_validation is SourceValidationProfile.UNIT_FLAG:
        return validate_unit_flag_source(
            path,
            item_key=item_key,
            category=category,
            required=required,
            release_blocking=release_blocking,
        )
    if source_validation is SourceValidationProfile.FULL_FRAME_OPAQUE:
        return validate_full_frame_source(
            path,
            item_key=item_key,
            category=category,
            required=required,
            release_blocking=release_blocking,
            expected_size=preferred_size or profile.working_size,
        )
    if source_validation is SourceValidationProfile.STRATEGIC_VIEW:
        return validate_strategic_view_source(
            path,
            item_key=item_key,
            category=category,
            required=required,
            release_blocking=release_blocking,
        )
    return validate_image_source(
        path,
        item_key=item_key,
        category=category,
        required=required,
        release_blocking=release_blocking,
        requires_square=(
            profile.requires_square_source if requires_square is None else requires_square
        ),
        preferred_size=preferred_size or profile.working_size,
    )


def validate_rendered_tile(image: Image.Image, profile: RenderProfile) -> tuple[ValidationIssue, ...]:
    """Validate geometry after rendering, before atlas compression."""

    metrics = render_metrics(image, profile)
    issues: list[ValidationIssue] = []
    common = {
        "blocking": True,
        "item_key": "rendered-tile",
        "category": "rendered",
        "source_path": Path("<memory>"),
    }
    if profile is RenderProfile.PORTRAIT_CIRCLE:
        if metrics.corner_alpha_max > 8:
            issues.append(
                _issue("PORTRAIT_OPAQUE_CORNER", "portrait corner is opaque", **common)
            )
        if not 0.61 <= metrics.transparent_fraction <= 0.69:
            issues.append(
                _issue(
                    "PORTRAIT_CIRCLE_GEOMETRY",
                    "portrait transparency is outside the vanilla 172/256 geometry",
                    details={"transparent_fraction": metrics.transparent_fraction},
                    **common,
                )
            )
        if metrics.center_alpha < 16:
            issues.append(
                _issue("PORTRAIT_EMPTY_CENTER", "portrait center is transparent", **common)
            )
    elif profile is RenderProfile.UNIT_FLAG:
        rgba = image.convert("RGBA")
        pixel_data = (
            rgba.get_flattened_data()
            if hasattr(rgba, "get_flattened_data")
            else rgba.getdata()
        )
        visible = [pixel for pixel in pixel_data if pixel[3] > 24]
        coverage = len(visible) / max(1, rgba.width * rgba.height)
        nonwhite = sum(1 for red, green, blue, _ in visible if min(red, green, blue) < 235)
        if metrics.corner_alpha_max > 8:
            issues.append(_issue("UNIT_FLAG_OPAQUE_CORNER", "unit flag corner is opaque", **common))
        if not 0.03 <= coverage <= 0.50:
            issues.append(
                _issue(
                    "UNIT_FLAG_RENDER_COVERAGE",
                    "rendered flag coverage is outside 3%-50%",
                    details={"coverage": coverage},
                    **common,
                )
            )
        if visible and nonwhite / len(visible) > 0.02:
            issues.append(
                _issue(
                    "UNIT_FLAG_RENDER_NOT_WHITE",
                    "rendered flag contains non-white visible pixels",
                    **common,
                )
            )
    elif profile is RenderProfile.ALPHA_GLYPH:
        alpha = image.convert("RGBA").getchannel("A")
        bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
        target = int(round(image.width * PORTRAIT_DIAMETER_RATIO))
        if metrics.corner_alpha_max > 8:
            issues.append(
                _issue("ALPHA_GLYPH_OPAQUE_CORNER", "alpha glyph corner is opaque", **common)
            )
        if not bbox:
            issues.append(
                _issue("ALPHA_GLYPH_EMPTY", "alpha glyph has no visible pixels", **common)
            )
        elif bbox[2] - bbox[0] > target or bbox[3] - bbox[1] > target:
            issues.append(
                _issue(
                    "ALPHA_GLYPH_GEOMETRY",
                    "alpha glyph exceeds the 172/256 safe footprint",
                    details={"target": target},
                    **common,
                )
            )
    return tuple(issues)
