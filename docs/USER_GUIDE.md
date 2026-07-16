# Civ V Civilization Studio beginner guide

Civilization Studio creates custom civilizations for **Sid Meier's
Civilization V: Brave New World**. You choose the names, leader, gameplay, and
pictures. Studio creates the project files, Civ V data, Lua, icon atlases, DDS
images, and installable mod package.

You do not need to edit JSON, SQL, XML, Lua, or DDS files.

## The short version

A normal custom civilization needs:

1. A mod name and creator name.
2. A civilization name, adjective, colors, cities, and spies.
3. A leader name and personality.
4. One special ability.
5. Normally two unique units, buildings, or improvements.
6. The required PNG artwork.
7. A successful Studio build followed by a real in-game test.

The default **Guided** view walks through those six pages. Promotions Expansion
Pack, Extra Gameplay Effects, and Advanced Tools are optional and do not appear
in the Continue sequence.

## Launch the portable Windows app

1. Extract the entire Civilization Studio ZIP to a normal writable folder.
2. Open the extracted folder.
3. Double-click `Civ5-Civilization-Studio-<version>-windows-x64.exe`.

Keep the executable beside its `_internal` folder. The executable is not a
standalone single file.

The current development build is unsigned. Windows may show a reputation
warning even when the ZIP hash is correct. A published, signed installer should
have a valid Authenticode signature.

## First launch

The Start Here page offers three choices:

- **Create my first civilization** focuses the first required field.
- **Try a worked example** fills a fictional River Kingdom that demonstrates
  safe names, one built-in ability, a leader personality, cities, spies, and two
  named unique items. Replace its content and add your own artwork.
- **Open an existing project** opens a `.civ5project.json` file created by
  Studio.

Press **F1** or choose **Help > How to Make a Civilization** at any time for the
in-app walkthrough and Civ V glossary.

## Guided page 1: Start Here

Enter:

- **Mod name:** the name shown in Civilization V's MODS menu.
- **Created by:** your real name, creator name, or screen name.

Studio automatically creates the technical ID. Guided users do not need to
choose a version, output directory, or save-game flags.

### Choose a playstyle

The **Choose playstyle** menu applies a safe built-in ability and matching
computer-player priorities. It does not overwrite names or artwork.

- **Naval Trader:** trade-range and commercially minded priorities.
- **Tall Cultural Empire:** Wonder production, culture, and growth.
- **Conquest Specialist:** cheaper expansion and aggressive priorities.
- **Diplomatic Federation:** trade resources and diplomatic priorities.

You can change every value afterward. Studio creates a history snapshot before
replacing an existing playstyle.

### Save the project

Choose **File > Save**. On the first save, select a parent folder. Studio creates
one self-contained workspace beneath it:

```text
<Mod Name> Civilization Studio Project/
  <Mod Name>.civ5project.json
  Assets/
  .civ5studio/
```

Keep that folder together when moving the project. Studio copies selected
source artwork and other project assets into the workspace; it never edits the
original files.

## Guided page 2: Your Civilization

### Names

- **Full name:** appears in game setup and introductions. Example: `The River
  Kingdom`.
- **Short name:** appears where the full name would not fit. Example: `River
  Kingdom`.
- **Adjective:** describes the people and their units. Example: `River` in
  `River cities` or `River units`.

Studio suggests the short name while you type the full name. Once you edit the
short name yourself, Studio stops replacing it.

### Colors

Choose an icon color and a background color with strong contrast. The live
preview is available from **Show preview** in the top bar.

### Cities and spies

Enter one name per line. The first city becomes the capital.

- Ten city names are enough to continue; sixteen or more gives the civilization
  better variety.
- Ten spy names are recommended.

### Story

- **Intro-screen message** appears on the Dawn of Man introduction.
- **In-game history** appears in the Civilopedia.

These add presentation and story; they do not change gameplay.

## Guided page 3: Your Leader

Enter the leader's name. A title and biography are optional.

Choose a computer-player personality:

- **Balanced** is the safest starting point.
- **Peaceful builder** favors growth, defense, and Wonders.
- **Scientific planner** emphasizes research and growth.
- **Cultural visionary** emphasizes culture and Wonders.
- **Diplomatic partner** values alliances and trade.
- **Wide expansionist** competes strongly for open land.
- **Aggressive conqueror** builds armies and expands by force.

These are Civ V preferences, not guaranteed hard-coded behavior. Expert
controls expose the individual 1-10 values.

Leader-screen and fallback artwork can be added now or later. Selected source
files stay read-only.

## Guided page 4: Abilities & Uniques

### Special ability

Every civilization needs one civilization-wide trait.

1. Enter the ability name.
2. Write the short setup-screen summary.
3. Choose a **built-in trait bonus**.
4. Choose the bonus amount.
5. Review or rewrite the player-facing explanation Studio suggests.

The built-in list contains only compiler-supported Brave New World fields. A
first project should use one of these choices:

- Great Person rate modifier
- Worker speed modifier
- Plot purchase cost modifier
- Wonder production modifier
- Land trade route range bonus
- Trade route resource modifier

### Unique items

A unique item starts from a normal Civ V item. This is how Studio safely keeps
all the normal rules that are not being changed.

For each unique:

1. Search for a familiar normal unit, building, or improvement.
2. Choose **Use this as a unique**.
3. Select its card on the right.
4. Give it a new unique name.
5. Add the short explanation players should see.

The starter project includes a Swordsman-based unit and a Monument-based
building. Both say **needs a unique name** until renamed.

Use **Customize stats and artwork** only when needed. Blank values mean “same
as the normal item,” so leaving them blank is safe.

Optional supported changes include:

- Unit combat, ranged strength, movement, cost, starting abilities, portrait,
  tactical flag, and Strategic View image.
- Building cost, maintenance, defense, city hit points, yields, unit experience,
  and portrait.
- Improvement yields, unlock technology, Civilopedia text, and portrait.

Raw Civ V Type names and the replacement matrix appear only in Expert controls.

## Guided page 5: Artwork

Studio takes normal PNG files and creates the Civ V DDS files and icon sizes.
The originals are never changed.

### Main pictures

- **Civilization portrait:** square 1024 x 1024 PNG.
- **White emblem on black:** simple white symbol on a black square.
- **Leader portrait:** preferably square 1024 x 1024 PNG.
- **Opening-screen artwork:** preferably 4:3, such as 1024 x 768.
- **Setup map image:** portrait-shaped, approximately 360 x 412.

The page also reports whether the leader-screen pictures and unique-item
pictures have been added.

### Important art rules

- Do not bake a gold ring, border, medallion, or UI frame into the artwork.
  Civilization V draws its frame. The Studio ring is preview-only.
- Unit flags should be white tactical silhouettes on black.
- Strategic View artwork is optional and should be a transparent square.
- Use the crop preview to drag, zoom, center, or reset a source.

Studio generates portrait/alpha/unit-flag atlases as legacy DX9 DXT5 with no
mip chain and Strategic View images as 64 x 64 A8R8G8B8. Beginners do not need
to configure those formats.

## Guided page 6: Check, Build & Play

The beginner flow has one main button: **Check and create my mod**.

1. Studio saves the current project.
2. Studio checks required fields and every Civ V reference.
3. Studio processes the artwork and validates every generated DDS file.
4. Studio generates and parses the XML and mod information.
5. Studio tests generated data against its isolated BNW reference database.
6. Studio creates the generated mod folder and player ZIP only if the required
   checks pass.

If something is wrong, the page says **Must fix** and offers **Fix the first
problem**. Selecting an issue opens and highlights its exact field. Technical
validator paths stay in tooltips instead of being the main labels.

When the current build is ready, choose **Install into Civilization V**. Studio
installs only the last validated build and never treats opening the game as a
successful runtime test.

## Test the installed civilization

Static checks cannot prove that Civilization V behaves correctly. Test the
exact installed build:

1. Open Civilization V and choose **MODS**.
2. Enable the custom civilization and Brave New World.
3. If the Promotions Pack was enabled, enable that mod too.
4. Start a new game; do not rely only on a saved game from an older build.
5. Confirm the civilization, leader, colors, intro, map image, and icons.
6. Confirm the ability text and both unique replacements.
7. Exercise every unique unit, building, and improvement.
8. Save, reload, and play at least two more turns.
9. If anything fails, exit the game and use **Optional extras > Advanced tools
   > Game Test & Logs**.

Record PASS only after testing that exact installed build. Opening Civ V alone
does not count as PASS.

## Optional extras

### Promotions Expansion Pack v9

Skip this for a first project. If enabled, the generated civilization requires
**Promotions - Expansion Pack (v 9)**, separately created by **Bloublou** and
not bundled with Civilization Studio. Every player must separately obtain,
install, and enable it from the
[Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=84863495).
Choose a named unique unit and a promotion; Studio preserves the exact
technical reference while showing cleaned, readable help text.

### Extra Gameplay Effects

Choose up to two of the 200 ready-made scripted effects. Search by plain
language, category, or timing. The page prevents declared incompatible pairs.

Every extra effect must be tested independently and together in a new game,
then through save/reload. Builds using extra effects are conservatively marked
as save-affecting and single-player only until separately certified.

### Advanced Tools

This section is optional and intended for experienced mod authors:

- Read-only inspection snapshots of existing mods
- Diplomacy text and localization CSVs
- Custom GR2/FXSXML unit-art packages
- Audio and music
- Game logs and diagnostic exports
- Compatibility scans against an installed MODS folder

Opening this page does not modify another mod or the game installation.

## Guided and Expert views

Switching views never removes project data.

**Guided** shows six required pages and hides:

- technical IDs and raw BNW Type names;
- individual AI priorities;
- replacement matrices and stable internal keys;
- implementation classes and database storage paths;
- separate audit/validation/build pipeline stages;
- optional pages from the Continue sequence.

**Expert controls** reveal those fields for experienced authors and debugging.

Useful shortcuts in Guided view:

- `Alt+1` through `Alt+6`: open the six guided pages.
- `F1`: open the beginner guide.
- `Ctrl+K`: search pages, fields, and actions.
- `Ctrl+Z` / `Ctrl+Shift+Z`: undo / redo complete project states.

## Preview and problem panels

The detailed Preview and Project Problems docks start closed so the form has
room to breathe. Use **Show preview**, the **View** menu, or `Ctrl+K` to open
them. Closing a dock never changes project data.

## Recovery, history, and safe file handling

- Studio autosaves recovery data after a saved workspace is edited.
- Manual saves replace the project atomically and retain a prior revision.
- Named snapshots are stored only inside Studio's marked workspace.
- Studio never recursively deletes an arbitrary user-selected folder.
- Generated builds are first created in a project-owned staging location.
- Imported mods and selected source files remain read-only.

## Troubleshooting

### The app will not launch from PowerShell

Relative paths are resolved from the current folder. From any PowerShell
location, use the full path:

```powershell
& "C:\Repos\PNGtoDDSConverter\.venv\Scripts\python.exe" -m civ5studio
```

The portable Windows build does not require Python. Extract its ZIP and run the
executable beside `_internal`.

### A page shows a percentage instead of ready

The percentage is a friendly editing guide, not a release verdict. Open the
page and complete the fields marked with an asterisk. Use **Check and create my
mod** for the authoritative static result.

### Install is disabled

Any edit makes the last build out of date. Choose **Check and create my mod**
again. Install unlocks only for the resulting validated build.

### Artwork fails

Confirm the source exists, is a readable PNG, uses the recommended shape, and
does not already contain a UI frame. White-on-black emblem and flag sources
must remain legible at small sizes.

### The mod builds but fails in game

That is a runtime failure, not a contradiction. Exit Civ V, open Advanced Tools
> Game Test & Logs, analyze fresh logs for the exact installed folder, fix the
reported issue, rebuild, reinstall, and retest a new game.

For backend and art-contract details, see [ARCHITECTURE.md](ARCHITECTURE.md) and
[ART_BACKEND.md](ART_BACKEND.md).
