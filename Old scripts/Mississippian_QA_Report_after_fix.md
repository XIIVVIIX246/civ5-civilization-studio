# Mississippian Civ V Asset QA Report

Generated: 2026-06-05T16:35:45.935428+00:00

## Profile Summary
- Alpha icon profile: civ5_alpha_glyph_black_to_transparent; black-background cleanup: yes
- civ `Civilization`: profile civ5_circular_icon, safe_subject_scale 0.82, master [1024, 1024], circular mask baked: preview-only
- leader `Leader`: profile civ5_circular_icon, safe_subject_scale 0.8, master [1024, 1024], circular mask baked: preview-only
- unit `ChunkeyWarrior`: profile civ5_circular_icon, safe_subject_scale 0.84, master [1024, 1024], circular mask baked: preview-only
- unit `RiverRaider`: profile civ5_circular_icon, safe_subject_scale 0.84, master [1024, 1024], circular mask baked: preview-only
- building `PlatformMound`: profile civ5_circular_icon, safe_subject_scale 0.84, master [1024, 1024], circular mask baked: preview-only
- building `CahokiaPlaza`: profile civ5_circular_icon, safe_subject_scale 0.84, master [1024, 1024], circular mask baked: preview-only
- support `MoundsOfTheSun`: profile civ5_circular_icon, safe_subject_scale 0.86, master [1024, 1024], circular mask baked: preview-only
- support `ChunkeyGuard`: profile civ5_circular_icon, safe_subject_scale 0.86, master [1024, 1024], circular mask baked: preview-only
- support `RiverRaid`: profile civ5_circular_icon, safe_subject_scale 0.86, master [1024, 1024], circular mask baked: preview-only
- unit_flag `ChunkeyWarrior`: profile civ5_unit_flag_black_to_transparent, black-background cleanup: yes, final [32, 32]
- unit_flag `RiverRaider`: profile civ5_unit_flag_black_to_transparent, black-background cleanup: yes, final [32, 32]
- Per-asset previews written: yes

## Warnings by severity
### FATAL
- None
### STRONG
- None
### NORMAL
- unit:ChunkeyWarrior: #TYPE_NAME UNIT_MISSISSIPPIAN_CHUNKEY_WARRIOR not found in existing usage; will assign a free index.
- unit:RiverRaider: #TYPE_NAME UNIT_MISSISSIPPIAN_RIVER_RAIDER not found in existing usage; will assign a free index.
- building:PlatformMound: #TYPE_NAME BUILDING_MISSISSIPPIAN_PLATFORM_MOUND not found in existing usage; will assign a free index.
- building:CahokiaPlaza: #TYPE_NAME BUILDING_MISSISSIPPIAN_CAHOKIA_PLAZA not found in existing usage; will assign a free index.
- support:MoundsOfTheSun: #TYPE_NAME PROMOTION_MISSISSIPPIAN_MOUNDS_OF_THE_SUN not found in existing usage; will assign a free index.
- support:ChunkeyGuard: #TYPE_NAME PROMOTION_MISSISSIPPIAN_CHUNKEY_GUARD not found in existing usage; will assign a free index.
- support:RiverRaid: #TYPE_NAME PROMOTION_MISSISSIPPIAN_RIVER_RAID not found in existing usage; will assign a free index.
- civ:Mississippian_CivilizationIcon.png: source is fully opaque; transparent safe padding was added but background may remain visible inside the circle.
- civ:Civilization: medallion QA detected possible subject clipping by the circular mask.
- leader:GreatSun_LeaderIcon.png: removed corner watermark/sparkle residue after mat cleanup (37037 alpha-px).
- leader:GreatSun_LeaderIcon.png: removed edge-connected white/gray source mat before icon fitting (21.4% of pixels).
- leader:Leader: medallion QA detected possible subject clipping by the circular mask.
- leader:Leader: subject fills too much of the medallion circle; consider lowering medallion_fill_percent or adding source padding.
- unit:ChunkeyWarrior_Icon.png: removed corner watermark/sparkle residue after mat cleanup (36893 alpha-px).
- unit:ChunkeyWarrior_Icon.png: removed edge-connected white/gray source mat before icon fitting (21.4% of pixels).
- unit:ChunkeyWarrior: medallion QA detected possible subject clipping by the circular mask.
- unit:ChunkeyWarrior: subject fills too much of the medallion circle; consider lowering medallion_fill_percent or adding source padding.
- unit:RiverRaider_Icon.png: source is fully opaque; transparent safe padding was added but background may remain visible inside the circle.
- unit:RiverRaider: medallion QA detected possible subject clipping by the circular mask.
- unit:RiverRaider: subject fills too much of the medallion circle; consider lowering medallion_fill_percent or adding source padding.
- building:PlatformMound_Icon.png: source is fully opaque; transparent safe padding was added but background may remain visible inside the circle.
- building:PlatformMound: medallion QA detected possible subject clipping by the circular mask.
- building:PlatformMound: subject fills too much of the medallion circle; consider lowering medallion_fill_percent or adding source padding.
- building:CahokiaPlaza_Icon.png: removed corner watermark/sparkle residue after mat cleanup (33790 alpha-px).
- building:CahokiaPlaza_Icon.png: removed edge-connected white/gray source mat before icon fitting (23.8% of pixels).
- building:CahokiaPlaza: medallion QA detected possible subject clipping by the circular mask.
- building:CahokiaPlaza: subject fills too much of the medallion circle; consider lowering medallion_fill_percent or adding source padding.
- support:MoundsOfTheSun: medallion QA detected possible subject clipping by the circular mask.
- support:ChunkeyGuard_PromotionIcon.png: removed corner watermark/sparkle residue after mat cleanup (655 alpha-px).
- support:ChunkeyGuard_PromotionIcon.png: removed edge-connected white/gray source mat before icon fitting (55.6% of pixels).
- support:ChunkeyGuard: medallion QA detected possible subject clipping by the circular mask.
- support:RiverRaid_PromotionIcon.png: removed corner watermark/sparkle residue after mat cleanup (1325 alpha-px).
- support:RiverRaid_PromotionIcon.png: removed edge-connected white/gray source mat before icon fitting (34.5% of pixels).
- support:RiverRaid: medallion QA detected possible subject clipping by the circular mask.
- unit_flag:ChunkeyWarrior: high edge/detail density at 32px; painted source suspected; use a hand-drawn simple white silhouette/glyph.
- unit_flag:RiverRaider: high edge/detail density at 32px; painted source suspected; use a hand-drawn simple white silhouette/glyph.
### INFO
- INFO: Medallion baking enabled for 9 normal icon atlas cell(s); alpha icons, unit flags, and large images are unchanged.

## DDS Validation
- `Mississippian_IconAtlas_256.dds`: {'width': 1024, 'height': 1024, 'pitch': 4096, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_IconAtlas_128.dds`: {'width': 512, 'height': 512, 'pitch': 2048, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_IconAtlas_80.dds`: {'width': 320, 'height': 320, 'pitch': 1280, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_IconAtlas_64.dds`: {'width': 256, 'height': 256, 'pitch': 1024, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_IconAtlas_45.dds`: {'width': 180, 'height': 180, 'pitch': 720, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_IconAtlas_32.dds`: {'width': 128, 'height': 128, 'pitch': 512, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_128.dds`: {'width': 128, 'height': 128, 'pitch': 512, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_80.dds`: {'width': 80, 'height': 80, 'pitch': 320, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_64.dds`: {'width': 64, 'height': 64, 'pitch': 256, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_48.dds`: {'width': 48, 'height': 48, 'pitch': 192, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_45.dds`: {'width': 45, 'height': 45, 'pitch': 180, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_32.dds`: {'width': 32, 'height': 32, 'pitch': 128, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_Alpha_24.dds`: {'width': 24, 'height': 24, 'pitch': 96, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Mississippian_UnitFlagAtlas_32.dds`: {'width': 256, 'height': 256, 'pitch': 1024, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `DawnOfMan_Mississippian.dds`: {'width': 1024, 'height': 768, 'pitch': 4096, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `Map_Mississippian512.dds`: {'width': 512, 'height': 512, 'pitch': 2048, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}
- `GreatSun_Scene.dds`: {'width': 1024, 'height': 768, 'pitch': 4096, 'mipmaps': 1, 'pf_flags': 65, 'fourcc': 0, 'bpp': 32, 'alpha_mask': 4278190080, 'exists': True}

## Alpha / Team Icon Metrics
- Alpha/team icon: `{'alpha_min': 0, 'alpha_max': 255, 'opaque_pct': 19.34, 'transparent_pct': 79.92, 'safe_margin_pct': 10.94, 'likely_full_bleed': False}`
- Meaningful white-on-transparent: yes

## Medallion Baking
- Enabled for DDS output: yes
- Preview-only: no
- Radius percent: 0.47
- Fill percent: 0.92
- Rim enabled: no
- Rim style: none
- Background: transparent
- Scope: normal icon atlas cells only; alpha/team icons, unit flags, maps, Dawn of Man, and leader scenes are not medallion-baked.

## Normal Icon Metrics
- civ `Civilization`: opaque 67.29%, transparent 32.71%, safe margin 8.98%, likely full-bleed: False
  - Medallion: clipped=True; fill-ratio=0.914; fills-too-much=False; 32px-unreadable-warning=False; 32px-visible-coverage=67.97%
- leader `Leader`: opaque 49.46%, transparent 50.17%, safe margin 9.96%, likely full-bleed: False
  - Medallion: clipped=True; fill-ratio=0.923; fills-too-much=True; 32px-unreadable-warning=False; 32px-visible-coverage=60.64%
- unit `ChunkeyWarrior`: opaque 54.54%, transparent 45.07%, safe margin 8.01%, likely full-bleed: False
  - Medallion: clipped=True; fill-ratio=0.923; fills-too-much=True; 32px-unreadable-warning=False; 32px-visible-coverage=60.94%
- unit `RiverRaider`: opaque 70.53%, transparent 29.47%, safe margin 8.01%, likely full-bleed: False
  - Medallion: clipped=True; fill-ratio=0.923; fills-too-much=True; 32px-unreadable-warning=False; 32px-visible-coverage=67.97%
- building `PlatformMound`: opaque 70.53%, transparent 29.47%, safe margin 8.01%, likely full-bleed: False
  - Medallion: clipped=True; fill-ratio=0.923; fills-too-much=True; 32px-unreadable-warning=False; 32px-visible-coverage=67.97%
- building `CahokiaPlaza`: opaque 52.79%, transparent 46.66%, safe margin 8.01%, likely full-bleed: False
  - Medallion: clipped=True; fill-ratio=0.923; fills-too-much=True; 32px-unreadable-warning=False; 32px-visible-coverage=59.57%
- support `MoundsOfTheSun`: opaque 56.62%, transparent 42.9%, safe margin 6.93%, likely full-bleed: True
  - Medallion: clipped=True; fill-ratio=0.918; fills-too-much=False; 32px-unreadable-warning=False; 32px-visible-coverage=60.45%
- support `ChunkeyGuard`: opaque 43.75%, transparent 55.67%, safe margin 6.93%, likely full-bleed: True
  - Medallion: clipped=True; fill-ratio=0.918; fills-too-much=False; 32px-unreadable-warning=False; 32px-visible-coverage=48.73%
- support `RiverRaid`: opaque 56.87%, transparent 42.71%, safe margin 6.93%, likely full-bleed: True
  - Medallion: clipped=True; fill-ratio=0.918; fills-too-much=False; 32px-unreadable-warning=False; 32px-visible-coverage=60.94%

## Unit Flag Metrics
- `ChunkeyWarrior` [packed (black-bg cleanup applied)]: profile civ5_unit_flag_black_to_transparent; raw source was opaque white-on-black and was converted to white-on-transparent (pre-cleanup painted-heuristic no longer applies).
- `RiverRaider` [packed (black-bg cleanup applied)]: profile civ5_unit_flag_black_to_transparent; raw source was opaque white-on-black and was converted to white-on-transparent (pre-cleanup painted-heuristic no longer applies).

## Mod Integration Plan
- No --mod-data-dir supplied; nothing to integrate.

## Validation Checklist
- Confirm the mod SQL/XML points at the atlas name and PortraitIndex values in the manifest.
- Confirm alpha/team icons preview as a white glyph on transparency, not a square/checkerboard.
- Confirm unit flags are readable white silhouettes at 32px.
- Clear the Civ V cache before retesting in-game.