# Blender Python Environment Bootstrap (Windows)
# Run as Administrator in PowerShell

$ErrorActionPreference = "Stop"

$PYTHON_VERSION = "3.11.9"
$VENV_DIR = ".venv"

function Log-Info {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Log-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Log-Error {
    param([string]$Message)
    Write-Host "[x] $Message" -ForegroundColor Red
}

Write-Host "Blender Python Environment Bootstrap (Windows)" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host ""
Log-Info "No administrator privileges required"

# 1. Check and install pyenv-win
Write-Host ""
Write-Host "Checking pyenv-win..."
$pyenvInstalled = $null -ne (Get-Command pyenv -ErrorAction SilentlyContinue)

if ($pyenvInstalled) {
    Log-Info "pyenv-win is already installed"
} else {
    Log-Warn "pyenv-win not found. Installing..."
    
    # Install pyenv-win using the official installer
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/pyenv-win/pyenv-win/master/pyenv-win/install-pyenv-win.ps1" -OutFile "$env:TEMP\install-pyenv-win.ps1"
    & "$env:TEMP\install-pyenv-win.ps1"
    Remove-Item "$env:TEMP\install-pyenv-win.ps1"
    
    # Add pyenv to PATH for current session
    $env:PYENV = "$env:USERPROFILE\.pyenv\pyenv-win"
    $env:PYENV_ROOT = "$env:USERPROFILE\.pyenv\pyenv-win"
    $env:PYENV_HOME = "$env:USERPROFILE\.pyenv\pyenv-win"
    $env:PATH = "$env:PYENV\bin;$env:PYENV\shims;$env:PATH"
    
    Log-Info "pyenv-win installed successfully"
}

# 2. Check and install Python 3.11.10
Write-Host ""
Write-Host "Checking Python $PYTHON_VERSION..."

# Ensure pyenv is in PATH
$env:PYENV = "$env:USERPROFILE\.pyenv\pyenv-win"
$env:PYENV_ROOT = "$env:USERPROFILE\.pyenv\pyenv-win"
$env:PYENV_HOME = "$env:USERPROFILE\.pyenv\pyenv-win"
$env:PATH = "$env:PYENV\bin;$env:PYENV\shims;$env:PATH"

$pythonInstalled = pyenv versions --bare 2>$null | Select-String -Pattern "^$PYTHON_VERSION`$"

if ($pythonInstalled) {
    Log-Info "Python $PYTHON_VERSION is already installed"
} else {
    Log-Warn "Python $PYTHON_VERSION not found. Installing via pyenv..."
    pyenv install $PYTHON_VERSION
    Log-Info "Python $PYTHON_VERSION installed successfully"
}

# Set local Python version
pyenv local $PYTHON_VERSION
pyenv rehash

# 3. Check and install uv
Write-Host ""
Write-Host "Checking uv..."

# Function to find uv executable in known locations
function Find-UvExecutable {
    $possiblePaths = @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:USERPROFILE\.cargo\bin\uv.exe",
        "$env:LOCALAPPDATA\uv\bin\uv.exe",
        "$env:APPDATA\uv\bin\uv.exe"
    )
    
    foreach ($path in $possiblePaths) {
        if (Test-Path $path) {
            return $path
        }
    }
    
    # Fall back to PATH lookup
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    
    return $null
}

# Refresh PATH from registry to pick up any changes from previous installs
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
$env:PATH = "$userPath;$machinePath"

$uvExe = Find-UvExecutable

if ($uvExe) {
    Log-Info "uv is already installed at: $uvExe"
} else {
    Log-Warn "uv not found. Installing..."
    
    # Install uv using the official installer (no admin required)
    irm https://astral.sh/uv/install.ps1 | iex
    
    # Refresh PATH from registry to pick up changes made by the installer
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    $env:PATH = "$userPath;$machinePath"
    
    $uvExe = Find-UvExecutable
    
    if (-not $uvExe) {
        Log-Error "uv installation succeeded but executable not found. Please restart PowerShell and run this script again."
        exit 1
    }
    
    Log-Info "uv installed successfully at: $uvExe"
}

# Add uv's directory to PATH for this session
$uvDir = Split-Path -Parent $uvExe
$env:PATH = "$uvDir;$env:PATH"

# 4. Create virtual environment
Write-Host ""
Write-Host "Setting up Python virtual environment..."

$pythonPath = pyenv which python
Log-Info "Using Python: $pythonPath"

if (Test-Path $VENV_DIR) {
    Log-Warn "Virtual environment already exists at $VENV_DIR"
    $response = Read-Host "Do you want to recreate it? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Remove-Item -Recurse -Force $VENV_DIR
        Log-Info "Removed existing virtual environment"
    } else {
        Log-Info "Using existing virtual environment"
    }
}

if (-not (Test-Path $VENV_DIR)) {
    python -m venv $VENV_DIR
    Log-Info "Virtual environment created at $VENV_DIR"
}

# 5. Install bpy module
Write-Host ""
Write-Host "Installing Blender bpy module..."
Log-Info "Activating virtual environment and installing bpy==5.0.1"

# Activate venv
& "$VENV_DIR\Scripts\Activate.ps1"

& $uvExe pip install --extra-index-url https://michaelgold.github.io/buildbpy/ bpy==5.0.1

Log-Info "bpy module installed successfully"

Write-Host ""
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "Bootstrap complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To activate the virtual environment, run:"
Write-Host "  $VENV_DIR\Scripts\Activate.ps1"
Write-Host ""
Write-Host "To verify the installation, run:"
Write-Host "  python -c 'import bpy; print(bpy.app.version_string)'"
Write-Host "===============================================" -ForegroundColor Cyan
