#!/bin/bash
# VideoStove CLI Installation Script
# Installs VideoStove CLI for headless/cloud environments

set -e  # Exit on any error

echo "🌊 VideoStove CLI Installation"
echo "================================"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root (not recommended)
if [ "$EUID" -eq 0 ]; then
    print_warning "Running as root. It's recommended to run this script as a regular user."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check Python version
print_status "Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    print_success "Python $PYTHON_VERSION found"
    
    # Check if Python version is 3.8 or higher
    if python3 -c 'import sys; exit(0 if sys.version_info >= (3, 8) else 1)'; then
        print_success "Python version is compatible (3.8+)"
    else
        print_error "Python 3.8 or higher is required. Found version: $PYTHON_VERSION"
        exit 1
    fi
else
    print_error "Python 3 is not installed or not in PATH"
    echo "Please install Python 3.8 or higher:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  CentOS/RHEL: sudo yum install python3 python3-pip"
    exit 1
fi

# Check for pip
print_status "Checking pip..."
if python3 -m pip --version &> /dev/null; then
    print_success "pip is available"
else
    print_error "pip is not available"
    echo "Please install pip:"
    echo "  Ubuntu/Debian: sudo apt install python3-pip"
    echo "  CentOS/RHEL: sudo yum install python3-pip"
    exit 1
fi

# Check for FFmpeg (critical dependency)
print_status "Checking for FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VERSION=$(ffmpeg -version 2>/dev/null | head -n1 | cut -d' ' -f3)
    print_success "FFmpeg $FFMPEG_VERSION found"
else
    print_error "FFmpeg is required but not found in PATH"
    echo ""
    echo "Please install FFmpeg:"
    echo "  Ubuntu/Debian: sudo apt update && sudo apt install ffmpeg"
    echo "  CentOS/RHEL: sudo yum install epel-release && sudo yum install ffmpeg"
    echo "  WSL: sudo apt install ffmpeg"
    echo "  macOS: brew install ffmpeg"
    echo ""
    read -p "Would you like to continue installation anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    print_warning "Continuing without FFmpeg - video processing will fail until FFmpeg is installed"
fi

# Check for optional dependencies
print_status "Checking optional system dependencies..."

# Check for development headers (needed for some Python packages)
if dpkg -l | grep -q python3-dev 2>/dev/null || rpm -qa | grep -q python3-devel 2>/dev/null; then
    print_success "Python development headers found"
else
    print_warning "Python development headers not found"
    echo "  Some packages may fail to install. Consider installing:"
    echo "  Ubuntu/Debian: sudo apt install python3-dev"
    echo "  CentOS/RHEL: sudo yum install python3-devel"
fi

# Create virtual environment (recommended)
print_status "Setting up Python virtual environment..."
VENV_DIR="videostove_cli_env"

if [ -d "$VENV_DIR" ]; then
    print_warning "Virtual environment already exists at $VENV_DIR"
    read -p "Remove and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_DIR"
        print_status "Removed existing virtual environment"
    else
        print_status "Using existing virtual environment"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    print_success "Created virtual environment: $VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"
print_success "Activated virtual environment"

# Upgrade pip in virtual environment
print_status "Upgrading pip..."
python -m pip install --upgrade pip

# Install requirements
print_status "Installing Python dependencies..."
if [ -f "requirements_cli.txt" ]; then
    python -m pip install -r requirements_cli.txt
    print_success "Installed Python dependencies from requirements_cli.txt"
else
    print_warning "requirements_cli.txt not found, installing core dependencies manually..."
    python -m pip install natsort openai-whisper faster-whisper
    print_success "Installed core dependencies"
fi

# Check if core modules can be imported
print_status "Validating installation..."

# Test core imports
python -c "
try:
    import natsort
    print('✓ natsort imported successfully')
except ImportError as e:
    print(f'✗ natsort import failed: {e}')

try:
    import whisper
    print('✓ openai-whisper imported successfully')
except ImportError as e:
    print(f'✗ openai-whisper import failed: {e}')

try:
    from faster_whisper import WhisperModel
    print('✓ faster-whisper imported successfully')
except ImportError as e:
    print(f'✗ faster-whisper import failed: {e}')
"

# Test if core VideoStove modules exist and can be imported
if [ -f "videostove_core.py" ]; then
    if python -c "import videostove_core; print('✓ videostove_core imported successfully')" 2>/dev/null; then
        print_success "VideoStove core module validated"
    else
        print_error "VideoStove core module failed to import"
    fi
else
    print_error "videostove_core.py not found in current directory"
fi

if [ -f "videostove_cli.py" ]; then
    print_success "VideoStove CLI script found"
else
    print_error "videostove_cli.py not found in current directory"
fi

# Create configuration directory
CONFIG_DIR="$HOME/.videostove"
if [ ! -d "$CONFIG_DIR" ]; then
    mkdir -p "$CONFIG_DIR"
    print_success "Created configuration directory: $CONFIG_DIR"
fi

# Deactivate virtual environment for final instructions
deactivate

# Final instructions
echo ""
echo "================================"
print_success "VideoStove CLI installation complete!"
echo ""
echo "📋 Usage Instructions:"
echo "1. Activate the virtual environment:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo "2. Run VideoStove CLI:"
echo "   python videostove_cli.py --help"
echo ""
echo "3. Example commands:"
echo "   # Process single project"
echo "   python videostove_cli.py single /path/to/project output.mp4"
echo ""
echo "   # Batch process multiple projects"
echo "   python videostove_cli.py batch /path/to/projects /path/to/outputs"
echo ""
echo "   # Use custom configuration"
echo "   python videostove_cli.py single /path/to/project output.mp4 --config my_preset.json"
echo ""
echo "📁 Configuration files are stored in: $CONFIG_DIR"
echo ""

if ! command -v ffmpeg &> /dev/null; then
    print_warning "Remember to install FFmpeg before processing videos!"
fi

print_success "Installation complete! Happy video processing! 🎬"