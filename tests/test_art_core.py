from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from civ5studio.art import (
    ALPHA_ICON_ATLAS,
    ALPHA_ICON_SIZES,
    ATLAS_CAPACITY,
    PORTRAIT_ATLAS,
    STATIC_SCREEN_OPAQUE,
    STRATEGIC_VIEW,
    ArtProcessingRole,
    ArtProjectSpec,
    AtlasItem,
    AtlasSpec,
    IndividualArtSpec,
    PipelineMode,
    PipelineStatus,
    RenderProfile,
    art_role_profile,
    atlas_page,
    alpha_icon_atlas_spec,
    build_available,
    local_atlas_index,
    paged_name,
    placement_for,
    read_dds_header,
    render_alpha_glyph,
    render_portrait_circle,
    render_unit_flag,
    run_art_pipeline,
    scrub_transparent_rgb,
    strict_release,
    unit_flag_atlas_spec,
    validate,
    validate_dds,
    validate_rendered_tile,
    validate_full_frame_source,
    validate_portrait_source,
    validate_unit_flag_source,
    write_dds,
)


def save_solid(path: Path, color=(160, 45, 30, 255), size=(64, 64)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)


def save_flag(path: Path, *, color=(255, 255, 255, 255), size=(64, 64)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, (0, 0, 0, 255))
    ImageDraw.Draw(image).rectangle(
        (size[0] // 3, size[1] // 4, size[0] * 2 // 3, size[1] * 3 // 4),
        fill=color,
    )
    image.save(path)


def tiny_project(input_root: Path) -> ArtProjectSpec:
    save_solid(input_root / "Icons" / "present.png")
    atlas = AtlasSpec(
        category="CivilizationIcons",
        atlas_name="TEST_CIV_ATLAS",
        filename_stem="TestCivAtlas",
        items=(
            AtlasItem("present", Path("Icons/present.png"), 0),
            AtlasItem("missing", Path("Icons/missing.png"), 4),
        ),
        output_sizes=(32,),
    )
    return ArtProjectSpec("test-project", atlases=(atlas,))


def test_contract_page_arithmetic_and_suffixes() -> None:
    assert ATLAS_CAPACITY == 64
    assert atlas_page(63) == 0
    assert local_atlas_index(63) == 63
    assert atlas_page(64) == 1
    assert local_atlas_index(69) == 5
    assert paged_name("CUSTOM_ATLAS", 0) == "CUSTOM_ATLAS"
    assert paged_name("CUSTOM_ATLAS", 1) == "CUSTOM_ATLAS_2"
    assert placement_for(69, "CUSTOM_ATLAS").row == 0
    assert placement_for(69, "CUSTOM_ATLAS").column == 5


def test_role_profiles_lock_civ5_art_contracts() -> None:
    portrait = art_role_profile(ArtProcessingRole.CIVILIZATION_ICON)
    assert portrait.working_size == (1024, 1024)
    assert portrait.render_profile is RenderProfile.PORTRAIT_CIRCLE
    assert portrait.dds_profile is PORTRAIT_ATLAS
    assert portrait.ensure_coverage

    flag = art_role_profile(ArtProcessingRole.UNIT_FLAG)
    assert flag.binary_black_white
    assert flag.render_profile is RenderProfile.UNIT_FLAG
    assert flag.working_size == (1024, 1024)

    strategic = art_role_profile(ArtProcessingRole.STRATEGIC_VIEW)
    assert strategic.output_size == (64, 64)
    assert strategic.dds_profile is STRATEGIC_VIEW
    assert not strategic.atlas_role


def test_portrait_validator_rejects_baked_gold_ring_without_false_positive(
    tmp_path: Path,
) -> None:
    framed_path = tmp_path / "framed.png"
    framed = Image.new("RGBA", (512, 512), (35, 70, 120, 255))
    ImageDraw.Draw(framed).ellipse(
        (48, 48, 463, 463), outline=(230, 170, 35, 255), width=18
    )
    framed.save(framed_path)
    validation = validate_portrait_source(
        framed_path,
        item_key="framed",
        category="portraits",
        required=True,
        release_blocking=True,
    )
    assert not validation.valid
    assert "BAKED_GOLD_FRAME_DETECTED" in {
        issue.code for issue in validation.blockers
    }

    gold_background_path = tmp_path / "gold-background.png"
    Image.new("RGBA", (512, 512), (220, 155, 30, 255)).save(gold_background_path)
    gold_background = validate_portrait_source(
        gold_background_path,
        item_key="gold-background",
        category="portraits",
        required=True,
        release_blocking=True,
    )
    assert gold_background.valid
    assert "BAKED_GOLD_FRAME_DETECTED" not in {
        issue.code for issue in gold_background.issues
    }


def test_full_frame_validator_rejects_transparency_and_wrong_dimensions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "screen.png"
    Image.new("RGBA", (100, 80), (20, 30, 40, 128)).save(source)
    validation = validate_full_frame_source(
        source,
        item_key="screen",
        category="screen",
        required=True,
        release_blocking=True,
        expected_size=(120, 90),
    )
    assert not validation.valid
    assert {issue.code for issue in validation.blockers} == {
        "FULL_FRAME_DIMENSIONS",
        "FULL_FRAME_HAS_TRANSPARENCY",
    }


def test_duplicate_slots_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate atlas indexes"):
        AtlasSpec(
            category="Icons",
            atlas_name="TEST_ATLAS",
            filename_stem="TestAtlas",
            items=(
                AtlasItem("one", Path("one.png"), 0),
                AtlasItem("two", Path("two.png"), 0),
            ),
        )


def test_alpha_atlas_accepts_the_firaxis_size_ladder() -> None:
    spec = AtlasSpec(
        category="CivilizationAlphaIcons",
        atlas_name="CUSTOM_ALPHA_ATLAS",
        filename_stem="CustomAlphaAtlas",
        items=(AtlasItem("alpha", Path("Alpha/alpha.png"), 0),),
        render_profile=RenderProfile.ALPHA_GLYPH,
        dds_profile=ALPHA_ICON_ATLAS,
        output_sizes=ALPHA_ICON_SIZES,
    )
    assert spec.output_sizes == (128, 80, 64, 48, 32, 24, 16)
    assert spec.dds_profile.format.value == "DXT5"
    factory_spec = alpha_icon_atlas_spec(
        category="CivilizationAlphaIcons",
        atlas_name="FACTORY_ALPHA_ATLAS",
        filename_stem="FactoryAlphaAtlas",
        items=(AtlasItem("alpha", Path("Alpha/alpha.png"), 0),),
    )
    assert 16 in factory_spec.output_sizes
    assert factory_spec.render_profile is RenderProfile.ALPHA_GLYPH
    with pytest.raises(ValueError, match="non-standard Civ V atlas sizes"):
        AtlasSpec(
            category="Portraits",
            atlas_name="PORTRAIT_ATLAS",
            filename_stem="PortraitAtlas",
            items=(AtlasItem("portrait", Path("portrait.png"), 0),),
            output_sizes=(48,),
        )


def test_alpha_glyph_removes_black_and_uses_portrait_safe_fit(tmp_path: Path) -> None:
    source = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
    ImageDraw.Draw(source).rectangle((96, 64, 160, 192), fill=(255, 255, 255, 255))
    rendered = render_alpha_glyph(source, 128)
    alpha = rendered.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    assert bbox is not None
    assert bbox[2] - bbox[0] <= 86
    assert bbox[3] - bbox[1] <= 86
    assert rendered.getpixel((0, 0)) == (0, 0, 0, 0)
    center = rendered.getpixel((64, 64))
    assert center[:3] == (255, 255, 255)
    assert center[3] > 245
    assert validate_rendered_tile(rendered, RenderProfile.ALPHA_GLYPH) == ()

    input_root = tmp_path / "input"
    source_path = input_root / "Alpha" / "emblem.png"
    source_path.parent.mkdir(parents=True)
    source.save(source_path)
    project = ArtProjectSpec(
        "alpha-glyph",
        atlases=(
            alpha_icon_atlas_spec(
                category="CivilizationAlphaIcons",
                atlas_name="CUSTOM_ALPHA_ATLAS",
                filename_stem="CustomAlphaAtlas",
                items=(AtlasItem("emblem", Path("Alpha/emblem.png"), 0),),
                output_sizes=(32,),
            ),
        ),
    )
    result = strict_release(
        project, input_root=input_root, staging_root=tmp_path / "stage"
    )
    assert result.status is PipelineStatus.WARN  # 256px source; 1024px preferred.
    atlas_path = tmp_path / "stage" / result.output_manifest[0].output_path
    with Image.open(atlas_path) as opened:
        tile = opened.convert("RGBA").crop((0, 0, 32, 32))
    assert tile.getpixel((0, 0))[3] == 0
    tile_center = tile.getpixel((16, 16))
    assert min(tile_center[:3]) > 240
    assert tile_center[3] > 240


def test_portrait_geometry_has_no_generated_ring() -> None:
    source = Image.new("RGBA", (400, 250), (230, 20, 30, 255))
    rendered = render_portrait_circle(source, 256)
    alpha = rendered.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    assert bbox is not None
    assert bbox[2] - bbox[0] <= 172
    assert bbox[3] - bbox[1] <= 172
    assert max(alpha.getpixel(point) for point in ((0, 0), (255, 0), (0, 255), (255, 255))) == 0
    assert rendered.getpixel((128, 128))[:3] == (230, 20, 30)
    pixels = (
        rendered.get_flattened_data()
        if hasattr(rendered, "get_flattened_data")
        else rendered.getdata()
    )
    assert not any(
        red > 200 and 140 < green < 230 and blue < 80
        for red, green, blue, alpha_value in pixels
        if alpha_value
    )
    assert validate_rendered_tile(rendered, RenderProfile.PORTRAIT_CIRCLE) == ()


def test_transparent_rgb_is_scrubbed() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata(((255, 10, 20, 0), (5, 6, 7, 1)))
    cleaned = scrub_transparent_rgb(image)
    assert cleaned.getpixel((0, 0)) == (0, 0, 0, 0)
    assert cleaned.getpixel((1, 0)) == (5, 6, 7, 1)


@pytest.mark.parametrize(
    ("profile", "expected_fourcc", "mode"),
    (
        (PORTRAIT_ATLAS, "DXT5", "RGBA"),
        (STATIC_SCREEN_OPAQUE, "DXT1", "RGBA"),
    ),
)
def test_compressed_dds_headers_are_legacy_one_surface(
    tmp_path: Path, profile, expected_fourcc: str, mode: str
) -> None:
    path = tmp_path / f"{profile.name}.dds"
    image = Image.new(mode, (64, 32), (20, 30, 40, 128))
    result = write_dds(image, path, profile)
    assert result.encoder == "pillow-bcn"
    header = read_dds_header(path)
    assert (header.width, header.height) == (64, 32)
    assert header.fourcc == expected_fourcc
    assert header.mipmap_count == 1
    assert header.caps2 == 0
    assert header.bits_per_pixel == 0
    assert header.flags == 0x000A1007
    assert header.depth == 1
    assert header.pitch_or_linear_size == path.stat().st_size - 128
    assert validate_dds(path, profile, (64, 32)) == header
    with Image.open(path) as opened:
        assert opened.size == (64, 32)


def test_alpha_required_profile_rejects_opaque_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires meaningful transparency"):
        write_dds(
            Image.new("RGBA", (32, 32), (255, 255, 255, 255)),
            tmp_path / "alpha.dds",
            ALPHA_ICON_ATLAS,
        )


def test_strategic_view_is_64px_bgra_one_surface(tmp_path: Path) -> None:
    path = tmp_path / "strategic.dds"
    write_dds(Image.new("RGBA", (64, 64), (10, 20, 30, 120)), path, STRATEGIC_VIEW)
    header = read_dds_header(path)
    assert (header.width, header.height) == (64, 64)
    assert header.fourcc == ""
    assert header.bits_per_pixel == 32
    assert header.alpha_mask == 0xFF000000
    assert header.mipmap_count == 1
    with Image.open(path) as opened:
        assert opened.convert("RGBA").getpixel((0, 0)) == (10, 20, 30, 120)


def test_unit_flag_validation_and_final_fit(tmp_path: Path) -> None:
    source = tmp_path / "flag.png"
    save_flag(source)
    validation = validate_unit_flag_source(
        source,
        item_key="flag",
        category="UnitFlags",
        required=True,
        release_blocking=True,
    )
    assert validation.valid
    assert validation.status == "WARN"  # 64px is accepted but 1024px is preferred.
    with Image.open(source) as opened:
        rendered = render_unit_flag(opened, 32)
    bbox = rendered.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    assert bbox is not None
    assert bbox[2] - bbox[0] <= 25
    assert bbox[3] - bbox[1] <= 25
    pixels = (
        rendered.get_flattened_data()
        if hasattr(rendered, "get_flattened_data")
        else rendered.getdata()
    )
    visible = [pixel for pixel in pixels if pixel[3] > 24]
    assert visible
    assert sum(1 for red, green, blue, _ in visible if min(red, green, blue) < 235) / len(visible) <= 0.02


def test_colored_unit_flag_is_a_blocker(tmp_path: Path) -> None:
    source = tmp_path / "bad.png"
    save_flag(source, color=(210, 30, 30, 255))
    validation = validate_unit_flag_source(
        source,
        item_key="bad-flag",
        category="UnitFlags",
        required=True,
        release_blocking=True,
    )
    assert not validation.valid
    assert "UNIT_FLAG_INTERMEDIATE_COLORS" in {issue.code for issue in validation.blockers}


def test_invalid_optional_flag_is_not_built_or_release_blocking(tmp_path: Path) -> None:
    source = tmp_path / "bad-optional.png"
    save_flag(source, color=(210, 30, 30, 255))
    validation = validate_unit_flag_source(
        source,
        item_key="bad-optional",
        category="UnitFlags",
        required=False,
        release_blocking=True,
    )
    assert not validation.valid
    assert validation.status == "INVALID"
    assert not validation.blockers


def test_unit_flag_spec_locks_32px_dxt5() -> None:
    spec = unit_flag_atlas_spec(
        category="UnitFlags",
        atlas_name="CUSTOM_FLAG_ATLAS",
        filename_stem="CustomFlagAtlas",
        items=(AtlasItem("flag", Path("Flags/flag.png"), 0),),
    )
    assert spec.output_sizes == (32,)
    assert spec.dds_profile.format.value == "DXT5"
    assert spec.render_profile is RenderProfile.UNIT_FLAG


def test_stable_missing_slot_does_not_shift_second_page(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    save_solid(input_root / "later.png")
    spec = AtlasSpec(
        category="Icons",
        atlas_name="CUSTOM_ATLAS",
        filename_stem="CustomAtlas",
        items=(
            AtlasItem("missing", Path("missing.png"), 0),
            AtlasItem("later", Path("later.png"), 64),
        ),
        output_sizes=(32,),
    )
    project = ArtProjectSpec("stable-pages", atlases=(spec,))
    result = build_available(
        project, input_root=input_root, staging_root=tmp_path / "stage"
    )
    assert result.status is PipelineStatus.WARN
    outputs = {entry.atlas_name: entry for entry in result.output_manifest}
    assert set(outputs) == {"CUSTOM_ATLAS", "CUSTOM_ATLAS_2"}
    assert outputs["CUSTOM_ATLAS"].built_item_keys == ()
    assert outputs["CUSTOM_ATLAS_2"].built_item_keys == ("later",)
    later = next(entry for entry in result.source_manifest if entry.item_key == "later")
    assert (later.atlas_page, later.global_index, later.local_index, later.row, later.column) == (
        1,
        64,
        0,
        0,
        0,
    )


def test_modes_report_missing_art_without_throwing(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    project = tiny_project(input_root)
    draft_result = run_art_pipeline(
        project,
        input_root=input_root,
        staging_root=tmp_path / "stage",
        mode=PipelineMode.DRAFT,
    )
    assert draft_result.status is PipelineStatus.WARN
    assert draft_result.succeeded
    assert not draft_result.build_performed
    assert {issue.code for issue in draft_result.blockers} == {"MISSING_REQUIRED_ART"}
    present = next(entry for entry in draft_result.source_manifest if entry.item_key == "present")
    assert present.source_path == "Icons/present.png"

    validate_result = validate(
        project, input_root=input_root, staging_root=tmp_path / "stage"
    )
    assert validate_result.status is PipelineStatus.FAIL
    assert not validate_result.succeeded

    build_result = build_available(
        project, input_root=input_root, staging_root=tmp_path / "stage"
    )
    assert build_result.status is PipelineStatus.WARN
    assert build_result.output_manifest
    output_manifest = build_result.report_paths["output_json"]
    before = output_manifest.read_bytes()

    validate(project, input_root=input_root, staging_root=tmp_path / "stage")
    assert output_manifest.read_bytes() == before
    assert json.loads(output_manifest.read_text(encoding="utf-8"))["kind"] == "output-manifest"

    strict_result = strict_release(
        project, input_root=input_root, staging_root=tmp_path / "stage"
    )
    assert strict_result.status is PipelineStatus.FAIL


def test_strict_release_builds_complete_individual_profiles(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    save_solid(input_root / "sv.png", size=(1024, 1024))
    save_solid(input_root / "screen.png", size=(1024, 768))
    project = ArtProjectSpec(
        "individuals",
        individuals=(
            IndividualArtSpec(
                key="strategic",
                category="StrategicView",
                source_path=Path("sv.png"),
                output_path=Path("Art/StrategicView/SV_Custom.dds"),
                output_size=(64, 64),
                dds_profile=STRATEGIC_VIEW,
                requires_square_source=True,
                preferred_source_size=(1024, 1024),
                stretch_to_output=False,
            ),
            IndividualArtSpec(
                key="dawn",
                category="DawnOfMan",
                source_path=Path("screen.png"),
                output_path=Path("Art/Screens/CustomDawn.dds"),
                output_size=(1024, 768),
                dds_profile=STATIC_SCREEN_OPAQUE,
                preferred_source_size=(1024, 768),
            ),
        ),
    )
    result = strict_release(
        project, input_root=input_root, staging_root=tmp_path / "stage"
    )
    assert result.status is PipelineStatus.PASS
    assert len(result.output_manifest) == 2
    formats = {entry.item_key: entry.dds_format for entry in result.output_manifest}
    assert formats == {"strategic": "A8R8G8B8", "dawn": "DXT1"}


def test_project_paths_cannot_escape_roots() -> None:
    with pytest.raises(ValueError, match="project-relative"):
        IndividualArtSpec(
            key="escape",
            category="Screen",
            source_path=Path("../secret.png"),
            output_path=Path("screen.dds"),
            output_size=(16, 16),
            dds_profile=STATIC_SCREEN_OPAQUE,
        )
