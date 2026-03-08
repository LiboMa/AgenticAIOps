#!/bin/bash
# =============================================================================
# AgenticAIOps - 停止脚本
# =============================================================================

PROJECT_DIR="/home/ubuntu/agentic-aiops-mvp"
PID_FILE="$PROJECT_DIR/.pids"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  AgenticAIOps Dashboard 停止中..."
echo "========================================"

# Kill processes from PID file
if [ -f "$PID_FILE" ]; then
    while read pid; do
        if kill -0 $pid 2>/dev/null; then
            echo -e "${YELLOW}停止进程 PID: $pid${NC}"
            kill $pid 2>/dev/null || true
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# Also kill by process name (backup)
pkill -f "api_server.py" 2>/dev/null || true
pkill -f "vite.*5173" 2>/dev/null || true

sleep 1

echo ""
echo -e "${GREEN}✅ 所有服务已停止${NC}"
echo ""
