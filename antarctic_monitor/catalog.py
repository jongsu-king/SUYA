"""화면과 문서가 함께 쓰는 데이터 소스·지도 레이어 목록. 글자는 i18n.tr()로 옮겨 보여 줍니다."""

from __future__ import annotations

KIND_LABEL = {
    "observation": "현장 관측",
    "satellite": "위성",
    "analysis": "분석",
    "model": "모델",
    "forecast": "예보",
    "climatology": "기후값",
}

SOURCES: list[dict] = [
    {
        "id": "metar", "name": "METAR 기지 관측", "provider": "NOAA Aviation Weather Center", "kind": "observation",
        "measures": "기온, 이슬점, 기압", "cadence": "기지별 약 1시간",
        "relation": "두 사이트 지도에 없는 실측값", "url": "https://aviationweather.gov/data/api/",
    },
    {
        "id": "openmeteo_current", "name": "GFS 현재 기온", "provider": "NOAA GFS / Open-Meteo", "kind": "model",
        "measures": "기온, 체감, 이슬점, 습구, 지표 온도, 습도, 기압, 풍속", "cadence": "15분 (모델 6시간)",
        "relation": "nullschool 기온 레이어와 같은 GFS", "url": "https://open-meteo.com/en/docs",
    },
    {
        "id": "openmeteo_forecast", "name": "모델별 기온 예보", "provider": "GFS, ECMWF, ICON, GEM, JMA / Open-Meteo",
        "kind": "forecast", "measures": "기온 7일 예보", "cadence": "3시간",
        "relation": "Windy 기본 모델 ECMWF 포함", "url": "https://open-meteo.com/en/docs",
    },
    {
        "id": "gfs_grid", "name": "GFS 기온 격자", "provider": "NOAA GFS / Open-Meteo", "kind": "model",
        "measures": "2 m 기온 (2.5°×10°)", "cadence": "3시간",
        "relation": "nullschool 기온 레이어와 같은 GFS", "url": "https://open-meteo.com/en/docs",
    },
    {
        "id": "windy", "name": "Windy Point Forecast", "provider": "Windy.com", "kind": "forecast",
        "measures": "기온, 이슬점, 습도, 기압", "cadence": "3시간",
        "relation": "Windy 공식 API. 수온·염분 항목 없음", "url": "https://api.windy.com/point-forecast/docs",
    },
    {
        "id": "oisst", "name": "OISST v2.1", "provider": "NOAA NCEI / CoastWatch ERDDAP", "kind": "analysis",
        "measures": "표층 수온, 수온 편차, 해빙 농도 (0.25°)", "cadence": "1일",
        "relation": "nullschool 수온 레이어 원천", "url": "https://www.ncei.noaa.gov/products/optimum-interpolation-sst",
    },
    {
        "id": "openmeteo_marine", "name": "해양 모델 표층 수온", "provider": "Open-Meteo Marine", "kind": "model",
        "measures": "표층 수온", "cadence": "30분", "relation": "육지 격자 값 제외",
        "url": "https://open-meteo.com/en/docs/marine-weather-api",
    },
    {
        "id": "hycom_grid", "name": "HYCOM 수온·염분 격자", "provider": "US Navy ESPC-D-V02 / HYCOM.org", "kind": "model",
        "measures": "0–2000 m 수온·염분 (약 0.5°)", "cadence": "3시간", "relation": "80°S 이남 없음",
        "url": "https://www.hycom.org/dataserver/espc-d-v02/global-analysis",
    },
    {
        "id": "hycom_profiles", "name": "HYCOM 해역 프로파일", "provider": "US Navy ESPC-D-V02 / HYCOM.org", "kind": "model",
        "measures": "40개 층 수온·염분", "cadence": "1일", "relation": "해역 대표 지점",
        "url": "https://www.hycom.org/dataserver/espc-d-v02/global-analysis",
    },
    {
        "id": "argo", "name": "Argo 플로트", "provider": "Argo GDAC / Ifremer ERDDAP", "kind": "observation",
        "measures": "약 2000 m까지 수온·염분", "cadence": "플로트별 약 10일", "relation": "QC 플래그 1·2만 사용",
        "url": "https://argo.ucsd.edu/",
    },
    {
        "id": "gosud", "name": "GOSUD 선박 관측", "provider": "GOSUD / Ifremer ERDDAP", "kind": "observation",
        "measures": "표층 수온, 일부 표층 염분", "cadence": "항로 있을 때", "relation": "QC 플래그 1·2만 사용",
        "url": "https://www.gosud.org/",
    },
    {
        "id": "smos", "name": "SMOS 위성 염분", "provider": "ESA SMOS / NOAA CoastWatch", "kind": "satellite",
        "measures": "표층 염분 3일 합성 (0.25°)", "cadence": "1일", "relation": "65°S 이남 대부분 결측",
        "url": "https://coastwatch.noaa.gov/cwn/products/sea-surface-salinity-near-real-time-smos.html",
    },
    {
        "id": "smap", "name": "SMAP 위성 염분", "provider": "NASA SMAP / NOAA CoastWatch", "kind": "satellite",
        "measures": "표층 염분 일별 (0.25°)", "cadence": "1일", "relation": "65°S 이남 대부분 결측",
        "url": "https://coastwatch.noaa.gov/cwn/products/sea-surface-salinity-near-real-time-smap.html",
    },
]

# 수집이 아니라 저장을 맡는 작업. 상태 표에는 함께 보여 줍니다.
OUTPUT_JOBS: list[dict] = [{"id": "excel", "name": "엑셀 DB 저장"}]

ON_DEMAND_SOURCES: list[dict] = [
    {
        "id": "mur", "name": "MUR SST", "provider": "NASA JPL / CoastWatch ERDDAP", "kind": "analysis",
        "measures": "0.01° 표층 수온, 오차, 해빙 농도", "url": "https://podaac.jpl.nasa.gov/MEaSUREs-MUR",
    },
    {
        "id": "woa23", "name": "World Ocean Atlas 2023", "provider": "NOAA NCEI", "kind": "climatology",
        "measures": "깊이별 수온·염분 기후값", "url": "https://www.ncei.noaa.gov/products/world-ocean-atlas",
    },
    {
        "id": "era5", "name": "ERA5", "provider": "ECMWF / Open-Meteo Archive", "kind": "analysis",
        "measures": "일별 평균·최저·최고 기온", "url": "https://open-meteo.com/en/docs/historical-weather-api",
    },
]

NOT_INCLUDED: list[dict] = [
    {"name": "nullschool 내부 데이터", "reason": "공개 API 없음. 데이터 라이선스는 별도 문의. 같은 원천인 GFS와 OISST를 직접 수집"},
    {"name": "Windy 웹사이트 내부 엔드포인트", "reason": "이용약관 4.6.1이 자동 수집 금지. 공식 Point Forecast API만 사용"},
    {"name": "Copernicus Marine", "reason": "계정 로그인 필요"},
    {"name": "MEOP 해양 포유류 CTD", "reason": "실시간 API 없음"},
]

DEPTH_LAYERS = (0, 100, 200, 500, 1000, 2000)

LAYERS: list[dict] = [
    {"id": "oisst_sst", "group": "temperature", "label": "SST · OISST", "source": "oisst", "kind": "analysis", "scale": "water_temp"},
    {"id": "oisst_anom", "group": "temperature", "label": "SST 편차 · OISST", "source": "oisst", "kind": "analysis", "scale": "anomaly"},
    {"id": "hycom_temp", "group": "temperature", "label": "수온 · HYCOM", "source": "hycom_grid", "kind": "model", "scale": "water_temp", "depths": DEPTH_LAYERS},
    {"id": "hycom_salt", "group": "salinity", "label": "염분 · HYCOM", "source": "hycom_grid", "kind": "model", "scale": "salinity", "depths": DEPTH_LAYERS},
    {"id": "smos_sss", "group": "salinity", "label": "SSS · SMOS", "source": "smos", "kind": "satellite", "scale": "salinity"},
    {"id": "smap_sss", "group": "salinity", "label": "SSS · SMAP", "source": "smap", "kind": "satellite", "scale": "salinity"},
    {"id": "oisst_ice", "group": "ice", "label": "해빙 농도 · OISST", "source": "oisst", "kind": "analysis", "scale": "ice"},
    {"id": "gfs_t2m", "group": "air", "label": "기온 2 m · GFS", "source": "gfs_grid", "kind": "model", "scale": "air_temp"},
]
