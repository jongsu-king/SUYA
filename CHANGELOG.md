# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-04

First public release of **SUYA** (Antarctic Ocean Monitor).
Archived on Zenodo: https://doi.org/10.5281/zenodo.23937853 (concept DOI for all versions: 10.5281/zenodo.23937852).

### Added
- Continuous collection engine with per-source intervals, exponential back-off, rate-limit handling,
  persisted schedules across restarts, and a daily call budget for Open-Meteo.
- Data sources: NOAA METAR, Open-Meteo (GFS current, GFS/ECMWF/ICON/GEM/JMA forecasts, marine SST,
  ERA5 archive), OISST v2.1, MUR SST, SMOS and SMAP sea surface salinity, HYCOM ESPC-D-V02
  temperature and salinity at six depths plus 40-level profiles, Argo float profiles with QC flag
  filtering, GOSUD underway ship data, World Ocean Atlas 2023 climatology, and the official Windy
  Point Forecast API (optional key).
- SQLite store for measurements, gridded snapshots, Argo profiles and collection history.
- Monthly Excel database (`antarctic_db_YYYY-MM.xlsx`, `argo_levels_YYYY-MM.xlsx`) rebuilt
  atomically from SQLite whenever new data arrives.
- PySide6 desktop interface: south-polar stereographic map with eight layers and six HYCOM depths,
  click-anywhere point inspector (surface values, vertical profiles with T-S diagram, air temperature
  with model comparison, 30-day time series), area statistics, station and point tables,
  collection status and live log, CSV export.
- Korean and English interface, chosen on first start and switchable from the View menu.
- Command line: `gui`, `daemon`, `collect`, `export`, `excel-sync`, `sources`, `self-test`.
- Installer builds for Windows (Inno Setup), macOS (DMG) and Linux (tar.gz) via GitHub Actions.
- Citation metadata: `CITATION.cff` for GitHub's "Cite this repository" button and `.zenodo.json`
  for Zenodo DOI archiving of releases.
