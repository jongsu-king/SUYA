#!/usr/bin/env bash
# Installs the unpacked Linux build for the current user (no root needed).
#   ~/.local/opt/suya      program files
#   ~/.local/bin/suya      launcher
#   ~/.local/share/applications         menu entry
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.local/opt/suya"
mkdir -p "$TARGET" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
rm -rf "$TARGET"
cp -R "$HERE/suya" "$TARGET"
ln -sf "$TARGET/suya" "$HOME/.local/bin/suya"
cp "$HERE/suya.png" "$HOME/.local/share/icons/hicolor/512x512/apps/suya.png"
sed "s|^Exec=.*|Exec=$TARGET/suya|" "$HERE/suya.desktop" > "$HOME/.local/share/applications/suya.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
echo "Installed. Run: suya   (make sure ~/.local/bin is on your PATH)"
