# Source and reference provenance

This record distinguishes original application code, reference-derived data,
and separately distributed dependencies for the public release.

| Area | Provenance | Public package treatment |
|---|---|---|
| `src/civ5studio` application | Original Civilization Studio implementation, released under MIT | Bundled as frozen Python application |
| Root PNG-to-DDS scripts and `Old scripts` | Preserved project-history/reference implementations | Not shipped as loose source in the Windows ZIP |
| Art sizing and DDS contracts | Implemented from the current Civ 5 Strategic Missile Project workflow used as a read-only technical authority | No Strategic Missile Project art or mod package is bundled |
| BNW reference catalog | Generated/curated from a locally owned Civilization V: Brave New World installation; catalog provenance and source hashes are embedded in the JSON | Derived schema/type catalog only; raw Firaxis XML and game assets are not bundled |
| Promotions - Expansion Pack v9 | Compatibility metadata derived from a read-only installed copy of Bloublou's separately distributed mod | The mod, gameplay XML, and art are not bundled; users are directed to Steam Workshop |
| Python, Qt/PySide6, Pillow, PyInstaller, OpenSSL, SQLite, VC runtime | Upstream runtime dependencies | Bundled under their respective licenses and documented in `THIRD_PARTY_NOTICES.md` |

## Promotions - Expansion Pack

Promotions - Expansion Pack was separately created by **Bloublou** and is not
bundled with Civilization Studio. Its official Steam Workshop page is:

<https://steamcommunity.com/sharedfiles/filedetails/?id=84863495>

The selector metadata exists only to let a generated civilization declare and
refer to the separate dependency. It must not be presented as original
Civilization Studio content.

## Contributor rule

Future copied or adapted code, text, or artwork must record the original
author, exact source location, source license or permission, files affected,
and a summary of modifications here before it is eligible for a public build.
Material without known redistribution permission must remain reference-only
and outside the public artifact.
