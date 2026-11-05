# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The collector installs without Qt. `pip install suya` (or the Git URL) now brings only httpx, numpy
  and XlsxWriter; the window needs the `gui` extra (`pip install "suya[gui]"`). `suya daemon`,
  `collect`, `export`, `excel-sync` and `self-test` work in the slim install, and `suya` alone says
  what is missing. A `Dockerfile` runs the daemon in a container with everything under `/data`.
  The single-instance lock falls back to an OS file lock when Qt is absent. CI checks the slim
  install and builds the image. The installers are unchanged.
- Every release build now installs its own installer on the runner and runs the installed copy's
  self-test before anything is attached: a silent install, self-test and silent uninstall on
  Windows (the same switches the in-app updater uses), mount, copy and run on macOS, extract,
  `install.sh` and run on Linux. The release job also refuses to publish if any of the four
  files the in-app updater looks for is missing.
- OISST, SMOS and SMAP fill in the days they missed. If the program was off or the server was down,
  the days that appeared in the meantime are fetched oldest first, three per run and up to seven
  days back, so the daily series keeps no holes after a short outage.
- A Homebrew cask (`packaging/homebrew/`) and a winget manifest set (`packaging/winget/`) for
  publishing on those channels.
- The map can step through time. A layer with two or more stored times shows a slider and a play
  button below the map, with the colour range fixed to the latest grid.
- A *Monthly summary* sheet opens each monthly workbook: samples, mean, minimum, maximum, standard
  deviation, first and last time per point, source and item, with last month's mean and the change.

### Changed
- The air-temperature tab lists the current values two per row. Four per row was wider than the
  panel in a narrow window, which cut off the values and the charts below them.
- The screenshots in the READMEs show the current window: legends above the charts and the air-temperature tab as it fits now.
- The first-run instructions describe macOS 15 and later, where right-clicking no longer gets past
  the warning: *System Settings ▸ Privacy & Security ▸ Open Anyway*.
- Closing the window while an update is being downloaded or installed now asks first. Closing used
  to cancel the update without a word and stop collection along with it.
- HYCOM jobs may run for 60 minutes (other sources keep 30). When the HYCOM server is slow, the
  grid job stops starting new variables after 20 minutes, keeps the layers it has and continues
  30 seconds later, so a slow day no longer ends in a timeout with nothing recorded.
- The test step in CI and in the release build stops after 15 minutes, so a stuck test fails
  instead of holding a runner for hours.
- The land outline on the map is built once and moved with a single transform, instead of being
  rebuilt point by point on every redraw. The drawing is unchanged.

### Fixed
- On Python 3.11, stopping the collector could hang when a manual collection was requested, or a
  job finished, at the same moment. `asyncio.wait_for` on that version drops a cancellation that
  arrives just as its inner task ends, so the job went on to its next long wait. The engine and the
  point queries now use `asyncio.timeout`. The installers and the container run on Python 3.12 and
  were not affected.

## [0.1.2] - 2026-11-05

The program now updates itself. Version DOI: https://doi.org/10.5281/zenodo.23967499 (concept DOI for all
versions: 10.5281/zenodo.23937852).

### Added
- WOA23 climatology profiles are kept in the database per grid point and month, so the
  vertical-profile tab shows the climatology at once for any point looked up before, even while
  the NCEI server is slow or down.
- Automatic updates. The program looks up the latest GitHub release 15 seconds after it starts and
  once a day; a new version is downloaded (Windows installer, macOS disk image or Linux archive for
  the running platform), verified against the release's `SHA256SUMS.txt`, installed and the program
  restarted. *Settings ▸ Updates* chooses between *do not check*, *notify and ask* (default) and
  *install automatically* (with a 20-second prompt to postpone); *Help ▸ Check for updates…* runs the
  check on demand. pip installations are only pointed to the download page. The Windows installer
  accepts `/relaunch=1` to start the program again after a silent update.
- Only one copy of the program runs per data folder: a second start (window or `suya daemon`)
  explains that SUYA is already running and exits instead of collecting everything twice.
- Native crashes are written to `crash.log` in the data folder (Python's fault handler), so a
  crash inside Qt or a driver leaves a trace to report.
- The vertical-profile note shows the mixed-layer depth of each profile (temperature criterion:
  0.2 °C from the 10 m value, de Boyer Montégut et al. 2004).
- Argo fetches up to 120 profiles per hourly run instead of 60, so the first day's backlog clears
  in about half the time.

### Changed
- When GitHub's request limit stops the update check, the status bar says so and tells how many
  minutes to wait, instead of showing the raw API response.
- Chart legends sit above the plot, outside the axes, so they never cover the data; the T-S
  diagram and the salinity profile were the worst affected.

### Fixed
- Error messages that carry another message inside them, such as Argo's "profile not found",
  are shown as readable text in both languages in the source table, the status bar and
  `monitor.log`, instead of the raw stored form. Collection failures are logged with the same
  words the program shows.
- A collection job that runs into the 30-minute limit is recorded as "stopped after 30 min
  without finishing" instead of an empty `TimeoutError:`; errors that carry no text show the
  error type alone.

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
