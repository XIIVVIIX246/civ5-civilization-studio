# Universal Civ V Art Pipeline

A robust, automated Python pipeline for converting standard PNG images into fully compliant, game-ready DDS texture atlases for *Sid Meier's Civilization V: Brave New World*.

This tool handles the tedious components of Civ V modding: standardizing masters, baking Firaxis-style antialiased circular crops, safely converting AI-generated black backgrounds into white-on-transparent alpha glyphs, and exporting uncompressed 32-bit `A8R8G8B8` / `DXT` DDS files with precise mipmap control.

## Included Files & Templates

* **`universal_civ5_pipeline.py`**: The master automation script engine.


* **`SpartanLeague_art_reference_v9.json`**: A pre-sanitized, fully documented production template configured with relative file paths and asset profile targets.


* **`./Input/SpartanLeague/`**: The local storage directory structure used to hold your target source PNG illustrations before compression.



---

## Target Asset Reference Dimensions (Ideal Source PNG Sizes)

To maintain precise pixel grid alignments and keep textures crisp in game UI frames, make sure your raw source artwork matches these target parameters before running the converter:

### 1. UI Icon Graphics (Circular Frame Roles)

* **Civ, Leader, Unit, Building, & Support Icons:** **1024x1024 pixels** (Preferred High-Resolution Master) or **256x256 pixels** (Standard Frame Master).


* *Sizing Note:* Ensure the item graphic is contained cleanly inside the center core of the canvas. The script sets a default footprint constraint of 65.625%, ensuring your active subject sits perfectly within the engine's round frame mask without blowing up to ugly square cutouts.




* **Alpha / Team Color Icons:** **1024x1024 pixels** or **256x256 pixels**.


* *Sizing Note:* Drawn as a flat white icon shape on a pure black background. The script handles stripping out the background to give you crisp transparency scaling down the ladder.





### 2. Full-Bleed Illustrations & Scenes

* **Dawn of Man (DOM) Screen:** Exactly **1024x768 pixels**.


* *Framing Note:* Drawn completely opaque with no transparency; automatically exported to an uncompressed 32-bit container.




* **Map Selection Image:** Exactly **512x512 pixels**.


* *Framing Note:* Must be a perfect 1:1 square asset. The pipeline forces a center-fit crop block if dimensions deviate.




* **Leaderboard 2D Scene:**
* **4:3 Profile Setting:** Exactly **1024x768 pixels**.


* **16:9 Profile Setting:** Exactly **1280x720 pixels**.





### 3. Combat & Map Assets

* **Unit Flag Glyphs:** **256x256 pixels**.


* *Sizing Note:* Rendered as a distinct white silhouette outline on a solid black backdrop. The tool tokenizes this down to a flawless 32x32 pixel block fitted directly into the game's final combat map grid.





---

## Features

* **Automated Atlasing:** Generates the standard 4x4 normal icon atlas at all required BNW sizes (256, 128, 80, 64, 45, 32).


* **Alpha & Flag Cleanup:** Automatically scrubs black backgrounds from unit flags and alpha/team icons, converting them to perfect white-on-transparent silhouettes.


* **Medallion Baking:** Optional mode to bake Firaxis-style circular UI frames (silver or gold) directly onto square source art.


* **Safe Mod Integration:** Use `--write-mod` to safely back up and overwrite existing DDS files inside your local `MODS` directory and automatically refresh your `.modinfo` file's MD5 hashes.



---

## Prerequisites

* **Python 3.7+** (Requires `dataclasses` support)


* **Pillow** (Python Imaging Library): Install via terminal:
```bash

```



pip install Pillow

```

---

## Quick Start Guide

The easiest way to use the pipeline is via the included JSON configuration template, which tracks all your input PNGs and output settings[cite: 1, 3].

### 1. Configure Your JSON Settings
Open `SpartanLeague_art_reference_v9.json` and adjust the paths to your local setup[cite: 1, 3].
*   **Paths:** The template is pre-loaded to pull relative assets directly from your `./Input/SpartanLeague/` folder[cite: 3].
*   **Mod Integration:** Update the `"mod_data_dir"` field by swapping out `YOUR_USERNAME_HERE` with your true Windows user folder context to connect the automated compiler loop[cite: 3].

### 2. Validate Your Setup
Before running image conversion, execute a safety validation check[cite: 3]:
```bash
python universal_civ5_pipeline.py --config SpartanLeague_art_reference_v9.json --check-only

```

This script confirms your files exist, your atlas won't spill past the 16-icon threshold, and your filename parameters are perfectly clean.

### 3. Build the Assets

To generate your DDS outputs, XML tables, and preview logs directly inside your target outputs folder:

```bash
python universal_civ5_pipeline.py --config SpartanLeague_art_reference_v9.json

```

### 4. Direct Export to active Mod Directory

Once you review your generated previews and are happy with the framing, execute with the `--write-mod` argument:

```bash
python universal_civ5_pipeline.py --config SpartanLeague_art_reference_v9.json --write-mod

```

This checks for matching `.dds` names in your active mod paths, caches backups (`.bak`), replaces the textures, and flashes updated MD5 fingerprint checksum records to your system `.modinfo` layout blocks.

---

## CLI Overrides

While JSON is recommended for complex projects, you can pass arguments directly via command prompt to instantly force or modify behavior:

* `--dry-run`: Performs complete conversion tracking and outputs a detailed Markdown layout of updates without making any physical directory adjustments.


* `--bake-medallions`: Forces the tool to paint structural UI rings around normal canvas layouts.


* `--allow-painted-flags`: Suppresses structural errors if you purposefully try to inject colored map flag art instead of clean vector alpha glyph shapes.



---

## Folder Output Structure

After a successful run, your assigned output folder will track:

* `Art/`: All game-ready `.dds` textures formatted to the system specifications.


* `XML/`: Raw templates detailing structural `<IconTextureAtlases>` tags to drop into your mod setup.


* `Previews/`: High-resolution PNG proof files showcasing background alpha bounds and circular clipping masks.


* `*_QA_Report.md`: Markdown audit reports listing dimension validation status, alpha metrics, and compression accuracy ratings.