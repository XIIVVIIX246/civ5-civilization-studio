# Simple Civ V DDS Builder

This is a smaller deterministic alternative to the large universal pipeline.

## What it does

It builds Civ V-compatible DDS assets using a small set of explicit profiles:

- `prebuilt_circle`
  - for finished circular Civ V-style icons that already include their own ring / medallion
- `raw_square_medallion`
  - for square art that still needs one Civ V-style medallion baked around it
- `alpha_glyph`
  - handled through the `alpha_icon` block as centered transparent glyph output
- `unit_flag`
  - handled through the `unit_flags` block as 32x32 slots packed into one 256x256 atlas
- `map`
  - outputs opaque 512x512 DDS
- `dawn`
  - outputs opaque 1024x768 DDS
- `leader_scene`
  - outputs opaque 1024x768 DDS

## Built-in sizing standards

### Prebuilt circular normal icons
- default: `172 / 256 = 0.671875`
- building icons: `178 / 256 = 0.6953125`
- leader icons: `176 / 256 = 0.6875`

### Unit flags
- visible glyph fit: `22 / 32 = 0.6875`

### Alpha icon
- default visible ratio: `0.70`

### Raw square medallion art
- default subject ratio inside medallion: `0.78`

## Output DDS files

### Normal icon atlases
- 256
- 128
- 80
- 64
- 45
- 32

These are written as 4x4 atlases.

### Alpha icon DDS files
- 128
- 80
- 64
- 48
- 45
- 32
- 24

These are standalone 1x1 DDS images.

### Unit flag atlas
- one `256x256` DDS
- `8x8` grid of `32x32` slots

## DDS format
- uncompressed 32-bit
- BGRA byte order
- A8R8G8B8-compatible masks
- no mipmaps

## Usage

```powershell
python .\simple_civ5_dds_builder.py --config .\simple_civ5_dds_manifest_template.json
```

Optional copy into a mod art folder:

```powershell
python .\simple_civ5_dds_builder.py --config .\simple_civ5_dds_manifest_template.json --copy-to-mod
```

## Notes

- The script intentionally avoids heavy auto-detection and hidden heuristics.
- If an icon is already a finished circular Civ V icon, use `prebuilt_circle`.
- If an icon is still raw square art, use `raw_square_medallion`.
- If a building icon still feels a little small, raise its per-icon `visible_ratio` slightly.
- If a raw square leader portrait is missing the ring in game, make sure it uses `raw_square_medallion`, not `prebuilt_circle`.
