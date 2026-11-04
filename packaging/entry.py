"""PyInstaller entry point. Keeps the frozen executable's argv handling identical to `suya`."""

import multiprocessing
import sys

from antarctic_monitor.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
