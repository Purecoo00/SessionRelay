#!/bin/zsh
set -euo pipefail
cd -- "${0:A:h}"
out="${1:-$HOME/Applications/Session Relay.app}"
mkdir -p "$out/Contents/MacOS" "$out/Contents/Resources"
# macOS 14 is the oldest system the app supports.
swiftc -O -parse-as-library -target "$(uname -m)-apple-macos14.0" \
  RelayApp.swift Views.swift Demo.swift -o "$out/Contents/MacOS/SessionRelay"
cp relay.py agents.py relay_mcp.py live.py i18n.py "$out/Contents/Resources/"
cp -R en.lproj zh-Hans.lproj "$out/Contents/Resources/"
cp Info.plist "$out/Contents/"
cp icon/AppIcon.icns "$out/Contents/Resources/"
codesign --force --sign - "$out" >/dev/null
