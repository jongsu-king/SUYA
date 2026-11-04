# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- WOA23 climatology profiles are kept in the database per grid point and month, so the
  vertical-profile tab shows the climatology at once for any point looked up before, even while
  the NCEI server is slow or down.

### Changed
- Chart legends sit above the plot, outside the axes, so they never cover the data; the T-S
  diagram and the salinity profile were the worst affected.

## [0.1.1] - 2026-11-04

Bug-fix release. Version DOI: https://doi.org/10.5281/zenodo.23945830 (concept DOI for all
versions: 10.5281/zenodo.23937852).

### Added
- The About dialog and the built-in user guide show the Zenodo DOI and how to cite the program.
- Dependabot keeps Python packages and GitHub Actions versions current with one grouped
  pull request per week.
- Download buttons for each operating system at the top of both READMEs, and release notes that
  begin with a download table, so the installers are easy to find.

### Changed
- The program, `CITATION.cff`, `AUTHORS.md` and the READMEs cite the concept DOI
  (10.5281/zenodo.23937852), which always resolves to the latest archived release; the DOI of each
  version is listed next to it. A version DOI only exists after Zenodo has archived the release, so
  it can never be built into the program of that same version.

### Fixed
- The installed program rebuilt matplotlib's font cache on every start (about six seconds on macOS)
  because the frozen build pointed matplotlib at a temporary folder that was deleted on exit. The
  cache now lives in the user data folder (`matplotlib/` next to `antarctic.db`) and is reused.
- Once a detail tab showed a wrapped note or error line, its scroll area grew to the charts'
  preferred height instead of the visible height, so the bottom of the T-S diagram ended up below
  the window edge with no obvious scrollbar. Charts now report their minimum height as the
  preferred one and the vertical-profile tab shares the visible height between its charts.
- The vertical-profile tab could wait on HYCOM indefinitely while the HYCOM grid or profile
  collector held the host's connection slots. Point lookups now use their own small per-host
  lane, every source in a point lookup has a time limit (HYCOM 120 s, WOA23 60 s, others 90 s) after which
  the rest of the panel is shown with a "no answer" note, and a partial result is cached for
  two minutes instead of hours.
- Argo: a profile that ERDDAP listed but answered with "no matching results" (its per-file
  index was stale) was retried every cycle and marked the whole source as failing. Levels are
  now fetched by cycle range as a fallback, a profile that really has no levels is stored as
  empty and skipped, and the source only reports failure when nothing at all could be fetched.
- Time-series charts looked empty on the first day: a single sample, or a value isolated between
  gaps, cannot form a line. Such values are now drawn as dots, a one-time-step axis is centred on
  the sample, and a note says how many samples exist until the line fills in.

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
