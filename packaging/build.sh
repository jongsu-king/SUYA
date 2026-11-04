#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python -c "import antarctic_monitor; print(antarctic_monitor.__version__)")
python packaging/make_icon.py
rm -rf build dist
pyinstaller --noconfirm --clean packaging/antarctic_monitor.spec

case "$(uname -s)" in
  Darwin)
    ARCH=$(uname -m)
    APP="dist/SUYA.app"
    "$APP/Contents/MacOS/suya" self-test --out dist/self-test.txt
    cat dist/self-test.txt
    codesign --force --deep --sign - "$APP"
    STAGE=$(mktemp -d)
    cp -R "$APP" "$STAGE/"
    ln -s /Applications "$STAGE/Applications"
    DMG="dist/SUYA-${VERSION}-macos-${ARCH}.dmg"
    hdiutil create -volname "SUYA" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
    rm -rf "$STAGE"
    echo "built $DMG"
    ;;
  Linux)
    ARCH=$(uname -m)
    dist/suya/suya self-test --out dist/self-test.txt
    cat dist/self-test.txt
    STAGE="dist/SUYA-${VERSION}-linux-${ARCH}"
    rm -rf "$STAGE"
    mkdir -p "$STAGE"
    cp -R dist/suya "$STAGE/"
    cp packaging/linux/suya.desktop packaging/linux/install.sh "$STAGE/"
    cp packaging/icons/icon.png "$STAGE/suya.png"
    cp LICENSE README.md "$STAGE/"
    tar -C dist -czf "$STAGE.tar.gz" "$(basename "$STAGE")"
    echo "built $STAGE.tar.gz"
    ;;
  *)
    echo "Use packaging/build.ps1 on Windows" >&2
    exit 1
    ;;
esac
