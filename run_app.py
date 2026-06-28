"""PyInstaller entry point — runs the same app as `python -m app`."""
import sys

from app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
