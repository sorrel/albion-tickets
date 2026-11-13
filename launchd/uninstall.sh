#!/usr/bin/env bash
# Unloads the albion-tickets LaunchAgent. Leaves data/ and the calendar alone.
set -euo pipefail
TARGET="${HOME}/Library/LaunchAgents/com.albion-tickets.check.plist"
launchctl unload "${TARGET}" 2>/dev/null || true
[[ -f "${TARGET}" ]] && mv "${TARGET}" "${TARGET}.disabled"
echo "Unloaded. The plist was renamed to ${TARGET}.disabled."
