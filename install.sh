#!/bin/bash
# ==============================================
# CamoManager - One-click Install Script
# Tested on: Ubuntu 22.04/24.04, WSL2
# ==============================================
set -e

echo "🦊 CamoManager Installer"
echo "========================"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# --- 1. Check system dependencies ---
echo ""
echo "📦 [1/5] Checking system dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Installing..."
    sudo apt update && sudo apt install -y python3 python3-venv python3-pip
fi

if ! command -v node &>/dev/null; then
    echo "❌ Node.js not found. Installing via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
fi

echo "   ✅ python3 $(python3 --version 2>&1 | awk '{print $2}')"
echo "   ✅ node $(node --version)"
echo "   ✅ npm $(npm --version)"

# --- 2. Create Python virtual environment ---
echo ""
echo "🐍 [2/5] Setting up Python virtual environment..."

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "   Created venv at $VENV_DIR"
else
    echo "   Venv already exists"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# --- 3. Install Python dependencies ---
echo ""
echo "📥 [3/5] Installing Python dependencies..."
pip install -r "$SCRIPT_DIR/requirements.txt" -q

# Install Camoufox browser binary
echo "   Installing Camoufox browser..."
python -m camoufox fetch 2>/dev/null || echo "   (Camoufox browser already installed or fetch skipped)"

# --- 4. Build frontend ---
echo ""
echo "🔨 [4/5] Building frontend..."

cd "$SCRIPT_DIR/web"
if [ ! -d "node_modules" ]; then
    npm install --silent 2>&1 | tail -1
fi
npm run build 2>&1 | tail -1
cd "$SCRIPT_DIR"

# --- 5. Create directories ---
echo ""
echo "📁 [5/5] Creating directories..."
mkdir -p "$SCRIPT_DIR/profiles"
mkdir -p "$SCRIPT_DIR/locks"

# --- 6. Create start script ---
cat > "$SCRIPT_DIR/start.sh" << 'STARTEOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🦊 CamoManager Web UI"
echo "===================="

# Activate venv
source "$SCRIPT_DIR/venv/bin/activate"

# Kill any existing process on port 8000
OLD_PID=$(fuser 8000/tcp 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "⚠️  Port 8000 busy. Killing old process..."
    kill $OLD_PID 2>/dev/null || true
    sleep 1
fi

# Check frontend
if [ ! -f "web/dist/index.html" ]; then
    echo "⚠️  Building frontend..."
    cd web && npm run build && cd ..
fi

echo "🚀 Server: http://localhost:8000"
echo "📖 API docs: http://localhost:8000/api/docs"
echo ""
python -m api.main
STARTEOF
chmod +x "$SCRIPT_DIR/start.sh"

# --- Done ---
echo ""
echo "=========================================="
echo "✅ CamoManager installed successfully!"
echo "=========================================="
echo ""
echo "Start server:"
echo "  cd $SCRIPT_DIR && ./start.sh"
echo ""
echo "Or install as system service (auto-start):"
echo "  sudo bash $SCRIPT_DIR/install-service.sh"
echo ""
