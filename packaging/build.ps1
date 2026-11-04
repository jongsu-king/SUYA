$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$version = python -c "import antarctic_monitor; print(antarctic_monitor.__version__)"
python packaging\make_icon.py
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
pyinstaller --noconfirm --clean packaging\antarctic_monitor.spec

& "dist\SUYA\SUYA.exe" self-test --out dist\self-test.txt | Out-Null
Get-Content dist\self-test.txt

$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "ISCC.exe" }
& $iscc "/DAppVersion=$version" packaging\windows\installer.iss
Get-ChildItem dist\*.exe | ForEach-Object { Write-Host "built $($_.FullName)" }
