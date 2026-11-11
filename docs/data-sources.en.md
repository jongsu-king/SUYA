# Data sources in detail

[한국어](data-sources.md)

Every remote service SUYA calls, the exact request shape, the variables it reads, the quality rules it applies and the known limits,
with the code location so you know where to look when a service changes.

## Summary

| ID | Code | Protocol | Host | Auth | Default interval |
|---|---|---|---|---|---|
| metar | `collectors/metar.py` | REST JSON | aviationweather.gov | none | 5 min |
| openmeteo_current / forecast / marine, gfs_grid | `collectors/openmeteo.py` | REST JSON | api.open-meteo.com, marine-api.open-meteo.com, archive-api.open-meteo.com | none (10,000 calls/day free) | 15 min / 3 h / 30 min / 3 h |
| oisst, smos, smap, (mur) | `collectors/erddap.py` | ERDDAP griddap JSON | coastwatch.pfeg.noaa.gov, coastwatch.noaa.gov | none | checked every 6 h |
| hycom_grid, hycom_profiles | `collectors/hycom.py` | OPeNDAP ascii | ncss.hycom.org, tds.hycom.org | none | 3 h / 24 h |
| argo | `collectors/argo.py` | ERDDAP tabledap CSV | erddap.ifremer.fr | none | hourly |
| gosud | `collectors/gosud.py` | ERDDAP tabledap CSV | erddap.ifremer.fr | none | hourly |
| osmc | `collectors/osmc.py` | ERDDAP tabledap CSV | osmc.noaa.gov | none | hourly |
| (woa23) | `collectors/woa.py` | THREDDS NCSS CSV | www.ncei.noaa.gov | none | on point query |
| windy | `collectors/windy.py` | REST JSON POST | api.windy.com | API key | 3 h |

Sources in parentheses are not scheduled; they are called only when a point is inspected.

## Common rules

- Every request goes through `Fetcher` in `http.py`: 2–4 concurrent connections per host, 20 s connect / 60–300 s read timeouts,
  up to three attempts with 2 s and 4 s back-off on 500/502/503/504 and transport errors; HTTP 429 is never retried but raised as
  `RateLimited`, which pauses the source for at least an hour.
- The User-Agent is `suya/<version> (Antarctic ocean monitor; https://github.com/jongsu-king/SUYA)` so operators of public servers can identify the traffic.
- All times are normalised to UTC `YYYY-MM-DDTHH:MM:SSZ` (`collectors/base.py: to_iso_utc`).
- Numbers pass through `finite()` (NaN and infinities dropped) and a per-variable physical range check.

## 1. METAR — NOAA Aviation Weather Center

- URLs: `https://aviationweather.gov/api/data/metar?ids=NZSP,NZCM,NZFX,NZWD,NZPG,NZIR,SAWB,SCRM&format=json&hours=6`
  merged with `…?bbox=-90,-180,-60,180&format=json&hours=6`, because the bounding box alone was seen to miss stations.
- Fields: `temp` (°C), `dewp` (°C), `slp` or `altim` (hPa), `obsTime` (epoch), position, station name.
- Stored as `source=metar`, `dataset=<ICAO>`, `location_id=metar:<ICAO>`, `quality=<station name>`.
- Stations: NZSP Amundsen-Scott (South Pole), NZCM McMurdo/Williams Field, NZFX Phoenix Field, NZWD Williams Field, SAWB Marambio (Argentina), SCRM Frei (Chile). NZPG and NZIR are closed but kept in case reports resume.
- Limits: reporting intervals differ per station (30–60 min); the South Pole often omits the dew point; King Sejong and Jang Bogo do not publish METAR on the public network.

## 2. Open-Meteo — GFS, model forecasts, marine, ERA5

### 2-1. Current conditions (`openmeteo_current`)
- `https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&current=temperature_2m,apparent_temperature,dew_point_2m,wet_bulb_temperature_2m,surface_temperature,relative_humidity_2m,surface_pressure,wind_speed_10m&models=gfs_global&timezone=UTC`
- The 24 points are sent as comma-separated lists in one request (counted as 24 calls).
- GFS 0.25°, interpolated to 15-minute "current" values. Model output, not observations.

### 2-2. Model forecasts (`openmeteo_forecast`)
- `hourly=temperature_2m&models=gfs_global,ecmwf_ifs025,icon_global,gem_global,jma_gsm&forecast_days=7&past_days=1`
- Models: NOAA GFS 0.25°, ECMWF IFS 0.25°, DWD ICON 0.125°, ECCC GEM 0.15°, JMA GSM 0.5°.
- Stored with `kind=forecast`; `prune()` deletes forecasts older than 30 days.

### 2-3. GFS air-temperature grid (`gfs_grid`)
- 2.5° latitude × 10° longitude from 87.5°S to 50°S (16 × 36 = 576 points) plus the pole. Requested in chunks of 100 with a 5 s pause.
- Runs only while 30 % of the daily budget remains (`consume_budget(reserve=0.3)`) so other sources never starve.

### 2-4. Marine SST (`openmeteo_marine`)
- `https://marine-api.open-meteo.com/v1/marine?…&current=sea_surface_temperature`
- If the response `elevation` is above 0 the cell is **land** and the value is discarded; a cell at 1023 m elevation really returned −1.8 °C. "No data is available for this location" is treated as missing.

### 2-5. ERA5 (on point query)
- `https://archive-api.open-meteo.com/v1/archive?…&daily=temperature_2m_mean,temperature_2m_min,temperature_2m_max`
- Last 30 days (end date two days ago). Reanalysis, 1–5 days behind.

### 2-6. Budget
- The free tier allows 10,000 calls per day (one point = one call). `MONITOR_OPENMETEO_DAILY_BUDGET` (default 9,000) is counted per day in the `kv` table; exceeding it raises `BudgetExceeded` (a `RateLimited`) and pauses for an hour. A point query on the air tab costs 3 calls, ERA5 one.
- Terms: CC BY 4.0, free for non-commercial use, attribution "Weather data by Open-Meteo.com" required.

## 3. ERDDAP — OISST, SMOS, SMAP, MUR

### Common
- The latest time is asked first: `griddap/<dataset>.json?time[(last)]`. If it equals `token:<source>` in `kv`, nothing is downloaded and the run ends as "Unchanged".
- If it is newer, `time[(token):1:(latest)]` lists what appeared since the last run. Missed days are fetched oldest first, three per run and at most the latest seven; the rest continue 30 seconds later. The token moves only as far as what was stored, so an interrupted run leaves no gap, and a day the server cannot deliver is skipped once a later day has arrived. The first run ever takes only the latest day.
- Grid request: `var[(time)][(0.0)][(-89.875):2:(-40.125)][(-179.875):2:(179.875)]` — stride 2, i.e. 0.5°, from 90°S to 40°S. About 1 MB of JSON per variable.
- Grids are stored gzip-compressed in `grids`; `grid_stats()` adds the area-weighted mean, min, max, valid ratio, 2nd/98th percentiles and sector means south of 60°S.
- Values at the ten sea areas are also sampled into `measurements`.

### 3-1. OISST v2.1 (`oisst`)
- Dataset `ncdcOisst21NrtAgg_LonPM180` at coastwatch.pfeg.noaa.gov. Variables `sst` (°C), `anom` (°C vs the 1971–2000 OI SST V2 climatology), `ice` (0–1), `err`.
- Near-real-time aggregate: one value per day, 1–2 days behind; values younger than two weeks are preliminary.
- Ranges: sst −3…40, anom −15…15, ice 0…1.
- nullschool's SST layer alternates between OISST, OSTIA and RTGSST; OISST is the one published through ERDDAP.

### 3-2. SMOS (`smos`) / SMAP (`smap`)
- `noaacwSMOSsss3day` (3-day composite) and `noaacwSMAPsssDaily` at coastwatch.noaa.gov, variable `sss` (PSU).
- **Values outside 28–37 PSU are dropped**; SMAP responses contained 0.00 and 42.83. L-band sensitivity falls in cold water (< 5 °C) and cells within 40–100 km of ice or coast are missing. Measured valid fractions were 20–35 % at 60–65°S and 0–11 % south of 65°S.
- That is why the program points to HYCOM for a salinity **map** and to Argo for salinity **measurements**.

### 3-3. MUR SST (on point query)
- `jplMURSST41` at coastwatch.pfeg.noaa.gov: `analysed_sst`, `analysis_error`, `sea_ice_fraction`; 0.01°, daily.
- The server often answers 503, in which case the point inspector shows "No response: MUR".

## 4. HYCOM ESPC-D-V02 — US Navy global ocean prediction

- Datasets `FMRC_ESPC-D-V02_t3z_best.ncd` (`water_temp`, °C) and `FMRC_ESPC-D-V02_s3z_best.ncd` (`salinity`, PSU). 1/12° (0.08° lon × 0.04° lat), 40 levels 0–5000 m, 3-hourly analysis plus an 8-day forecast.
- Access: OPeNDAP `.ascii` subsets, e.g. `…_best.ncd.ascii?salinity[60][0][0:12:1000][0:6:4499]` = time index 60, depth 0 m, latitude 80°S–40°S every 12 cells (0.48°), every 6th longitude (0.48°).
- The time axis is `hours since <analysis time>`; the origin is read from `.das` and the index nearest to now is used. Identical times are not re-downloaded (`token:hycom_salt_0` etc.).
- Hosts: `ncss.hycom.org` first, then `tds.hycom.org`. `tds` was seen to return 500 for some requests (small latitude ranges, the full `time` axis). One grid takes 3–30 s.
- The twelve map grids (2 variables × 6 depths) are fetched in parallel; partial failures keep what succeeded.
- Point profiles (`fetch_profile`) read one column `[time][0:1:39][lat][lon]`; even with both variables in parallel this takes 30–60 s. NaN means land or ice shelf in the model grid.
- Ranges: temperature −3…40, salinity 20…42. Nothing south of 80°S.
- License: open; credit the HYCOM consortium and the US Naval Research Laboratory.

## 5. Argo — float profiles

- Dataset `ArgoFloats` at erddap.ifremer.fr (tabledap, CSV).
- Listing: `platform_number,cycle_number,direction,time,latitude,longitude,data_mode,position_qc,pres,pres_qc,pres_adjusted,pres_adjusted_qc,temp,temp_qc,psal,psal_qc,temp_adjusted,…&latitude<=-55&time>=now-30days&pres<=100&orderByMin("platform_number,cycle_number,direction,pres")` — for every cycle and direction the row with the lowest pressure within 100 dbar; when a cycle has both an ascending and a descending cast the ascending one is used; about 600 profiles per 30 days at the time of writing.
- Levels: `…&platform_number="<id>"&cycle_number=<n>` per profile, 120 profiles per run newest first; if more remain the job reruns after 30 s (`backlog`).
- **Quality rules** (`argo.select_value`):
  - In `data_mode` A (real-time adjusted) or D (delayed) the `*_adjusted` value and `*_adjusted_qc` are used; in R the raw value and `*_qc`.
  - Only QC flags `1` (good) and `2` (probably good) are accepted; `3`, `4`, `8`, `9` are dropped.
  - When an ascending profile (`direction=A`) exists, descending data is ignored.
  - Temperature −3…40 °C, salinity 20…42 PSU, pressure 0…12000 dbar.
  - Real case: float 1902223 cycle 282 reported `psal=0.014, psal_qc=4`. Without the flag check a salinity of zero ends up on the chart.
- **Surface value** (`seawater.surface_values`): the surface temperature and salinity of a profile are the shallowest stored level within 100 dbar that has the value, chosen separately for temperature and salinity; the measurement row records that level's depth in `depth_m`. A profile with nothing usable within 100 dbar gets no surface row. The listed value is only a stand-in until the levels arrive, and it is not used when the pressure flag of the listed row is bad.
  - Earlier versions stored the first listed row as the surface value. On the first collection after the upgrade the surface rows of every profile that has levels are chosen again, once (guarded by `argo:surface` in `kv`). Case seen on a copy of a real database (2026-11-11): float 6903128 cycle 178, surface salinity 27.581 → 33.995 (at 5.5 m).
- Pressure (dbar) is converted to depth (m) with Saunders & Fofonoff (1976).
- `position_qc=8` marks profiles whose position was estimated under sea ice; the UI says "estimated position".
- When delayed-mode data appears later, the changed `data_mode` triggers a re-download of the levels.
- Required acknowledgement: "These data were collected and made freely available by the International Argo Program and the national programs that contribute to it." (doi:10.17882/42182)

## 6. GOSUD — underway ship data

- Dataset `gosud` at erddap.ifremer.fr: `SSTP` (SST), `SSPS` (surface salinity) with `_QC` flags and `ship_call_sign`.
- Request: `latitude<=-50&time>=now-30days&orderByLimit("ship_call_sign,time/1hour,1")` — one point per ship per hour.
- QC 1 and 2 only. Real case: 26 °C at 59°S with flag 4.
- Only ships with a thermosalinograph report salinity.

## 7. OSMC — real-time in situ reports from the GTS

- Dataset `OSMC_30day` at osmc.noaa.gov (tabledap, CSV): the last 30 days of in situ reports that reached the Global Telecommunication System (GTS), gathered by NOAA's Observing System Monitoring Center. The dataset metadata states CC0 1.0.
- Platforms: drifting buoys, ice buoys, ships, uncrewed surface vehicles and tagged animals (such as seals carrying sensors). `PROFILING FLOATS AND GLIDERS` is left out of the request because Argo (section 5) covers it.
- Values: surface `sst` (°C) and `sss` (PSU); `observation_depth` (m) with `ztmp` and `zsal`; weather `atmp`, `dewpoint` (°C) and `slp` (hPa).
- Request: four queries, one after another, each with the common constraints `latitude<=-50&time>=now-<N>days&platform_type!="PROFILING FLOATS AND GLIDERS"`. One collection takes about 50 s.

  | Columns | Value constraint | Thinning |
  |---|---|---|
  | `observation_depth,ztmp,zsal` | `ztmp>=-5` | `orderByLimit("platform_code,observation_depth,time/1hour,1")` |
  | `sst` | `sst>=-5` | `orderByLimit("platform_code,time/1hour,1")` |
  | `sss` | `sss>=0` | same |
  | `atmp,dewpoint,slp` | `slp>=800` | same |

  - One point per platform per hour (per depth for the depth values).
  - Filtering missing values with `!=NaN` makes the server answer 500, so a lower bound on the value is used instead. As a result, depth reports with salinity but no temperature and weather reports with air temperature but no pressure are not fetched.
  - A 404 the server sends when it briefly cannot find the dataset is recorded as a failure, not as "no observations". Only "Your query produced no matching results" counts as an empty result.
- Window: the full 30 days once a day and only the last 3 days in between (`osmc:last_full` in `kv`). Reports that arrive late are filled in by the next full collection.
- **Quality rules** (`osmc.read_reports`, `osmc.stuck_hours`, `osmc.build_rows`): the dataset carries no QC flags, so values are screened by range and position only.
  - Dropped outside: temperature −3…40 °C, salinity 20…42 PSU, depth 0…12000 m, air temperature and dew point −95…30 °C, sea-level pressure 890…1070 hPa. A dew point above the air temperature drops both.
  - Sea values are kept only north of 79°S; farther south is ice shelf or continent. Weather values have no such limit.
  - Reports dated more than 6 hours after the collection time are treated as a wrong clock and dropped.
  - **Stuck drifting buoys**: when twelve consecutive hourly reports stay within 0.002° in both latitude and longitude, the buoy is taken to be aground or recovered and its sea values for those hours are dropped. Sea values already stored for those hours are deleted as well (`Store.delete_measurements`). Weather values are kept. The rule applies to drifting buoys only, because a ship at anchor is expected to stay put.
  - Real cases (2026-11-11): drifting buoy 2802071 had not moved for 712 hours. None of its sea values were stored; its sea-level pressure agreed with neighbouring buoys within 1 hPa and was kept. Platform 1897495 reported 44.38 °C with salinity 76.84 at 29.2 m and 12.34 °C at 1725 m from 88.0°S, and failed both the range and the position rule. Ship 2KZJ7DD reported a sea-level pressure of 868.9 hPa, outside the range.
- Stored as `source=osmc`, `dataset=<platform_code>`, `quality=<platform_type>`, `kind=observation`. Surface values use `level=surface`, depth values `level=depth:<m>` with `depth_m` (depth 0 becomes `surface`), weather values `level=2m`. `2m` only matches the notation of the other weather sources; it is not the sensor height (buoys sit near the waterline, ships carry sensors higher up).
- Use: the Excel sheets `OSMC obs` and `Ion composition`. The point query shows the nearest temperature and salinity within 300 km, the last 30 days and the top 10 m, one line each. OSMC values are not used for the representative value or the monthly summary.
- Real collection (2026-11-11, full 30 days): 46,096 rows from 71 platforms. Drifting buoys 40 / 37,165 rows, ships 20 / 4,770, ice buoys 3 / 2,144, uncrewed surface vehicle 1 / 1,511, tagged animals 7 / 506. By variable: surface temperature 27,031 rows, sea-level pressure 15,287, air temperature 1,693, dew point 1,172, surface salinity 407 (a single uncrewed surface vehicle), temperature and salinity at depth 253 each (tagged animals).
- Limits: the values are not quality controlled, so an isolated bad value stays. Cases seen: 13.57 °C at 61.7°S, the only report of drifting buoy 7810718, and 9.54 °C as the first report of ice buoy 4804098 (−1.24 °C in the next one). A check against the neighbouring values in time caught nothing in this data and was not added. When surveyed, only one platform, an uncrewed surface vehicle, reported surface salinity.

## 8. World Ocean Atlas 2023 (on point query)

- `https://www.ncei.noaa.gov/thredds-ocean/ncss/grid/woa23/DATA/<temperature|salinity>/netcdf/decav/0.25/woa23_decav_<t|s><MM>_04.nc?var=<t|s>_an&latitude=…&longitude=…&accept=csv`
- `decav` = 1955–2022 average, 0.25°. Monthly files (`01`–`12`) stop at 1500 m, the annual file (`00`) reaches 5500 m, so deeper levels come from the annual mean.
- `_an` = objectively analysed value; NaN on land.

## 9. Windy Point Forecast API (optional)

- `POST https://api.windy.com/api/point-forecast/v2` with JSON `{lat, lon, model, parameters:[temp,dewpoint,rh,pressure], levels:[surface,1000h,…,150h], key}`.
- Response: `ts` (ms epoch), `units`, `temp-surface`, `temp-850h`, …; kelvin and pascal are converted to °C and hPa.
- **Testing (free) keys**: 500 calls per day and, per Windy's pricing page, "randomly shuffled and slightly modified data". Values are stored with `quality=windy_testing_shuffled` and charted as "(altered)". Professional keys allow 10,000 calls per day.
- The API offers no water temperature or salinity (confirmed in the documentation and Windy community answers). Models include GFS, ICON and AROME; ECMWF is excluded for licensing reasons.
- The website's internal endpoints are never used: Windy's general terms §4.6.1 prohibit automated collection and crawling.

## 10. Not used, and why

| Candidate | Reason |
|---|---|
| nullschool internal data files | No public API; the About page refers licensing to inquiries@nullschool.net. The upstream data (GFS, OISST) is fetched directly |
| Windy website endpoints | Prohibited by the terms of use |
| Copernicus Marine (GLORYS12, ARMOR3D, OSTIA) | Requires an account. With one, an adapter can be added under `collectors/` |
| MEOP marine-mammal CTD | The best in-situ salinity under ice, but the quality-controlled data is distributed as files without a real-time API. The real-time values that reach the GTS are collected through OSMC (section 7) |
| NSIDC sea-ice concentration | Covered by OISST `ice` and MUR `sea_ice_fraction` |
| IEM METAR archive | AWC serves recent reports directly; a candidate if history is needed |

## 11. Where values are stored

| Table | Contents | Key |
|---|---|---|
| `measurements` | Point values: source, dataset, variable, kind (observation/satellite/analysis/model/forecast/climatology), lat, lon, level, depth_m, pressure_hpa, obs_time, value, unit, location_id, quality | (source, dataset, variable, lat, lon, level, obs_time) |
| `grids` | Map-layer snapshots (gzip JSON) with statistics | (layer, valid_time) |
| `argo_profiles` | Profile listing and level JSON | (platform, cycle) |
| `seawater_ions` | Reference salinity and the eight major ions in g/kg, derived for every salinity row, and the range-check verdict `salinity_check` (section 12); triggers keep it in step with `measurements` | (source, dataset, lat, lon, level, obs_time) |
| `seawater_ions_mmol` (view) | The same rows in mmol/kg | |
| `argo_level_ions` (view) | Temperature, salinity, derived ions in g/kg and the range-check verdict per Argo level; uses no storage | |
| `grid_ions` (view) | Reference salinity, ions in g/kg and mmol/kg and the range-check verdict derived from the mean south of 60°S and each sector mean of every salinity grid; uses no storage | |
| `runs` / `source_state` | Collection history, next run, consecutive errors | |
| `kv` | Source tokens, daily budgets, Excel stamp | |

Variable names: `sea_water_temperature`, `sea_water_salinity`, `sst_anomaly`, `sea_ice_fraction`, `sst_uncertainty`, `air_temperature`, `apparent_temperature`, `dew_point`, `wet_bulb_temperature`, `surface_temperature`, `relative_humidity`, `surface_pressure`, `sea_level_pressure`, `wind_speed`.

## 12. Ion composition derived from salinity

Not fetched from a remote service: SUYA computes it from the stored salinity (`composition.py`).
The major ions dissolved in seawater keep nearly the same ratios in every ocean, so one practical salinity S_P gives the amount of each ion.

- Reference salinity: S_R = (35.16504 / 35) × S_P [g/kg]
- Amount of ion i: S_R × (mass fraction of i in the Reference Composition) [g/kg]; divided by the molar mass it is [mmol/kg]. The kg is one kilogram of seawater.
- Chlorinity: S_P / 1.80655 [g/kg]. Ionic strength, per kg of water [mol/kg], is shown only in the window and by `suya ions`.
- Mass fractions and molar masses: Millero, Feistel, Wright, McDougall (2008), "The composition of Standard Seawater and the definition of the Reference-Composition Salinity Scale", Deep-Sea Research I 55, 50–72 (doi:10.1016/j.dsr.2007.10.001).

Eight components are stored in the database and in Excel; together they are 99.85 % of the dissolved salt by mass. The other seven (B(OH)₃, CO₃²⁻, Sr²⁺, B(OH)₄⁻, F⁻, OH⁻, CO₂) appear in the *Ion composition* tab, the *Ion factors* sheet and `suya ions`.

| Component | Symbol | DB column | Mass share % | g/kg at salinity 35 | mmol/kg at salinity 35 |
|---|---|---|---|---|---|
| Chloride | Cl⁻ | `chloride_g_kg` | 55.0340 | 19.3527 | 545.870 |
| Sodium | Na⁺ | `sodium_g_kg` | 30.6596 | 10.7815 | 468.967 |
| Sulfate | SO₄²⁻ | `sulfate_g_kg` | 7.7132 | 2.7123 | 28.235 |
| Magnesium | Mg²⁺ | `magnesium_g_kg` | 3.6506 | 1.2837 | 52.817 |
| Calcium | Ca²⁺ | `calcium_g_kg` | 1.1719 | 0.4121 | 10.282 |
| Potassium | K⁺ | `potassium_g_kg` | 1.1350 | 0.3991 | 10.208 |
| Bicarbonate | HCO₃⁻ | `bicarbonate_g_kg` | 0.2980 | 0.1048 | 1.718 |
| Bromide | Br⁻ | `bromide_g_kg` | 0.1913 | 0.0673 | 0.842 |

**Limits.** These are derived values, not measurements.

- Real seawater differs slightly from the Reference Composition. Any error in a satellite or model salinity carries over to the ion amounts in the same proportion.
- Where sea ice forms or melts (brine) and where river or glacial meltwater mixes in, the ion ratios themselves can change; this conversion does not model that.
- The carbonate and borate species (HCO₃⁻, CO₃²⁻, B(OH)₃, B(OH)₄⁻, CO₂, OH⁻) are the Reference Composition values for standard conditions and do not follow the actual speciation with temperature and pH.
- Rows with no salinity, or a salinity of zero or less, are not converted.

Storage: whenever a salinity row is inserted into, changed in or deleted from `measurements`, triggers bring the row with the same key in `seawater_ions` in line. The first start after the upgrade fills in every salinity row already stored, once (guarded by `ions:method` in `kv`).
Argo level salinities are stored once, in `argo_profiles`; the view `argo_level_ions` computes the ion amounts when it is read, so the same hundreds of thousands of rows are not kept a second time.

### Salinity range check

Every stored salinity is compared with the range that can occur at its depth and labelled (`ranges.py`). **No value is dropped or changed.**

- Ranges: Boyer, T. and S. Levitus (1994), *Quality Control and Processing of Historical Oceanographic Temperature, Salinity, and Oxygen Data*, NOAA Technical Report NESDIS 81, Appendix A, Table 3f (Southern Ocean): a minimum and a maximum for each of 33 standard depths from 0 to 5500 m. <https://repository.library.noaa.gov/view/noaa/13443/noaa_13443_DS1.pdf>
- Depth windows: following the same report, the range of a standard depth applies upward for 3/4 of the distance to the previous standard depth and downward for 1/4 of the distance to the next. Example: the 100 m range (30.5–36.5) applies deeper than 81.25 m and down to 106.25 m. A row with no depth uses the surface (0 m) range.
- Result: `ok`, `low` or `high` in `seawater_ions.salinity_check` and `argo_level_ions.salinity_check`. In Excel the *Range check* column is filled only where the value is outside (`low` / `high`), and the *Salinity ranges* sheet lists the table. `ions:check` in `kv` holds the edition of the table (`boyer1994-so/1`); if the table changes, every row is judged again once.
- Limits: the report makes the ranges broad on purpose, so only gross errors are caught. The window down to 2.5 m is 0–40, so surface values are practically never labelled, and a value inside the range is not thereby confirmed. The Southern Ocean table is applied to every stored salinity whatever its latitude (the basin boundary was not found in the report).
- Seen on a copy of a real database (2026-11-11): all 4,007 point rows were `ok`; of the 525,907 rows of `argo_level_ions`, 1,647 were `high` (1,597 levels of float 7900928 at 325–1,246 m and 50 levels of float 7901081 at 345–511 m) and none `low`.

### Volume basis (mmol/L)

mmol/kg times the density of the seawater gives mmol/L: mmol/L = mmol/kg × ρ / 1000.

- Density ρ: the density at 1 atm for the row's salinity and temperature (Millero & Poisson 1981, `seawater.density_surface`); 1027.675 kg/m³ at salinity 35 and 5 °C.
- Temperature: the temperature row with the same source, dataset, position, level and time. A salinity row without such a partner leaves density and mmol/L blank. Computed only for −3…40 °C and salinity up to 42.
- In-situ pressure is not included; the real density of deep water is higher (about 0.4 % at 1000 m).
- Not stored in the database: the *Ion composition* sheet, `suya export ions` and `suya ions --temperature` compute it when they read. The Argo levels workbook and `argo_level_ions` do not carry it.
- Seen on a copy of a real database (2026-11-11): 4,000 of the 4,007 point rows had a paired temperature.

### Ion conversion of the whole-area grids

Besides the point values, the salinity grids behind the map (`hycom_salt_<depth>`, `smos_sss`, `smap_sss`) are converted with the same factors. The conversion is proportional to salinity, so converting a mean salinity gives the same result as converting every cell and averaging with the same weights.

- Area means: for every grid time the view `grid_ions` gives the reference salinity, the eight major ions in g/kg and mmol/kg and the range-check verdict, derived from the mean salinity of the whole area south of 60°S (`area` = `all`) and of the five sectors (`weddell`, `indian`, `west_pacific`, `ross`, `amundsen_bell`). A sector without a mean has no row. The *Grid ions* sheet carries that month's rows.
- Cell values: `suya export grid-ions --layer <layer> --out <file>` and the menu entry *File > Export CSV > Current layer ions…* write one row for every cell that has a value in the latest grid of the layer. Columns: `valid_time`, `lat`, `lon`, `depth_m`, `practical_salinity`, `reference_salinity`, `_g_kg` and `_mmol_kg` for the eight ions, and `salinity_check`. The values are not rounded, and cells north of 60°S are included (the area means cover only the area south of 60°S). A layer that is not a salinity layer, or one not collected yet, is refused.
- Map: on a salinity layer the *Show* box selects an ion and a unit (g/kg or mmol/kg); the colour-bar ticks, the cursor value and the caption then give that ion's concentration. Colours and pattern are those of the salinity map.
- Storage: neither cell nor area ion amounts are stored. They are computed from the grids and statistics in `grids` whenever they are read; one grid has tens of thousands of cells, so storing them would keep the same information several times over.
- Limits: the mean salinities are stored in the statistics with three decimals, so a rounding error of up to 0.0005 PSU carries into the ion amounts. No paired temperature is used, so there is no mmol/L. The range check uses the depth of the layer (0 m for satellite salinity); the surface range is 0–40, so satellite salinity and the 0 m level are practically never labelled. This is the salinity map read on another scale, not a map of measured ions, and the limits above apply unchanged.
- Seen on a copy of a real database (2026-11-11): none of the 1,493 rows of `grid_ions` (1,481 in the 2026-11 sheet) was labelled. The cell CSV had 49,949 rows for `hycom_salt_0`, 42,597 for `hycom_salt_2000`, 29,624 for `smos_sss` and 22,565 for `smap_sss`, and every row equalled the grid value times the factor.
