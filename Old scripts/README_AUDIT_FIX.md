# PNG-to-DDS Pipeline Audit Fix

Use `universal_civ5_pipeline_auditfix.py` as the patched script.

The included Mississippian example config uses local absolute paths from the audit environment as an example only; update paths before running on Windows.

Key code changes:

1. White-on-black unit-flag glyph cleanup now uses a higher black threshold and a 0.90 safe fill.
2. It avoids preserving low-luma AI watermark sparkles that were expanding the crop bbox and shrinking flags.
3. Opaque white/gray/black source mats are removed with edge-connected flood fill before normal icon fitting.
4. Corner watermark residue is removed after mat cleanup.
5. Flattened checkerboard sources are detected/handled better, but if checkerboard is baked under semi-transparent artwork, regenerate or manually clean that source PNG.
