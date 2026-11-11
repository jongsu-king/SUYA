# Third-party notices / 제3자 고지

The program source is MIT licensed (see `LICENSE`); that license covers the code only. The data the
program downloads belongs to the organisations that publish it. Everything below is owned by others and
comes with its own terms. If you redistribute the program or publish results made with it,
keep these attributions.

프로그램 소스는 MIT 라이선스입니다(`LICENSE`). 아래 항목은 각 기관·저자의 것이며 고유한 조건이 있습니다.
프로그램을 재배포하거나 이 프로그램으로 만든 결과를 공개할 때는 아래 출처 표기를 유지하세요.

## Data services the program calls at run time / 실행 중 호출하는 데이터 서비스

| Data | Provider | Terms / 조건 |
|---|---|---|
| GFS current conditions, multi-model forecasts, ERA5 archive, marine SST | [Open-Meteo](https://open-meteo.com/) (serving NOAA GFS, ECMWF IFS, DWD ICON, ECCC GEM, JMA GSM, ECMWF ERA5) | [CC BY 4.0](https://open-meteo.com/en/terms). Non-commercial free tier, 10,000 calls/day. Attribution required: "Weather data by Open-Meteo.com". |
| METAR station reports | [NOAA Aviation Weather Center](https://aviationweather.gov/data/api/) | US Government work, public domain. |
| OISST v2.1 (SST, anomaly, sea ice) | NOAA NCEI via [CoastWatch ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/) | Public domain. Cite: Huang et al. (2021), *J. Climate*, doi:10.1175/JCLI-D-20-0166.1. |
| MUR SST v4.1 | NASA JPL PO.DAAC via CoastWatch ERDDAP | Open. Cite: JPL MUR MEaSUREs Project (2015), doi:10.5067/GHGMR-4FJ04. |
| SMOS sea surface salinity | ESA SMOS, distributed by NOAA CoastWatch | Open for research; attribute ESA and NOAA CoastWatch. |
| SMAP sea surface salinity | NASA / RSS, distributed by NOAA CoastWatch | Open; attribute NASA and NOAA CoastWatch. |
| HYCOM ESPC-D-V02 global analysis | US Naval Research Laboratory via [HYCOM.org](https://www.hycom.org/) | Open. Cite HYCOM consortium; funding by the US Office of Naval Research. |
| Argo float profiles | [Argo Program](https://argo.ucsd.edu/) via Ifremer ERDDAP | Free. Required acknowledgement: "These data were collected and made freely available by the International Argo Program and the national programs that contribute to it (https://argo.ucsd.edu, https://www.ocean-ops.org). The Argo Program is part of the Global Ocean Observing System." doi:10.17882/42182. |
| GOSUD underway ship data | [GOSUD](https://www.gosud.org/) via Ifremer ERDDAP | Free for research; acknowledge GOSUD and the contributing ships. |
| Real-time in situ reports from the GTS (drifting and ice buoys, ships, uncrewed surface vehicles, tagged animals) | [NOAA OSMC](https://www.osmc.noaa.gov/) via the [OSMC ERDDAP](https://osmc.noaa.gov/erddap/tabledap/OSMC_30day.html) | CC0 1.0 as stated in the dataset metadata. Not quality controlled; acknowledge NOAA OSMC and the platform operators. |
| World Ocean Atlas 2023 | NOAA NCEI | Public domain. Cite Reagan et al. (2024) / Locarnini et al. (2024). |
| Windy Point Forecast API (optional, needs your own key) | [Windy.com](https://api.windy.com/) | Subject to Windy's API terms. The free *testing* tier returns shuffled, altered values and may not be used in production. This program never uses Windy's website endpoints (terms of use §4.6.1). |

## Not used / 쓰지 않는 것

- **earth.nullschool.net** has no public API and its *About* page directs data licensing questions to its
  owner. The program instead downloads the same upstream datasets nullschool renders (GFS, OISST).
- **windy.com** website internals are not called; only the documented Point Forecast API with a user-supplied key.

## Bundled files / 동봉 파일

| File | Origin | License |
|---|---|---|
| `antarctic_monitor/data/southern-land.json` | Coastlines derived from [Natural Earth](https://www.naturalearthdata.com/) 1:50m land via `world-atlas` 2.0.2, clipped south of 36°S | Public domain |
| `antarctic_monitor/data/colormaps.json` | 256-entry tables of the *thermal*, *haline*, *balance* and *ice* colormaps from [cmocean](https://matplotlib.org/cmocean/) (Thyng et al., 2016, *Oceanography* 29(3):9-13) | MIT © Kristen Thyng |
| Seawater formulas in `antarctic_monitor/seawater.py` | UNESCO 1983 (EOS-80): Millero & Poisson 1981 density, Millero 1978 freezing point, Saunders & Fofonoff 1976 depth | Public formulas |

## Python libraries / 파이썬 라이브러리

| Library | License |
|---|---|
| [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) | LGPL-3.0 / GPL-2.0 / commercial. The program uses it unmodified via dynamic linking, which the LGPL permits. |
| [matplotlib](https://matplotlib.org/) | PSF-based license |
| [NumPy](https://numpy.org/) | BSD-3-Clause |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause |
| [XlsxWriter](https://xlsxwriter.readthedocs.io/) | BSD-2-Clause |
| [PyInstaller](https://pyinstaller.org/) (build only) | GPL-2.0 with bootloader exception; built programs are not affected |
