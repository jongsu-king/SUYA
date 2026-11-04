# 빌드와 배포 / Building and releasing

## 개발 환경 / Development setup

```bash
git clone https://github.com/jongsu-king/SUYA.git
cd suya
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,build]"
python -m pytest -q                                     # no network needed
QT_QPA_PLATFORM=offscreen python -m antarctic_monitor self-test
python -m antarctic_monitor                             # run from source
```

`uv`를 쓴다면 `uv venv && uv pip install -e ".[dev,build]"`.

## 프로젝트 구조 / Layout

```
antarctic_monitor/      파이썬 패키지 (CLI 이름은 suya)
  collectors/           소스 어댑터
  gui/                  PySide6 화면
  data/                 해안선, 색표, 라이선스 사본 (설치 파일에 동봉)
packaging/
  antarctic_monitor.spec   PyInstaller 명세 (모든 OS 공용)
  entry.py                 PyInstaller 진입점
  make_icon.py             해안선으로 아이콘 생성 (PNG, ICO, macOS에서는 ICNS)
  make_colormaps.py        cmocean에서 색표 JSON 재생성 (빌드 시에만 cmocean 필요)
  build.sh / build.ps1     운영체제별 빌드 스크립트
  windows/installer.iss    Inno Setup 6 스크립트
  linux/                   .desktop 파일과 사용자 설치 스크립트
.github/workflows/
  ci.yml                   push·PR마다 테스트: Linux·Windows는 Python 3.11~3.13, macOS는 설치 파일과 같은 3.12 하나
  release.yml              v* 태그마다 설치 파일 빌드 후 Release에 첨부
tests/                  pytest (네트워크 불필요, 실제 응답 형태를 고정값으로 사용)
docs/                   상세 문서와 화면 캡처
```

## 로컬 빌드 / Local builds

### macOS → `.dmg`
```bash
bash packaging/build.sh
# dist/SUYA.app, dist/SUYA-<version>-macos-<arm64|x86_64>.dmg
```
PyInstaller가 `SUYA.app`을 만들고, `self-test`로 창을 띄워 보고 엑셀을 써 본 뒤, ad-hoc 서명(`codesign --sign -`)을 하고 `hdiutil`로 DMG를 만듭니다.
Apple 개발자 인증서가 없으므로 공증(notarization)은 하지 않습니다. 처음 열 때 우클릭 → 열기가 필요합니다.
인증서가 있다면 `codesign --sign "Developer ID Application: …"`과 `xcrun notarytool submit`을 `build.sh`에 추가하세요.

### Linux → `.tar.gz`
```bash
sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1
bash packaging/build.sh
# dist/SUYA-<version>-linux-x86_64.tar.gz  (suya/ 폴더 + suya.desktop + install.sh)
```
glibc 2.35(Ubuntu 22.04) 이상에서 동작합니다. 사용자는 풀고 `./install.sh`를 실행하면 `~/.local/opt/suya`에 설치되고 메뉴에 등록됩니다.

### Windows → `setup.exe`
Inno Setup 6(https://jrsoftware.org/isinfo.php)을 설치한 뒤:
```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# dist\SUYA\SUYA.exe, dist\SUYA-<version>-windows-x64-setup.exe
```
설치 프로그램은 영어·한국어 안내를 지원하고, 관리자 권한 없이 사용자 폴더에 설치할 수도 있습니다(`PrivilegesRequiredOverridesAllowed=dialog`).
코드 서명이 없어 SmartScreen 경고가 납니다. 서명 인증서가 있으면 `SignTool=` 지시자를 `installer.iss`에 추가하세요.

## GitHub Actions 릴리스 / Releasing

1. 버전을 올립니다: `antarctic_monitor/__init__.py`, `pyproject.toml`, `packaging/windows/installer.iss`(기본값), `CITATION.cff`(`version`, `date-released`),
   두 README의 내려받기 표·단추 파일 이름과 인용 문구, `AUTHORS.md`. `CHANGELOG.md`에 항목을 적습니다. `tests/test_package.py`가 버전과 DOI가 맞는지 확인합니다.
   DOI는 개념 DOI(모든 버전)를 그대로 두고, 릴리스가 Zenodo에 보관된 뒤 새 버전 DOI를 `CITATION.cff`의 `identifiers`와 README 표에 추가합니다.
2. 커밋하고 태그를 밉니다:
   ```bash
   git tag -a v0.2.0 -m "SUYA 0.2.0"
   git push origin main --tags
   ```
3. `release.yml`이 Windows x64, macOS arm64, macOS x86_64, Linux x86_64에서 빌드해 테스트와 `self-test`를 통과한 설치 파일과 `SHA256SUMS.txt`를 Release에 첨부합니다. 20~30분 걸립니다.
4. Release 노트는 자동 생성된 목록 위에 CHANGELOG 내용을 붙여 넣으세요.
5. 프로그램 안의 자동 업데이트(`antarctic_monitor/updates.py`)는 릴리스 자산 이름(`SUYA-<버전>-windows-x64-setup.exe`,
   `-macos-arm64.dmg`, `-macos-x86_64.dmg`, `-linux-x86_64.tar.gz`)과 `SHA256SUMS.txt`에 의존합니다. 이름을 바꾸면 이미 설치된
   버전들이 새 릴리스를 찾지 못하므로 바꾸지 마세요. Windows 설치 프로그램은 `/relaunch=1` 매개변수로 설치 뒤 프로그램을 다시 띄웁니다.

## 설치 파일 안에 들어가는 것 / What ships

- 파이썬 런타임 + PySide6(Qt 6 Widgets, Gui, Core, 이미지 플러그인) + matplotlib + numpy + httpx + XlsxWriter.
- `antarctic_monitor/data/`: `southern-land.json`(Natural Earth 1:50m 해안선, 36°S 이남), `colormaps.json`(cmocean 4종), `LICENSE.txt`, `THIRD_PARTY_NOTICES.md`.
- Qt의 WebEngine·QML·Multimedia 등 쓰지 않는 모듈은 명세의 `excludes`로 뺐습니다. 결과물은 OS마다 60~90 MB입니다.

## 자주 생기는 빌드 문제 / Common build problems

| 증상 | 해결 |
|---|---|
| `ModuleNotFoundError: matplotlib.backends.backend_qtagg` | 명세의 `hiddenimports`에 있습니다. PyInstaller 6.11 이상인지 확인 |
| macOS에서 `.app`이 바로 꺼짐 | 터미널에서 `dist/SUYA.app/Contents/MacOS/suya self-test`를 실행해 오류를 봅니다. 로그는 `~/Library/Application Support/SUYA/monitor.log` |
| Linux: `xcb` 플러그인 로드 실패 | 위의 apt 패키지 설치 |
| Windows: Inno Setup에서 `Korean.isl` 없음 | Inno Setup 6.1 이상에 포함됩니다. 없으면 `[Languages]`에서 korean 줄을 지웁니다 |
| 아이콘이 기본 아이콘 | `python packaging/make_icon.py`를 먼저 실행 (build 스크립트가 자동으로 합니다) |
