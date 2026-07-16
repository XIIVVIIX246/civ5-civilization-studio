"""Pure Pillow renderers for Civ V icons and tactical flags."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw

from .profiles import (
    PORTRAIT_DIAMETER_RATIO,
    UNIT_FLAG_SUBJECT_SCALE,
    RenderProfile,
)


@dataclass(frozen=True, slots=True)
class RenderMetrics:
    profile: RenderProfile
    width: int
    height: int
    corner_alpha_max: int
    center_alpha: int
    transparent_fraction: float
    visible_fraction: float


def scrub_transparent_rgb(image: Image.Image) -> Image.Image:
    """Set RGB to black wherever alpha is exactly zero.

    DXT block compression can otherwise pull hidden RGB into visible edge
    pixels and create colored halos in game.
    """

    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    transparent = alpha.point(lambda value: 255 if value == 0 else 0)
    rgba.paste(Image.new("RGBA", rgba.size, (0, 0, 0, 0)), (0, 0), transparent)
    return rgba


def center_crop_square(image: Image.Image) -> Image.Image:
    side = min(image.width, image.height)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def antialiased_ellipse_mask(
    size: int, bbox: tuple[float, float, float, float], *, scale: int = 4
) -> Image.Image:
    if size <= 0 or scale <= 0:
        raise ValueError("mask size and scale must be positive")
    large = Image.new("L", (size * scale, size * scale), 0)
    scaled_bbox = tuple(int(round(value * scale)) for value in bbox)
    ImageDraw.Draw(large).ellipse(scaled_bbox, fill=255)
    return large.resize((size, size), Image.Resampling.LANCZOS)


def render_portrait_circle(image: Image.Image, size: int) -> Image.Image:
    """Render art inside the vanilla 172/256 circle, with no UI ring.

    The transparent area outside the circle is intentional.  Civ V draws the
    decorative gold frame at runtime; exported pixels must not contain it.
    """

    if size <= 0:
        raise ValueError("render size must be positive")
    diameter = max(1, int(round(size * PORTRAIT_DIAMETER_RATIO)))
    subject = center_crop_square(image.convert("RGBA")).resize(
        (diameter, diameter), Image.Resampling.LANCZOS
    )
    circle = antialiased_ellipse_mask(
        diameter, (0.5, 0.5, diameter - 1.5, diameter - 1.5)
    )
    subject.putalpha(ImageChops.darker(subject.getchannel("A"), circle))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(subject, ((size - diameter) // 2, (size - diameter) // 2))
    return scrub_transparent_rgb(canvas)


def black_background_to_white_alpha(image: Image.Image) -> Image.Image:
    """Turn white-on-black source art into a white antialiased alpha glyph."""

    source = image.convert("RGBA")
    luminance = source.convert("RGB").convert("L")
    black_threshold = 100
    white_threshold = 200
    span = white_threshold - black_threshold

    def alpha_ramp(value: int) -> int:
        if value <= black_threshold:
            return 0
        if value >= white_threshold:
            return 255
        return int(round((value - black_threshold) / span * 255))

    alpha = luminance.point(alpha_ramp)
    source_alpha = source.getchannel("A")
    if source_alpha.getextrema()[0] < 250:
        alpha = ImageChops.multiply(alpha, source_alpha)
    glyph = Image.new("RGBA", source.size, (255, 255, 255, 0))
    glyph.putalpha(alpha)
    return scrub_transparent_rgb(glyph)


def render_unit_flag(image: Image.Image, size: int) -> Image.Image:
    """Fit a tactical silhouette within 78 percent of a square cell."""

    if size <= 0:
        raise ValueError("render size must be positive")
    glyph = black_background_to_white_alpha(image)
    bbox = glyph.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if not bbox:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))
    subject = glyph.crop(bbox)
    target = max(1, int(round(size * UNIT_FLAG_SUBJECT_SCALE)))
    ratio = min(target / subject.width, target / subject.height)
    fitted = (
        max(1, int(round(subject.width * ratio))),
        max(1, int(round(subject.height * ratio))),
    )
    subject = subject.resize(fitted, Image.Resampling.LANCZOS)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.alpha_composite(
        subject, ((size - subject.width) // 2, (size - subject.height) // 2)
    )
    return scrub_transparent_rgb(output)


def render_alpha_glyph(image: Image.Image, size: int) -> Image.Image:
    """Render a civilization alpha emblem in the 172/256 safe footprint.

    Alpha-icon sources commonly arrive as an opaque white emblem on black.
    This removes the black background, preserves antialiased white alpha, and
    uses portrait-safe geometry without applying the tactical flag's 78% fit.
    """

    if size <= 0:
        raise ValueError("render size must be positive")
    glyph = black_background_to_white_alpha(image)
    bbox = glyph.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if not bbox:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))
    subject = glyph.crop(bbox)
    target = max(1, int(round(size * PORTRAIT_DIAMETER_RATIO)))
    ratio = min(target / subject.width, target / subject.height)
    fitted = (
        max(1, int(round(subject.width * ratio))),
        max(1, int(round(subject.height * ratio))),
    )
    subject = subject.resize(fitted, Image.Resampling.LANCZOS)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.alpha_composite(
        subject, ((size - subject.width) // 2, (size - subject.height) // 2)
    )
    return scrub_transparent_rgb(output)


def render_passthrough(image: Image.Image, size: int) -> Image.Image:
    """Contain source art in a square cell without circularizing it."""

    if size <= 0:
        raise ValueError("render size must be positive")
    subject = image.convert("RGBA")
    subject.thumbnail((size, size), Image.Resampling.LANCZOS)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.alpha_composite(
        subject, ((size - subject.width) // 2, (size - subject.height) // 2)
    )
    return scrub_transparent_rgb(output)


def render_image(image: Image.Image, size: int, profile: RenderProfile) -> Image.Image:
    if profile is RenderProfile.PORTRAIT_CIRCLE:
        return render_portrait_circle(image, size)
    if profile is RenderProfile.UNIT_FLAG:
        return render_unit_flag(image, size)
    if profile is RenderProfile.ALPHA_GLYPH:
        return render_alpha_glyph(image, size)
    if profile is RenderProfile.PASSTHROUGH_ALPHA:
        return render_passthrough(image, size)
    raise ValueError(f"unsupported render profile: {profile}")


def render_metrics(image: Image.Image, profile: RenderProfile) -> RenderMetrics:
    alpha = image.convert("RGBA").getchannel("A")
    histogram = alpha.histogram()
    pixels = image.width * image.height
    transparent = sum(histogram[:8]) / max(1, pixels)
    visible = sum(histogram[9:]) / max(1, pixels)
    corners = (
        (0, 0),
        (image.width - 1, 0),
        (0, image.height - 1),
        (image.width - 1, image.height - 1),
    )
    return RenderMetrics(
        profile=profile,
        width=image.width,
        height=image.height,
        corner_alpha_max=max(alpha.getpixel(point) for point in corners),
        center_alpha=alpha.getpixel((image.width // 2, image.height // 2)),
        transparent_fraction=transparent,
        visible_fraction=visible,
    )
