#!/usr/bin/env bash

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

PYTHON_VERSION="3.11.9"
VENV_DIR=".venv"

echo "Blender Python Environment Bootstrap"
echo "====================================="

log_info() {
    echo "[+] $1"
}

log_warn() {
    echo "[!] $1"
}

log_error() {
    echo "[x] $1"
}

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    log_error "This script is designed for macOS only"
    exit 1
fi

# 1. Check and install Homebrew
echo ""
echo "Checking Homebrew..."
if command -v brew >/dev/null 2>&1; then
    log_info "Homebrew is already installed ($(brew --version | head -n1))"
else
    log_warn "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add Homebrew to PATH for Apple Silicon Macs
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    
    log_info "Homebrew installed successfully"
fi

# 2. Check and install pyenv
echo ""
echo "Checking pyenv..."
if command -v pyenv >/dev/null 2>&1; then
    log_info "pyenv is already installed ($(pyenv --version))"
else
    log_warn "pyenv not found. Installing via Homebrew..."
    brew install pyenv
    log_info "pyenv installed successfully"
fi

# Set up pyenv in current shell
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# 3. Check and install Python 3.11.10
echo ""
echo "Checking Python ${PYTHON_VERSION}..."
if pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
    log_info "Python ${PYTHON_VERSION} is already installed"
else
    log_warn "Python ${PYTHON_VERSION} not found. Installing via pyenv..."
    pyenv install ${PYTHON_VERSION}
    log_info "Python ${PYTHON_VERSION} installed successfully"
fi

# Set local Python version
pyenv local ${PYTHON_VERSION}

# 4. Check and install uv
echo ""
echo "Checking uv..."
if command -v uv >/dev/null 2>&1; then
    log_info "uv is already installed ($(uv --version))"
else
    log_warn "uv not found. Installing via Homebrew..."
    brew install uv
    log_info "uv installed successfully"
fi

# 5. Create virtual environment
echo ""
echo "Setting up Python virtual environment..."
PYTHON_PATH=$(pyenv which python)
log_info "Using Python: ${PYTHON_PATH}"

if [[ -d "${VENV_DIR}" ]]; then
    log_warn "Virtual environment already exists at ${VENV_DIR}"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "${VENV_DIR}"
        log_info "Removed existing virtual environment"
    else
        log_info "Using existing virtual environment"
    fi
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    ${PYTHON_PATH} -m venv ${VENV_DIR}
    log_info "Virtual environment created at ${VENV_DIR}"
fi

# 6. Install bpy module
echo ""
echo "Installing Blender bpy module..."
log_info "Activating virtual environment and installing bpy==5.0.1"

source ${VENV_DIR}/bin/activate
uv pip install --extra-index-url https://michaelgold.github.io/buildbpy/ bpy==5.0.1

log_info "bpy module installed successfully"

echo ""
echo "====================================="
echo "Bootstrap complete!"
echo ""
echo "To activate the virtual environment, run:"
echo "  source ${VENV_DIR}/bin/activate"
echo ""
echo "To verify the installation, run:"
echo "  python -c 'import bpy; print(bpy.app.version_string)'"
echo "====================================="
