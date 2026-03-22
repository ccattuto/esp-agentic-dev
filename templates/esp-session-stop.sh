#!/bin/bash
#
# esp-session-stop.sh — Tear down agentic firmware development infrastructure.
#
# Stops OpenOCD and any rtt_reader.py that may be running.
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.esp-agent"

info() { echo "[session] $*"; }

if [ ! -d "$STATE_DIR" ]; then
    info "No active session found."
    exit 0
fi

info "Stopping infrastructure..."

# Stop OpenOCD
if [ -f "$STATE_DIR/openocd.pid" ]; then
    PID=$(cat "$STATE_DIR/openocd.pid")
    if kill "$PID" 2>/dev/null; then
        info "Stopped OpenOCD (PID $PID)"
    fi
    rm -f "$STATE_DIR/openocd.pid"
fi

# Kill any rtt_reader that may have been started during the session
pkill -f "rtt_reader.py" 2>/dev/null && info "Stopped RTT reader" || true

# Catch orphan OpenOCD processes
pkill -f "openocd" 2>/dev/null || true

info "Done. Logs preserved in $STATE_DIR/"
