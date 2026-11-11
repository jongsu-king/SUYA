# Excel database layout

[한국어](excel-database.md)

Every 15 minutes (`MONITOR_INTERVAL_EXCEL`) SUYA checks whether new data reached SQLite and, if so, rewrites the monthly workbooks.
`File > Save Excel database now` or `suya excel-sync` does it immediately.

## Files

| File | Contents |
|---|---|
| `antarctic_db_YYYY-MM.xlsx` | Every point value, grid statistic and listing for that month (sheets below) |
| `argo_levels_YYYY-MM.xlsx` | Every level of every Argo profile that month with its derived ion amounts; hundreds of thousands of rows, hence a separate file |

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
Period, creation time (UTC), time-basis note, warning, notes on the ion conversion, the range check, the volume basis and the grid ion conversion, rows per sheet.

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
| SST °C, SSS PSU | Shallowest valid level (QC 1 and 2) within 100 dbar of the stored levels; the listed value until the levels arrive |
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

### Ion composition — major ions derived for every row that has a salinity
That month's rows of the SQLite table `seawater_ions`: surface values of the sea areas, the 40 HYCOM levels, satellite salinity and salinity at points clicked on the map.
These are **not direct ion measurements**; each salinity is multiplied by the ratios of the Reference Composition (Millero et al. 2008). The formula and its limits are in [Data sources, section 11](data-sources.en.md#11-ion-composition-derived-from-salinity).

| Column | Meaning |
|---|---|
| Time UTC, Point, Lat, Lon | As in the salinity row. Clicked points have no point name |
| Data, Type | `hycom`, `smos`, `smap`, `argo`, … / model, satellite, observation |
| Level, Depth m | `surface` or `depth:<m>` |
| Salinity PSU | The practical salinity S_P that was converted |
| Reference salinity g/kg | S_R = (35.16504 / 35) × S_P |
| Cl⁻ … Br⁻ g/kg | The eight major ions (Cl⁻, Na⁺, SO₄²⁻, Mg²⁺, Ca²⁺, K⁺, HCO₃⁻, Br⁻) per kg of seawater |
| Cl⁻ … Br⁻ mmol/kg | The same eight as amounts of substance |
| Temp °C | Temperature of the same source, position, level and time; blank without one |
| Density at 1 atm kg/m³ | Density at 1 atm for that temperature and salinity (Millero & Poisson 1981); in-situ pressure not included; blank without a temperature |
| Cl⁻ … Br⁻ mmol/L | mmol/kg × density / 1000; blank without a temperature |
| Range check | `low` or `high` where the salinity is outside the Southern Ocean range for its depth; blank inside the range. A label only: the value is kept |

### Grid ions — ions derived from the area means of the salinity grids
That month's rows of the SQLite view `grid_ions`: for every time of a salinity grid (the HYCOM salinity layer of each depth, SMOS, SMAP) one row for the whole area south of 60°S and one per sector.
These are **derived values**: the mean salinity times the same factors. The conversion is proportional to salinity, so the result equals converting every cell and averaging. Cell values come from `suya export grid-ions`. The formula and its limits are in [Data sources, section 11](data-sources.en.md#11-ion-composition-derived-from-salinity).

| Column | Meaning |
|---|---|
| Time UTC | Data time of the grid |
| Layer | `hycom_salt_<depth>`, `smos_sss`, `smap_sss` |
| Area | `Southern Ocean (south of 60°S)` or one of the five sectors (Weddell Sea, Indian Ocean, Western Pacific, Ross Sea, Amundsen-Bellingshausen Seas). A sector without a mean has no row |
| Depth m | Depth of the layer; 0 for satellite salinity |
| Valid cells | Cells with a value south of 60°S; in a sector row, the cells inside that sector |
| Salinity PSU | Weighted mean salinity of the area (the value of the *Grid means* sheet, three decimals) |
| Reference salinity g/kg | S_R = (35.16504 / 35) × S_P |
| Cl⁻ … Br⁻ g/kg | The eight major ions per kg of seawater |
| Cl⁻ … Br⁻ mmol/kg | The same eight as amounts of substance |
| Range check | `low` or `high` where the mean salinity is outside the Southern Ocean range for the layer depth; blank inside the range |

No paired temperature is used, so there are no density and mmol/L columns.

### Ion factors — the Reference Composition used
Fifteen components with symbol, charge, molar mass, mass share %, g/kg and mmol/kg per unit of salinity, and g/kg and mmol/kg at salinity 35.
The eight rows with a `DB column` are the ones stored in the database and in Excel. Multiplying these factors by any salinity reproduces every value.

### Salinity ranges — the salinity range by depth used for the range check
The Southern Ocean table of Boyer & Levitus (1994, NOAA Technical Report NESDIS 81), one row for each of the 33 standard depths.

| Column | Meaning |
|---|---|
| Standard depth m | 0 to 5500 m |
| Deeper than m, Down to m | The depth window this row's range applies to; the outer side of the first and the last row is blank |
| Salinity minimum, Salinity maximum | Below the minimum is `low`, above the maximum `high` |

The ranges are broad and catch gross errors only. Rule and limits: [Data sources, section 11](data-sources.en.md#11-ion-composition-derived-from-salinity).

## `argo_levels_YYYY-MM.xlsx`

### Argo levels
| Column | Meaning |
|---|---|
| Time UTC, Float, Cycle, Lat, Lon, Mode | Profile identity |
| Pressure dbar | Raw pressure (adjusted in modes A/D) |
| Depth m | Converted with Saunders & Fofonoff (1976) |
| Temp °C, Salinity PSU | QC 1 and 2 only; blank otherwise |
| Reference salinity g/kg, Cl⁻ … Br⁻ g/kg | Reference salinity and the eight major ions derived from that level's salinity; blank where the level has no salinity |
| Range check | `low` or `high` where that level's salinity is outside the Southern Ocean range for its depth; blank inside the range |

The nine ion columns make this file about 1.9 times larger and about 1.8 times slower to write than before
(measured 2026-11-10: a month of 433,396 rows went from 17.8 MB in 10.2 s to 33.7 MB in 17.8 s). The range-check column adds almost nothing (measured 2026-11-11: a month of 434,000 rows went from 33,724,118 to 33,728,674 bytes). It is written by the child process, so the window does not block.

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
ions = pd.read_sql("SELECT obs_time, location_id, depth_m, practical_salinity, chloride_g_kg, sodium_g_kg FROM seawater_ions WHERE source='hycom'", con)
argo_ions = pd.read_sql("SELECT * FROM argo_level_ions WHERE obs_time >= '2026-11-01'", con)
```

```r
library(DBI); con <- dbConnect(RSQLite::SQLite(), "~/Library/Application Support/SUYA/antarctic.db")
dbGetQuery(con, "SELECT * FROM measurements WHERE variable='sea_water_temperature' LIMIT 10")
```

Derived ion amounts are read from one table and three views: `seawater_ions` (g/kg, one row per salinity row), `seawater_ions_mmol` (mmol/kg), `argo_level_ions` (per Argo level, g/kg) and `grid_ions` (the mean south of 60°S and the sector means of every salinity grid, g/kg and mmol/kg). The range-check verdict is the column `salinity_check` (`ok`, `low`, `high`) of `seawater_ions`, `argo_level_ions` and `grid_ions`. Density and mmol/L are not in the database; the workbook and `suya export ions` compute them.
For CSV use `suya export ions --out ions.csv` and `suya export argo-ions --out argo_ions.csv`; for the value of every cell of a salinity grid, `suya export grid-ions --layer hycom_salt_0 --out salt0_ions.csv`.

`grids.payload` is gzip-compressed JSON (`{"lats":[…],"lons":[…],"values":[…]}`); `antarctic_monitor.db.Store.load_grid("oisst_sst")` decodes it.
