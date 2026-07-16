"""Non-destructive source normalization for project-owned art staging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from civ5studio.art.profiles import (
    ArtProcessingRole,
    ImageFitMode,
    art_role_profile,
)


@dataclass(frozen=True, slots=True)
class ImageTransform:
    """Manual cover transform shared by GUI previews and release builds."""

    zoom: int = 100
    offset_x: int = 0
    offset_y: int = 0

    def __post_init__(self) -> None:
        if not 60 <= self.zoom <= 160:
            raise ValueError("zoom must be between 60 and 160 percent")
        if not -100 <= self.offset_x <= 100 or not -100 <= self.offset_y <= 100:
            raise ValueError("image offsets must be between -100 and 100")


def prepare_source_image(
    source: str | Path,
    destination: str | Path,
    *,
    size: tuple[int, int],
    transform: ImageTransform = ImageTransform(),
    binary_black_white: bool = False,
    fit_mode: ImageFitMode | str = ImageFitMode.COVER,
    canvas_rgba: tuple[int, int, int, int] = (0, 0, 0, 0),
    ensure_coverage: bool = False,
) -> Path:
    """Create a normalized working PNG without modifying ``source``.

    The image is cover-scaled, then zoomed and positioned using the same
    percentage controls exposed by the GUI. Transparent padding is retained;
    DDS profiles that require opacity composite it later in the art backend.
    """

    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"source image does not exist: {source_path}")
    if destination_path == source_path:
        raise ValueError("working image destination must differ from its source")
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("working image dimensions must be positive")

    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    fit_mode = ImageFitMode(fit_mode)
    if fit_mode is ImageFitMode.COVER:
        base_scale = max(width / image.width, height / image.height)
    else:
        base_scale = min(width / image.width, height / image.height)
    scale = base_scale
    scale *= transform.zoom / 100
    if ensure_coverage:
        if fit_mode is not ImageFitMode.COVER:
            raise ValueError("ensure_coverage requires cover fitting")
        scale = max(scale, base_scale)
    resized_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    resized = image.resize(resized_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, canvas_rgba)
    left = round((width - resized.width) / 2 + transform.offset_x * width / 200)
    top = round((height - resized.height) / 2 + transform.offset_y * height / 200)
    if ensure_coverage:
        left = min(0, max(width - resized.width, left))
        top = min(0, max(height - resized.height, top))
    canvas.alpha_composite(resized, (left, top))

    if binary_black_white:
        luminance = ImageOps.grayscale(canvas)
        thresholded = luminance.point(lambda value: 255 if value >= 128 else 0)
        opaque = Image.new("L", size, 255)
        canvas = Image.merge("RGBA", (thresholded, thresholded, thresholded, opaque))

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination_path, format="PNG", optimize=True)
    return destination_path


def prepare_role_source_image(
    source: str | Path,
    destination: str | Path,
    *,
    role: ArtProcessingRole | str,
    transform: ImageTransform = ImageTransform(),
    crop_mode: str = "",
) -> Path:
    """Normalize a source using the locked policy for its Civ V art role.

    Glyph roles always use contain fitting because the final alpha/flag
    renderer owns their safe footprint. Full-frame roles are cover-fitted and
    clamped so user offsets cannot create transparent strips that DXT1 would
    turn into black bars. ``manual`` retains the role default while applying
    the supplied transform.
    """

    profile = art_role_profile(role)
    if profile.working_size is None:
        raise ValueError(f"{profile.role.value} has no locked working size")
    fit_mode = profile.fit_mode
    if crop_mode in {ImageFitMode.COVER.value, ImageFitMode.CONTAIN.value}:
        # Fixed glyph and Strategic View roles must keep their contract fit.
        if profile.validation_profile.value not in {
            "alpha_glyph",
            "unit_flag",
            "strategic_view",
        }:
            fit_mode = ImageFitMode(crop_mode)
    ensure_coverage = profile.ensure_coverage and fit_mode is ImageFitMode.COVER
    return prepare_source_image(
        source,
        destination,
        size=profile.working_size,
        transform=transform,
        binary_black_white=profile.binary_black_white,
        fit_mode=fit_mode,
        canvas_rgba=profile.canvas_rgba,
        ensure_coverage=ensure_coverage,
    )
