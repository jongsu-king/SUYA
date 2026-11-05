# Excel database layout

[한국어](excel-database.md)

Every 15 minutes (`MONITOR_INTERVAL_EXCEL`) SUYA checks whether new data reached SQLite and, if so, rewrites the monthly workbooks.
`File > Save Excel database now` or `suya excel-sync` does it immediately.

## Files

| File | Contents |
|---|---|
| `antarctic_db_YYYY-MM.xlsx` | Every point value, grid statistic and listing for that month (sheets below) |
| `argo_levels_YYYY-MM.xlsx` | Every level of every Argo profile that month; tens of thousands of rows, hence a separate file |

Default folder: Windows `Documents\SUYA`, macOS/Linux `~/Documents/SUYA`. Change it in `File > Settings` or with `MONITOR_EXCEL_DIR`.

## How it works

1. The engine's `excel` job reads `data_stamp()` (the time data last arrived). If it equals the previous stamp the run ends as "No new data".
2. Otherwise it starts a **child process** (`suya excel-sync --db … --dir …`) so the window and the collectors never block.
3. It picks the months to write (`months_to_write`): the current month, the previous month, and any month without a file. Older months are **never rewritten**, so a month's file is frozen one month after it ends.
4. Each workbook is written completely to `.antarctic_db_YYYY-MM.tmp.xlsx` and then moved into place with `os.replace`; a crash never leaves a broken file.
5. On Windows a workbook that is open in Excel cannot be replaced. That month is skipped, retried on the next cycle, and the status tab shows "Could not save … because the file is open".
6. When a sheet reaches Excel's limit (1,048,576 rows) it continues as `<sheet>_2`, `_3`, …

Why regenerate rather than append: an xlsx file is zipped XML, so appending one row means reading and rewriting the whole file. It gets slower as it grows and a crash mid-write corrupts it. Treat SQLite as the master and the workbooks as a readable copy. **Manual edits are lost on the next save**; analyse a copy.

## Common format

- Bold underlined header row, frozen panes, auto-filter.
- Time columns are Excel dates (`yyyy-mm-dd hh:mm`) in **UTC**.
- Empty cells are missing values (absent, or removed by a quality rule).
- Point names, sheet names and headers follow the program language at the time of writing (Korean or English).

## Sheets in `antarctic_db_YYYY-MM.xlsx`

### Info
Period, creation time (UTC), time-basis note, warning, rows per sheet.

### Monthly summary — one month's statistics per point, source and item
Only surface and 2 m values count. Forecasts for days ahead (`kind = forecast`), deep levels and points clicked on the map are left out.

| Column | Meaning |
|---|---|
| Point | Sea area or base name; the ICAO code for METAR stations |
| Data | `oisst`, `smos`, `smap`, `hycom`, `openmeteo_marine`, `openmeteo`, `metar` |
| Item, Unit | Temperature, salinity, SST anomaly, sea-ice fraction, SST uncertainty, air temperature |
| Samples | Number of values in the month. Sources differ in cadence, so read it next to the mean |
| Mean, Min, Max, Std dev | Plain statistics of the samples (population standard deviation), not time-weighted |
| First UTC, Last UTC | The range with values in that month. The month collection began does not cover the whole month |
| Prev month mean, Change vs prev | The previous month's mean for the same point, source and item, and the difference. Empty when that month has no values |

### Grid means — statistics per map layer and time
| Column | Meaning |
|---|---|
| Time UTC | Data time of the grid |
| Layer | `oisst_sst`, `oisst_anom`, `oisst_ice`, `smos_sss`, `smap_sss`, `gfs_t2m`, `hycom_temp_<depth>`, `hycom_salt_<depth>` (depths 0, 100, 200, 500, 1000, 2000) |
| Unit | °C, PSU, fraction |
| Mean south of 60°S | Cosine-of-latitude weighted mean |
| Min, Max | South of 60°S |
| Valid ratio | Fraction of cells south of 60°S with a value (satellite salinity is 0.0x; sea ice counts only ice cells) |
| Weddell Sea … Amundsen-Bellingshausen Seas | Weighted means for the five sectors |

### Water by area — surface values at the ten sea-area points
| Column | Meaning |
|---|---|
| Time UTC, Point, Lat, Lon | |
| Data | `oisst`, `smos`, `smap`, `hycom`, `openmeteo_marine` |
| Type | analysis, satellite, model |
| Item | Temperature / Salinity / SST anomaly / Sea ice concentration |
| Value, Unit | |

### Water vertical — HYCOM 40-level profiles
Ten areas × time × depth; temperature and salinity share a row (blank when one is missing). Collected daily.

### Argo list — one row per profile
| Column | Meaning |
|---|---|
| Time UTC | Profile time |
| Float | WMO number |
| Cycle | cycle_number |
| Lat, Lon | |
| Mode | R real-time, A real-time adjusted, D delayed mode |
| Position QC | 1 good, 8 estimated (under ice), … |
| SST °C, SSS PSU | Shallowest valid level, QC 1 and 2 only |
| Max depth m, Levels | Filled once the levels have been fetched |

### Ships — GOSUD
Per call sign: time, position, SST and salinity (when available). QC 1 and 2 only.

### Stations — METAR
Per ICAO station: report time, name, position, air temperature, dew point, pressure.

### GFS air — current values at the 24 points
Time, point, lat, lon, air temperature, apparent, dew point, wet bulb, surface temperature, humidity, pressure, wind speed.

### Forecasts — 24 points × forecast time
2 m air temperature from GFS, ECMWF IFS, ICON, GEM and JMA GSM side by side. When the same forecast hour is refreshed several times only the **latest collected value** remains (the SQLite key is the forecast time).

### Windy
Only with a key: forecast time, point, model, level (surface, hpa:850 …), item, value, unit, key type (`windy_testing_shuffled` = altered values).

### Point queries — points clicked on the map
Every value fetched for an arbitrary point (OISST, MUR, SMOS, SMAP, HYCOM 40 levels, GFS current, Marine). Measurements without a `location_id` end up here.

## `argo_levels_YYYY-MM.xlsx`

### Argo levels
| Column | Meaning |
|---|---|
| Time UTC, Float, Cycle, Lat, Lon, Mode | Profile identity |
| Pressure dbar | Raw pressure (adjusted in modes A/D) |
| Depth m | Converted with Saunders & Fofonoff (1976) |
| Temp °C, Salinity PSU | QC 1 and 2 only; blank otherwise |

## Reading the data directly from Python or R

Reading SQLite is faster than going through Excel.

```python
import sqlite3, pandas as pd
con = sqlite3.connect("~/Library/Application Support/SUYA/antarctic.db")  # Windows: %APPDATA%/SUYA/antarctic.db
salt = pd.read_sql("""
  SELECT obs_time, lat, lon, depth_m, value FROM measurements
  WHERE source='hycom' AND variable='sea_water_salinity' AND location_id='weddell'
  ORDER BY obs_time""", con)
argo = pd.read_sql("SELECT platform, cycle, obs_time, lat, lon, surface_temp, surface_salt FROM argo_profiles", con)
```

```r
library(DBI); con <- dbConnect(RSQLite::SQLite(), "~/Library/Application Support/SUYA/antarctic.db")
dbGetQuery(con, "SELECT * FROM measurements WHERE variable='sea_water_temperature' LIMIT 10")
```

`grids.payload` is gzip-compressed JSON (`{"lats":[…],"lons":[…],"values":[…]}`); `antarctic_monitor.db.Store.load_grid("oisst_sst")` decodes it.
