# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.8] - 2026-11-11

A new source, NOAA OSMC, adds the real-time in situ reports of drifting buoys, ice buoys, ships,
uncrewed surface vehicles and tagged animals south of 50°S to the database, the workbook, the
point inspector and the ion composition. Version DOI: https://doi.org/10.5281/zenodo.24131554
(concept DOI for all versions: 10.5281/zenodo.23937852).

### Added

- **A new source: real-time in situ reports from NOAA OSMC.** The collector `osmc` reads the
  dataset `OSMC_30day` of the OSMC ERDDAP server (the reports that reach the WMO Global
  Telecommunication System, CC0) south of 50°S every hour: sea-surface temperature and salinity,
  air temperature, dew point and sea-level pressure from drifting buoys, ice buoys, ships and
  uncrewed surface vehicles, and temperature and salinity at depth from tagged animals. Profiling
  floats are left out because the Argo collector already has them. The last 3 days are asked for
  every hour and all 30 days once a day, so late reports are picked up. A first run on 2026-11-11
  stored 46,096 values from 71 platforms. No key and no account are needed.
- **Quality rules for a source without flags.** OSMC carries no quality flags, so the values pass
  range checks only (water −3…40 °C, salinity 20–42 PSU, air −95…30 °C, sea-level pressure
  890–1070 hPa, a dew point above the air temperature drops both). Sea values south of 79°S are
  dropped, as are sea values of a drifting buoy that stayed within 0.002° for 12 hourly reports
  (stranded or recovered; values stored before the buoy was recognised are removed again) and
  reports dated more than 6 hours ahead. What these rules cannot catch stays in: a single warm
  report from an otherwise cold buoy, for example. Treat OSMC as unchecked observations.
- **OSMC in the workbook, the point inspector and the ion composition.** A new sheet, *OSMC obs*,
  holds one row per time, platform, position and depth. A click on the map lists the nearest OSMC
  surface values within 300 km and 30 days in the Surface tab, for comparison only: they are never
  chosen as the representative value. OSMC salinity is converted to ions like every other salinity.

## [0.1.7] - 2026-11-11

The ion composition now carries a salinity range check and a volume basis, the whole-area salinity
grids are converted to ions as well, and the surface values of Argo profiles come from the
quality-controlled levels. Version DOI: https://doi.org/10.5281/zenodo.24123936
(concept DOI for all versions: 10.5281/zenodo.23937852).

### Added

- **Salinity range check.** Every stored salinity is compared with the Southern Ocean range for its
  depth from Boyer and Levitus (1994), *Quality Control and Processing of Historical Oceanographic
  Temperature, Salinity, and Oxygen Data*, NOAA Technical Report NESDIS 81 (Appendix A, Table 3f;
  33 standard depths, each applied over the depth window the report defines). The verdict is kept
  in the new column `salinity_check` of `seawater_ions` (`ok`, `low`, `high`) and in the view
  `argo_level_ions`, and shown as a *Range check* column in the *Ion composition* sheet, the Argo
  levels workbook and both ion CSV exports. It is a label only: no value is dropped or changed.
  The ranges are broad on purpose, so only gross errors are caught. A new sheet, *Salinity
  ranges*, lists the table that was used.
- **Volume basis.** Where a salinity row has a temperature from the same source, place, level and
  time, the *Ion composition* sheet and `suya export ions` add that temperature, the density at
  1 atm (Millero and Poisson 1981) and the eight major ions in mmol/L. In-situ pressure is not
  included, and the cells stay blank without a paired temperature.
- `suya ions` takes `--temperature` (adds the density at 1 atm and mmol/L) and `--depth` (adds the
  range check); `--json` carries both.
- **Ion conversion of the whole-area grids.** The salinity grids behind the map (HYCOM salinity at
  each depth, SMOS, SMAP) are converted with the same factors as the point values.
  - Map: a *Show* box on the salinity layers reads the map as one of the eight major ions in g/kg
    or mmol/kg. The colours stay the same; the colour-bar ticks, the cursor value and the caption
    change.
  - Workbook: a new sheet, *Grid ions*, with one row per grid time for the whole area south of
    60°S and for each of the five sectors: valid cells, mean salinity, reference salinity, the
    eight ions in g/kg and mmol/kg and the range check for the layer depth. The *Info* sheet
    carries a note on it.
  - Database: the new view `grid_ions` gives the same rows. Nothing is stored for it; the amounts
    are computed from `grids` when read.
  - CSV: `suya export grid-ions --layer hycom_salt_0 --out salt0_ions.csv` and the menu entry
    *File > Export CSV > Current layer ions…* write every cell of the latest grid of a salinity
    layer with its ions. Other layers are refused.
  - The conversion is proportional to salinity, so the ions of a mean salinity equal the mean of
    the cell ions. The stored means have three decimals. There is no mmol/L here, because no
    paired temperature is used.

### Fixed

- **Argo surface values.** The surface temperature and salinity of a profile were taken from the
  first row the listing request returned for it. That request did not sort by pressure, did not
  read the pressure flag and did not separate ascending from descending casts, so the row was not
  always the shallowest good level. The surface values are now the shallowest quality-controlled
  level within 100 dbar of the stored profile, chosen separately for temperature and salinity,
  and the measurement row records that depth. The listed value is used only until the levels
  arrive. Rows written by earlier versions are corrected once, on the first collection after the
  upgrade. On a copy of a real database this changed 10 of 781 profiles: one surface salinity
  went from 27.581 to 33.995, and a salinity of 39.063 was removed because that profile has no
  usable value within 100 dbar.
- **GOSUD outages recorded as "no ship observations".** Every HTTP 404 from the GOSUD server was
  taken as an empty answer, including the 404 ERDDAP sends while it cannot find the dataset. A run
  two minutes after an HTTP 503 was therefore recorded as successful with no ships, while the runs
  before and after found five. Only the "no matching results" 404 now means no observations; any
  other 404 is recorded as a failure, as for Argo.

## [0.1.6] - 2026-11-10

The eight major ions are now derived from every stored salinity and kept in the database, the
workbooks and a new tab of the point window. Version DOI: https://doi.org/10.5281/zenodo.24106903
(concept DOI for all versions: 10.5281/zenodo.23937852).

### Added
- **Ion composition derived from salinity.** Every stored salinity is converted to the eight major
  ions (Cl⁻, Na⁺, SO₄²⁻, Mg²⁺, Ca²⁺, K⁺, HCO₃⁻, Br⁻) with the Reference Composition of Millero,
  Feistel, Wright and McDougall (2008, doi:10.1016/j.dsr.2007.10.001): reference salinity
  S_R = (35.16504 / 35) × S_P times each ion's mass fraction. These are derived values, not ion
  measurements; real seawater differs slightly, and the changed ratios in sea-ice brine or where
  river water or meltwater mixes in are not modelled.
- **A `seawater_ions` table that fills itself.** Triggers on `measurements` add, change and remove
  the ion row together with its salinity row, and salinity collected before the upgrade is filled in
  once when the database is first opened. Two views use no storage: `seawater_ions_mmol` gives the
  same rows in mmol/kg and `argo_level_ions` derives the ions of every Argo level when it is read.
  Salinity that a point query stores (dataset `point_query`) gets its ion row the same way.
- **An *Ion composition* tab** in the point window: reference salinity, chlorinity and ionic
  strength, fifteen components in g/kg, mmol/kg and mass share, and the eight major ions for each
  source's salinity. It reuses the Surface query, so it makes no extra calls.
- **Two new sheets in the monthly workbook**, *Ion composition* and *Ion factors*, and a note on the
  *Info* sheet saying the values are derived. The Argo levels workbook gains reference salinity and
  the eight ions in g/kg for every level.
- **Commands:** `suya ions 34.5` converts one salinity (`--json` for machine-readable output),
  `suya export ions` and `suya export argo-ions` write the derived values as CSV, and
  `suya self-test` now also checks that the database derives an ion row.

### Changed
- The Argo levels workbook is about 1.9 times larger and takes about 1.8 times longer to write
  because of the nine new columns (measured on 433,396 levels: 17.8 MB in 10.2 s before, 33.7 MB in
  17.8 s after). It is still written by the background process, so the window stays responsive.

## [0.1.5] - 2026-11-10

Updates now install themselves by default, and a clearer Open-Meteo budget message. Version DOI:
https://doi.org/10.5281/zenodo.24096560 (concept DOI for all versions: 10.5281/zenodo.23937852).

### Changed
- **Automatic updates are on by default** (`MONITOR_UPDATE_MODE=auto`): when the daily check finds a
  newer release, SUYA downloads the installer for this system, verifies it against the release's
  `SHA256SUMS.txt`, installs it and restarts; a 20-second prompt lets you postpone. *Settings ▸
  Updates* still offers *ask first* and *off*, and a choice saved there is kept. An unknown value of
  `MONITOR_UPDATE_MODE` now falls back to `auto`. `suya self-test` never checks for updates.

### Fixed
- The Open-Meteo budget message no longer reads "used up (5998/9000)" when the GFS map is held back by
  its 30 % reserve. It now names the calls needed and the share the map may use, for example
  "short (5998/6300 used, 613 calls needed; 30% of 9000 is kept for other sources)".

## [0.1.4] - 2026-11-08

Fixes to stored values: garbled METAR reports kept out of the temperature series, METAR pressure
stored under its own name, and a network outage no longer using up the daily call budget. Also a
Homebrew tap. Version DOI: https://doi.org/10.5281/zenodo.24054813 (concept DOI for all versions:
10.5281/zenodo.23937852).

### Added
- A Homebrew tap: `brew install --cask jongsu-king/suya/suya` installs the macOS disk image.

### Fixed
- Open-Meteo and Windy calls that never reached the server no longer count against the daily budget.
  During a long network outage the failed attempts used the budget up, so the GFS map stayed blocked
  after the connection came back. A failure after the server was reached still counts.
- Garbled METAR reports no longer reach the database as air temperature or dew point. NOAA's JSON
  turned `M048/M08` at Marambio into +48 °C and `M04/09` into a dew point of +9 °C above an air
  temperature of -4 °C. Values outside -95 to 30 °C and pairs with the dew point above the air
  temperature are dropped, and rows of this kind already stored are removed at the next collection.
- METAR pressure is stored as `sea_level_pressure` instead of `surface_pressure`. The value is the
  sea-level reduced pressure (SLP, or QNH when SLP is missing), so the South Pole read about 963 hPa
  under the same name as Open-Meteo's station-level 676 hPa. Rows already stored are relabelled at the
  next collection, and the station sheet in the monthly Excel file names the column sea-level pressure.

## [0.1.3] - 2026-11-05

A slim collector install and a container image, missed satellite days filled in, a monthly summary
sheet, map playback, and Argo profiles that no longer go missing. Version DOI: https://doi.org/10.5281/zenodo.23981834 (concept DOI for all
versions: 10.5281/zenodo.23937852).

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
- On Linux with Python 3.11, playing the map through stored times could abort the program
  (`Fatal Python error: deallocating None`) while the land outline was being rebuilt. The outline is
  now built once, and the abort no longer appears in the test runs. The installers and the container
  run on Python 3.12 and were not affected.
- Argo profiles that came back empty are asked for again a day later, for as long as they are within
  the 30-day list. A profile the server had not finished indexing used to be stored as empty and
  never fetched again, so its levels stayed missing from the database and the Excel files.
- Argo treated every HTTP 404 as "no data", including the one ERDDAP sends while a dataset is
  briefly unavailable. Such an answer is now a failure that is retried soon: profiles are no longer
  marked empty during an outage, and a completely empty list is no longer reported as a success.

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
