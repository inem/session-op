#!/usr/bin/env bash
set -euo pipefail

DEST_DIR="${HOME}/bin"
CONFIG_DIR="${HOME}/.config/tap-operators"

mkdir -p "${DEST_DIR}" "${CONFIG_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "${SCRIPT_DIR}/session_op.py"

ln -sf "${SCRIPT_DIR}/session_op.py" "${DEST_DIR}/session-op"

echo "✨ Installed session-op to ${DEST_DIR}/session-op"
if [[ ":$PATH:" != *":${DEST_DIR}:"* ]]; then
  echo "⚠️ Warning: ${DEST_DIR} is not in your \$PATH. Add it to your ~/.zshrc or ~/.bashrc:"
  echo "   export PATH=\"${DEST_DIR}:\$PATH\""
fi
