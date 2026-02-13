#!/usr/bin/env bash
# scripts/server.sh — Unified API Server management
# ⚠️  ALL agents MUST use this script to start/stop/restart the server.
#     Direct kill, fuser -k, kill -9 are PROHIBITED.
#
# Usage: scripts/server.sh {start|stop|restart|status}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="/tmp/aiops-api.pid"
LOG_FILE="/tmp/aiops-api.log"
HOST="${AIOPS_HOST:-0.0.0.0}"
PORT="${AIOPS_PORT:-8000}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

_pid_alive() {
    local pid=$1
    kill -0 "$pid" 2>/dev/null
}

_get_pid() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$pid" ]] && _pid_alive "$pid"; then
            echo "$pid"
            return 0
        fi
    fi
    return 1
}

do_start() {
    if pid=$(_get_pid); then
        echo -e "${YELLOW}⚠️  Server already running (PID $pid)${NC}"
        return 1
    fi

    # Clean stale PID file
    rm -f "$PID_FILE"

    echo -e "${GREEN}Starting API server on ${HOST}:${PORT}...${NC}"
    cd "$PROJECT_DIR"

    # Activate venv if present
    if [[ -f "venv/bin/activate" ]]; then
        source venv/bin/activate
    fi

    # Start in background, redirect output to log
    nohup python3 api_server.py > "$LOG_FILE" 2>&1 &
    local bg_pid=$!

    # Wait up to 5s for PID file to appear (api_server.py writes it on startup)
    for i in {1..10}; do
        sleep 0.5
        if [[ -f "$PID_FILE" ]] && _pid_alive "$(cat "$PID_FILE" 2>/dev/null)"; then
            echo -e "${GREEN}✅ Server started (PID $(cat "$PID_FILE"))${NC}"
            echo -e "   Log: $LOG_FILE"
            return 0
        fi
        # Check if process died
        if ! _pid_alive "$bg_pid"; then
            echo -e "${RED}❌ Server failed to start. Check log:${NC}"
            tail -20 "$LOG_FILE"
            return 1
        fi
    done

    echo -e "${YELLOW}⏳ Server starting (PID $bg_pid) but PID file not yet written.${NC}"
    echo -e "   Check: scripts/server.sh status"
}

do_stop() {
    if ! pid=$(_get_pid); then
        echo -e "${YELLOW}Server not running${NC}"
        rm -f "$PID_FILE"
        return 0
    fi

    echo -e "Stopping server (PID $pid)..."
    # Graceful SIGTERM first
    kill "$pid" 2>/dev/null || true

    # Wait up to 10s for graceful shutdown
    for i in {1..20}; do
        sleep 0.5
        if ! _pid_alive "$pid"; then
            rm -f "$PID_FILE"
            echo -e "${GREEN}✅ Server stopped${NC}"
            return 0
        fi
    done

    # Force kill if still alive
    echo -e "${YELLOW}Graceful shutdown timed out, sending SIGKILL...${NC}"
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo -e "${GREEN}✅ Server killed${NC}"
}

do_restart() {
    do_stop
    sleep 1
    do_start
}

do_status() {
    if pid=$(_get_pid); then
        echo -e "${GREEN}✅ Server running (PID $pid)${NC}"
        # Show uptime
        local etime
        etime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
        [[ -n "$etime" ]] && echo "   Uptime: $etime"
        echo "   Port: $PORT"
        echo "   Log: $LOG_FILE"
        return 0
    else
        echo -e "${RED}❌ Server not running${NC}"
        [[ -f "$PID_FILE" ]] && echo "   (stale PID file cleaned)" && rm -f "$PID_FILE"
        return 1
    fi
}

do_log() {
    if [[ -f "$LOG_FILE" ]]; then
        tail -${2:-50} "$LOG_FILE"
    else
        echo "No log file found at $LOG_FILE"
    fi
}

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    log)     do_log "$@" ;;
    *)
        echo "Usage: scripts/server.sh {start|stop|restart|status|log}"
        echo ""
        echo "  start    Start the API server (background)"
        echo "  stop     Graceful stop (SIGTERM → SIGKILL fallback)"
        echo "  restart  Stop + Start"
        echo "  status   Show running state"
        echo "  log      Tail server log (default 50 lines)"
        exit 1
        ;;
esac
