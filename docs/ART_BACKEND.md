# Art backend

`civ5studio.art` is the project-neutral implementation of the current Civ V
BNW art contract used by the Strategic Missile Project. It does not contain
SMP type names, atlas names, or paths.

## Public build API

Create an `ArtProjectSpec` from explicit project-relative source paths, then
call `run_art_pipeline` with exactly one `PipelineMode`:

```python
from pathlib import Path

from civ5studio.art import (
    ArtProjectSpec,
    AtlasItem,
    AtlasSpec,
    PipelineMode,
    run_art_pipeline,
)

project = ArtProjectSpec(
    project_id="my-civilization",
    atlases=(
        AtlasSpec(
            category="CivilizationIcons",
            atlas_name="MY_CIV_ICON_ATLAS",
            filename_stem="MyCivIconAtlas",
            items=(AtlasItem("civilization", Path("Icons/civilization.png"), 0),),
        ),
    ),
)

result = run_art_pipeline(
    project,
    input_root=Path("project/ArtSources"),
    staging_root=Path("project/.staging/build-42"),
    mode=PipelineMode.STRICT_RELEASE,
)
```

The application controller owns creation and atomic publication of the staging
directory. The art backend never recursively deletes or swaps directories.

## Modes

- `draft` scans and reports without failing on blockers.
- `validate` scans and returns `FAIL` when release blockers exist.
- `build_available` builds every valid asset, preserves stable blank atlas
  slots, and returns `WARN` while blockers remain.
- `strict_release` builds and returns `FAIL` for source, render, DDS, index, or
  expected-output blockers.

Missing required art is always represented by a structured
`MISSING_REQUIRED_ART` issue; it is not raised as a pipeline exception.

## Locked output contracts

- Normal portrait atlases: 256, 128, 80, 64, 45, and 32 pixels.
- Civilization alpha atlases: 128, 80, 64, 48, 32, 24, and 16 pixels. A 45px
  entry remains accepted for legacy compatibility. Opaque black source
  backgrounds become transparent, and white emblems are centered within the
  172/256 portrait-safe footprint.
- Atlas pages: fixed 8 by 8, with `_2`, `_3`, and later page suffixes.
- Portrait, alpha, and unit-flag atlases: legacy DX9 DXT5, one surface, no
  mipmaps.
- Unit flags: 32px atlas cells; white-on-black source validation; fitted to 78
  percent of the cell.
- Strategic View: individual 64 by 64 A8R8G8B8 DDS.
- Opaque static screens: one-surface DXT1 DDS.

Portraits use the 172/256 circular artwork geometry. No ring, medallion, frame,
or other Firaxis UI decoration is drawn into exported pixels.

## Role-aware preprocessing

`ArtProcessingRole` is the single source of truth for working dimensions,
fit behavior, canvas alpha, source validation, render geometry, and DDS
profile. The application adapter applies these policies non-destructively to
project-owned working PNGs:

- Civilization, leader, unique-unit, and unique-building portraits are
  cover-fitted to 1024px square sources, validated for circular output, and
  checked for a confidently detected continuous baked gold frame.
- Civilization alpha art is binary-normalized and contain-fitted before the
  172/256 alpha-glyph renderer. Unit flags use the separate white-on-black
  validator and fixed 78 percent fit.
- Leader scenes, leader fallbacks, Dawn of Man images, and setup maps are
  cover-fitted onto opaque canvases. Their offsets are clamped so a manual
  transform cannot expose transparent strips that DXT1 would turn into black
  gaps.
- Optional per-unit Strategic View sources are contain-fitted on transparent
  1024px working canvases and exported as 64px A8R8G8B8 DDS files. Opaque
  backgrounds are reported as warnings, while empty or illegible 64px results
  are release blockers.

The preprocessing output is deterministic for a given source, role, and
transform. Original source files are never modified.

## Reports

Reports are written under `Reports/Art` in the supplied staging directory.
Scan-only modes update the source manifest and their own mode-specific run
report, but do not overwrite the last built output manifest.

The source manifest records item key, category, output kind, required state,
explicit source path and hash, validation status/codes, dimensions, stable
atlas page/index/row/column, and expected individual output path.

The output manifest records physical output path and hash, DDS profile/format,
dimensions, mip count, encoder, atlas page/size, and the item keys present on
each page. Both JSON and CSV forms are generated.

All validation in this backend is static. It does not prove that Civilization V
loaded or displayed a generated asset correctly; that requires an in-game BNW
test of the exact packaged mod.
