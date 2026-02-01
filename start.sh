#!/bin/bash
# =============================================================================
# AgenticAIOps - 一键启动脚本
# =============================================================================

set -e

PROJECT_DIR="/home/ubuntu/agentic-aiops-mvp"
PID_FILE="$PROJECT_DIR/.pids"
LOG_DIR="$PROJECT_DIR/logs"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "========================================"
echo "  AgenticAIOps Dashboard 启动中..."
echo "========================================"

# Create logs directory
mkdir -p "$LOG_DIR"

# Change to project directory
cd "$PROJECT_DIR"

# Activate virtual environment
source venv/bin/activate

# Kill any existing processes
if [ -f "$PID_FILE" ]; then
    echo -e "${YELLOW}停止旧进程...${NC}"
    while read pid; do
        kill $pid 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    sleep 2
fi

# Start Backend API
echo -e "${GREEN}启动后端 API (FastAPI)...${NC}"
nohup python api_server.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID >> "$PID_FILE"

# Wait for backend to start
sleep 3
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "  ✅ 后端 API: http://localhost:8000 (PID: $BACKEND_PID)"
else
    echo -e "  ${RED}⚠️  后端启动中... 请稍等${NC}"
fi

# Start Frontend
echo -e "${GREEN}启动前端 Dashboard (React)...${NC}"
cd dashboard
nohup npm run dev -- --host 0.0.0.0 > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID >> "$PID_FILE"
cd ..

# Wait for frontend to start
sleep 3

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "========================================"
echo -e "${GREEN}  ✅ AgenticAIOps Dashboard 已启动！${NC}"
echo "========================================"
echo ""
echo "  📊 Dashboard:  http://${SERVER_IP}:5173"
echo "  🔧 API:        http://localhost:8000"
echo "  📋 API Docs:   http://localhost:8000/docs"
echo ""
echo "  日志文件:"
echo "    - $LOG_DIR/backend.log"
echo "    - $LOG_DIR/frontend.log"
echo ""
echo "  停止服务:  ./stop.sh"
echo "  查看日志:  tail -f $LOG_DIR/backend.log"
echo ""
