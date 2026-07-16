# Lua Effect Library

Civilization Studio includes a curated library of 200 selectable civilization
effects: 100 designs reimplemented from patterns in the read-only mod archives
and 100 Civilization Studio originals. They are arranged as 20 searchable
categories of 10 effects. A project may select any two distinct current v1
entries. The normal workflow never asks the player to paste or edit Lua.

## What a selection contains

Each catalog entry has a stable effect ID and template version, a plain-English
name and description, a category and trigger, typed default parameters, a
runtime primitive, compatibility metadata, and provenance. Provenance marks an
entry as either reimplemented from a behavior observed in the user's read-only
mod archives or designed as a Studio-original effect. Archived third-party Lua
is not bundled into the application or copied into generated projects.

The project document stores the stable ID, version, instance ID, and any typed
parameter overrides. It does not store executable source. Unknown versions,
invalid parameters, duplicate selections, incompatible pairs, and more than two
selections are validation errors rather than silently changed behavior.

## Generation model

The compiler resolves both selections through the versioned catalog and emits
one namespaced `Lua/CivilizationRuntime.lua` entry point. Effects sharing a Civ
V event share one guarded dispatcher. Generated gameplay logic:

- checks that the player is alive, is a major civilization, and uses the
  generated civilization;
- uses gameplay `GameEvents`, never the active UI player as gameplay authority;
- avoids unsynchronized randomness and arbitrary source interpolation;
- uses only the documented, dependency-free BNW primitive assigned to the
  catalog entry; and
- fails closed when Civ V does not provide an expected player, city, unit,
  plot, team, or type.

Production rewards advance an active unit, building, project, or specialist
order. Rewards triggered by a unit/building completion callback are stored as
overflow to avoid Civ V's normal completion-overflow cap; the same preservation
applies if the city has no concrete order or is running a Process.

Every build includes machine-readable and human-readable Lua-effect manifests
under `Documentation`. They record the selected IDs, template versions,
triggers, parameters, provenance, compatibility decision, generated runtime
file, and still-open runtime gates.

## Compatibility boundary

The initial catalog is deliberately pure BNW and has no Community Patch, DLL,
SaveUtils, or third-party framework requirement. Static generation and tests do
not prove turn processing, AI behavior, save/reload behavior, multiplayer
synchronization, or IGE compatibility.

Until the exact effect pair receives recorded runtime certification, generated
mods with Lua effects conservatively declare:

- `AffectsSavedGames = 1`;
- `SupportsMultiplayer = 0`; and
- `SupportsHotSeat = 0`.

Those derived values are also reported in the generated manifests. They are a
safety boundary, not a claim that multiplayer support can never be added.

## Required in-game test

For each selected effect, test the positive trigger, a non-qualifying player,
the relevant AI path, and any city/unit/plot edge case described in its
manifest. Then save, exit, reload, and trigger it again. For a two-effect build,
also trigger both effects in each order and on the same turn when possible.
Review `Lua.log`, `Database.log`, `xml.log`, and `Modding.log`, then repeat the
smoke test with IGE enabled. Only that exact tested build and pair can receive
runtime certification.

## Adding catalog entries

New entries must reuse or introduce a small typed primitive, declare every
event and parameter, identify pair conflicts, remain deterministic, handle AI
players, and include catalog-count, serialization, validation, generated-Lua,
and manifest tests. A new primitive also needs a focused in-game test plan.
Free-form Lua and unverified external hooks stay outside the compiled library.
