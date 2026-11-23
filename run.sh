#!/data/data/com.termux/files/usr/bin/bash
# NewAgent Server Lifecycle Runner
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/server_manager.py" "$@"
