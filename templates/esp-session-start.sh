#!/bin/bash
#
# esp-session-start.sh — Start OpenOCD for agentic firmware development.
#
# Run this before starting Claude Code. Reads board config and ports
# from esp_target_config.json. Does not depend on firmware being built.
#
# RTT logging and apptrace are started separately when needed.
#
# Usage:
#   ./esp-session-start.sh
#   ./esp-session-start.sh --config path/to/esp_target_config.json
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.esp-agent"
CONFIG="$SCRIPT_DIR/esp_target_config.json"

[[ "$1" == "--config" ]] && CONFIG="$2"

# ── Helpers ─────────────────────────────────────────

die()  { echo "[session] ERROR: $*" >&2; exit 1; }
info() { echo "[session] $*"; }

read_cfg() {
    python3 -c "import json; d=json.load(open('$CONFIG')); print($1)"
}

# ── Read config ─────────────────────────────────────

[ -f "$CONFIG" ] || die "Config not found: $CONFIG"

BOARD_CFG=$(read_cfg "d['openocd']['board_cfg']")
TCL_PORT=$(read_cfg "d['openocd'].get('tcl_port', 6666)")

info "Config:       $CONFIG"
info "Board config: $BOARD_CFG"
info "Tcl port:     $TCL_PORT"

# ── Kill stale processes ────────────────────────────

info "Cleaning up stale processes..."

if [ -f "$STATE_DIR/openocd.pid" ]; then
    kill "$(cat "$STATE_DIR/openocd.pid")" 2>/dev/null || true
fi

pkill -f "openocd.*$(basename "$BOARD_CFG" .cfg)" 2>/dev/null || true
sleep 1

# ── Create state directory ──────────────────────────

mkdir -p "$STATE_DIR"

# ── Start OpenOCD ───────────────────────────────────

info "Starting OpenOCD..."
openocd -f "$BOARD_CFG" \
    >> "$STATE_DIR/openocd.log" 2>&1 &
echo $! > "$STATE_DIR/openocd.pid"

info "Waiting for OpenOCD..."
TRIES=0
while ! nc -z localhost "$TCL_PORT" 2>/dev/null; do
    sleep 0.5
    TRIES=$((TRIES + 1))
    if [ $TRIES -ge 20 ]; then
        die "OpenOCD failed to start. Check $STATE_DIR/openocd.log"
    fi
done
info "OpenOCD ready (PID $(cat "$STATE_DIR/openocd.pid"))"

# ── Verify target ───────────────────────────────────

HEALTH=$(python3 "$SCRIPT_DIR/esp_target.py" --config "$CONFIG" health 2>/dev/null || echo '{"ok": false}')
if echo "$HEALTH" | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('ok') else 1)" 2>/dev/null; then
    info "Target responsive: $HEALTH"
else
    info "WARNING: Target not responding. Check USB connection."
fi

# ── Summary ─────────────────────────────────────────

echo ""
info "═══════════════════════════════════════════"
info "OpenOCD running. Start Claude Code now."
info "═══════════════════════════════════════════"
info ""
info "OpenOCD log: $STATE_DIR/openocd.log"
info ""
info "To start RTT logging (after firmware is built and flashed):"
info "  python3 rtt_reader.py --elf build/<project>.elf --output $STATE_DIR/rtt.log &"
info ""
info "To stop: ./esp-session-stop.sh"
