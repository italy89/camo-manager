#!/bin/bash
# Start CamoManager Web UI
# Usage: ./start.sh [--dev]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🦊 CamoManager Web UI"
echo "===================="

# Activate venv
VENV="$SCRIPT_DIR/../camoufox-env/bin/activate"
if [ ! -f "$VENV" ]; then
    echo "❌ Không tìm thấy venv tại $VENV"
    exit 1
fi
source "$VENV"

# Kill any existing process on port 8000
OLD_PID=$(fuser 8000/tcp 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "⚠️  Port 8000 đang bị chiếm (PID: $OLD_PID). Đang kill..."
    kill $OLD_PID 2>/dev/null || true
    sleep 1
    echo "✅ Đã giải phóng port 8000"
fi

# Check if frontend is built
if [ ! -f "web/dist/index.html" ]; then
    echo "⚠️  Frontend not built. Building now..."
    cd web && npm run build && cd ..
    echo ""
fi

if [ "$1" = "--dev" ]; then
    echo "🔧 Development mode"
    echo "   Backend:  http://localhost:8000  (FastAPI + Swagger: /api/docs)"
    echo "   Frontend: http://localhost:3000  (Vite dev server with hot reload)"
    echo ""

    # Start both in parallel
    (cd web && npm run dev) &
    VITE_PID=$!

    python -m api.main &
    API_PID=$!

    trap "kill $VITE_PID $API_PID 2>/dev/null; exit" INT TERM
    wait
else
    echo "🚀 Production mode"
    echo "   Web UI:   http://localhost:8000"
    echo "   API docs: http://localhost:8000/api/docs"
    echo ""

    python -m api.main
fi
