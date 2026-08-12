"""PyInstaller entry point for the bundled PhotoS executable.

Dispatches CLI / GUI / serve exactly like `photo-s` (see photo_s.cli:main).
"""

import sys

from photo_s.cli import main

if __name__ == "__main__":
    sys.exit(main())
