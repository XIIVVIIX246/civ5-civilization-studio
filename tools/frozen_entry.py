"""PyInstaller entry point kept outside the package for reliable freezing."""

from civ5studio.main import main


if __name__ == "__main__":
    raise SystemExit(main())
