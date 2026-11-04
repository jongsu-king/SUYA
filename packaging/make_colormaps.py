"""Regenerate antarctic_monitor/data/colormaps.json from cmocean (MIT, Thyng et al. 2016).

The app only needs the 256-entry tables, so cmocean is a build-time tool, not a runtime dependency.
Usage: pip install cmocean && python packaging/make_colormaps.py
"""

import json
from pathlib import Path

import cmocean
import numpy as np

names = {"thermal": cmocean.cm.thermal, "haline": cmocean.cm.haline, "balance": cmocean.cm.balance, "ice": cmocean.cm.ice}
tables = {name: (cmap(np.linspace(0, 1, 256))[:, :3] * 255).round().astype(int).tolist() for name, cmap in names.items()}
target = Path(__file__).resolve().parent.parent / "antarctic_monitor" / "data" / "colormaps.json"
target.write_text(json.dumps(tables, separators=(",", ":")), encoding="utf-8")
print(target, target.stat().st_size)
