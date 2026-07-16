from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from civ5studio.application import (
    ImageTransform,
    prepare_role_source_image,
    prepare_source_image,
)
from civ5studio.art import ArtProcessingRole


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepare_source_is_non_destructive_and_exact_size(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (300, 200), (20, 40, 60)).save(source)
    before = _sha(source)
    output = prepare_source_image(
        source,
        tmp_path / "working" / "normalized.png",
        size=(1024, 1024),
        transform=ImageTransform(zoom=120, offset_x=10, offset_y=-5),
    )
    assert _sha(source) == before
    with Image.open(output) as image:
        assert image.size == (1024, 1024)
        assert image.mode == "RGBA"


def test_binary_source_normalization_removes_intermediate_colors(tmp_path: Path) -> None:
    source = tmp_path / "flag.png"
    image = Image.new("RGB", (32, 32), (120, 120, 120))
    image.putpixel((0, 0), (255, 255, 255))
    image.save(source)
    output = prepare_source_image(
        source,
        tmp_path / "flag-normalized.png",
        size=(64, 64),
        binary_black_white=True,
    )
    with Image.open(output) as normalized:
        colors = normalized.getcolors(maxcolors=3)
        assert colors is not None
        assert {color for _, color in colors} <= {
            (0, 0, 0, 255),
            (255, 255, 255, 255),
        }


def test_role_preprocessing_is_deterministic_and_full_frames_cannot_gap(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wide.png"
    Image.new("RGBA", (800, 300), (30, 60, 90, 180)).save(source)
    first = prepare_role_source_image(
        source,
        tmp_path / "one.png",
        role=ArtProcessingRole.DAWN_OF_MAN,
        transform=ImageTransform(zoom=60, offset_x=100, offset_y=-100),
    )
    second = prepare_role_source_image(
        source,
        tmp_path / "two.png",
        role=ArtProcessingRole.DAWN_OF_MAN,
        transform=ImageTransform(zoom=60, offset_x=100, offset_y=-100),
    )
    assert _sha(first) == _sha(second)
    with Image.open(first) as prepared:
        assert prepared.size == (1024, 768)
        assert prepared.getchannel("A").getextrema() == (255, 255)


def test_glyph_role_uses_binary_contain_preprocessing(tmp_path: Path) -> None:
    source = tmp_path / "glyph.png"
    glyph = Image.new("RGB", (400, 200), "black")
    ImageDraw.Draw(glyph).rectangle((10, 20, 390, 180), fill=(180, 180, 180))
    glyph.save(source)
    output = prepare_role_source_image(
        source,
        tmp_path / "glyph-normalized.png",
        role=ArtProcessingRole.CIVILIZATION_ALPHA,
    )
    with Image.open(output) as prepared:
        assert prepared.size == (1024, 1024)
        colors = prepared.getcolors(maxcolors=3)
        assert colors is not None
        assert {color for _, color in colors} == {
            (0, 0, 0, 255),
            (255, 255, 255, 255),
        }


@pytest.mark.parametrize(
    "transform",
    [ImageTransform(60, -100, 100), ImageTransform(160, 100, -100)],
)
def test_transform_boundary_values_are_supported(transform: ImageTransform) -> None:
    assert transform.zoom in {60, 160}


def test_transform_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="zoom"):
        ImageTransform(zoom=59)
