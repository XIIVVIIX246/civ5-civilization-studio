# Civ V Civilization Studio project rules

This repository contains a preserved legacy PNG-to-DDS tool at the root and the
new application under `src/civ5studio`. Treat root legacy scripts and `Old
scripts/` as reference code unless a task explicitly targets them.

## Product scope

- Target Sid Meier's Civilization V: Brave New World / Expansion2.
- Build a Windows desktop application for creating complete custom
  civilizations without requiring users to edit JSON, SQL, XML, Lua, or DDS
  files by hand.
- Generated projects must remain portable and editable outside the GUI.
- Static validation is not an in-game test. Never claim runtime success unless
  Civ V was launched and the exact generated mod was tested.

## Art authority

The current Strategic Missile Project implementation is the art authority:

- Prefer square 1024x1024 source PNGs.
- Use 8x8 atlas pages and output sizes 256, 128, 80, 64, 45, and 32.
- Fit portrait artwork to a 172/256 diameter with an antialiased circular alpha
  mask.
- Never bake a gold ring, border, medallion, or UI frame into exported art.
- Preview overlays may show the expected Firaxis frame but must never alter
  exported pixels.
- Portrait, alpha, and unit-flag atlases use legacy DX9 DXT5 with one surface
  and no mip chain.
- Strategic View uses 64x64 A8R8G8B8 with one surface.
- Unit flags are white tactical silhouettes on black source backgrounds and
  are fitted to 78 percent of a 32px cell.

## Engineering rules

- Put new code under `src/civ5studio`; do not expand the root monolith.
- Keep UI widgets separate from domain models, generators, art processing, and
  filesystem writes.
- All build output first goes to a project-owned staging directory.
- Never recursively delete an arbitrary or user-selected directory. Rebuilds
  may replace only a validated project-owned generated directory, using a
  backup or atomic swap.
- Verify every generated Civ V table, column, type reference, atlas index, and
  `.modinfo` entry against bundled BNW reference data or tested templates.
- Unsupported mechanics must be reported explicitly, never silently omitted.
- Use `apply_patch` for source edits and preserve unrelated user changes.

## Required validation

- Run the unit and integration test suite for changed components.
- Parse generated XML and `.modinfo` files.
- Validate generated SQL against the bundled reference catalog and an isolated
  SQLite schema where supported.
- Validate DDS magic, dimensions, FourCC, alpha contract, atlas coordinates,
  and mip count.
- Run `git diff --check` and report the exact Git status at handoff.

