"""한국어·영어 전환. 코드에는 한국어 원문을 쓰고, 영어일 때 EN 표에서 찾습니다.

수집 결과 메시지는 DB에 언어 중립 형태(msg)로 저장하고 보여 줄 때 옮깁니다(render).
그래야 언어를 바꿨을 때 이미 저장된 메시지도 함께 바뀝니다.
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

from .config import SETTINGS_FILE, app_data_dir, load_dotenv

LANGUAGES = ("ko", "en")
_MARK = "\x1f"
_SEP = "\x1e"
_language = "ko"

EN: dict[str, str] = {
    "해당 조건의 데이터가 없습니다": "No data for this query",
    "원천 갱신 없음": "No new source data",
    "{layer} 유효 {pct}%": "{layer} valid {pct}%",
    "HYCOM 오류 응답: {detail}": "HYCOM error response: {detail}",
    "HYCOM 시간 기준을 해석하지 못했습니다": "Could not read the HYCOM time axis",
    "같은 시각의 격자를 이미 보유": "Grids for this time already stored",
    "격자 {n}개 갱신": "{n} grids updated",
    "실패 {n}개": "{n} failed",
    "실패 {n}곳": "{n} failed",
    "HYCOM은 80°S 이남을 다루지 않습니다": "HYCOM does not cover south of 80°S",
    "모델 격자상 육지이거나 빙붕입니다": "Land or ice shelf in the model grid",
    "해역 {n}곳": "{n} sea areas",
    "프로파일 없음: {platform}/{cycle}": "Profile not found: {platform}/{cycle}",
    "최근 {days}일 프로파일 {listed}개, 층별 값 {fetched}개 수신, 대기 {remaining}개":
        "{listed} profiles in {days} days, {fetched} fetched, {remaining} queued",
    "Argo 프로파일을 받지 못했습니다: {error}": "Could not fetch Argo profiles: {error}",
    "Argo 목록이 비어 있습니다": "The Argo list came back empty",
    "최근 30일 이 해역의 선박 관측 없음": "No ship observations here in the last 30 days",
    "선박 {n}척": "{n} ships",
    "최근 {days}일 이 해역의 OSMC 관측 없음": "No OSMC observations here in the last {days} days",
    "플랫폼 {n}개": "{n} platforms",
    "기후값 격자상 육지입니다": "Land in the climatology grid",
    "Open-Meteo 오늘 호출 예산 부족 ({used}/{limit} 사용, {calls}호출 필요)":
        "Open-Meteo daily budget short ({used}/{limit} used, {calls} calls needed)",
    "Open-Meteo 오늘 호출 예산 부족 ({used}/{cap} 사용, {calls}호출 필요, 전체 {limit} 중 {percent}%는 다른 수집용 예비)":
        "Open-Meteo daily budget short ({used}/{cap} used, {calls} calls needed; {percent}% of {limit} is kept for other sources)",
    "지점 {n}곳": "{n} points",
    "모델 {n}종": "{n} models",
    "육지 격자 제외 {n}곳": "{n} land cells skipped",
    "GFS 격자 응답에 시각이 없습니다": "GFS grid response has no time",
    "격자 {n}지점": "{n} grid points",
    "기지 {n}곳": "{n} stations",
    "WINDY_API_KEY가 없어 건너뜀": "Skipped: no WINDY_API_KEY",
    "Windy가 요청을 거부했습니다: {detail}": "Windy rejected the request: {detail}",
    "Windy 오늘 호출 예산 소진 ({used}/{limit})": "Windy daily budget used up ({used}/{limit})",
    "testing 키: 변형된 값": "testing key: altered values",
    "새 자료 없음": "No new data",
    "엑셀 저장 프로세스 종료 코드 {code}": "Excel writer exit code {code}",
    "실시간 수집 시작": "Collecting continuously",
    "OISST 편차": "OISST anomaly",
    "1971–2000 대비": "vs 1971–2000",
    "OISST 해빙": "OISST sea ice",
    "분석 오차 ±{err}°C": "analysis error ±{err}°C",
    "MUR 해빙": "MUR sea ice",
    "육지 격자라 제외": "land cell, excluded",
    "지도 격자(약 0.5°)": "map grid (about 0.5°)",
    "SMOS 3일 합성": "SMOS 3-day",
    "해빙·연안 결측": "missing (ice or coast)",
    "SMAP 일별": "SMAP daily",
    "플로트 {platform}, {km} km": "float {platform}, {km} km",
    "Argo 현장 관측": "Argo in situ",
    "선박 {ship}": "ship {ship}",
    "플랫폼 {code}, {km} km": "platform {code}, {km} km",
    "표류 부이": "Drifting buoy",
    "해빙 부이": "Ice buoy",
    "계류 부이": "Moored buoy",
    "선박": "Ship",
    "무인 수상정": "Uncrewed surface vehicle",
    "계측 동물": "Tagged animal",
    "글라이더": "Glider",
    "종류 미상": "Unknown type",
    "좌표가 숫자가 아닙니다": "Coordinates are not numbers",
    "위도 범위를 벗어났습니다: {lat}": "Latitude out of range: {lat}",
    "nullschool 링크에서 좌표를 찾지 못했습니다": "No coordinates found in the nullschool link",
    "Windy 링크에서 좌표를 찾지 못했습니다": "No coordinates found in the Windy link",
    "nullschool 또는 Windy 링크만 해석할 수 있습니다": "Only nullschool and Windy links can be read",
    "아직 수집되지 않은 레이어입니다: {layer}": "Layer not collected yet: {layer}",
    "웨델해": "Weddell Sea",
    "인도양": "Indian Ocean",
    "서태평양": "Western Pacific",
    "로스해": "Ross Sea",
    "아문젠·벨링스하우젠해": "Amundsen-Bellingshausen Seas",
    "현장 관측": "In situ",
    "위성": "Satellite",
    "분석": "Analysis",
    "모델": "Model",
    "예보": "Forecast",
    "기후값": "Climatology",
    "METAR 기지 관측": "METAR station observations",
    "기온, 이슬점, 기압": "Air temperature, dew point, pressure",
    "기지별 약 1시간": "About hourly per station",
    "두 사이트 지도에 없는 실측값": "Measured values not on either site's map",
    "GFS 현재 기온": "GFS current air temperature",
    "기온, 체감, 이슬점, 습구, 지표 온도, 습도, 기압, 풍속":
        "Air, apparent, dew point, wet bulb, surface temperature, humidity, pressure, wind speed",
    "15분 (모델 6시간)": "15 min (model every 6 h)",
    "nullschool 기온 레이어와 같은 GFS": "Same GFS as the nullschool temperature layer",
    "모델별 기온 예보": "Air temperature forecast by model",
    "기온 7일 예보": "7-day air temperature forecast",
    "3시간": "3 h",
    "Windy 기본 모델 ECMWF 포함": "Includes ECMWF, Windy's default model",
    "GFS 기온 격자": "GFS air temperature grid",
    "2 m 기온 (2.5°×10°)": "2 m air temperature (2.5°×10°)",
    "기온, 이슬점, 습도, 기압": "Air temperature, dew point, humidity, pressure",
    "Windy 공식 API. 수온·염분 항목 없음": "Windy's official API. No water temperature or salinity",
    "표층 수온, 수온 편차, 해빙 농도 (0.25°)": "SST, SST anomaly, sea ice concentration (0.25°)",
    "1일": "1 day",
    "nullschool 수온 레이어 원천": "A source of the nullschool SST layer",
    "해양 모델 표층 수온": "Ocean model SST",
    "표층 수온": "SST",
    "30분": "30 min",
    "육지 격자 값 제외": "Land cells excluded",
    "HYCOM 수온·염분 격자": "HYCOM temperature and salinity grids",
    "0–2000 m 수온·염분 (약 0.5°)": "0–2000 m temperature and salinity (about 0.5°)",
    "80°S 이남 없음": "Nothing south of 80°S",
    "HYCOM 해역 프로파일": "HYCOM area profiles",
    "40개 층 수온·염분": "Temperature and salinity at 40 levels",
    "해역 대표 지점": "Representative sea-area points",
    "Argo 플로트": "Argo floats",
    "약 2000 m까지 수온·염분": "Temperature and salinity to about 2000 m",
    "플로트별 약 10일": "About 10 days per float",
    "QC 플래그 1·2만 사용": "Only QC flags 1 and 2 are used",
    "GOSUD 선박 관측": "GOSUD ship observations",
    "표층 수온, 일부 표층 염분": "SST, surface salinity on some ships",
    "항로 있을 때": "When ships pass",
    "OSMC 실시간 현장 관측": "OSMC real-time in situ observations",
    "표층 수온·염분, 기온·이슬점·해면 기압, 계측 동물 수심별 수온·염분":
        "SST and surface salinity, air temperature, dew point and sea-level pressure, tagged-animal temperature and salinity by depth",
    "1시간": "1 h",
    "QC 플래그 없음. 범위와 위치 검사로 거름": "No QC flags. Filtered by range and position checks",
    "SMOS 위성 염분": "SMOS satellite salinity",
    "표층 염분 3일 합성 (0.25°)": "Surface salinity, 3-day composite (0.25°)",
    "65°S 이남 대부분 결측": "Mostly missing south of 65°S",
    "SMAP 위성 염분": "SMAP satellite salinity",
    "표층 염분 일별 (0.25°)": "Surface salinity, daily (0.25°)",
    "엑셀 DB 저장": "Excel database",
    "0.01° 표층 수온, 오차, 해빙 농도": "0.01° SST, error, sea ice concentration",
    "깊이별 수온·염분 기후값": "Temperature and salinity climatology by depth",
    "일별 평균·최저·최고 기온": "Daily mean, min and max air temperature",
    "지점 조회 시": "On point query",
    "지점을 고를 때만 호출": "Called only when a point is selected",
    "nullschool 내부 데이터": "nullschool internal data",
    "공개 API 없음. 데이터 라이선스는 별도 문의. 같은 원천인 GFS와 OISST를 직접 수집":
        "No public API; data licensing by inquiry. The same sources, GFS and OISST, are collected directly",
    "Windy 웹사이트 내부 엔드포인트": "Windy website internal endpoints",
    "이용약관 4.6.1이 자동 수집 금지. 공식 Point Forecast API만 사용":
        "Terms of use 4.6.1 prohibit automated collection. Only the official Point Forecast API is used",
    "계정 로그인 필요": "Requires an account login",
    "MEOP 해양 포유류 CTD": "MEOP marine mammal CTD",
    "품질 검사를 마친 자료는 실시간 API 없음. GTS로 들어온 실시간 값은 OSMC로 수집":
        "Quality-controlled data has no real-time API. Real-time values sent over the GTS are collected through OSMC",
    "SST 편차 · OISST": "SST anomaly · OISST",
    "수온 · HYCOM": "Temperature · HYCOM",
    "염분 · HYCOM": "Salinity · HYCOM",
    "해빙 농도 · OISST": "Sea ice · OISST",
    "기온 2 m · GFS": "Air temperature 2 m · GFS",
    "수온": "Temperature",
    "염분": "Salinity",
    "수온 편차": "SST anomaly",
    "해빙 농도": "Sea ice concentration",
    "수온 오차": "SST error",
    "기온 °C": "Air temp °C",
    "체감 °C": "Apparent °C",
    "이슬점 °C": "Dew point °C",
    "습구 °C": "Wet bulb °C",
    "지표 온도 °C": "Surface temp °C",
    "습도 %": "Humidity %",
    "기압 hPa": "Pressure hPa",
    "해면 기압 hPa": "Sea-level pressure hPa",
    "풍속 km/h": "Wind km/h",
    "{name} 파일이 열려 있어 저장하지 못했습니다": "Could not save {name} because the file is open",
    "정보": "Info",
    "기간": "Period",
    "생성 시각 UTC": "Created UTC",
    "시각 기준": "Time basis",
    "모든 시각은 UTC": "All times are UTC",
    "주의": "Note",
    "SQLite에서 다시 생성되는 파일. 직접 고친 내용은 다음 저장 때 덮어씀":
        "Regenerated from SQLite. Manual edits are overwritten on the next save",
    "시트": "Sheet",
    "행 수": "Rows",
    "격자평균": "Grid means",
    "월간요약": "Monthly summary",
    "저장된 시각을 차례로 재생": "Play the stored times in order",
    "저장된 시각 고르기": "Choose a stored time",
    "표본 수": "Samples",
    "평균": "Mean",
    "표준편차": "Std dev",
    "첫 시각 UTC": "First UTC",
    "마지막 시각 UTC": "Last UTC",
    "전월 평균": "Prev month mean",
    "전월 대비": "Change vs prev",
    "빠진 날 {n}일치 보충": "{n} missed day(s) backfilled",
    "남은 {n}일치는 잠시 뒤 이어받습니다": "The remaining {n} continue in a moment",
    "업데이트를 받는 중입니다. 지금 닫으면 업데이트가 취소되고 수집도 멈춥니다. 닫을까요?":
        "An update is being downloaded. Closing now cancels it and stops collection. Close anyway?",
    "수온염분_해역": "Water by area",
    "수온염분_수직": "Water vertical",
    "Argo_목록": "Argo list",
    "선박관측": "Ships",
    "OSMC관측": "OSMC obs",
    "기지기온": "Stations",
    "GFS기온": "GFS air",
    "모델예보": "Forecasts",
    "지점조회": "Point queries",
    "Argo층별": "Argo levels",
    "시각 UTC": "Time UTC",
    "레이어": "Layer",
    "단위": "Unit",
    "60°S 이남 평균": "Mean south of 60°S",
    "최소": "Min",
    "최대": "Max",
    "유효 비율": "Valid ratio",
    "지점": "Point",
    "위도": "Lat",
    "경도": "Lon",
    "자료": "Data",
    "종류": "Type",
    "항목": "Item",
    "값": "Value",
    "수심 m": "Depth m",
    "수온 °C": "Temp °C",
    "염분 PSU": "Salinity PSU",
    "플로트": "Float",
    "회차": "Cycle",
    "모드": "Mode",
    "위치 QC": "Position QC",
    "표층 수온 °C": "SST °C",
    "표층 염분 PSU": "SSS PSU",
    "최대 수심 m": "Max depth m",
    "층 수": "Levels",
    "호출부호": "Call sign",
    "플랫폼": "Platform",
    "기지": "Station",
    "예보 시각 UTC": "Forecast time UTC",
    "층": "Level",
    "키 구분": "Key type",
    "압력 dbar": "Pressure dbar",
    "정상": "OK",
    "갱신 없음": "Unchanged",
    "오류": "Error",
    "호출 한도": "Rate limited",
    "꺼짐": "Off",
    "수집 중": "Running",
    "대기": "Waiting",
    "{n}초": "{n} s",
    "{n}분": "{n} min",
    "{n}시간": "{n} h",
    "{n}일": "{n} d",
    "처음 범위": "Reset view",
    "이전": "Back",
    "다음": "Forward",
    "이동": "Pan",
    "영역 확대": "Zoom to area",
    "그림 저장": "Save figure",
    "표": "Table",
    "값을 표로 보기": "Show values as a table",
    "자료 없음": "No data",
    "표본 {n}개 — 수집이 이어지면 선으로 채워집니다": "{n} sample(s) so far — the line fills in as collection continues",
    "시각": "Time",
    "수심 (m)": "Depth (m)",
    "기온 (°C)": "Air temperature (°C)",
    "어는점": "Freezing point",
    "염분 (PSU)": "Salinity (PSU)",
    "수온 (°C)": "Temperature (°C)",
    "오류: {message}": "Error: {message}",
    "응답 없음: {items}": "No response: {items}",
    "자료 시각": "Data time",
    "경과": "Age",
    "비고": "Notes",
    "대표값": "Representative",
    "표층 염분": "Surface salinity",
    "어는점과의 차": "Above freezing point",
    "결측": "Missing",
    "해빙": "Sea ice",
    "WOA23 기후값": "WOA23 climatology",
    "T-S 다이어그램 (등치선: σt)": "T-S diagram (contours: σt)",
    "실시간": "Real-time",
    "보정": "Adjusted",
    "지연 보정": "Delayed mode",
    ", 추정 위치": ", estimated position",
    "Argo: 500 km 이내 최근 45일 프로파일 없음": "Argo: no profile within 500 km in the last 45 days",
    "WOA23: {month}월 기후값 (1500 m 아래 연평균)": "WOA23: climatology for month {month} (annual below 1500 m)",
    "기온": "Air temperature",
    "체감": "Apparent",
    "이슬점": "Dew point",
    "습구": "Wet bulb",
    "지표 온도": "Surface temperature",
    "상대 습도": "Relative humidity",
    "지표 기압": "Surface pressure",
    "풍속": "Wind speed",
    "현재 (GFS)": "Current (GFS)",
    "현재 (GFS, {time})": "Current (GFS, {time})",
    "Windy: testing 키, 값이 변형되어 있음": "Windy: testing key, values are altered",
    "Windy: 공식 API 값": "Windy: official API values",
    "Windy: API 키 없음 (파일 > 설정)": "Windy: no API key (File > Settings)",
    "Windy GFS (변형값)": "Windy GFS (altered)",
    "2 m 기온 예보, 모델별": "2 m air temperature forecast by model",
    "고도별 기온": "Air temperature by pressure level",
    "기지 실측: {station} ({km} km)": "Station observed: {station} ({km} km)",
    "기지 실측": "Station observed",
    "400 km 이내 METAR 기지 없음": "No METAR station within 400 km",
    "표층 수온, OISST ({days}일)": "SST, OISST ({days} days)",
    "표층 염분, 위성 ({days}일)": "Surface salinity, satellite ({days} days)",
    "결측 (해빙 또는 연안)": "Missing (ice or coast)",
    "해빙 농도, OISST ({days}일)": "Sea ice concentration, OISST ({days} days)",
    "해빙 없음": "No sea ice",
    "기온, ERA5 일평균·최저·최고": "Air temperature, ERA5 daily mean, min and max",
    "일평균": "Daily mean",
    "설정": "Settings",
    "testing (무료, 변형된 값)": "testing (free, altered values)",
    "professional (유료)": "professional (paid)",
    "찾아보기…": "Browse…",
    "Windy API 키": "Windy API key",
    "Windy 키 종류": "Windy key type",
    "엑셀 저장 폴더": "Excel folder",
    "데이터베이스": "Database",
    "데이터 출처": "Data sources",
    "제공처": "Provider",
    "갱신": "Update",
    "nullschool·Windy와의 관계": "Relation to nullschool and Windy",
    "수집하지 않는 자료": "Data not collected",
    "프로그램 정보": "About",
    "남극해 수온·염분 모니터": "Antarctic Ocean Monitor",
    "MIT 라이선스": "MIT License",
    "자료 출처": "Data sources",
    "파일": "File",
    "설정…": "Settings…",
    "엑셀 DB 지금 저장": "Save Excel database now",
    "엑셀 폴더 열기": "Open Excel folder",
    "데이터 폴더 열기": "Open data folder",
    "CSV 내보내기": "Export CSV",
    "측정값…": "Measurements…",
    "Argo 전 층…": "Argo all levels…",
    "현재 레이어…": "Current layer…",
    "종료": "Quit",
    "보기": "View",
    "언어": "Language",
    "수집": "Collect",
    "지금 전체 수집": "Collect all now",
    "소스별 수집": "Collect source",
    "도움말": "Help",
    "사용 설명서…": "User guide…",
    "사용 설명서": "User guide",
    "데이터 출처…": "Data sources…",
    "라이선스…": "License…",
    "라이선스": "License",
    "제3자 고지…": "Third-party notices…",
    "제3자 고지": "Third-party notices",
    "저작권": "Copyright",
    "모든 버전": "all versions",
    "인용": "Cite as",
    "문의": "Contact",
    "프로그램 정보…": "About…",
    "업데이트 확인…": "Check for updates…",
    "업데이트 확인": "Check for updates",
    "업데이트 확인 중…": "Checking for updates…",
    "새 버전 {version}이 있습니다. 내려받기 페이지를 열까요?": "Version {version} is available. Open the download page?",
    "최신 버전입니다 ({version})": "You have the latest version ({version})",
    "업데이트 확인 실패: {error}": "Update check failed: {error}",
    "업데이트": "Updates",
    "확인하지 않음": "Do not check",
    "새 버전이 있으면 알리고 물어본 뒤 설치": "Tell me about a new version and ask before installing",
    "자동으로 내려받아 설치하고 다시 시작": "Download, install and restart automatically",
    "새 버전 {version}이 있습니다. 지금 내려받아 설치하고 다시 시작할까요?": "Version {version} is available. Download it now, install it and restart?",
    "새 버전 {version}을 {seconds}초 뒤에 설치하고 다시 시작합니다.": "Version {version} will be installed and the program restarted in {seconds} s.",
    "지금 설치": "Install now",
    "나중에": "Later",
    "업데이트 내려받는 중… {percent}%": "Downloading the update… {percent}%",
    "업데이트 설치 중…": "Installing the update…",
    "업데이트 실패: {error}": "Update failed: {error}",
    "이 운영체제용 설치 파일이 릴리스에 없습니다": "The release has no installer for this operating system",
    "내려받은 파일의 SHA-256이 다릅니다": "The downloaded file's SHA-256 does not match",
    "GitHub 요청 한도에 걸렸습니다. 약 {minutes}분 뒤에 다시 확인하세요": "GitHub's request limit was reached. Check again in about {minutes} min",
    "GitHub 요청 한도에 걸렸습니다. 잠시 후 다시 확인하세요": "GitHub's request limit was reached. Check again in a little while",
    "{minutes}분 안에 끝나지 않아 중단했습니다": "Stopped after {minutes} min without finishing",
    "시간이 길어져 남은 변수 {n}개는 잠시 뒤 이어받습니다": "Taking long; the remaining {n} variable(s) continue in a moment",
    "화면 구성 요소가 설치되지 않았습니다. pip install \"suya[gui]\" 로 설치하거나 suya daemon 으로 창 없이 수집하세요":
        "The window libraries are not installed. Install them with pip install \"suya[gui]\" or collect without a window with suya daemon",
    "이 설치본은 스스로 업데이트할 수 없습니다": "This installation cannot update itself",
    "SUYA가 이미 실행 중입니다. 창이 보이지 않으면 Dock이나 작업 표시줄을 확인하세요.": "SUYA is already running. If you cannot see its window, look in the Dock or the taskbar.",
    "혼합층 깊이 (10 m 기준 수온에서 0.2 °C 차): {items}": "Mixed-layer depth (0.2 °C from the 10 m temperature): {items}",
    "이 설치본은 스스로 업데이트할 수 없습니다. 새 버전 {version}의 내려받기 페이지를 열까요?": "This installation cannot update itself. Open the download page for version {version}?",
    "수심": "Depth",
    "기지·해역": "Stations and areas",
    "위치": "Location",
    "위도, 경도 또는 nullschool·Windy 링크": "Lat, lon or nullschool / Windy link",
    "표층": "Surface",
    "수직 프로파일": "Vertical profile",
    "시계열": "Time series",
    "이 레이어는 수집 대기 중": "This layer is waiting for collection",
    "유효 {pct}%": "valid {pct}%",
    "범위 밖 {n}개 제외": "{n} out of range removed",
    "선택한 지점": "Selected point",
    "육지/빙붕. 최근접 해양 격자 {coord} ({km} km) 값 표시": "Land or ice shelf. Showing nearest ocean cell {coord} ({km} km)",
    "육지/빙붕. 주변에 해양 격자 없음": "Land or ice shelf. No ocean cell nearby",
    "받는 중…": "Loading…",
    "HYCOM 응답 대기 중 (최대 약 2분)…": "Waiting for HYCOM (up to about 2 min)…",
    "응답 시간 초과 ({seconds}초)": "no answer within {seconds} s",
    "층별 값 없음 {n}개": "{n} without level data",
    "표층 값 {n}개를 층별 값으로 바로잡음": "{n} surface values corrected from level data",
    "지도": "Map",
    "해역 통계": "Area statistics",
    "기지 관측": "Station observations",
    "지점 목록": "Points",
    "층별 평균": "Mean by depth",
    "수집 상태": "Collection status",
    "수집 로그": "Collection log",
    "해역": "Area",
    "SST 편차 °C": "SST anomaly °C",
    "500 m 수온 °C": "500 m temp °C",
    "500 m 염분": "500 m salinity",
    "남극해 전체 (60°S 이남)": "Southern Ocean (south of 60°S)",
    "Argo {profiles}개 프로파일, 최근 {days}일, 60°S 이남": "Argo: {profiles} profiles, last {days} days, south of 60°S",
    "기지명": "Station name",
    "기압": "Pressure",
    "좌표": "Coordinates",
    "기온 갱신": "Air temp updated",
    "입력한 링크": "Linked points",
    "소스": "Source",
    "상태": "Status",
    "주기": "Interval",
    "최종 수집": "Last run",
    "다음 수집": "Next run",
    "행": "Rows",
    "메시지": "Message",
    "측정값 {rows}행": "{rows} measurements",
    "수집 꺼짐": "Collection off",
    "수집 중 {n}": "Running {n}",
    "정상 {ok}/{total}": "OK {ok}/{total}",
    "오류 {n}": "Errors {n}",
    "엑셀 {time}": "Excel {time}",
    "CSV로 저장": "Save as CSV",
    "저장 중…": "Saving…",
    "{path}: {count}행 저장": "{path}: {count} rows saved",
    "저장 실패: {error}": "Save failed: {error}",
    "다시 시작 전까지 일부 설정은 적용되지 않을 수 있습니다": "Some settings may apply after a restart",
    "이온 조성": "Ion composition",
    "이온조성": "Ion composition",
    "이온환산계수": "Ion factors",
    "이온 환산": "Ion conversion",
    "기준 염분 g/kg": "Reference salinity g/kg",
    "기준 염분 S_R": "Reference salinity S_R",
    "실용 염분": "Practical salinity",
    "염소량": "Chlorinity",
    "이온 세기": "Ionic strength",
    "물 1 kg 기준": "per kg of water",
    "성분": "Component",
    "기호": "Symbol",
    "전하": "Charge",
    "몰질량 g/mol": "Molar mass g/mol",
    "질량 비율 %": "Mass share %",
    "염분 1당 g/kg": "g/kg per unit salinity",
    "염분 1당 mmol/kg": "mmol/kg per unit salinity",
    "염분 35에서 g/kg": "g/kg at salinity 35",
    "염분 35에서 mmol/kg": "mmol/kg at salinity 35",
    "DB 열": "DB column",
    "합계": "Total",
    "DB·엑셀에 저장": "Stored in DB and Excel",
    "기준 염분 S_R 과 같음": "Equals reference salinity S_R",
    "자료별 염분에서 환산한 주요 이온 (g/kg)": "Major ions derived from each source's salinity (g/kg)",
    "이 지점에서 쓸 수 있는 염분 값이 없어 환산하지 못했습니다": "No usable salinity at this point, so nothing was derived",
    "염분은 0보다 큰 수여야 합니다": "Salinity must be a number greater than 0",
    "염분에 기준 조성(Millero 외 2008)을 곱한 환산값입니다. 이온을 직접 잰 값이 아닙니다.": (
        "Derived by multiplying salinity by the Reference Composition (Millero et al. 2008). "
        "These are not direct ion measurements."
    ),
    "이온 시트와 이온 열은 염분에 기준 조성(Millero 외 2008)을 곱한 환산값. 이온을 직접 잰 값이 아님": (
        "Ion sheets and ion columns are derived by multiplying salinity by the Reference Composition "
        "(Millero et al. 2008). They are not direct ion measurements"
    ),
    "염분에 기준 조성(Millero 외 2008)의 비율을 곱한 환산값입니다. 이온을 직접 잰 값이 아니며, "
    "해빙 주변의 브라인이나 강물이 섞이는 곳에서는 실제 비율이 다를 수 있습니다. "
    "주요 이온 여덟 가지는 염분이 저장될 때마다 DB와 엑셀에 함께 쌓입니다.": (
        "Derived by multiplying salinity by the ratios of the Reference Composition (Millero et al. 2008). "
        "These are not direct ion measurements, and real ratios can differ near sea-ice brine or where river "
        "water mixes in. The eight major ions are added to the database and Excel whenever a salinity is stored."
    ),
    "염화 이온": "Chloride",
    "나트륨 이온": "Sodium",
    "황산 이온": "Sulfate",
    "마그네슘 이온": "Magnesium",
    "칼슘 이온": "Calcium",
    "칼륨 이온": "Potassium",
    "탄산수소 이온": "Bicarbonate",
    "브롬화 이온": "Bromide",
    "붕산": "Boric acid",
    "탄산 이온": "Carbonate",
    "스트론튬 이온": "Strontium",
    "붕산 이온": "Borate",
    "플루오린화 이온": "Fluoride",
    "수산화 이온": "Hydroxide",
    "이산화 탄소": "Carbon dioxide",
    "1기압 밀도": "Density at 1 atm",
    "1기압 밀도 kg/m³": "Density at 1 atm kg/m³",
    "범위 검사": "Range check",
    "범위 안": "within range",
    "낮음": "low",
    "높음": "high",
    "{low}~{high} PSU": "{low} to {high} PSU",
    "부피 기준": "Volume basis",
    "염분범위": "Salinity ranges",
    "표준 수심 m": "Standard depth m",
    "적용 수심 초과 m": "Deeper than m",
    "적용 수심 이하 m": "Down to m",
    "염분 하한": "Salinity minimum",
    "염분 상한": "Salinity maximum",
    "범위 검사 열은 염분이 남극해 수심별 범위(Boyer & Levitus 1994, NOAA NESDIS 81)를 벗어난 행에만 낮음·높음을 적음. "
    "범위가 넓어 큰 오류만 걸리며 값은 지우거나 고치지 않음": "The range check column says low or high only on rows whose salinity "
    "is outside the Southern Ocean range for that depth (Boyer & Levitus 1994, NOAA NESDIS 81). The ranges are broad, "
    "so only gross errors are caught, and no value is removed or changed",
    "mmol/L 과 밀도는 같은 자료·위치·층·시각의 수온이 있는 행만 계산. 밀도는 그 수온과 염분의 1기압 값이고 현장 압력은 넣지 않음": "mmol/L "
    "and density are filled only on rows that have a temperature for the same source, place, level and time. The density "
    "is the 1 atm value for that temperature and salinity; in-situ pressure is not included",
    "밀도는 수온 {low}~{high} °C, 염분 {limit} 이하에서만 계산합니다": "Density is computed only for temperatures of {low} to {high} °C "
    "and salinity up to {limit}",
    "수심은 0 이상이어야 합니다": "Depth must be 0 or more",
    "mmol/L 은 그 수온과 염분의 1기압 밀도로 바꾼 값입니다. 현장 압력은 넣지 않았습니다.": "mmol/L uses the density at 1 atm for that "
    "temperature and salinity. In-situ pressure is not included.",
    "범위는 남극해 수심별 염분 범위(Boyer & Levitus 1994)이고, 넓게 잡혀 있어 큰 오류만 가려냅니다.": "The range is the Southern Ocean "
    "salinity range by depth (Boyer & Levitus 1994). It is broad and catches gross errors only.",
    "유효 격자 수": "Valid cells",
    "격자이온": "Grid ions",
    "격자 이온 환산": "Grid ion conversion",
    "격자이온 시트는 염분 격자의 60°S 이남 평균과 해역 평균에 같은 계수를 곱한 값. 환산이 염분에 비례하므로 "
    "칸마다 환산해 평균한 값과 같음. 평균 염분은 소수 셋째 자리까지 저장된 값이고, 짝이 되는 수온이 없어 mmol/L 은 없음": (
        "The Grid ions sheet multiplies the mean of each salinity grid south of 60°S, and the mean of each sector, "
        "by the same ratios. The conversion is proportional to salinity, so the result equals converting every cell "
        "and then averaging. Mean salinity is stored to three decimals, and there is no mmol/L because no paired "
        "temperature exists"
    ),
    "염분 레이어가 아니어서 이온으로 환산할 수 없습니다: {layer}": "Not a salinity layer, so it cannot be converted to ions: {layer}",
    "표시": "Show",
    "염분 지도를 염분에서 환산한 이온 농도로 읽습니다. 색은 그대로이고 눈금과 커서 값이 바뀝니다.": "Reads the salinity map as an "
    "ion concentration derived from salinity. Colors stay the same; the legend ticks and the cursor value change.",
    "현재 레이어 이온…": "Current layer ions…",
    "{ion} {unit} = 염분 × {factor} (기준 조성으로 환산, 측정값 아님)": "{ion} {unit} = salinity × {factor} "
    "(derived from the Reference Composition, not measured)",
}


def set_language(language: str) -> None:
    global _language
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    _language = language


def get_language() -> str:
    return _language


def saved_language() -> str | None:
    """환경 변수, .env, 사용자 설정 순으로 저장된 언어를 찾습니다."""
    value = (
        os.environ.get("MONITOR_LANG")
        or load_dotenv(Path(".env")).get("MONITOR_LANG")
        or load_dotenv(app_data_dir() / SETTINGS_FILE).get("MONITOR_LANG")
    )
    return value if value in LANGUAGES else None


def system_language() -> str:
    name = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
    return "ko" if name.startswith(("ko", "korean")) else "en"


def default_language() -> str:
    return saved_language() or system_language()


def tr(text: str, **kwargs) -> str:
    template = EN.get(text, text) if _language == "en" else text
    return template.format(**kwargs) if kwargs else template


def msg(text: str, **kwargs) -> str:
    """나중에 어느 언어로든 보여 줄 수 있게 원문과 인자를 묶습니다."""
    return _MARK + json.dumps([text, kwargs], ensure_ascii=False)


def is_encoded(text: str) -> bool:
    return text.startswith(_MARK) or _SEP in text


def join(*parts: str) -> str:
    return _SEP.join(part for part in parts if part)


def render(raw: str | None) -> str:
    """저장된 메시지를 현재 언어 글자로 바꿉니다. 일반 문자열은 그대로 두고, 인자 안에 든 메시지도 함께 바꿉니다."""
    if not raw:
        return ""
    output = []
    for part in raw.split(_SEP):
        if part.startswith(_MARK):
            try:
                text, kwargs = json.loads(part[1:])
            except ValueError:
                output.append(part[1:])
                continue
            for key, value in kwargs.items():
                if isinstance(value, str) and is_encoded(value):
                    kwargs[key] = render(value)
            output.append(tr(text, **kwargs))
        else:
            output.append(part)
    return ", ".join(output)
