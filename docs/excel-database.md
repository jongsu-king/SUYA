# 엑셀 데이터베이스 구조

[English version](excel-database.en.md)

SUYA는 15분마다(`MONITOR_INTERVAL_EXCEL`) SQLite에 새 자료가 들어왔는지 확인하고, 들어왔으면 월별 엑셀 파일을 다시 씁니다.
`파일 > 엑셀 DB 지금 저장` 또는 `suya excel-sync`로 바로 쓸 수도 있습니다.

## 파일

| 파일 | 내용 |
|---|---|
| `antarctic_db_YYYY-MM.xlsx` | 그 달의 모든 지점값·격자 통계·목록 (아래 시트) |
| `argo_levels_YYYY-MM.xlsx` | 그 달 Argo 프로파일의 모든 층과 층별 이온 환산값. 월 수십만 행이라 따로 둡니다 |

기본 폴더: Windows `문서\SUYA`, macOS·Linux `~/Documents/SUYA`. `파일 > 설정`이나 `MONITOR_EXCEL_DIR`로 바꿉니다.

## 어떻게 쓰이나

1. 수집 엔진의 `excel` 작업이 `data_stamp()`(마지막으로 자료가 들어온 시각)를 읽어 지난번과 같으면 "새 자료 없음"으로 끝냅니다.
2. 다르면 **별도 프로세스**(`suya excel-sync --db … --dir …`)를 띄웁니다. 화면과 수집이 멈추지 않게 하기 위해서입니다.
3. 쓸 달을 고릅니다(`months_to_write`): 이번 달, 지난달, 그리고 파일이 아직 없는 달. 그보다 오래된 달은 **다시 쓰지 않습니다**. 그래서 지난달이 끝난 뒤 한 달이 지나면 그 파일은 고정됩니다.
4. 달마다 `.antarctic_db_YYYY-MM.tmp.xlsx`에 전부 쓴 뒤 `os.replace`로 원래 이름으로 바꿉니다. 중간에 꺼져도 깨진 파일이 남지 않습니다.
5. Windows에서 엑셀이 파일을 열어 두고 있으면 교체가 실패합니다. 그 달은 건너뛰고 다음 주기에 다시 시도하며, 수집 상태에 "파일이 열려 있어 저장하지 못했습니다"가 보입니다.
6. 엑셀 시트 한도(1,048,576행)에 닿으면 `시트이름_2`, `_3`으로 이어 씁니다.

왜 추가 기록이 아니라 재생성인가: xlsx는 압축된 XML이라 행 하나를 붙이려 해도 파일 전체를 읽고 다시 써야 합니다. 행이 늘수록 느려지고, 쓰는 도중 꺼지면 파일이 깨집니다.
SQLite가 원본이고 엑셀은 그것을 보기 좋게 펼친 사본이라고 생각하면 됩니다. **직접 고친 내용은 다음 저장 때 사라집니다.** 분석은 복사본에서 하세요.

## 공통 형식

- 첫 행은 머리글(굵게, 밑줄), 틀 고정, 자동 필터.
- 시각 열은 엑셀 날짜 형식(`yyyy-mm-dd hh:mm`)의 **UTC**입니다. 한국 시각은 +9시간.
- 빈 칸은 결측(값이 없거나 품질 규칙에 걸려 버린 값).
- 지점 이름은 저장할 때의 프로그램 언어를 따릅니다(한국어 또는 영어). 시트 이름과 머리글도 같습니다.

## `antarctic_db_YYYY-MM.xlsx` 시트

### 정보
기간, 생성 시각(UTC), 시각 기준 안내, 주의 문구, 이온 환산·범위 검사·부피 기준·격자 이온 환산 안내, 시트별 행 수.

### 월간요약 — 지점·자료·항목별 한 달 통계
표층과 2 m 값만 셉니다. 앞날 예보(`kind = forecast`), 깊은 층, 지도에서 클릭한 임의 지점은 뺍니다.

| 열 | 설명 |
|---|---|
| 지점 | 해역·기지 이름. METAR 기지는 ICAO 코드 |
| 자료 | `oisst`, `smos`, `smap`, `hycom`, `openmeteo_marine`, `openmeteo`, `metar` |
| 항목, 단위 | 수온, 염분, 수온 편차, 해빙 농도, 수온 오차, 기온 |
| 표본 수 | 그달의 값 개수. 자료마다 주기가 달라 평균을 비교할 때 함께 보세요 |
| 평균, 최소, 최대, 표준편차 | 표본의 단순 통계(모표준편차). 시간 가중이 아닙니다 |
| 첫 시각 UTC, 마지막 시각 UTC | 그달에 값이 있는 범위. 수집을 시작한 달은 한 달 전체가 아닙니다 |
| 전월 평균, 전월 대비 | 앞달 같은 지점·자료·항목의 평균과 그 차이. 앞달 값이 없으면 비어 있습니다 |

### 격자평균 — 지도 레이어마다 시각별 통계
| 열 | 설명 |
|---|---|
| 시각 UTC | 격자의 자료 시각 |
| 레이어 | `oisst_sst`, `oisst_anom`, `oisst_ice`, `smos_sss`, `smap_sss`, `gfs_t2m`, `hycom_temp_<수심>`, `hycom_salt_<수심>` (수심 0·100·200·500·1000·2000) |
| 단위 | °C, PSU, fraction |
| 60°S 이남 평균 | 위도 코사인 가중 평균 |
| 최소, 최대 | 60°S 이남 |
| 유효 비율 | 60°S 이남 격자 중 값이 있는 비율. 위성 염분은 0.0x, 해빙은 해빙 격자만 |
| 웨델해 … 아문젠·벨링스하우젠해 | 해역 5곳의 가중 평균 |

### 수온염분_해역 — 해역 대표 지점 10곳의 표층값
| 열 | 설명 |
|---|---|
| 시각 UTC, 지점, 위도, 경도 | |
| 자료 | `oisst`, `smos`, `smap`, `hycom`, `openmeteo_marine` |
| 종류 | analysis, satellite, model |
| 항목 | 수온 / 염분 / 수온 편차 / 해빙 농도 |
| 값, 단위 | |

### 수온염분_수직 — HYCOM 40층 프로파일
해역 10곳 × 시각 × 수심. 한 행에 수온과 염분이 함께 있습니다(둘 중 하나가 없으면 빈 칸). 하루 1회 수집.

### Argo_목록 — 프로파일 하나당 한 행
| 열 | 설명 |
|---|---|
| 시각 UTC | 프로파일 관측 시각 |
| 플로트 | WMO 번호 |
| 회차 | cycle_number |
| 위도, 경도 | |
| 모드 | R 실시간, A 실시간 보정, D 지연 보정 |
| 위치 QC | 1 양호, 8 추정(해빙 아래) 등 |
| 표층 수온 °C, 표층 염분 PSU | 받아 둔 층별 값 가운데 100 dbar 안에서 가장 얕은 유효 층(QC 1·2). 층별 값을 받기 전에는 목록의 임시값 |
| 최대 수심 m, 층 수 | 층별 값을 받은 뒤 채워짐 |

### 선박관측 — GOSUD
선박 호출부호별 시각·위치·표층 수온·염분(있을 때). QC 1·2만.

### OSMC관측 — OSMC 실시간 현장 관측
표류 부이, 해빙 부이, 선박, 무인 수상정, 계측 동물이 GTS로 보낸 보고입니다. 같은 시각·플랫폼·위치·수심의 값이 한 행에 모입니다.

| 열 | 설명 |
|---|---|
| 시각 UTC | 보고 시각 |
| 플랫폼 | WMO 번호 또는 선박 호출부호 |
| 종류 | 표류 부이, 해빙 부이, 선박, 무인 수상정, 계측 동물 등 |
| 위도, 경도 | |
| 수심 m | 수심별 값의 수심. 표층 값과 기상 값의 행은 빈 칸 |
| 수온 °C, 염분 PSU | 표층 또는 그 수심의 값. 없으면 빈 칸 |
| 기온 °C, 이슬점 °C, 해면 기압 hPa | 같은 보고의 기상 값. 없으면 빈 칸 |

품질 플래그가 없는 자료라 범위와 위치 검사만 거친 값입니다. 규칙과 한계는 [데이터 출처 7절](data-sources.md#7-osmc--gts로-들어온-실시간-현장-관측)에 있습니다.

### 기지기온 — METAR
기지(ICAO)별 보고 시각·이름·위치·기온·이슬점·기압.

### GFS기온 — 24개 지점 현재값
시각, 지점, 위도, 경도, 기온, 체감, 이슬점, 습구, 지표 온도, 습도, 기압, 풍속.

### 모델예보 — 24개 지점 × 예보 시각
GFS, ECMWF IFS, ICON, GEM, JMA GSM 다섯 모델의 2 m 기온이 열로 나란히 있습니다. 같은 예보 시각이 여러 번 갱신되면 **마지막 수집값**만 남습니다(SQLite 키가 시각 기준이기 때문).

### Windy
키가 있을 때만. 예보 시각, 지점, 모델, 층(surface, hpa:850 …), 항목, 값, 단위, 키 구분(`windy_testing_shuffled` = 변형된 값).

### 지점조회 — 지도에서 클릭한 지점
클릭한 지점마다 소스별로 받은 값(OISST, MUR, SMOS, SMAP, HYCOM 40층, GFS 현재값, Marine). `location_id`가 없는 측정값이 여기로 옵니다.

### 이온조성 — 염분이 있는 행마다 환산한 주요 이온
SQLite `seawater_ions` 표의 그 달 행을 그대로 옮깁니다. 해역 표층, HYCOM 40층, 위성 염분, Argo·GOSUD·OSMC 관측 염분, 지도에서 클릭한 지점의 염분이 모두 들어옵니다.
**이온을 직접 잰 값이 아니라** 염분에 기준 조성(Millero 외 2008)의 비율을 곱한 환산값입니다. 식과 한계는 [데이터 출처 12절](data-sources.md#12-염분에서-환산하는-이온-조성)에 있습니다.

| 열 | 설명 |
|---|---|
| 시각 UTC, 지점, 위도, 경도 | 염분 행과 같습니다. 클릭한 지점은 지점 칸이 비어 있습니다 |
| 자료, 종류 | `hycom`, `smos`, `smap`, `argo` 등 / model, satellite, observation |
| 층, 수심 m | `surface` 또는 `depth:<m>` |
| 염분 PSU | 환산에 쓴 실용 염분 S_P |
| 기준 염분 g/kg | S_R = (35.16504 / 35) × S_P |
| Cl⁻ … Br⁻ g/kg | 주요 이온 여덟 가지(Cl⁻, Na⁺, SO₄²⁻, Mg²⁺, Ca²⁺, K⁺, HCO₃⁻, Br⁻). 바닷물 1 kg 기준 |
| Cl⁻ … Br⁻ mmol/kg | 같은 여덟 가지의 물질량 |
| 수온 °C | 같은 자료·위치·층·시각의 수온. 짝이 없으면 빈 칸 |
| 1기압 밀도 kg/m³ | 그 수온과 염분의 1기압 밀도(Millero & Poisson 1981). 현장 압력은 넣지 않음. 수온이 없으면 빈 칸 |
| Cl⁻ … Br⁻ mmol/L | mmol/kg × 밀도 / 1000. 수온이 없으면 빈 칸 |
| 범위 검사 | 염분이 그 수심의 남극해 범위를 벗어나면 `낮음`·`높음`. 범위 안이면 빈 칸. 표시일 뿐이고 값은 그대로 둠 |

### 격자이온 — 염분 격자의 해역 평균에서 환산한 이온
SQLite `grid_ions` 뷰의 그 달 행을 그대로 옮깁니다. 염분 격자(HYCOM 염분의 수심별 레이어, SMOS, SMAP)의 시각마다 60°S 이남 전체 한 행과 해역마다 한 행입니다.
평균 염분에 같은 계수를 곱한 **환산값**입니다. 환산이 염분에 비례하므로 칸마다 환산해 평균한 값과 같습니다. 칸마다의 값은 `suya export grid-ions`로 받습니다. 식과 한계는 [데이터 출처 12절](data-sources.md#12-염분에서-환산하는-이온-조성)에 있습니다.

| 열 | 설명 |
|---|---|
| 시각 UTC | 격자의 자료 시각 |
| 레이어 | `hycom_salt_<수심>`, `smos_sss`, `smap_sss` |
| 해역 | `남극해 전체 (60°S 이남)` 또는 해역 5곳(웨델해, 인도양, 서태평양, 로스해, 아문젠·벨링스하우젠해). 평균이 없는 해역은 행이 없습니다 |
| 수심 m | 레이어의 수심. 위성 염분은 0 |
| 유효 격자 수 | 60°S 이남에서 값이 있는 칸 수. 해역 행은 그 해역 안의 칸 수 |
| 염분 PSU | 그 해역의 가중 평균 염분(`격자평균` 시트와 같은 값, 소수 셋째 자리) |
| 기준 염분 g/kg | S_R = (35.16504 / 35) × S_P |
| Cl⁻ … Br⁻ g/kg | 주요 이온 여덟 가지. 바닷물 1 kg 기준 |
| Cl⁻ … Br⁻ mmol/kg | 같은 여덟 가지의 물질량 |
| 범위 검사 | 평균 염분이 레이어 수심의 남극해 범위를 벗어나면 `낮음`·`높음`. 범위 안이면 빈 칸 |

짝이 되는 수온을 쓰지 않으므로 밀도와 mmol/L 열은 없습니다.

### 이온환산계수 — 환산에 쓴 기준 조성
성분 열다섯 가지의 기호, 전하, 몰질량, 질량 비율 %, 염분 1당 g/kg·mmol/kg, 염분 35에서의 g/kg·mmol/kg.
`DB 열`이 채워진 여덟 행이 DB와 엑셀에 쌓이는 성분입니다. 이 시트의 계수에 염분을 곱하면 어느 값이든 다시 계산할 수 있습니다.

### 염분범위 — 범위 검사에 쓴 수심별 염분 범위
Boyer & Levitus(1994, NOAA Technical Report NESDIS 81)의 남극해 표입니다. 표준 수심 33개마다 한 행입니다.

| 열 | 설명 |
|---|---|
| 표준 수심 m | 0~5500 m |
| 적용 수심 초과 m, 적용 수심 이하 m | 이 행의 범위를 적용하는 수심 구간. 맨 위 행과 맨 아래 행은 바깥쪽이 빈 칸 |
| 염분 하한, 염분 상한 | 하한보다 낮으면 `낮음`, 상한보다 높으면 `높음` |

범위가 넓어 큰 오류만 걸립니다. 규칙과 한계는 [데이터 출처 12절](data-sources.md#12-염분에서-환산하는-이온-조성)에 있습니다.

## `argo_levels_YYYY-MM.xlsx`

### Argo층별
| 열 | 설명 |
|---|---|
| 시각 UTC, 플로트, 회차, 위도, 경도, 모드 | 프로파일 식별 |
| 압력 dbar | 원시 압력(보정 모드면 보정 압력) |
| 수심 m | Saunders & Fofonoff(1976)로 환산 |
| 수온 °C, 염분 PSU | QC 1·2만. 없으면 빈 칸 |
| 기준 염분 g/kg, Cl⁻ … Br⁻ g/kg | 그 층의 염분에서 환산한 기준 염분과 주요 이온 여덟 가지. 염분이 없는 층은 빈 칸 |
| 범위 검사 | 그 층의 염분이 수심별 남극해 범위를 벗어나면 `낮음`·`높음`. 범위 안이면 빈 칸 |

이온 열 아홉 개가 붙어 이 파일은 전보다 약 1.9배 크고 쓰는 데 약 1.8배 걸립니다
(2026-11-10 실측: 433,396행인 달이 17.8 MB·10.2초에서 33.7 MB·17.8초). 범위 검사 열은 크기를 거의 늘리지 않습니다(2026-11-11 실측: 434,000행인 달이 33,724,118바이트에서 33,728,674바이트). 별도 프로세스가 쓰므로 화면은 멈추지 않습니다.

## 파이썬·R에서 바로 읽기

엑셀을 거치지 않고 SQLite를 읽는 편이 빠릅니다.

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
library(DBI); con <- dbConnect(RSQLite::SQLite(), "~/Documents/../Library/Application Support/SUYA/antarctic.db")
dbGetQuery(con, "SELECT * FROM measurements WHERE variable='sea_water_temperature' LIMIT 10")
```

이온 환산값은 표 하나와 뷰 셋으로 읽습니다: `seawater_ions`(g/kg, 염분 행마다 한 행), `seawater_ions_mmol`(mmol/kg), `argo_level_ions`(Argo 층별, g/kg), `grid_ions`(염분 격자의 60°S 이남 평균과 해역 평균, g/kg·mmol/kg). 범위 검사 결과는 `seawater_ions`, `argo_level_ions`, `grid_ions`의 `salinity_check` 열(`ok`·`low`·`high`)입니다. 밀도와 mmol/L은 DB에 없고 엑셀과 `suya export ions`가 계산합니다.
CSV가 필요하면 `suya export ions --out ions.csv`, `suya export argo-ions --out argo_ions.csv`를 쓰고, 염분 격자 칸마다의 값은 `suya export grid-ions --layer hycom_salt_0 --out salt0_ions.csv`로 받습니다.

`grids` 표의 `payload`는 gzip으로 압축한 JSON(`{"lats":[…],"lons":[…],"values":[…]}`)이며 `antarctic_monitor.db.Store.load_grid("oisst_sst")`로 풀 수 있습니다.
