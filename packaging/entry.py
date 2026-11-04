"""PyInstaller entry point. Keeps the frozen executable's argv handling identical to `suya`."""

import multiprocessing
import sys

from antarctic_monitor.config import use_persistent_matplotlib_cache

use_persistent_matplotlib_cache()

from antarctic_monitor.cli import main  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
