#!/bin/bash
set -e

# Configuration
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
REQUIREMENTS_FILE="$BACKEND_DIR/requirements/development.txt"
DJANGO_SETTINGS_MODULE="config.settings.development"
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:5173"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo "============================================================"
    echo "  Numarator development launcher"
    echo "============================================================"
    echo "Root      : $ROOT_DIR"
    echo "Backend   : $BACKEND_DIR"
    echo "Frontend  : $FRONTEND_DIR"
    echo ""
}

fail() {
    echo -e "${RED}✗ Error: $1${NC}"
    exit 1
}

success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_success() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN}  Numarator development environment started!${NC}"
    echo "============================================================"
    echo "Backend URL : $BACKEND_URL"
    echo "Frontend URL: $FRONTEND_URL"
    echo ""
    echo "Press Ctrl+C to stop all services"
    echo "============================================================"
}

validate_directories() {
    echo "[0/5] Validating project structure..."
    [ -f "$BACKEND_DIR/manage.py" ] || fail "Backend manage.py was not found."
    [ -f "$FRONTEND_DIR/package.json" ] || fail "Frontend package.json was not found."
    [ -f "$REQUIREMENTS_FILE" ] || fail "Backend development requirements were not found."
    success "Project structure validated"
}

detect_python() {
    echo "[1/5] Detecting Python installation..."
    if command -v python3 &> /dev/null; then
        PYTHON_COMMAND="python3"
    elif command -v python &> /dev/null; then
        PYTHON_COMMAND="python"
    else
        fail "Python 3 was not found in PATH. Install Python 3.11+ and retry."
    fi
    success "Found Python: $PYTHON_COMMAND"
}

validate_node() {
    echo "[1/5] Validating Node.js installation..."
    command -v node &> /dev/null || fail "Node.js was not found in PATH. Install Node.js 20+ and retry."
    command -v npm &> /dev/null || fail "npm was not found in PATH. Reinstall Node.js with npm enabled."
    success "Node.js and npm validated"
}

prepare_backend() {
    echo "[2/5] Preparing Python virtual environment..."
    
    if [ ! -f "$VENV_PYTHON" ]; then
        $PYTHON_COMMAND -m venv "$VENV_DIR" || fail "Could not create Python virtual environment."
    fi
    
    "$VENV_PYTHON" -m pip install --upgrade pip --quiet || fail "Could not upgrade pip. Check network or proxy settings."
    success "pip upgraded"
    
    "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE" || fail "Could not install backend dependencies. Check network or proxy settings."
    success "Backend dependencies installed"
}

run_django_checks() {
    echo "[3/5] Running Django checks and migrations..."
    
    cd "$BACKEND_DIR"
    DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" "$VENV_PYTHON" manage.py check || fail "Django system check failed."
    success "Django system check passed"
    
    DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" "$VENV_PYTHON" manage.py migrate --no-input || fail "Database migration failed."
    success "Database migration completed"
    
    cd - > /dev/null
}

prepare_frontend() {
    echo "[4/5] Installing frontend dependencies..."
    
    cd "$FRONTEND_DIR"
    npm install --prefer-offline || fail "Could not install frontend dependencies. Check network or proxy settings."
    success "Frontend dependencies installed"
    
    cd - > /dev/null
}

start_services() {
    echo "[5/5] Starting backend and frontend services..."
    
    # Function to handle cleanup on exit
    cleanup() {
        echo ""
        echo -e "${YELLOW}Shutting down services...${NC}"
        kill %1 2>/dev/null || true
        kill %2 2>/dev/null || true
        exit 0
    }
    
    trap cleanup SIGINT SIGTERM
    
    # Start backend in background
    (
        cd "$BACKEND_DIR"
        export DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE"
        "$VENV_PYTHON" manage.py runserver 127.0.0.1:8000
    ) &
    BACKEND_PID=$!
    success "Backend started (PID: $BACKEND_PID)"
    
    # Give backend a moment to start
    sleep 2
    
    # Start frontend in background
    (
        cd "$FRONTEND_DIR"
        npm run dev -- --host 127.0.0.1
    ) &
    FRONTEND_PID=$!
    success "Frontend started (PID: $FRONTEND_PID)"
    
    # Wait for both processes
    wait
}

# Main execution
main() {
    print_header
    validate_directories
    detect_python
    validate_node
    prepare_backend
    run_django_checks
    prepare_frontend
    print_success
    start_services
}

# Run main function
main
