# 데이터 출처 상세

[English version](data-sources.en.md)

SUYA가 호출하는 모든 원격 서비스, 정확한 요청 형태, 받아 오는 변수, 적용하는 품질 규칙, 알려진 한계를 적었습니다.
서비스가 바뀌어 수집이 깨질 때 어디를 고쳐야 하는지 알 수 있도록 코드 위치도 함께 둡니다.

## 요약표

| ID | 코드 | 프로토콜 | 호스트 | 인증 | 기본 주기 |
|---|---|---|---|---|---|
| metar | `collectors/metar.py` | REST JSON | aviationweather.gov | 없음 | 5분 |
| openmeteo_current / forecast / marine, gfs_grid | `collectors/openmeteo.py` | REST JSON | api.open-meteo.com, marine-api.open-meteo.com, archive-api.open-meteo.com | 없음 (무료 10,000/일) | 15분 / 3시간 / 30분 / 3시간 |
| oisst, smos, smap, (mur) | `collectors/erddap.py` | ERDDAP griddap JSON | coastwatch.pfeg.noaa.gov, coastwatch.noaa.gov | 없음 | 6시간 확인 |
| hycom_grid, hycom_profiles | `collectors/hycom.py` | OPeNDAP ascii | ncss.hycom.org, tds.hycom.org | 없음 | 3시간 / 24시간 |
| argo | `collectors/argo.py` | ERDDAP tabledap CSV | erddap.ifremer.fr | 없음 | 1시간 |
| gosud | `collectors/gosud.py` | ERDDAP tabledap CSV | erddap.ifremer.fr | 없음 | 1시간 |
| (woa23) | `collectors/woa.py` | THREDDS NCSS CSV | www.ncei.noaa.gov | 없음 | 지점 조회 시 |
| windy | `collectors/windy.py` | REST JSON POST | api.windy.com | API 키 | 3시간 |

괄호는 주기 수집이 아니라 지점을 조회할 때만 호출하는 소스입니다.

## 공통 규칙

- 모든 요청은 `http.py`의 `Fetcher`를 거칩니다. 호스트별 동시 연결 2~4개, 연결 20초·응답 60~300초 제한, 500/502/503/504와 네트워크 오류는 2초·4초 간격으로 최대 3회 재시도, 429는 재시도하지 않고 `RateLimited`로 올려 1시간 이상 쉽니다.
- User-Agent는 `suya/<버전> (Antarctic ocean monitor; https://github.com/jongsu-king/SUYA)`입니다. 공용 서버 운영자가 트래픽 출처를 알 수 있게 합니다.
- 시각은 모두 UTC `YYYY-MM-DDTHH:MM:SSZ`로 통일해 저장합니다(`collectors/base.py: to_iso_utc`).
- 숫자는 `finite()`로 NaN·무한대를 걸러내고, 변수마다 물리 범위 밖은 버립니다.

## 1. METAR — NOAA Aviation Weather Center

- URL: `https://aviationweather.gov/api/data/metar?ids=NZSP,NZCM,NZFX,NZWD,NZPG,NZIR,SAWB,SCRM&format=json&hours=6`
  와 `…?bbox=-90,-180,-60,180&format=json&hours=6` 두 가지를 합칩니다. bbox만으로는 일부 기지가 빠지는 것을 확인했기 때문입니다.
- 받는 값: `temp`(°C), `dewp`(°C), `slp` 또는 `altim`(hPa), 관측 시각 `obsTime`(epoch), 위치, 기지 이름.
- 저장: `source=metar`, `dataset=<ICAO>`, `location_id=metar:<ICAO>`, `quality=<기지 이름>`.
- 기지: NZSP 아문센-스콧(남극점), NZCM 맥머도 윌리엄스 필드, NZFX 피닉스 필드, NZWD 윌리엄스 필드, SAWB 마람비오(아르헨티나), SCRM 프레이(칠레). NZPG·NZIR는 운영이 끝났지만 목록에 두어 혹시 보고가 오면 받습니다.
- 한계: 기지마다 보고 간격이 다르고(30분~1시간), 남극점은 이슬점이 자주 비어 있습니다. 세종·장보고 기지는 METAR를 공개 네트워크에 보내지 않습니다.

## 2. Open-Meteo — GFS, 모델 예보, 해양, ERA5

### 2-1. 현재값 (`openmeteo_current`)
- URL: `https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&current=temperature_2m,apparent_temperature,dew_point_2m,wet_bulb_temperature_2m,surface_temperature,relative_humidity_2m,surface_pressure,wind_speed_10m&models=gfs_global&timezone=UTC`
- 24개 지점을 쉼표로 묶어 한 번에 요청합니다(호출 수 24로 계산됨).
- GFS 0.25°, 15분 간격으로 보간된 "현재" 값입니다. 관측이 아니라 모델입니다.

### 2-2. 모델별 예보 (`openmeteo_forecast`)
- `hourly=temperature_2m&models=gfs_global,ecmwf_ifs025,icon_global,gem_global,jma_gsm&forecast_days=7&past_days=1`
- 모델: NOAA GFS 0.25°, ECMWF IFS 0.25°, DWD ICON 0.125°, ECCC GEM 0.15°, JMA GSM 0.5°.
- `kind=forecast`로 저장되고 30일 지난 예보는 `prune()`이 지웁니다.

### 2-3. GFS 기온 격자 (`gfs_grid`)
- 2.5° 위도 × 10° 경도, 87.5°S~50°S(16 × 36 = 576점) + 남극점 1점. 100점씩 묶어 요청하고 묶음 사이에 5초 쉽니다.
- 일일 예산의 30%를 남겨 두고만 실행합니다(`consume_budget(reserve=0.3)`). 다른 수집이 예산 부족으로 멈추지 않게 하기 위해서입니다.

### 2-4. 해양 표층 수온 (`openmeteo_marine`)
- `https://marine-api.open-meteo.com/v1/marine?…&current=sea_surface_temperature`
- 응답의 `elevation`이 0보다 크면 **육지 격자**이므로 값을 버립니다. 실제로 해발 1023 m 격자에서 −1.8 °C가 내려왔습니다. "No data is available for this location" 오류도 결측으로 처리합니다.

### 2-5. ERA5 (지점 조회 시)
- `https://archive-api.open-meteo.com/v1/archive?…&daily=temperature_2m_mean,temperature_2m_min,temperature_2m_max`
- 최근 30일(종료일은 2일 전) 일별 기온. 재분석이라 1~5일 지연됩니다.

### 2-6. 예산
- 무료 한도는 하루 10,000 호출(지점 하나 = 1 호출)입니다. `MONITOR_OPENMETEO_DAILY_BUDGET`(기본 9,000)을 DB의 `kv` 표에서 날짜별로 세고, 넘으면 `BudgetExceeded`(RateLimited)로 1시간 쉽니다. 지점 조회(기온 탭)는 3 호출, ERA5는 1 호출을 씁니다.
- 이용 조건: CC BY 4.0, 비상업적 무료. 결과물에 "Weather data by Open-Meteo.com" 표기가 필요합니다.

## 3. ERDDAP — OISST, SMOS, SMAP, MUR

### 공통
- 최신 시각을 먼저 묻습니다: `griddap/<dataset>.json?time[(last)]`. DB `kv`의 `token:<source>`와 같으면 격자를 내려받지 않고 "원천 갱신 없음"으로 끝냅니다.
- 최신 시각이 토큰보다 새로우면 `time[(토큰):1:(최신)]`로 그사이에 나온 시각을 묻고, 빠진 날을 오래된 순으로 한 번에 3개, 최근 7개까지 받습니다. 나머지는 30초 뒤 이어받습니다. 토큰은 저장한 곳까지만 나아가므로 중간에 끊겨도 빈 날이 생기지 않고, 서버가 주지 못하는 날은 그 뒤 날을 받으면 건너뜁니다. 맨 처음 실행은 최신 하루만 받습니다.
- 격자 요청: `var[(time)][(0.0)][(-89.875):2:(-40.125)][(-179.875):2:(179.875)]` — 위도·경도 stride 2로 0.5° 간격, 90°S~40°S. 응답 JSON 한 번에 약 1 MB.
- 격자는 `grids` 표에 gzip JSON으로 저장되고 `grid_stats()`가 60°S 이남 면적 가중 평균·최소·최대·유효 비율·2/98 백분위·해역별 평균을 함께 저장합니다.
- 해역 10곳의 값은 가장 가까운 격자에서 뽑아 `measurements`에도 넣습니다.

### 3-1. OISST v2.1 (`oisst`)
- 데이터셋 `ncdcOisst21NrtAgg_LonPM180` @ coastwatch.pfeg.noaa.gov. 변수 `sst`(°C), `anom`(°C, 1971–2000 OI SST V2 기후값 대비), `ice`(0~1), `err`.
- NRT(near-real-time) 집계라 보통 하루 1값, 1~2일 지연. 2주 이내 값은 잠정치입니다.
- 범위: sst −3~40, anom −15~15, ice 0~1.
- nullschool의 SST 레이어는 OISST, OSTIA, RTGSST 세 가지를 번갈아 쓰는데 그중 OISST가 ERDDAP으로 공개됩니다.

### 3-2. SMOS (`smos`) / SMAP (`smap`)
- `noaacwSMOSsss3day`(3일 합성), `noaacwSMAPsssDaily`(일별) @ coastwatch.noaa.gov. 변수 `sss`(PSU).
- **28~37 PSU 밖은 버립니다.** SMAP 응답에서 0.00과 42.83이 확인되었습니다. 저온(< 5 °C)에서 L-밴드 민감도가 떨어져 오차가 크고, 해빙·연안 40~100 km는 결측입니다. 실측 기준으로 조사한 유효 비율은 60~65°S에서 20~35%, 65°S 이남 0~11%였습니다.
- 그래서 염분 **지도**는 HYCOM을, 염분 **실측**은 Argo를 기준으로 보라고 안내합니다.

### 3-3. MUR SST (지점 조회 시)
- `jplMURSST41` @ coastwatch.pfeg.noaa.gov. 변수 `analysed_sst`, `analysis_error`, `sea_ice_fraction`. 0.01° 해상도, 하루 1값.
- 서버가 종종 503을 돌려주므로 지점 조회 결과에 "응답 없음: MUR"로 표시될 수 있습니다.

## 4. HYCOM ESPC-D-V02 — 미 해군 전구 해양 예측

- 데이터셋: `FMRC_ESPC-D-V02_t3z_best.ncd`(수온 `water_temp`, °C), `FMRC_ESPC-D-V02_s3z_best.ncd`(염분 `salinity`, PSU). 1/12°(0.08° 경도, 0.04° 위도), 40개 층(0~5000 m), 3시간 간격, 분석 + 8일 예보.
- 접근: OPeNDAP `.ascii` 부분 요청. 예: `…_best.ncd.ascii?salinity[60][0][0:12:1000][0:6:4499]` = 시각 인덱스 60, 수심 0 m, 위도 80°S~40°S를 12칸(0.48°)마다, 경도 전체를 6칸(0.48°)마다.
- 시각 축은 `hours since <분석 기준 시각>`이며 `.das`에서 기준을 읽고 현재 시각에 가장 가까운 인덱스를 고릅니다. 같은 시각이면 다시 받지 않습니다(`token:hycom_salt_0` 등).
- 호스트: `ncss.hycom.org`를 먼저, 실패하면 `tds.hycom.org`. tds는 일부 요청(위도 범위가 작은 요청, `time` 전체 요청)에 500을 돌려주는 것을 확인했습니다. 격자 하나에 3~30초 걸립니다.
- 지도용 격자 12개(2변수 × 6수심)는 병렬로 받고, 일부가 실패해도 성공한 것은 저장합니다.
- 지점 프로파일(`fetch_profile`): `[time][0:1:39][lat][lon]` 한 열을 받습니다. 두 변수를 병렬로 요청해도 30~60초 걸립니다. 격자상 육지(NaN)면 "모델 격자상 육지이거나 빙붕입니다".
- 범위: 수온 −3~40, 염분 20~42. 80°S 이남은 모델에 없습니다.
- 라이선스: 공개. HYCOM 컨소시엄과 미 해군연구소(NRL) 출처 표기.

## 5. Argo — 플로트 프로파일

- 데이터셋 `ArgoFloats` @ erddap.ifremer.fr (tabledap, CSV).
- 목록: `platform_number,cycle_number,direction,time,latitude,longitude,data_mode,position_qc,pres,pres_qc,pres_adjusted,pres_adjusted_qc,temp,temp_qc,psal,psal_qc,temp_adjusted,…&latitude<=-55&time>=now-30days&pres<=100&orderByMin("platform_number,cycle_number,direction,pres")` — 사이클과 관측 방향마다 100 dbar 안에서 압력이 가장 낮은 행 하나. 같은 사이클에 상승·하강이 다 있으면 상승 쪽을 씁니다. 조사 당시 30일에 600여 개.
- 층별 값: `…&platform_number="<id>"&cycle_number=<n>` 으로 프로파일 하나씩. 한 번에 120개(최신순)를 받고 남아 있으면 30초 뒤 다시 돌아 밀린 것을 처리합니다(`backlog`).
- **품질 규칙** (`argo.select_value`):
  - `data_mode`가 A(실시간 보정) 또는 D(지연 보정)면 `*_adjusted` 값과 `*_adjusted_qc`를, R이면 원시값과 `*_qc`를 봅니다.
  - QC 플래그 `1`(good), `2`(probably good)만 받습니다. `3`(probably bad), `4`(bad), `8`(estimated), `9`(missing) 등은 버립니다.
  - `direction=A`(상승) 관측이 있으면 하강(D) 관측은 버립니다.
  - 수온 −3~40 °C, 염분 20~42 PSU, 압력 0~12000 dbar 밖은 버립니다.
  - 실제 사례: 플로트 1902223 cycle 282는 `psal=0.014, psal_qc=4` 였습니다. 플래그를 안 보면 염분 0이 그래프에 찍힙니다.
- **표층 값** (`seawater.surface_values`): 프로파일의 표층 수온·염분은 받아 둔 층별 값 가운데 100 dbar 안에서 그 값이 있는 가장 얕은 층입니다. 수온과 염분을 따로 고르고, 측정 행의 `depth_m`에 그 층의 수심을 적습니다. 100 dbar 안에 쓸 값이 없으면 표층 행을 두지 않습니다. 목록의 값은 층별 값을 받기 전까지만 쓰는 임시값이고, 목록 행의 압력 플래그가 나쁘면 쓰지 않습니다.
  - 이전 버전은 목록의 첫 행을 그대로 표층 값으로 적었습니다. 올린 뒤 첫 수집 때 한 번, 층별 값이 있는 프로파일의 표층 행을 다시 고릅니다(`kv`의 `argo:surface`). 실제 DB 사본에서 확인한 사례(2026-11-11): 플로트 6903128 cycle 178의 표층 염분 27.581 → 33.995(5.5 m).
- 압력(dbar)은 Saunders & Fofonoff(1976)로 수심(m)으로 바꿉니다.
- `position_qc=8`은 해빙 아래에서 위치를 추정한 프로파일입니다. 화면에 "추정 위치"로 표시합니다.
- 지연 보정(D)이 나중에 나오면 `data_mode`가 바뀐 것을 감지해 층별 값을 다시 받습니다.
- 출처 표기 의무: "These data were collected and made freely available by the International Argo Program and the national programs that contribute to it." (doi:10.17882/42182)

## 6. GOSUD — 항해 중 선박 관측

- 데이터셋 `gosud` @ erddap.ifremer.fr. 변수 `SSTP`(표층 수온), `SSPS`(표층 염분)와 각 `_QC`, `ship_call_sign`.
- 요청: `latitude<=-50&time>=now-30days&orderByLimit("ship_call_sign,time/1hour,1")` — 선박별 1시간에 1점.
- QC 1·2만. 실제 사례: 59°S에서 26 °C(플래그 4).
- 염분을 보내는 선박은 일부(열염 센서 장착 선박)뿐입니다.

## 7. World Ocean Atlas 2023 (지점 조회 시)

- URL: `https://www.ncei.noaa.gov/thredds-ocean/ncss/grid/woa23/DATA/<temperature|salinity>/netcdf/decav/0.25/woa23_decav_<t|s><MM>_04.nc?var=<t|s>_an&latitude=…&longitude=…&accept=csv`
- `decav` = 1955–2022 전 기간 평균, 0.25°. 월별 파일(`01`~`12`)은 1500 m까지, 연평균 파일(`00`)은 5500 m까지라 깊은 층은 연평균으로 채웁니다.
- `_an` = 객관 분석값. 격자상 육지면 NaN.

## 8. Windy Point Forecast API (선택)

- `POST https://api.windy.com/api/point-forecast/v2` JSON `{lat, lon, model, parameters:[temp,dewpoint,rh,pressure], levels:[surface,1000h,…,150h], key}`.
- 응답 `ts`(ms epoch), `units`, `temp-surface`, `temp-850h` … 켈빈과 파스칼을 °C·hPa로 바꿉니다.
- **testing(무료) 키**: 하루 500회, "randomly shuffled and slightly modified data"를 돌려줍니다(Windy 가격 페이지). 그래서 `quality=windy_testing_shuffled`로 저장하고 그래프에 "(변형값)"이라고 적습니다. professional 키는 하루 10,000회.
- 이 API에는 수온·염분 항목이 없습니다(Windy 커뮤니티 답변과 문서로 확인). 모델은 GFS, ICON, AROME 등이며 ECMWF는 라이선스상 제외됩니다.
- 웹사이트(windy.com)의 내부 엔드포인트는 쓰지 않습니다. 일반 이용약관 4.6.1이 자동화된 수집·크롤링을 금지합니다.

## 9. 쓰지 않는 것과 이유

| 후보 | 이유 |
|---|---|
| nullschool 내부 데이터 파일 | 공개 API 없음. About 페이지는 라이선스를 inquiries@nullschool.net 문의로 안내. 원천(GFS·OISST)을 직접 받음 |
| Windy 웹사이트 내부 주소 | 이용약관 금지 |
| Copernicus Marine (GLORYS12, ARMOR3D, OSTIA) | 계정 로그인 필요. 계정이 있으면 `collectors/`에 어댑터를 추가할 수 있음 |
| MEOP 해양 포유류 CTD | 해빙 아래 염분에 가장 좋은 실측이지만 실시간 API 없이 파일로만 배포 |
| NSIDC 해빙 농도 | OISST의 `ice`와 MUR의 `sea_ice_fraction`으로 대체 |
| IEM(Iowa Environmental Mesonet) METAR 아카이브 | AWC가 최근 자료를 바로 주므로 불필요. 과거 자료가 필요하면 후보 |

## 10. 수집한 값이 저장되는 표

| 표 | 내용 | 키 |
|---|---|---|
| `measurements` | 지점값. source, dataset, variable, kind(observation/satellite/analysis/model/forecast/climatology), lat, lon, level, depth_m, pressure_hpa, obs_time, value, unit, location_id, quality | (source, dataset, variable, lat, lon, level, obs_time) |
| `grids` | 지도 레이어 스냅샷(gzip JSON)과 통계 | (layer, valid_time) |
| `argo_profiles` | 프로파일 목록과 층별 값 JSON | (platform, cycle) |
| `seawater_ions` | 염분 행마다 환산한 기준 염분과 주요 이온 여덟 가지 g/kg, 범위 검사 결과 `salinity_check` (11절). 트리거가 `measurements`와 맞춥니다 | (source, dataset, lat, lon, level, obs_time) |
| `seawater_ions_mmol` (뷰) | 같은 행의 mmol/kg | |
| `argo_level_ions` (뷰) | Argo 층마다 수온·염분, 환산 이온 g/kg, 범위 검사 결과. 저장 공간을 쓰지 않습니다 | |
| `runs` / `source_state` | 수집 기록, 다음 실행 시각, 연속 오류 수 | |
| `kv` | 원천 갱신 토큰, 일일 예산, 엑셀 생성 기준 | |

변수 이름: `sea_water_temperature`, `sea_water_salinity`, `sst_anomaly`, `sea_ice_fraction`, `sst_uncertainty`, `air_temperature`, `apparent_temperature`, `dew_point`, `wet_bulb_temperature`, `surface_temperature`, `relative_humidity`, `surface_pressure`, `sea_level_pressure`, `wind_speed`.

## 11. 염분에서 환산하는 이온 조성

원격 서비스에서 받는 값이 아니라 SUYA가 저장된 염분에서 계산하는 값입니다(`composition.py`).
바닷물에 녹은 주요 이온의 비율은 어느 바다에서나 거의 같다는 성질을 써서, 실용 염분 S_P 하나에서 이온별 양을 환산합니다.

- 기준 염분: S_R = (35.16504 / 35) × S_P [g/kg]
- 이온 i의 양: S_R × (기준 조성에서 i의 질량 분율) [g/kg], 몰질량으로 나누면 [mmol/kg]. kg은 바닷물 1 kg입니다.
- 염소량: S_P / 1.80655 [g/kg]. 이온 세기는 물 1 kg 기준 [mol/kg]으로 화면과 `suya ions`에만 보입니다.
- 질량 분율과 몰질량: Millero, Feistel, Wright, McDougall (2008), "The composition of Standard Seawater and the definition of the Reference-Composition Salinity Scale", Deep-Sea Research I 55, 50–72 (doi:10.1016/j.dsr.2007.10.001).

DB와 엑셀에 쌓는 성분은 여덟 가지이고 녹은 염 질량의 99.85 %입니다. 나머지 일곱 가지(B(OH)₃, CO₃²⁻, Sr²⁺, B(OH)₄⁻, F⁻, OH⁻, CO₂)는 화면의 `이온 조성` 탭, 엑셀 `이온환산계수` 시트, `suya ions`에서 봅니다.

| 성분 | 기호 | DB 열 | 질량 비율 % | 염분 35에서 g/kg | 염분 35에서 mmol/kg |
|---|---|---|---|---|---|
| 염화 이온 | Cl⁻ | `chloride_g_kg` | 55.0340 | 19.3527 | 545.870 |
| 나트륨 이온 | Na⁺ | `sodium_g_kg` | 30.6596 | 10.7815 | 468.967 |
| 황산 이온 | SO₄²⁻ | `sulfate_g_kg` | 7.7132 | 2.7123 | 28.235 |
| 마그네슘 이온 | Mg²⁺ | `magnesium_g_kg` | 3.6506 | 1.2837 | 52.817 |
| 칼슘 이온 | Ca²⁺ | `calcium_g_kg` | 1.1719 | 0.4121 | 10.282 |
| 칼륨 이온 | K⁺ | `potassium_g_kg` | 1.1350 | 0.3991 | 10.208 |
| 탄산수소 이온 | HCO₃⁻ | `bicarbonate_g_kg` | 0.2980 | 0.1048 | 1.718 |
| 브롬화 이온 | Br⁻ | `bromide_g_kg` | 0.1913 | 0.0673 | 0.842 |

**한계.** 이 값은 측정값이 아니라 환산값입니다.

- 실제 바닷물의 조성은 기준 조성과 조금 다릅니다. 위성·모델 염분의 오차는 이온 값에도 같은 비율로 들어갑니다.
- 해빙이 얼거나 녹는 곳의 브라인, 강물·빙하 융해수가 섞이는 곳에서는 이온 비율 자체가 달라질 수 있는데, 이 환산은 그것을 반영하지 않습니다.
- 탄산·붕산 계열(HCO₃⁻, CO₃²⁻, B(OH)₃, B(OH)₄⁻, CO₂, OH⁻)은 표준 조건의 기준 조성 값이며 수온과 pH에 따른 실제 화학종 분포를 따르지 않습니다.
- 염분이 없거나 0 이하인 행은 환산하지 않습니다.

저장: 염분 행이 `measurements`에 들어오거나 바뀌거나 지워질 때마다 트리거가 `seawater_ions`의 같은 키 행을 맞춥니다. 프로그램을 처음 올린 뒤 한 번, 이미 있던 염분 행을 모두 채웁니다(`kv`의 `ions:method`로 한 번만).
Argo 층별 염분은 `argo_profiles`에 한 번만 저장하고, 이온 값은 `argo_level_ions` 뷰가 읽을 때 계산합니다. 같은 수십만 행을 표로 한 번 더 두지 않기 위해서입니다.

### 염분 범위 검사

저장된 염분이 그 수심에서 나올 수 있는 범위 안에 있는지 보고 표시합니다(`ranges.py`). **값을 지우거나 고치지 않습니다.**

- 범위: Boyer, T. and S. Levitus (1994), *Quality Control and Processing of Historical Oceanographic Temperature, Salinity, and Oxygen Data*, NOAA Technical Report NESDIS 81, 부록 A의 표 3f(Southern Ocean). 표준 수심 33개(0~5500 m)마다 하한과 상한이 있습니다. <https://repository.library.noaa.gov/view/noaa/13443/noaa_13443_DS1.pdf>
- 적용 구간: 같은 보고서의 규칙대로, 표준 수심의 범위를 위로는 앞 표준 수심까지 거리의 3/4, 아래로는 다음 표준 수심까지 거리의 1/4까지 씁니다. 예: 100 m 범위(30.5~36.5)는 81.25 m 초과 106.25 m 이하에 적용합니다. 수심을 모르는 행은 표층(0 m) 범위를 씁니다.
- 결과: `seawater_ions.salinity_check`와 `argo_level_ions.salinity_check`에 `ok`, `low`, `high`. 엑셀의 `범위 검사` 열에는 벗어난 행만 `낮음`·`높음`으로 적고, 쓴 범위 표는 `염분범위` 시트에 있습니다. `kv`의 `ions:check`에 범위 표의 판(`boyer1994-so/1`)을 적어 두고, 표가 바뀌면 모든 행을 한 번 다시 판정합니다.
- 한계: 보고서가 밝힌 대로 범위는 일부러 넓습니다. 그래서 큰 오류만 걸립니다. 2.5 m까지의 구간은 0~40이라 표층 값은 사실상 걸리지 않고, 범위 안에 있다고 그 값이 맞다는 뜻도 아닙니다. 남극해 표는 위도와 상관없이 저장된 모든 염분에 씁니다(보고서에서 남극해 구역의 경계는 확인하지 못했습니다).
- 실제 DB 사본에서 확인(2026-11-11): 지점값 4,007행은 모두 `ok`였습니다. `argo_level_ions` 525,907행 가운데 1,647행이 `high`(플로트 7900928의 325~1,246 m 1,597개, 플로트 7901081의 345~511 m 50개)였고 `low`는 없었습니다.

### 부피 기준 (mmol/L)

mmol/kg에 바닷물 밀도를 곱해 mmol/L로 바꿉니다: mmol/L = mmol/kg × ρ / 1000.

- 밀도 ρ: 그 행의 염분과 수온에서의 1기압 밀도(Millero & Poisson 1981, `seawater.density_surface`). 염분 35, 5 °C에서 1027.675 kg/m³입니다.
- 수온: 같은 자료·데이터셋·위치·층·시각의 수온 행. 짝이 되는 수온이 없는 염분 행은 밀도와 mmol/L 칸을 비웁니다. 수온 −3~40 °C, 염분 42 이하에서만 계산합니다.
- 현장 압력은 넣지 않았습니다. 깊은 층의 실제 밀도는 이보다 큽니다(1000 m에서 약 0.4 %).
- DB에는 저장하지 않습니다. 엑셀 `이온조성` 시트, `suya export ions`, `suya ions --temperature`가 읽을 때 계산합니다. Argo 층별 파일과 `argo_level_ions`에는 넣지 않았습니다.
- 실제 DB 사본에서 확인(2026-11-11): 지점값 4,007행 가운데 4,000행에 짝이 되는 수온이 있었습니다.
