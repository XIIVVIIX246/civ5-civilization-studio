# Nabataea simple Civ V DDS manifest

Use this with `simple_civ5_dds_builder_v2.py`.

Expected local input folder:

```text
C:/Repos/PNGtoDDSConverter/Input/Nabataea
```

Run from any folder:

```powershell
python .\simple_civ5_dds_builder_v2.py --config .\Nabataea_simple_civ5_dds_manifest.json
```

Optional direct copy into the mod art folder:

```powershell
python .\simple_civ5_dds_builder_v2.py --config .\Nabataea_simple_civ5_dds_manifest.json --copy-to-mod
```

Outputs are named to match the existing Nabataea mod art filenames:

```text
NabataeaIconAtlas256/128/80/64/45/32.dds
NabataeaAlpha128/80/64/48/45/32/24.dds
NabataeaUnitFlags32.dds
Map_Nabataea512.dds
DawnOfMan_Nabataea.dds
```

Profile choices:
- Most already-ringed circular icons use `prebuilt_circle`.
- `CamelSkirmisher_Icon.png` and `NoHorses_PromotionIcon.png` use `raw_square_medallion` because they are transparent square/cutout art, not finished circular medallions.
- Alpha and unit flags use `source_mode: white_on_black` so the black background is converted to transparent.
