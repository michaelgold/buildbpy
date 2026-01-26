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

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    log_error "This script is designed for Linux only"
    exit 1
fi

# Detect package manager
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt-get"
    PKG_UPDATE="sudo apt-get update"
    PKG_INSTALL="sudo apt-get install -y"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
    PKG_UPDATE="sudo dnf check-update || true"
    PKG_INSTALL="sudo dnf install -y"
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
    PKG_UPDATE="sudo yum check-update || true"
    PKG_INSTALL="sudo yum install -y"
elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
    PKG_UPDATE="sudo pacman -Sy"
    PKG_INSTALL="sudo pacman -S --noconfirm"
else
    log_error "No supported package manager found (apt-get, dnf, yum, or pacman)"
    exit 1
fi

log_info "Detected package manager: ${PKG_MANAGER}"

# 1. Install build dependencies for pyenv
echo ""
echo "Checking build dependencies..."
if [[ "$PKG_MANAGER" == "apt-get" ]]; then
    DEPS="build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev curl git libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev"
elif [[ "$PKG_MANAGER" == "dnf" ]] || [[ "$PKG_MANAGER" == "yum" ]]; then
    DEPS="gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel openssl-devel tk-devel libffi-devel xz-devel git curl"
elif [[ "$PKG_MANAGER" == "pacman" ]]; then
    DEPS="base-devel openssl zlib xz tk git curl"
fi

log_info "Installing build dependencies..."
$PKG_UPDATE >/dev/null 2>&1 || true
$PKG_INSTALL $DEPS >/dev/null 2>&1 || log_warn "Some dependencies may already be installed"

# 2. Check and install pyenv
echo ""
echo "Checking pyenv..."
if command -v pyenv >/dev/null 2>&1; then
    log_info "pyenv is already installed ($(pyenv --version))"
else
    log_warn "pyenv not found. Installing..."
    curl -fsSL https://pyenv.run | bash
    
    # Set up pyenv in current shell
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    
    # Add to shell profile if not already there
    SHELL_RC="$HOME/.bashrc"
    if [[ -n "${ZSH_VERSION:-}" ]]; then
        SHELL_RC="$HOME/.zshrc"
    fi
    
    if ! grep -q 'PYENV_ROOT' "$SHELL_RC" 2>/dev/null; then
        echo '' >> "$SHELL_RC"
        echo '# pyenv configuration' >> "$SHELL_RC"
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> "$SHELL_RC"
        echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> "$SHELL_RC"
        echo 'eval "$(pyenv init -)"' >> "$SHELL_RC"
        log_info "Added pyenv to $SHELL_RC"
    fi
    
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
    log_warn "uv not found. Installing..."
    curl -fsSL https://astral.sh/uv/install.sh | sh
    
    # Add uv to PATH for current session
    export PATH="$HOME/.cargo/bin:$PATH"
    
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
