"""프로그램 안의 사용 설명서. 도움말 > 사용 설명서 에서 보여 줍니다."""

from __future__ import annotations

from . import __concept_doi__, __email__, __url__, __version__
from .i18n import get_language

_STYLE = """
<style>
 body { font-size: 10.5pt; }
 h1 { font-size: 15pt; margin-bottom: 2px; }
 h2 { font-size: 12.5pt; margin-top: 18px; border-bottom: 1px solid #999; }
 h3 { font-size: 11pt; margin-top: 12px; }
 table { border-collapse: collapse; }
 td, th { border: 1px solid #aaa; padding: 3px 7px; vertical-align: top; }
 th { background: #e8e8e8; }
 code { font-family: Menlo, Consolas, monospace; }
 .note { color: #555; }
</style>
"""

HELP_KO = _STYLE + f"""
<h1>SUYA {__version__} — 남극해 수온·염분 모니터 사용 설명서</h1>
<p class="note">Copyright © 2026 임종수 (Jongsu Lim) &lt;{__email__}&gt;, 인천대학교 물리학과 학부연구생, HMOL 연구실 (ORCID 0009-0000-3395-1484) ·
박수연 (Suyeon Park) &lt;dbsnt110@inu.ac.kr&gt;, 인천대학교 신소재공학과 석사과정, CELLMATE 연구실 · MIT 라이선스 · <a href="{__url__}">{__url__}</a> ·
DOI <a href="https://doi.org/{__concept_doi__}">{__concept_doi__}</a></p>

<h2>1. 이 프로그램이 하는 일</h2>
<p>남극해(대략 40°S 이남)의 <b>수온, 염분, 기온</b>을 공개 데이터 API에서 <b>계속 자동으로 받아</b>
컴퓨터에 쌓고, 남극 중심 지도와 그래프로 보여 줍니다. 창을 열어 두기만 하면 소스마다 정해진 주기로 수집이 반복되고,
새 자료가 들어올 때마다 지도·표·그래프가 스스로 갱신되며, 15분마다 월별 엑셀 파일로도 정리됩니다.</p>
<p>earth.nullschool.net 과 windy.com 이 지도에 그리는 것과 <b>같은 원천 데이터</b>(GFS, OISST, ECMWF 등)를 직접 받습니다.
두 사이트 자체를 긁어오지는 않습니다(nullschool은 공개 API가 없고, Windy 이용약관 4.6.1은 자동 수집을 금지합니다).
Windy는 <b>공식 Point Forecast API</b>만, 사용자가 키를 넣었을 때 씁니다.</p>

<h2>2. 처음 실행하면</h2>
<ol>
 <li>언어(한국어/영어)를 고릅니다. 나중에 <b>보기 &gt; 언어</b>에서 바꿀 수 있습니다.</li>
 <li>창이 뜨면 바로 수집이 시작됩니다. 빠른 소스(기지 관측, GFS, OISST)는 1분 안에, HYCOM 격자와 Argo 층별 자료는
  5~15분쯤 지나야 채워집니다. 지도에 "수집 대기 중"이 보이면 기다리면 됩니다.</li>
 <li>아무 것도 설정할 필요가 없습니다. Windy 키만 선택 사항입니다(<b>파일 &gt; 설정</b>).</li>
</ol>

<h2>3. 화면 구성</h2>
<h3>지도 탭</h3>
<table>
 <tr><th>요소</th><th>설명</th></tr>
 <tr><td>레이어</td><td>SST·OISST, SST 편차, 수온·HYCOM, 염분·HYCOM, SSS·SMOS, SSS·SMAP, 해빙 농도, 기온 2 m·GFS.
  HYCOM 레이어는 <b>수심</b>(0·100·200·500·1000·2000 m)을 고를 수 있습니다.</td></tr>
 <tr><td>Argo, 기지·해역</td><td>지도 위 표시를 켜고 끕니다. 검은 점 = 최근 30일 Argo 프로파일 위치, 삼각형 = 기지, 네모 = 해역 대표 지점.</td></tr>
 <tr><td>마우스</td><td>움직이면 상태 표시줄에 좌표와 값이 나옵니다. <b>휠</b>: 확대, <b>끌기</b>: 이동, <b>더블클릭</b>: 원래 크기,
  <b>클릭</b>: 그 지점 상세 조회(빨간 십자). 점 위에서 클릭하면 그 Argo/기지를 조회합니다.</td></tr>
 <tr><td>위치 입력</td><td>"-65, -60" 처럼 위도, 경도를 넣거나 nullschool·Windy 주소를 그대로 붙여 넣고 OK. 주소에서 좌표만 읽고 그 사이트에 접속하지는 않습니다.</td></tr>
 <tr><td>색 범례</td><td>지도 아래 막대. 수온 thermal, 염분 haline, 편차 balance, 해빙 ice(cmocean 해양 표준 색).</td></tr>
</table>
<p>육지나 빙붕을 클릭하면 "최근접 해양 격자 … 값 표시"라고 알려 주고, 가장 가까운 바다 격자의 값을 대신 보여 줍니다. 기온은 클릭한 지점 그대로입니다.</p>

<h3>지점 상세(오른쪽)</h3>
<table>
 <tr><th>탭</th><th>내용</th></tr>
 <tr><td>표층</td><td>대표값(표층 수온·염분, 어는점, 어는점과의 차, 밀도 σt)과 소스별 값 표. 소스마다 자료 시각과 경과 시간이 함께 나옵니다.</td></tr>
 <tr><td>수직 프로파일</td><td>깊이별 수온·염분 그래프(Argo 실측, HYCOM 모델, WOA23 기후값)와 T-S 다이어그램(회색 등치선 σt, 검은 선 어는점).
  HYCOM 서버 응답에 최대 1분 걸립니다.</td></tr>
 <tr><td>기온</td><td>GFS 현재값 8종, 5개 모델(GFS·ECMWF·ICON·GEM·JMA)의 7일 기온 예보 비교, 가까운 기지의 METAR 실측, 기압 고도별 기온.</td></tr>
 <tr><td>시계열</td><td>최근 30일 OISST 수온, 위성 염분(SMOS·SMAP), 해빙 농도, ERA5 일별 기온.</td></tr>
</table>
<p>모든 그래프 위의 도구막대: 처음 범위 / 이전 / 다음 / 이동 / 영역 확대 / 그림 저장(PNG·PDF·SVG) / <b>표</b>(값을 표로 보기).
그래프에 마우스를 올리면 그 위치의 값이 풍선으로 나옵니다. 표에서 행을 고르고 Ctrl+C(⌘C)하면 엑셀에 바로 붙습니다.</p>

<h3>해역 통계 탭</h3>
<p>60°S 이남 전체 평균과, 5개 해역(웨델해, 인도양, 서태평양, 로스해, 아문젠·벨링스하우젠해)별 면적 가중 평균.
아래 그래프는 층별 평균 수온·염분(Argo 실측 vs HYCOM 모델)입니다.</p>
<h3>지점 목록 탭</h3>
<p>24개 기본 지점(입력한 두 링크 지점, 기지 12곳, 해역 10곳)의 최신값과 METAR 기지 관측. 행을 <b>더블클릭</b>하면 지도에서 그 지점이 열립니다.</p>
<h3>수집 상태 탭</h3>
<table>
 <tr><th>상태</th><th>뜻</th></tr>
 <tr><td>정상</td><td>새 자료를 받아 저장했습니다.</td></tr>
 <tr><td>갱신 없음</td><td>원천에 새 자료가 없어 저장할 것이 없었습니다(정상).</td></tr>
 <tr><td>오류</td><td>서버 오류나 네트워크 문제. 잠시 뒤 자동으로 다시 시도하며 간격을 늘려 갑니다.</td></tr>
 <tr><td>호출 한도</td><td>무료 한도에 걸려 1시간 이상 쉽니다.</td></tr>
 <tr><td>꺼짐</td><td>설정이 없어 건너뜁니다(Windy 키 없음).</td></tr>
 <tr><td>수집 중 / 대기</td><td>지금 받는 중 / 아직 한 번도 돌지 않음.</td></tr>
</table>
<p>오른쪽 로그에는 이 창을 연 뒤의 수집 결과가 시간순으로 쌓입니다.</p>

<h2>4. 메뉴</h2>
<table>
 <tr><td><b>파일 &gt; 설정</b></td><td>Windy API 키와 종류, 엑셀 저장 폴더.</td></tr>
 <tr><td><b>파일 &gt; 엑셀 DB 지금 저장</b></td><td>15분 주기를 기다리지 않고 바로 엑셀 파일을 다시 씁니다.</td></tr>
 <tr><td><b>파일 &gt; 엑셀 폴더 열기 / 데이터 폴더 열기</b></td><td>탐색기(Finder)로 엽니다.</td></tr>
 <tr><td><b>파일 &gt; CSV 내보내기</b></td><td>측정값 전체, Argo 전 층, 현재 지도 레이어를 CSV로.</td></tr>
 <tr><td><b>보기 &gt; 언어</b></td><td>한국어 / English. 창이 다시 열립니다(수집은 끊기지 않습니다).</td></tr>
 <tr><td><b>수집 &gt; 지금 전체 수집</b> (F5)</td><td>모든 소스를 즉시 한 번 받습니다. <b>소스별 수집</b>으로 하나만 고를 수도 있습니다.</td></tr>
</table>

<h2>5. 데이터 출처와 품질 규칙</h2>
<table>
 <tr><th>자료</th><th>제공</th><th>주기</th><th>내용</th></tr>
 <tr><td>METAR</td><td>NOAA AWC</td><td>5분 확인</td><td>남극점·맥머도·마람비오 등 기지의 실측 기온·이슬점·기압</td></tr>
 <tr><td>GFS 현재·격자</td><td>NOAA / Open-Meteo</td><td>15분 / 3시간</td><td>기온, 체감, 이슬점, 습구, 지표 온도, 습도, 기압, 풍속. nullschool 기온 레이어와 같은 모델</td></tr>
 <tr><td>모델별 예보</td><td>Open-Meteo</td><td>3시간</td><td>GFS·ECMWF·ICON·GEM·JMA 7일 기온</td></tr>
 <tr><td>OISST v2.1</td><td>NOAA NCEI</td><td>6시간 확인(하루 1값)</td><td>0.25° 수온·편차·해빙 농도. nullschool 수온 레이어 원천</td></tr>
 <tr><td>MUR SST</td><td>NASA JPL</td><td>지점 조회 시</td><td>0.01° 수온, 분석 오차, 해빙 농도</td></tr>
 <tr><td>SMOS / SMAP</td><td>ESA / NASA, NOAA CoastWatch</td><td>6시간 확인</td><td>위성 표층 염분. 65°S 이남과 해빙 근처는 대부분 결측</td></tr>
 <tr><td>HYCOM ESPC-D-V02</td><td>미 해군 / HYCOM.org</td><td>3시간</td><td>1/12° 모델의 40개 층 수온·염분. 지도는 약 0.5° 간격, 6개 수심. 80°S 이남 없음</td></tr>
 <tr><td>Argo</td><td>Argo / Ifremer</td><td>1시간 확인</td><td>최근 30일, 55°S 이남 플로트 프로파일(~2000 m). 염분의 기준값</td></tr>
 <tr><td>GOSUD</td><td>Ifremer</td><td>1시간 확인</td><td>항해 중 선박 표층 수온·염분</td></tr>
 <tr><td>WOA23</td><td>NOAA NCEI</td><td>지점 조회 시</td><td>월별 기후값(1500 m 아래는 연평균)</td></tr>
 <tr><td>ERA5</td><td>ECMWF / Open-Meteo</td><td>지점 조회 시</td><td>일별 평균·최저·최고 기온</td></tr>
 <tr><td>Windy</td><td>Windy.com 공식 API</td><td>3시간</td><td>키가 있을 때만. 기온·이슬점·습도·기압. 수온·염분 항목은 이 API에 없음</td></tr>
</table>
<ul>
 <li><b>Argo 품질</b>: 플래그 1(양호)·2(대체로 양호)만 받습니다. 보정 모드(A·D)면 보정값을, 실시간(R)이면 원시값을 씁니다. 상승 관측이 있으면 그것만 씁니다.</li>
 <li><b>범위 밖 값 제거</b>: 수온 −3~40 °C, 위성 염분 28~37 PSU, 모델·Argo 염분 20~42 PSU 밖은 버립니다(위성 염분에서 실제로 0.0이나 42.8이 내려옵니다).</li>
 <li><b>대표값</b>: 100 km·10일 안의 Argo 실측이 있으면 그것, 없으면 수온은 OISST → MUR → HYCOM, 염분은 HYCOM → SMOS → SMAP 순.</li>
 <li><b>파생값</b>: 어는점 Millero(1978), 밀도 σt EOS-80(Millero &amp; Poisson 1981), 압력→수심 Saunders &amp; Fofonoff(1976).</li>
 <li><b>시각</b>: 저장은 모두 UTC, 화면은 이 컴퓨터의 현지 시각으로 보여 줍니다.</li>
</ul>

<h2>6. 데이터가 저장되는 곳</h2>
<table>
 <tr><th>운영체제</th><th>데이터베이스·설정·로그</th><th>엑셀 DB(기본)</th></tr>
 <tr><td>Windows</td><td><code>%APPDATA%\\SUYA\\</code></td><td><code>문서\\SUYA\\</code></td></tr>
 <tr><td>macOS</td><td><code>~/Library/Application Support/SUYA/</code></td><td><code>~/Documents/SUYA/</code></td></tr>
 <tr><td>Linux</td><td><code>~/.local/share/SUYA/</code></td><td><code>~/Documents/SUYA/</code></td></tr>
</table>
<ul>
 <li><code>antarctic.db</code>: 모든 원본 값(SQLite). 다른 프로그램(파이썬, R, DB Browser)에서 바로 열 수 있습니다.</li>
 <li><code>settings.env</code>: 설정. <code>monitor.log</code>: 로그(문제가 생기면 이 파일을 보세요).</li>
 <li><code>antarctic_db_YYYY-MM.xlsx</code>: 월별 엑셀. 시트 = 정보, 격자평균, 수온염분_해역, 수온염분_수직, Argo_목록, 선박관측, 기지기온, GFS기온, 모델예보, Windy, 지점조회.</li>
 <li><code>argo_levels_YYYY-MM.xlsx</code>: Argo 전 층(행이 많아 별도 파일).</li>
</ul>
<p><b>주의</b>: 엑셀 파일은 SQLite에서 <b>다시 생성</b>됩니다. 직접 고친 내용은 다음 저장 때 덮어쓰입니다. 분석은 복사본에서 하세요.
Windows에서 엑셀로 파일을 열어 둔 채로는 저장이 실패하고 다음 주기에 다시 시도합니다. 지난달까지의 파일은 더 이상 건드리지 않습니다.</p>

<h2>7. 한계</h2>
<ul>
 <li>Windy 무료(testing) 키는 Windy가 값을 섞고 변형해서 돌려줍니다. 그래프에 "(변형값)"으로 표시하며 실제 예보로 쓰면 안 됩니다.</li>
 <li>위성 염분은 해빙 아래와 연안에서 값이 없습니다. 염분 지도는 HYCOM 모델을, 실측은 Argo를 보세요.</li>
 <li>HYCOM은 80°S 이남(로스·필히너 빙붕 아래 등)을 다루지 않습니다.</li>
 <li>Open-Meteo 무료 한도(하루 10,000 호출) 안에서 하루 9,000 호출까지만 쓰도록 스스로 제한합니다.</li>
 <li>수치모델·위성 값은 관측이 아니라 추정값이며, 어느 제공 기관도 정확도를 보증하지 않습니다.</li>
</ul>

<h2>8. 명령줄</h2>
<pre>suya                 창 열기 (기본)
suya daemon          창 없이 계속 수집
suya collect         모든 소스 한 번 수집
suya excel-sync      엑셀 파일 지금 쓰기 (--all: 모든 달)
suya export measurements --out a.csv
suya sources         소스 목록
suya --lang en       영어로 실행</pre>

<h2>9. 문제 해결</h2>
<ul>
 <li><b>지도가 비어 있음</b>: 첫 수집이 끝날 때까지 몇 분 기다리세요. 수집 상태 탭에서 오류가 계속되면 네트워크(방화벽, 프록시)를 확인하세요.</li>
 <li><b>HYCOM이 느리거나 오류</b>: HYCOM 서버가 종종 500을 돌려줍니다. 프로그램이 두 호스트를 번갈아 시도하고 다음 주기에 다시 받습니다.</li>
 <li><b>처음부터 다시</b>: 프로그램을 끄고 데이터 폴더의 <code>antarctic.db</code>를 지우면 빈 상태로 시작합니다.</li>
 <li><b>버그 신고</b>: <a href="{__url__}/issues">{__url__}/issues</a> 또는 {__email__}. <code>monitor.log</code>를 함께 보내 주세요.</li>
</ul>

<h2>10. 인용</h2>
<p>논문이나 보고서에 쓸 때는 데이터를 제공한 기관(5장)을 인용하고, 이 프로그램은 아래처럼 인용해 주세요.
릴리스마다 Zenodo가 버전 DOI를 발급하고, 개념 DOI <a href="https://doi.org/{__concept_doi__}">{__concept_doi__}</a>는 모든 버전을 묶어 항상 최신 릴리스로 연결됩니다.
아래 인용은 개념 DOI를 쓰며, 특정 버전을 밝혀야 하면 Zenodo 기록에서 그 버전의 DOI를 고르세요.
저장소의 <code>CITATION.cff</code>와 GitHub의 "Cite this repository" 버튼에서 APA·BibTeX 형식을 바로 받을 수 있습니다.</p>
<pre>Lim, J. &amp; Park, S. (2026). SUYA: Antarctic ocean temperature, salinity and air temperature monitor ({__version__}).
Zenodo. https://doi.org/{__concept_doi__}</pre>
"""

HELP_EN = _STYLE + f"""
<h1>SUYA {__version__} — Antarctic Ocean Monitor user guide</h1>
<p class="note">Copyright © 2026 Jongsu Lim &lt;{__email__}&gt;, Undergraduate Researcher, Hybrid Materials &amp; Optoelectronics Laboratory (HMOL), Department of Physics, Incheon National University (ORCID 0009-0000-3395-1484) ·
Suyeon Park &lt;dbsnt110@inu.ac.kr&gt;, M.S. Student, Clean Energy and Materials Lab (CELLMATE), Department of Materials Science and Engineering, Incheon National University · MIT License · <a href="{__url__}">{__url__}</a> ·
DOI <a href="https://doi.org/{__concept_doi__}">{__concept_doi__}</a></p>

<h2>1. What the program does</h2>
<p>It <b>continuously downloads</b> ocean <b>temperature, salinity and air temperature</b> for the Southern Ocean
(roughly south of 40°S) from public data APIs, stores everything on your computer and shows it on a south-polar
map with charts. Leave the window open: each source is refreshed on its own schedule, the map, tables and charts
update themselves when new data arrives, and every 15 minutes the data is also written to monthly Excel workbooks.</p>
<p>It fetches the <b>same upstream datasets</b> that earth.nullschool.net and windy.com render (GFS, OISST, ECMWF, …).
It does not scrape either site: nullschool has no public API, and Windy's terms of use (§4.6.1) prohibit automated
collection. Windy is used only through its <b>official Point Forecast API</b>, and only if you enter your own key.</p>

<h2>2. First start</h2>
<ol>
 <li>Pick a language (Korean / English). You can change it later under <b>View &gt; Language</b>.</li>
 <li>Collection starts as soon as the window opens. Fast sources (station reports, GFS, OISST) arrive within a minute;
  HYCOM grids and Argo profile levels take 5–15 minutes. "Waiting for collection" on the map means just that.</li>
 <li>Nothing needs configuring. A Windy key is optional (<b>File &gt; Settings</b>).</li>
</ol>

<h2>3. The window</h2>
<h3>Map tab</h3>
<table>
 <tr><th>Item</th><th>Description</th></tr>
 <tr><td>Layer</td><td>SST · OISST, SST anomaly, Temperature · HYCOM, Salinity · HYCOM, SSS · SMOS, SSS · SMAP, Sea ice, Air temperature 2 m · GFS.
  HYCOM layers have a <b>depth</b> selector (0, 100, 200, 500, 1000, 2000 m).</td></tr>
 <tr><td>Argo, Stations and areas</td><td>Toggle markers. Black dots = Argo profiles from the last 30 days, triangles = stations, squares = sea-area points.</td></tr>
 <tr><td>Mouse</td><td>Move to read coordinates and the value in the status bar. <b>Wheel</b>: zoom, <b>drag</b>: pan, <b>double-click</b>: reset,
  <b>click</b>: inspect that point (red cross). Clicking a marker inspects that Argo float or station.</td></tr>
 <tr><td>Location box</td><td>Type "-65, -60" (lat, lon) or paste a nullschool / Windy URL and press OK. Only the coordinates are read; the site is not contacted.</td></tr>
 <tr><td>Colour bar</td><td>Below the map. cmocean oceanographic colormaps: thermal (temperature), haline (salinity), balance (anomaly), ice.</td></tr>
</table>
<p>Clicking land or an ice shelf shows "nearest ocean cell …" and uses the closest ocean grid cell for water values. Air temperature is for the clicked point itself.</p>

<h3>Point details (right side)</h3>
<table>
 <tr><th>Tab</th><th>Contents</th></tr>
 <tr><td>Surface</td><td>Representative values (SST, surface salinity, freezing point, margin above freezing, density σt) and a table of every source with data time and age.</td></tr>
 <tr><td>Vertical profile</td><td>Temperature and salinity against depth (Argo in situ, HYCOM model, WOA23 climatology) and a T-S diagram (grey contours σt, black line freezing point).
  The HYCOM server can take up to a minute.</td></tr>
 <tr><td>Air temperature</td><td>Eight GFS current values, 7-day forecasts from five models (GFS, ECMWF, ICON, GEM, JMA), METAR observations from the nearest station, temperature by pressure level.</td></tr>
 <tr><td>Time series</td><td>Last 30 days of OISST SST, satellite salinity (SMOS, SMAP), sea ice concentration and ERA5 daily air temperature.</td></tr>
</table>
<p>Every chart has a toolbar: reset view / back / forward / pan / zoom to area / save figure (PNG, PDF, SVG) / <b>Table</b>.
Hovering shows the values at the cursor. Select rows in any table and press Ctrl+C (⌘C) to paste them into Excel.</p>

<h3>Area statistics tab</h3>
<p>Area-weighted means south of 60°S overall and for five sectors (Weddell, Indian, Western Pacific, Ross, Amundsen-Bellingshausen),
plus mean temperature and salinity by depth (Argo vs HYCOM).</p>
<h3>Points tab</h3>
<p>Latest values at the 24 built-in points (the two linked points, 12 stations, 10 sea areas) and METAR station observations. <b>Double-click</b> a row to open it on the map.</p>
<h3>Collection status tab</h3>
<table>
 <tr><th>Status</th><th>Meaning</th></tr>
 <tr><td>OK</td><td>New data was fetched and stored.</td></tr>
 <tr><td>Unchanged</td><td>The source had nothing new (normal).</td></tr>
 <tr><td>Error</td><td>Server or network problem. Retried automatically with increasing delays.</td></tr>
 <tr><td>Rate limited</td><td>A free-tier limit was hit; the source pauses for at least an hour.</td></tr>
 <tr><td>Off</td><td>Skipped because it is not configured (no Windy key).</td></tr>
 <tr><td>Running / Waiting</td><td>Fetching now / has not run yet.</td></tr>
</table>

<h2>4. Menus</h2>
<table>
 <tr><td><b>File &gt; Settings</b></td><td>Windy API key and tier, Excel folder.</td></tr>
 <tr><td><b>File &gt; Save Excel database now</b></td><td>Rewrite the workbooks immediately instead of waiting for the 15-minute cycle.</td></tr>
 <tr><td><b>File &gt; Open Excel folder / Open data folder</b></td><td>Opens them in Explorer / Finder.</td></tr>
 <tr><td><b>File &gt; Export CSV</b></td><td>All measurements, all Argo levels, or the current map layer.</td></tr>
 <tr><td><b>View &gt; Language</b></td><td>Korean / English. The window reopens; collection keeps running.</td></tr>
 <tr><td><b>Collect &gt; Collect all now</b> (F5)</td><td>Fetch every source once, right now. <b>Collect source</b> runs a single one.</td></tr>
</table>

<h2>5. Data sources and quality rules</h2>
<table>
 <tr><th>Data</th><th>Provider</th><th>Interval</th><th>Contents</th></tr>
 <tr><td>METAR</td><td>NOAA AWC</td><td>5 min</td><td>Measured air temperature, dew point and pressure at South Pole, McMurdo, Marambio and other stations</td></tr>
 <tr><td>GFS current / grid</td><td>NOAA via Open-Meteo</td><td>15 min / 3 h</td><td>Air, apparent, dew point, wet bulb, surface temperature, humidity, pressure, wind. Same model as the nullschool temperature layer</td></tr>
 <tr><td>Model forecasts</td><td>Open-Meteo</td><td>3 h</td><td>7-day air temperature from GFS, ECMWF, ICON, GEM, JMA</td></tr>
 <tr><td>OISST v2.1</td><td>NOAA NCEI</td><td>checked every 6 h (daily product)</td><td>0.25° SST, anomaly, sea ice. A source of the nullschool SST layer</td></tr>
 <tr><td>MUR SST</td><td>NASA JPL</td><td>on point query</td><td>0.01° SST, analysis error, sea ice</td></tr>
 <tr><td>SMOS / SMAP</td><td>ESA / NASA via NOAA CoastWatch</td><td>checked every 6 h</td><td>Satellite surface salinity. Mostly missing south of 65°S and near ice</td></tr>
 <tr><td>HYCOM ESPC-D-V02</td><td>US Navy / HYCOM.org</td><td>3 h</td><td>1/12° model, 40 levels. Map at about 0.5° and six depths. Nothing south of 80°S</td></tr>
 <tr><td>Argo</td><td>Argo Program via Ifremer</td><td>checked hourly</td><td>Float profiles (to ~2000 m) south of 55°S from the last 30 days. The reference for salinity</td></tr>
 <tr><td>GOSUD</td><td>Ifremer</td><td>checked hourly</td><td>Underway ship SST and salinity</td></tr>
 <tr><td>WOA23</td><td>NOAA NCEI</td><td>on point query</td><td>Monthly climatology (annual below 1500 m)</td></tr>
 <tr><td>ERA5</td><td>ECMWF via Open-Meteo</td><td>on point query</td><td>Daily mean / min / max air temperature</td></tr>
 <tr><td>Windy</td><td>Windy.com official API</td><td>3 h</td><td>Only with a key. Air temperature, dew point, humidity, pressure. The API has no water temperature or salinity</td></tr>
</table>
<ul>
 <li><b>Argo quality</b>: only QC flags 1 (good) and 2 (probably good). Adjusted values in modes A/D, raw values in mode R. Ascending profiles are preferred.</li>
 <li><b>Range checks</b>: temperature −3…40 °C, satellite salinity 28…37 PSU, model and Argo salinity 20…42 PSU. Values outside are dropped (satellite salinity really does return 0.0 and 42.8).</li>
 <li><b>Representative value</b>: an Argo profile within 100 km and 10 days if there is one; otherwise temperature OISST → MUR → HYCOM, salinity HYCOM → SMOS → SMAP.</li>
 <li><b>Derived values</b>: freezing point Millero (1978), density σt from EOS-80 (Millero &amp; Poisson 1981), pressure to depth Saunders &amp; Fofonoff (1976).</li>
 <li><b>Times</b>: stored in UTC, displayed in this computer's local time.</li>
</ul>

<h2>6. Where the data lives</h2>
<table>
 <tr><th>OS</th><th>Database, settings, log</th><th>Excel database (default)</th></tr>
 <tr><td>Windows</td><td><code>%APPDATA%\\SUYA\\</code></td><td><code>Documents\\SUYA\\</code></td></tr>
 <tr><td>macOS</td><td><code>~/Library/Application Support/SUYA/</code></td><td><code>~/Documents/SUYA/</code></td></tr>
 <tr><td>Linux</td><td><code>~/.local/share/SUYA/</code></td><td><code>~/Documents/SUYA/</code></td></tr>
</table>
<ul>
 <li><code>antarctic.db</code>: every raw value (SQLite). Open it directly from Python, R or DB Browser.</li>
 <li><code>settings.env</code>: settings. <code>monitor.log</code>: log file (check it when something goes wrong).</li>
 <li><code>antarctic_db_YYYY-MM.xlsx</code>: monthly workbook. Sheets: Info, Grid means, Water by area, Water vertical, Argo list, Ships, Stations, GFS air, Forecasts, Windy, Point queries.</li>
 <li><code>argo_levels_YYYY-MM.xlsx</code>: every Argo level (separate because of the row count).</li>
</ul>
<p><b>Note</b>: the workbooks are <b>regenerated</b> from SQLite. Manual edits are overwritten on the next save; analyse a copy.
On Windows a workbook that is open in Excel cannot be replaced; the program retries on the next cycle. Months before the previous one are never touched again.</p>

<h2>7. Limitations</h2>
<ul>
 <li>Windy's free (testing) key returns shuffled, altered values. Charts label them "(altered)"; do not use them as a forecast.</li>
 <li>Satellite salinity has no values under sea ice or near the coast. Use the HYCOM layer for a complete salinity map and Argo for measurements.</li>
 <li>HYCOM does not cover south of 80°S (under the Ross and Filchner ice shelves, for example).</li>
 <li>The program caps itself at 9,000 Open-Meteo calls per day, under the free limit of 10,000.</li>
 <li>Model and satellite values are estimates, not measurements, and no provider guarantees their accuracy.</li>
</ul>

<h2>8. Command line</h2>
<pre>suya                 open the window (default)
suya daemon          collect continuously without a window
suya collect         collect every source once
suya excel-sync      write the workbooks now (--all: every month)
suya export measurements --out a.csv
suya sources         list the sources
suya --lang ko       run in Korean</pre>

<h2>9. Troubleshooting</h2>
<ul>
 <li><b>Empty map</b>: wait a few minutes for the first collection. If the status tab keeps showing errors, check the network (firewall, proxy).</li>
 <li><b>HYCOM slow or failing</b>: the HYCOM server often answers 500. The program alternates between two hosts and retries on the next cycle.</li>
 <li><b>Start over</b>: quit, delete <code>antarctic.db</code> in the data folder, and the program starts empty.</li>
 <li><b>Bug reports</b>: <a href="{__url__}/issues">{__url__}/issues</a> or {__email__}. Please attach <code>monitor.log</code>.</li>
</ul>

<h2>10. Citing</h2>
<p>In a paper or report, cite the organisations that provide the data (section 5) and cite this program as below.
Zenodo issues a version DOI for every release; the concept DOI <a href="https://doi.org/{__concept_doi__}">{__concept_doi__}</a> groups all versions and always resolves to the latest release.
The citation below uses the concept DOI; pick the version DOI from the Zenodo record when the exact version matters.
<code>CITATION.cff</code> in the repository and GitHub's "Cite this repository" button give APA and BibTeX entries.</p>
<pre>Lim, J. &amp; Park, S. (2026). SUYA: Antarctic ocean temperature, salinity and air temperature monitor ({__version__}).
Zenodo. https://doi.org/{__concept_doi__}</pre>
"""


def help_html() -> str:
    return HELP_EN if get_language() == "en" else HELP_KO
