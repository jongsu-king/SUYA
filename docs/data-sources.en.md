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
- Listing: `platform_number,cycle_number,time,latitude,longitude,data_mode,position_qc,pres,temp,temp_qc,psal,psal_qc,temp_adjusted,…&latitude<=-55&time>=now-30days&pres<=100&orderByLimit("platform_number,cycle_number,1")` — the shallowest level of every profile; about 600 profiles per 30 days at the time of writing.
- Levels: `…&platform_number="<id>"&cycle_number=<n>` per profile, 60 profiles per run newest first; if more remain the job reruns after 30 s (`backlog`).
- **Quality rules** (`argo.select_value`):
  - In `data_mode` A (real-time adjusted) or D (delayed) the `*_adjusted` value and `*_adjusted_qc` are used; in R the raw value and `*_qc`.
  - Only QC flags `1` (good) and `2` (probably good) are accepted; `3`, `4`, `8`, `9` are dropped.
  - When an ascending profile (`direction=A`) exists, descending data is ignored.
  - Temperature −3…40 °C, salinity 20…42 PSU, pressure 0…12000 dbar.
  - Real case: float 1902223 cycle 282 reported `psal=0.014, psal_qc=4`. Without the flag check a salinity of zero ends up on the chart.
- Pressure (dbar) is converted to depth (m) with Saunders & Fofonoff (1976).
- `position_qc=8` marks profiles whose position was estimated under sea ice; the UI says "estimated position".
- When delayed-mode data appears later, the changed `data_mode` triggers a re-download of the levels.
- Required acknowledgement: "These data were collected and made freely available by the International Argo Program and the national programs that contribute to it." (doi:10.17882/42182)

## 6. GOSUD — underway ship data

- Dataset `gosud` at erddap.ifremer.fr: `SSTP` (SST), `SSPS` (surface salinity) with `_QC` flags and `ship_call_sign`.
- Request: `latitude<=-50&time>=now-30days&orderByLimit("ship_call_sign,time/1hour,1")` — one point per ship per hour.
- QC 1 and 2 only. Real case: 26 °C at 59°S with flag 4.
- Only ships with a thermosalinograph report salinity.

## 7. World Ocean Atlas 2023 (on point query)

- `https://www.ncei.noaa.gov/thredds-ocean/ncss/grid/woa23/DATA/<temperature|salinity>/netcdf/decav/0.25/woa23_decav_<t|s><MM>_04.nc?var=<t|s>_an&latitude=…&longitude=…&accept=csv`
- `decav` = 1955–2022 average, 0.25°. Monthly files (`01`–`12`) stop at 1500 m, the annual file (`00`) reaches 5500 m, so deeper levels come from the annual mean.
- `_an` = objectively analysed value; NaN on land.

## 8. Windy Point Forecast API (optional)

- `POST https://api.windy.com/api/point-forecast/v2` with JSON `{lat, lon, model, parameters:[temp,dewpoint,rh,pressure], levels:[surface,1000h,…,150h], key}`.
- Response: `ts` (ms epoch), `units`, `temp-surface`, `temp-850h`, …; kelvin and pascal are converted to °C and hPa.
- **Testing (free) keys**: 500 calls per day and, per Windy's pricing page, "randomly shuffled and slightly modified data". Values are stored with `quality=windy_testing_shuffled` and charted as "(altered)". Professional keys allow 10,000 calls per day.
- The API offers no water temperature or salinity (confirmed in the documentation and Windy community answers). Models include GFS, ICON and AROME; ECMWF is excluded for licensing reasons.
- The website's internal endpoints are never used: Windy's general terms §4.6.1 prohibit automated collection and crawling.

## 9. Not used, and why

| Candidate | Reason |
|---|---|
| nullschool internal data files | No public API; the About page refers licensing to inquiries@nullschool.net. The upstream data (GFS, OISST) is fetched directly |
| Windy website endpoints | Prohibited by the terms of use |
| Copernicus Marine (GLORYS12, ARMOR3D, OSTIA) | Requires an account. With one, an adapter can be added under `collectors/` |
| MEOP marine-mammal CTD | The best in-situ salinity under ice, but distributed as files without a real-time API |
| NSIDC sea-ice concentration | Covered by OISST `ice` and MUR `sea_ice_fraction` |
| IEM METAR archive | AWC serves recent reports directly; a candidate if history is needed |

## 10. Where values are stored

| Table | Contents | Key |
|---|---|---|
| `measurements` | Point values: source, dataset, variable, kind (observation/satellite/analysis/model/forecast/climatology), lat, lon, level, depth_m, pressure_hpa, obs_time, value, unit, location_id, quality | (source, dataset, variable, lat, lon, level, obs_time) |
| `grids` | Map-layer snapshots (gzip JSON) with statistics | (layer, valid_time) |
| `argo_profiles` | Profile listing and level JSON | (platform, cycle) |
| `runs` / `source_state` | Collection history, next run, consecutive errors | |
| `kv` | Source tokens, daily budgets, Excel stamp | |

Variable names: `sea_water_temperature`, `sea_water_salinity`, `sst_anomaly`, `sea_ice_fraction`, `sst_uncertainty`, `air_temperature`, `apparent_temperature`, `dew_point`, `wet_bulb_temperature`, `surface_temperature`, `relative_humidity`, `surface_pressure`, `wind_speed`.
