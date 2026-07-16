# Civ V Icon Pipeline — Changes

## 1. Locked to verified vanilla proportions
The subject occupancy for every role now matches your measured vanilla values and
will not be raised without re-measuring stock atlases:

| Role | Occupancy | Source of truth |
|---|---|---|
| Standard icons — units, buildings, civ emblems | **0.82** | ~204–210px in a 256px canvas (0.80–0.82) |
| Leader portraits | **0.85** | composed tighter, features centered |
| Alpha / team icons | **0.78** | clipping-sensitive under strategic-view scaling |
| Unit flags | **0.75** | white silhouette inside a 24×24 box in a 32×32 cell |

Applied in code:
- `SAFE_OCCUPANCY` 0.94 → **0.82**
- `ROLE_SAFE_SUBJECT_SCALE`: civ/unit/building/support/promotion/dummy/trait → **0.82**, leader → **0.85**, alpha → **0.78**, unit_flag → **0.75**
- `civ5_unit_flag_black_to_transparent` profile scale 0.90 → **0.75**
- Unit-flag non-glyph path now also enforces **0.75** (previously fell back to the standard ratio)
- Medallion defaults realigned to vanilla: `fill_percent` 0.94 → **0.82**, `radius_percent` 0.495 → **0.46**
- Role-aware occupancy is now applied for **both** legacy and profiled configs (legacy leaders correctly use 0.85, not 0.82)

## 2. Always fills the circle — square OR circular input, never oversized
A single fixed ratio can't satisfy both goals for every shape: a disc scaled to
0.82 leaves a transparent ring, and a full-bleed square scaled to 0.82 leaves gaps
at the circle's edges. So fitting is now **content-aware** (`fit_icon_master`):

- **COVER** — used for full-bleed squares, solid square emblems, and discs/circular
  art. The shorter dimension is scaled to the full circle diameter, centered, and
  the overflow is cropped (the game's circular mask trims the corners). Result: the
  circle is completely filled, no blank ring, no gaps.
- **CONTAIN** — used for discrete glyph art (swords, stars, silhouettes). The subject's
  longest side is scaled to the vanilla occupancy (0.82/0.85) and centered. The
  surrounding transparency is the intended vanilla breathing room, and the glyph is
  **never enlarged past its vanilla size**.

Auto-classification: COVER when the art is fully opaque, full-bleed, or occupies a
roughly **square** footprint *and* is solid (disc/medallion/tile); otherwise CONTAIN.
The square-footprint gate is what prevents a thin glyph (which densely fills its own
tight bounding box) from being mistaken for a fillable shape and blown up.

Alpha/team icons and unit flags deliberately stay strictly CONTAIN at 0.78 / 0.75
(they are the most clipping-sensitive), so the fitter does not touch them.

### New option
`--icon-fit-policy {auto,contain,cover}` (default **auto**)
- `auto` — cover full-bleed/disc art, contain glyph art (recommended)
- `contain` — strict vanilla occupancy for everything (may leave a ring around discs)
- `cover` — always fill the circle and crop overflow

The QA report now records the chosen mode per icon, e.g.
`INFO: civ:emblem.png: fit=cover (subject covers ~100% of the circle).`

## Verified end-to-end
Measured from a freshly generated 256 atlas:
- disc emblem → cover, **99.7%** of circle filled, 0 stray pixels
- opaque square portrait → cover, **100%** filled (corners masked by the game)
- thin sword glyph → contain, spans **81.2%** of the cell — sized to vanilla, not oversized
- solid building emblem → cover, **100%** filled

DDS output unchanged and Civ V–compatible: uncompressed 32-bit BGRA, legacy DX9
header, single mip.
