#!/usr/bin/env bash
# Installs the albion-tickets LaunchAgent for the current user.
# The committed plist is a template: the real repo path is substituted here,
# so no machine path is ever stored in git.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.albion-tickets.check"
TEMPLATE="${REPO_DIR}/launchd/${LABEL}.plist"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

command -v uv >/dev/null 2>&1 || { echo "error: 'uv' not found on PATH." >&2; exit 1; }

# Build the venv now; the agent then runs the venv's albion directly, never uv.
( cd "${REPO_DIR}" && uv sync )
[[ -x "${REPO_DIR}/.venv/bin/albion" ]] || { echo "error: .venv/bin/albion missing after uv sync" >&2; exit 1; }

mkdir -p "${HOME}/Library/LaunchAgents" "${REPO_DIR}/data"
sed -e "s#__REPO_DIR__#${REPO_DIR}#g" "${TEMPLATE}" > "${TARGET}"
launchctl unload "${TARGET}" 2>/dev/null || true
launchctl load "${TARGET}"
echo "Loaded ${LABEL}: checks every two hours, 07:00–22:00."
echo "  logs: ${REPO_DIR}/data/check.{out,err}.log"
