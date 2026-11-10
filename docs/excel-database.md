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
기간, 생성 시각(UTC), 시각 기준 안내, 주의 문구, 이온 환산 안내, 시트별 행 수.

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
| 표층 수온 °C, 표층 염분 PSU | 가장 얕은 유효 층. QC 1·2만 |
| 최대 수심 m, 층 수 | 층별 값을 받은 뒤 채워짐 |

### 선박관측 — GOSUD
선박 호출부호별 시각·위치·표층 수온·염분(있을 때). QC 1·2만.

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
SQLite `seawater_ions` 표의 그 달 행을 그대로 옮깁니다. 해역 표층, HYCOM 40층, 위성 염분, 지도에서 클릭한 지점의 염분이 모두 들어옵니다.
**이온을 직접 잰 값이 아니라** 염분에 기준 조성(Millero 외 2008)의 비율을 곱한 환산값입니다. 식과 한계는 [데이터 출처 11절](data-sources.md#11-염분에서-환산하는-이온-조성)에 있습니다.

| 열 | 설명 |
|---|---|
| 시각 UTC, 지점, 위도, 경도 | 염분 행과 같습니다. 클릭한 지점은 지점 칸이 비어 있습니다 |
| 자료, 종류 | `hycom`, `smos`, `smap`, `argo` 등 / model, satellite, observation |
| 층, 수심 m | `surface` 또는 `depth:<m>` |
| 염분 PSU | 환산에 쓴 실용 염분 S_P |
| 기준 염분 g/kg | S_R = (35.16504 / 35) × S_P |
| Cl⁻ … Br⁻ g/kg | 주요 이온 여덟 가지(Cl⁻, Na⁺, SO₄²⁻, Mg²⁺, Ca²⁺, K⁺, HCO₃⁻, Br⁻). 바닷물 1 kg 기준 |
| Cl⁻ … Br⁻ mmol/kg | 같은 여덟 가지의 물질량 |

### 이온환산계수 — 환산에 쓴 기준 조성
성분 열다섯 가지의 기호, 전하, 몰질량, 질량 비율 %, 염분 1당 g/kg·mmol/kg, 염분 35에서의 g/kg·mmol/kg.
`DB 열`이 채워진 여덟 행이 DB와 엑셀에 쌓이는 성분입니다. 이 시트의 계수에 염분을 곱하면 어느 값이든 다시 계산할 수 있습니다.

## `argo_levels_YYYY-MM.xlsx`

### Argo층별
| 열 | 설명 |
|---|---|
| 시각 UTC, 플로트, 회차, 위도, 경도, 모드 | 프로파일 식별 |
| 압력 dbar | 원시 압력(보정 모드면 보정 압력) |
| 수심 m | Saunders & Fofonoff(1976)로 환산 |
| 수온 °C, 염분 PSU | QC 1·2만. 없으면 빈 칸 |
| 기준 염분 g/kg, Cl⁻ … Br⁻ g/kg | 그 층의 염분에서 환산한 기준 염분과 주요 이온 여덟 가지. 염분이 없는 층은 빈 칸 |

이온 열 아홉 개가 붙어 이 파일은 전보다 약 1.9배 크고 쓰는 데 약 1.8배 걸립니다
(2026-11-10 실측: 433,396행인 달이 17.8 MB·10.2초에서 33.7 MB·17.8초). 별도 프로세스가 쓰므로 화면은 멈추지 않습니다.

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

이온 환산값은 표 하나와 뷰 둘로 읽습니다: `seawater_ions`(g/kg, 염분 행마다 한 행), `seawater_ions_mmol`(mmol/kg), `argo_level_ions`(Argo 층별, g/kg).
CSV가 필요하면 `suya export ions --out ions.csv`, `suya export argo-ions --out argo_ions.csv`를 씁니다.

`grids` 표의 `payload`는 gzip으로 압축한 JSON(`{"lats":[…],"lons":[…],"values":[…]}`)이며 `antarctic_monitor.db.Store.load_grid("oisst_sst")`로 풀 수 있습니다.
