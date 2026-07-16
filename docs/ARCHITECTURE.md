# Architecture

The application uses a strict dependency direction:

```text
PySide6 UI
    -> application services
        -> project/domain model
        -> BNW reference catalog
        -> gameplay/text generators
        -> SMP-standard art and DDS pipeline
        -> advanced-content packagers
        -> validators
        -> atomic packager/installer
```

UI widgets never generate SQL or write build outputs directly. A portable,
versioned project document is the single source of truth. Build services render
that model into a new staging tree, validate the tree, and only then publish a
versioned package or install copy.

The desktop interaction layer consumes and emits the same plain project
dictionaries as its nine backing pages. Guided mode presents six required
steps while Expert controls and Optional extras expose the remaining fields and
pages. Problems navigation, workflow health, live presentation-only previews,
the donor workspace, Extra Gameplay Effects explorer, command palette, and
Artwork page do not own persistence or generation. The controller owns a
bounded complete-dictionary history. Named
snapshots use a digest-verified document at the fixed marked-workspace path
`.civ5studio/history/project-history.json`, published by same-directory atomic
replacement; UI code never chooses or writes that path.

## Project workspace

The first save creates a marked, self-contained workspace. Its project document
uses schema version 5. Selected PNG art is copied into `Assets/Source` under
content-addressed names; custom unit-art packages and audio are copied into
their own project-owned asset trees. The `.civ5studio` control folder contains
the workspace marker, immutable project backups, recovery metadata, and
short-lived mutation locks. Saving and autosaving use atomic file replacement;
the application never recursively deletes a user-selected folder.

Legacy loose `.civ5project.json` files can still be opened. Saving them as a new
project creates the current marked workspace layout.

## Compiler authority

The bundled BNW reference catalog records the verified Expansion2 schema and
donor contracts. A unique unit, building, or improvement starts as a clone of
the selected vanilla donor: all catalogued parent columns and child-table rows
are retained, then the typed project overrides are applied. Unique improvements
also clone the verified donor `Builds` actions and their child rows. The
compiler does not invent unknown columns or silently translate prose into
gameplay code.

The generated capability report records the active compiled recipe registry,
donor-clone surface, project usage, explicitly unimplemented mechanics, static
release gates, and the still-required BNW/IGE runtime gates.

Civilization-level Lua choices are a separate typed catalog surface. Schema v5
stores no more than two stable effect IDs, template versions, instance IDs, and
typed overrides. The catalog contains 200 curated pure-BNW definitions with
explicit triggers, shared primitive IDs, provenance, and pair-compatibility
metadata. Compilation resolves those definitions into one namespaced runtime,
groups effects behind shared guarded event dispatchers, and writes JSON and
Markdown selection manifests. It never evaluates project text or archived
third-party source as executable Lua. Generated compatibility flags remain
conservatively single-player and save-affecting until the exact effect pair has
recorded runtime certification.

Optional external-mod content is typed separately from BNW content. The current
schema retains an explicit Promotions Expansion Pack dependency flag and
per-unit PEP assignments. Its compact bundled catalog records the exact v9
identity, promotion metadata, and source hashes; the source mod itself remains
read-only and is not copied into generated projects.

Advanced content is stored as versioned portable extension data. Diplomacy
responses are compiled from verified response IDs, localization becomes
per-locale text XML, FXSXML/GR2/DDS unit packages are validated and bound to
generated unit-member art definitions, and WAV/MP3 sources receive generated
audio registration rows. These generators record explicit runtime gates; they
do not claim that static structure proves animation or playback behavior.

The existing-mod importer is intentionally conservative. It inventories and
hashes a selected `.modinfo` tree, extracts trustworthy metadata and candidate
Type evidence, and copies all safe source bytes into a new marked workspace.
Arbitrary SQL, XML, Lua, DLL, and art remain immutable inspection evidence
instead of being rewritten as if fully understood. They are never added to the
compiler source inventory. Draft validation warns about this boundary and
strict validation blocks release while `existing_mod_import` is present.
Save As uses the recorded path, size, and SHA-256 manifest to copy the complete
snapshot between marked workspaces through a reverified staging tree; it never
merges with or overwrites an existing `ImportedMod` directory.

The game-test assistant and compatibility scanner are read-only application
services. The former inspects the four useful Civ V logs and can create a
redacted evidence ZIP; the latter inspects installed `.modinfo` relationships,
duplicate IDs, and probable Type collisions. Neither service launches the game
or mutates the Civ V user-data tree. A separate controller action may, only
after user confirmation, ask Windows to open Civ V's Steam URI. The command
center records that handoff as `REQUESTED`; it never promotes it to a runtime
pass. Command-center statuses, timing, and manual runtime notes are transient
UI evidence for the current session; generated validation reports and exported
diagnostics bundles are the durable evidence surfaces. Artifact buttons only
open a path already returned by an application service and never write to it.

## Reuse boundaries

- Root `universal_civ5_pipeline.py`: algorithms and compatibility reference.
- `C:\Repos\PNGtoDDSConverter_V2`: regression-test reference.
- Strategic Missile Project: authoritative image geometry, DDS profiles,
  atlas indexing, and release-gate behavior.
- `civ5_bnw_builder_v10_0_real_png_import_crop_preview.zip`: domain,
  generator, reference-catalog, and workflow reference. Its repeated-atlas art
  implementation and recursive output deletion are intentionally excluded.

## Build states

1. **Draft audit** reports missing or incomplete inputs without failing.
2. **Validate** fails on release-blocking source or project errors.
3. **Build available** generates safe available artifacts and retains blockers.
4. **Strict release** requires complete inputs and validates every generated
   reference, DDS, import, atlas position, and package entry.

## Publication and installation

A strict build writes to a unique project-owned staging tree, parses and checks
the generated content, compares the exact file inventory, records SHA-256
digests, and atomically publishes under `generated`. A rebuild moves only a
matching, marked output into the workspace backup area. The clean player ZIP
has a deterministic inventory and excludes application control metadata.

Installation is available only for the most recent unchanged strict build. The
installer verifies the marker, inventory, and hashes before copying, verifies
the copy again, retains an existing installed version in a timestamped backup,
and atomically publishes the replacement into the selected Civ V `MODS` folder.

The Windows release path is separate from generated Civ V mods. PyInstaller
creates the desktop application in project-owned staging, a hidden `--version`
probe checks the frozen executable, a hidden UI probe constructs the complete
Qt application graph, and deterministic packaging produces a release manifest
and SHA-256 sidecar.

Inno Setup 6 can wrap that exact frozen folder in a per-user Windows installer
with Start menu/uninstall registration, an optional desktop shortcut, and a
non-default-taking JSON **Open with** registration. The installer builder
requires a clean worktree and a frozen manifest matching the current commit.
With a certificate thumbprint it invokes `signtool`, applies a SHA-256
timestamped Authenticode signature, verifies it, and reports
`SIGNED_AND_VERIFIED`; without one it reports `UNSIGNED_NO_CERTIFICATE`. Both
paths produce a separate installer SHA-256 sidecar.

## Runtime boundary

The automated layers can validate project structure, reference contracts,
generated SQL/XML, DDS headers and geometry, modinfo imports, custom unit-art
package structure, audio containers, log evidence, package inventory, and file
hashes. They cannot establish BNW gameplay, animation, audio playback, combined
mod behavior, or IGE compatibility. Those remain explicit manual gates for the
exact generated mod.
