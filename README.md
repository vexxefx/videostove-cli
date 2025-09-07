# VideoStove CLI - Command Line Interface

A headless, CLI-only version of VideoStove designed for cloud deployments, WSL environments, and automation scripts. This version removes all GUI dependencies while maintaining full video processing capabilities.

## Files

### Core Files
- **`videostove_cli.py`** - Main CLI application entry point
- **`videostove_core.py`** - Core video processing engine (extracted from GUI version)
- **`config_manager.py`** - Configuration and preset management utilities

### Installation & Dependencies
- **`install_cli.sh`** - Automated installation script with dependency checking
- **`requirements_cli.txt`** - Python dependencies (GUI-free)

### Configuration
- **`configs/`** - Sample configuration files:
  - `basic.json` - Basic slideshow settings
  - `high_quality.json` - High quality processing settings
  - `fast_processing.json` - Fast processing settings  
  - `montage.json` - Video montage configuration

## Installation

1. Make the installation script executable:
   ```bash
   chmod +x install_cli.sh
   ```

2. Run the installation script:
   ```bash
   ./install_cli.sh
   ```

   This will:
   - Check system requirements (Python 3.8+, FFmpeg, pip)
   - Create a virtual environment
   - Install Python dependencies
   - Create sample configuration files

## Usage

### Basic Commands

```bash
# Show help
python videostove_cli.py --help

# Process single project
python videostove_cli.py single /path/to/project output.mp4

# Batch process multiple projects
python videostove_cli.py batch /path/to/projects /path/to/outputs

# Use custom configuration
python videostove_cli.py single /path/to/project output.mp4 --config configs/high_quality.json

# Verbose output
python videostove_cli.py batch /path/to/projects /path/to/outputs --verbose
```

### Configuration Management

```bash
# List available presets
python config_manager.py list

# Show preset details
python config_manager.py show preset_name

# Create sample configurations
python config_manager.py create-samples

# Export all presets
python config_manager.py export my_presets.json

# Import presets
python config_manager.py import exported_presets.json
```

## Project Structure

VideoStove CLI expects projects to be organized as follows:

```
project_folder/
├── image1.jpg
├── image2.jpg
├── image3.jpg
├── audio.mp3
└── background_music.mp3 (optional)
```

Or for video projects:
```
project_folder/
├── video1.mp4
├── video2.mp4
├── video3.mp4
├── audio.mp3
└── background_music.mp3 (optional)
```

## Features

- **GPU Acceleration**: Full support for NVIDIA NVENC, AMD VCE, Intel QuickSync
- **Multiple Project Types**: Slideshows, video montages, mixed media
- **Advanced Effects**: Crossfades, motion effects, overlays
- **AI Captioning**: OpenAI Whisper and Faster-Whisper integration
- **Configuration Management**: Preset system with import/export
- **Batch Processing**: Process multiple projects automatically
- **Error Handling**: Proper exit codes for scripting integration

## System Requirements

- **Python**: 3.8 or higher
- **FFmpeg**: Required for video processing
- **GPU**: Optional but recommended for acceleration
- **Memory**: 4GB+ RAM recommended for HD processing

## Configuration Files

Configuration files are JSON format containing all VideoStove settings:

```json
{
  "image_duration": 8.0,
  "use_gpu": true,
  "crf": 22,
  "preset": "fast",
  "crossfade_duration": 0.6,
  "use_crossfade": true,
  "captions_enabled": false
}
```

## Differences from GUI Version

**Removed:**
- PyWebView GUI framework
- HTML/CSS/JS interface files
- Tkinter file dialogs
- Real-time progress updates
- Interactive controls

**Added:**
- Command-line argument parsing
- Batch processing capabilities
- Configuration file management
- Automated installation script
- Exit codes for scripting

## Cloud Deployment

This CLI version is perfect for:
- **Docker containers**: Lightweight, headless processing
- **CI/CD pipelines**: Automated video generation
- **Cloud functions**: Serverless video processing
- **WSL environments**: Windows Subsystem for Linux
- **Remote servers**: SSH-only environments

## Support

For issues specific to the CLI version, check:
1. FFmpeg installation: `ffmpeg -version`
2. Python version: `python3 --version`
3. Dependencies: `pip list | grep -E "(natsort|whisper)"`
4. GPU drivers: `nvidia-smi` (for NVIDIA GPUs)

The CLI version maintains full compatibility with configurations and presets from the GUI version.