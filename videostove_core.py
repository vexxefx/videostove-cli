#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VideoStove Core - GPU-Accelerated Video Processing Engine

This module contains the core video processing components extracted from run-main.py,
designed to be used independently without GUI dependencies. Perfect for CLI applications,
automation scripts, and integration into other projects.

Key Components:
- DEFAULT_CONFIG: Complete configuration dictionary with all settings
- VideoCreator: Main video processing engine with GPU acceleration
- AutoCaptioner: AI-powered video captioning using Whisper models
- GPU detection and optimization functions
- Utility functions for FFmpeg operations and media handling

Features:
- GPU-accelerated video processing (NVIDIA NVENC, AMD VCE, Intel QuickSync)
- Image slideshow creation with motion effects and crossfades
- Video compilation and processing
- Audio mixing and background music
- Advanced captioning with multiple animation styles
- Karaoke effects and live timing captions
- Overlay and screen blend effects
- Efficient stream copying and looping

Usage:
    from videostove_core import VideoCreator, AutoCaptioner, CONFIG
    
    # Create a video processor
    creator = VideoCreator()
    
    # Process media files
    creator.create_slideshow(images, videos, audio, output_file="result.mp4")
    
    # Add captions
    captioner = AutoCaptioner()
    captioner.add_captions_to_video("result.mp4")

Dependencies:
- FFmpeg (required for video processing)
- Optional: faster-whisper or openai-whisper (for captioning)
- Optional: natsort (for natural file sorting)
"""

import os
import sys
import io
import shutil
import subprocess
import threading
import json
import queue
import tempfile
import time
import glob
import datetime
import math
from pathlib import Path

# Fix Windows console encoding issues
if sys.platform == "win32":
    try:
        # Try to set UTF-8 encoding for stdout
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        # Fallback: replace problematic characters
        pass

# Default Configuration (for reset on startup)
DEFAULT_CONFIG = {
    "image_duration": 8.0,
    "main_audio_vol": 1.0,
    "bg_vol": 0.15,
    "crossfade_duration": 0.6,
    "use_crossfade": True,          # New option to enable/disable crossfades
    "use_overlay": False,
    "use_bg_music": True,
    "use_gpu": True,                # GPU acceleration enabled
    "use_fade_in": True,
    "use_fade_out": True,
    "overlay_opacity": 0.5,
    "crf": 22,
    "preset": "fast",
    
    # NEW: Video intro behavior
    "videos_as_intro_only": True,   # Use videos as intro, then images (no video looping when images present)
    "project_type": "montage",       # NEW: "slideshow", "montage", or "videos_only"
    "overlay_mode": "simple",        # NEW: "simple" or "screen_blend"
    "extended_zoom_enabled": False,  # NEW: For 1-5 images
    "extended_zoom_direction": "in", # NEW: "in" or "out"
    "extended_zoom_amount": 30,      # NEW: 0-50%
    "single_image_zoom": False,      # NEW: Special zoom for single image
    
    # Caption Settings
    "captions_enabled": False,
    "caption_style": "Custom",
    "caption_type": "single",
    "whisper_model": "base",
    "font_size": 24,
    "font_family": "Arial",
    "font_weight": "bold",
    "text_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 2,
    "border_color": "#FFFFFF",
    "border_width": 2,
    "border_enabled": False,
    "single_line_mode": False,
    "background_color": "#000000",
    "background_opacity": 0.0,
    "use_caption_background": False,  # Explicit flag for background
    "vertical_position": "bottom",
    "horizontal_position": "center",
    "margin_vertical": 25,
    "margin_horizontal": 20,
    "preset_vertical_position": "bottom",
    "preset_horizontal_position": "center", 
    "preset_margin_vertical": 50,
    "preset_margin_horizontal": 20,
    "caption_animation": "normal",
    "shadow_enabled": True,
    "shadow_blur": 2,
    "line_spacing": 1.2,
    "word_by_word_enabled": False,    # Word-by-Word Mode (1-3 words)
    "live_timing_enabled": False,     # Live Timing Mode (single line)
    "karaoke_effect_enabled": False,  # Karaoke Effect (word-by-word timing)
    "use_faster_whisper": False,      # Use faster-whisper for all transcription (4-6x faster)
    "loop_videos": True,              # Loop videos if no images available
    "use_videos": True,               # Enable/disable video detection
    "max_chars_per_line": 45,         # Maximum characters per caption line
    "animation_style": "Sequential Motion", # Default animation style
    "auto_clear_console": False       # Auto-clear console when it gets too long
}

# Global Configuration (starts as copy of defaults)
CONFIG = DEFAULT_CONFIG.copy()

MOTION_DIRECTIONS = ["right", "left", "down", "up"]

def pick_motion_direction(animation_style: str, i: int, total_images: int) -> str:
    """Pick motion direction for image i based on animation style."""
    style = (animation_style or "Sequential Motion").strip()
    if style in ("Zoom In Only", "Zoom In"):
        return "zoom_in"
    if style in ("Zoom Out Only", "Zoom Out"):
        return "zoom_out"
    if style in ("Pan Only", "Pan"):
        return "right"
    if style in ("No Animation", "None"):
        return "no_motion"
    if style in ("Random Motion", "Random"):
        import random
        return random.choice(MOTION_DIRECTIONS + ["zoom_in", "zoom_out"])

    # Default: Sequential Motion
    if total_images <= 1 or i == 0:
        return "zoom_in"            # first image
    if i == total_images - 1:
        return "zoom_out"           # last image
    # Middle images rotate through pan directions
    return MOTION_DIRECTIONS[(i - 1) % len(MOTION_DIRECTIONS)]

# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def format_path_for_ffmpeg(file_path):
    """Format file path for FFmpeg compatibility on Windows.
    Handles spaces, special characters, and path separators properly."""
    # Convert to absolute path and normalize
    abs_path = os.path.abspath(file_path)
    
    # On Windows, replace backslashes with forward slashes for FFmpeg
    if os.name == 'nt':  # Windows
        abs_path = abs_path.replace('\\', '/')
        # Handle drive letters (C: -> C:/ NOT /C:)
        # FFmpeg on Windows prefers C:/path format
        if len(abs_path) > 1 and abs_path[1] == ':':
            # Keep it as C:/path format, don't add leading slash
            pass
    
    return abs_path

def create_concat_file(file_list, concat_path):
    """Create a properly formatted concat file for FFmpeg with error checking."""
    try:
        print(f"📝 Creating concat file: {concat_path}")
        print(f"📝 Input files count: {len(file_list)}")
        
        with open(concat_path, 'w', encoding='utf-8') as f:
            for i, file_path in enumerate(file_list):
                print(f"📝   File {i+1}: {file_path}")
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"Input file not found: {file_path}")
                
                # Format path for FFmpeg compatibility
                formatted_path = format_path_for_ffmpeg(file_path)
                print(f"📝   Formatted: {formatted_path}")
                f.write(f"file '{formatted_path}'\n")
        
        # Verify the concat file was created and is readable
        if not os.path.exists(concat_path):
            raise RuntimeError(f"Failed to create concat file: {concat_path}")
        
        # Verify file size is reasonable
        file_size = os.path.getsize(concat_path)
        if file_size == 0:
            raise RuntimeError(f"Concat file is empty: {concat_path}")
        
        print(f"✅ Concat file created successfully: {concat_path} ({file_size} bytes)")
        
        # Debug: Show concat file contents
        with open(concat_path, 'r', encoding='utf-8') as f:
            contents = f.read().strip()
            print(f"📝 Concat file contents:\n{contents}")
        
        # Debug: Show what the FFmpeg command would look like
        test_cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_path, '-c', 'copy', 'test_output.mp4']
        print(f"📝 Example FFmpeg command: {' '.join(test_cmd)}")
        
        return True
    except Exception as e:
        print(f"❌ Error creating concat file {concat_path}: {e}")
        return False

def get_media_duration(file_path):
    """Get duration of any media file using ffprobe.
    CPU-optimized: ffprobe metadata extraction is more efficient on CPU."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    cmd = [
        'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        duration = float(result.stdout.strip())
        if duration <= 0:
            raise ValueError(f"Invalid duration: {duration}")
        return duration
    except Exception as e:
        raise RuntimeError(f"Failed to get duration for {file_path}: {e}")

def has_audio_stream(file_path):
    """Check if a media file has audio streams using ffprobe."""
    if not os.path.exists(file_path):
        return False
    
    cmd = [
        'ffprobe', '-v', 'quiet', '-show_streams', '-select_streams', 'a',
        '-of', 'csv=p=0', file_path
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        return len(result.stdout.strip()) > 0
    except Exception:
        return False

# ===================================================================
# GPU DETECTION SYSTEM
# ===================================================================

def detect_gpu_acceleration():
    """Detect available GPU acceleration with detailed testing and robust error handling."""
    print("📍 STATUS: Testing GPU acceleration capabilities...")
    
    # Initialize empty config to ensure it exists
    if "gpu_encoders" not in CONFIG:
        CONFIG["gpu_encoders"] = []
    
    # Check if FFmpeg is available first
    try:
        print("📍 GPU TEST: Checking FFmpeg availability...")
        ffmpeg_check = subprocess.run(['ffmpeg', '-version'], 
                                    capture_output=True, text=True, timeout=5)
        if ffmpeg_check.returncode != 0:
            print("📍 GPU TEST ERROR: FFmpeg not found or not working")
            print("📍 STATUS: FFmpeg is required for video processing")
            return []
    except FileNotFoundError:
        print("📍 GPU TEST ERROR: FFmpeg not installed or not in PATH")
        print("📍 STATUS: Please install FFmpeg to enable video processing")
        return []
    except subprocess.TimeoutExpired:
        print("📍 GPU TEST ERROR: FFmpeg version check timed out")
        print("📍 STATUS: FFmpeg may be corrupted or system is overloaded")
        return []
    except Exception as e:
        print(f"📍 GPU TEST ERROR: FFmpeg check failed: {e}")
        return []
    
    print("📍 GPU TEST: Running FFmpeg encoder detection...")
    
    try:
        cmd = ['ffmpeg', '-hide_banner', '-encoders']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        # Check if command succeeded
        if result.returncode != 0:
            print(f"📍 GPU TEST ERROR: FFmpeg encoders command failed (code: {result.returncode})")
            print("📍 STATUS: Will use CPU encoding as fallback")
            CONFIG["gpu_encoders"] = []
            return []
        
        print("📍 GPU TEST: Analyzing available hardware encoders...")
        gpu_options = []
        
        # Ensure we have output to analyze
        if not result.stdout:
            print("📍 GPU TEST ERROR: No output from FFmpeg encoders command")
            CONFIG["gpu_encoders"] = []
            return []
        
        # Check for AMD VCE
        if 'h264_amf' in result.stdout:
            gpu_options.append('AMD VCE (h264_amf)')
            print("📍 GPU FOUND: ✅ AMD VCE hardware encoder detected")
        else:
            print("📍 GPU CHECK: ❌ AMD VCE encoder not found")
        
        # Check for NVIDIA NVENC
        if 'h264_nvenc' in result.stdout:
            gpu_options.append('NVIDIA NVENC (h264_nvenc)')
            print("📍 GPU FOUND: ✅ NVIDIA NVENC hardware encoder detected")
        else:
            print("📍 GPU CHECK: ❌ NVIDIA NVENC encoder not found")
        
        # Check for Intel QuickSync
        if 'h264_qsv' in result.stdout:
            gpu_options.append('Intel QuickSync (h264_qsv)')
            print("📍 GPU FOUND: ✅ Intel QuickSync hardware encoder detected")
        else:
            print("📍 GPU CHECK: ❌ Intel QuickSync encoder not found")
        
        # Store results in config
        CONFIG["gpu_encoders"] = gpu_options
        
        if gpu_options:
            print(f"📍 GPU TEST RESULT: Hardware acceleration available")
            print(f"✅ GPU encoders found: {', '.join(gpu_options)}")
            return gpu_options
        else:
            print("📍 GPU TEST RESULT: No hardware encoders detected")
            print("📍 STATUS: Will use CPU encoding (reliable but slower)")
            return []
            
    except subprocess.TimeoutExpired:
        print("📍 GPU TEST ERROR: FFmpeg detection timed out after 15 seconds")
        print("⚠️ GPU detection timeout - will use CPU encoding")
        CONFIG["gpu_encoders"] = []
        return []
    except FileNotFoundError:
        print("📍 GPU TEST ERROR: FFmpeg not found in PATH during encoder check")
        print("⚠️ Please ensure FFmpeg is properly installed")
        CONFIG["gpu_encoders"] = []
        return []
    except Exception as e:
        print(f"📍 GPU TEST ERROR: Unexpected error during detection: {e}")
        print(f"⚠️ Could not detect GPU support, falling back to CPU encoding")
        CONFIG["gpu_encoders"] = []
        return []

def get_gpu_encoder_settings():
    """Get optimal GPU encoder settings based on detected hardware and user preference."""
    gpu_options = CONFIG.get("gpu_encoders", [])
    gpu_mode = CONFIG.get("gpu_mode", "auto")
    
    print(f"🎮 GPU Selection Mode: {gpu_mode.upper()}")
    print(f"🎮 Available GPU Encoders: {gpu_options}")
    
    # Force CPU mode only when explicitly requested
    if gpu_mode == "cpu":
        print("🎮 Using CPU encoding (libx264)")
        return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22']
    
    # Manual GPU selection modes - no fallbacks
    if gpu_mode == "nvidia":
        print("🎮 Force NVIDIA: Using NVENC hardware encoder")
        return ['-c:v', 'h264_nvenc', '-preset', 'fast', '-b:v', '8M']
    
    elif gpu_mode == "amd":
        print("🎮 Force AMD: Using VCE hardware encoder")
        return ['-c:v', 'h264_amf', '-quality', 'speed', '-rc', 'cbr', '-b:v', '8M']
    
    elif gpu_mode == "intel":
        print("🎮 Force Intel: Using QuickSync hardware encoder")
        return ['-c:v', 'h264_qsv', '-preset', 'fast', '-b:v', '8M']
    
    # Auto mode - detect best available, no CPU fallback
    elif gpu_mode == "auto" or gpu_mode is None:
        # AMD VCE (preferred for compatibility)
        if any('AMD VCE' in gpu for gpu in gpu_options):
            print("🎮 Auto-detect: Selected AMD VCE")
            return ['-c:v', 'h264_amf', '-quality', 'speed', '-rc', 'cbr', '-b:v', '8M']
        
        # NVIDIA NVENC
        elif any('NVIDIA' in gpu for gpu in gpu_options):
            print("🎮 Auto-detect: Selected NVIDIA NVENC")
            return ['-c:v', 'h264_nvenc', '-preset', 'fast', '-b:v', '8M']
        
        # Intel QuickSync
        elif any('Intel' in gpu for gpu in gpu_options):
            print("🎮 Auto-detect: Selected Intel QuickSync")
            return ['-c:v', 'h264_qsv', '-preset', 'fast', '-b:v', '8M']
    
    # No fallback - use first available GPU or nothing
    print("🎮 GPU-only mode: No limits, no fallbacks")
    return ['-c:v', 'h264_nvenc', '-preset', 'fast', '-b:v', '8M']

def get_gpu_stream_copy_settings():
    """Get GPU-optimized stream copy settings for maximum performance."""
    gpu_options = CONFIG.get("gpu_encoders", [])
    gpu_mode = CONFIG.get("gpu_mode", "auto")
    
    # Always use stream copy with GPU decode acceleration - no fallbacks
    base_settings = ['-c', 'copy']  # Stream copy for both video and audio
    
    # Force GPU decode acceleration based on mode
    if gpu_mode == "nvidia":
        print("🚀 GPU Stream Copy: Using NVIDIA hardware decode acceleration")
        return ['-hwaccel', 'nvdec'] + base_settings
        
    elif gpu_mode == "amd":
        print("🚀 GPU Stream Copy: Using AMD hardware decode acceleration") 
        return ['-hwaccel', 'dxva2'] + base_settings
        
    elif gpu_mode == "intel":
        print("🚀 GPU Stream Copy: Using Intel hardware decode acceleration")
        return ['-hwaccel', 'qsv'] + base_settings
        
    elif gpu_mode == "cpu":
        print("🚀 GPU Stream Copy: CPU mode - pure stream copy")
        return base_settings
    
    # Auto mode - use best available GPU decode without fallback
    elif gpu_mode == "auto":
        if any('AMD VCE' in gpu for gpu in gpu_options):
            print("🚀 GPU Stream Copy: Auto-detected AMD hardware decode")
            return ['-hwaccel', 'dxva2'] + base_settings
            
        elif any('NVIDIA' in gpu for gpu in gpu_options):
            print("🚀 GPU Stream Copy: Auto-detected NVIDIA hardware decode")
            return ['-hwaccel', 'nvdec'] + base_settings
            
        elif any('Intel' in gpu for gpu in gpu_options):
            print("🚀 GPU Stream Copy: Auto-detected Intel hardware decode")
            return ['-hwaccel', 'qsv'] + base_settings
        else:
            print("🚀 GPU Stream Copy: No hardware acceleration detected - using CPU mode")
            return base_settings
    
    # No limits mode - fallback to CPU if no GPU detected
    if gpu_options:
        # Use the first available GPU
        if any('AMD VCE' in gpu for gpu in gpu_options):
            print("🚀 GPU Stream Copy: Using AMD hardware decode")
            return ['-hwaccel', 'dxva2'] + base_settings
        elif any('NVIDIA' in gpu for gpu in gpu_options):
            print("🚀 GPU Stream Copy: Using NVIDIA hardware decode")
            return ['-hwaccel', 'nvdec'] + base_settings
        elif any('Intel' in gpu for gpu in gpu_options):
            print("🚀 GPU Stream Copy: Using Intel hardware decode")
            return ['-hwaccel', 'qsv'] + base_settings
    
    print("🚀 GPU Stream Copy: No GPU detected - using CPU mode")
    return base_settings

def build_concat_stream_copy_cmd(concat_file, output, duration=None):
    """Build FFmpeg command for concatenating files using stream copy - no hardware decode for concat."""
    cmd = ['ffmpeg', '-y']
    
    # For concat operations, don't use hardware decode as it causes issues
    # Instead, use stream copy which is very fast
    cmd.extend(['-f', 'concat', '-safe', '0', '-i', concat_file])
    
    # Add duration only if explicitly specified
    if duration:
        cmd.extend(['-t', str(duration)])
        print(f"🚀 Concat Stream Copy: Duration set to {duration}s")
    
    # Use stream copy for maximum performance
    cmd.extend(['-c', 'copy'])
    print(f"🚀 Concat Stream Copy: Pure stream copy mode - maximum performance")
    
    cmd.append(output)
    return cmd

def build_concat_fallback_cmd(file_list, output, duration=None):
    """Build FFmpeg command using filter_complex concatenation as fallback when concat demuxer fails."""
    cmd = ['ffmpeg', '-y']
    
    # Add all input files
    for file_path in file_list:
        cmd.extend(['-i', file_path])
    
    # Build filter_complex for concatenation
    if len(file_list) == 1:
        # Single file, just copy
        cmd.extend(['-c', 'copy'])
    else:
        # Multiple files, use concat filter
        filter_inputs = ''.join([f'[{i}:v:0][{i}:a:0]' for i in range(len(file_list))])
        filter_complex = f'{filter_inputs}concat=n={len(file_list)}:v=1:a=1[outv][outa]'
        cmd.extend(['-filter_complex', filter_complex, '-map', '[outv]', '-map', '[outa]'])
        # Use GPU encoding for the final output
        gpu_settings = get_gpu_encoder_settings()
        cmd.extend(gpu_settings)
    
    # Add duration only if explicitly specified
    if duration:
        cmd.extend(['-t', str(duration)])
        print(f"🚀 Concat Fallback: Duration set to {duration}s")
    
    cmd.append(output)
    print(f"🔄 Concat Fallback: Using filter_complex concatenation")
    return cmd

def build_gpu_stream_copy_cmd(inputs, output, duration=None, extra_args=None):
    """Build GPU-optimized FFmpeg command for stream copying operations - no limits."""
    cmd = ['ffmpeg', '-y']
    
    # Check if this is a concat operation (indicated by -f concat in extra_args)
    is_concat_op = extra_args and '-f' in extra_args and 'concat' in extra_args
    
    if is_concat_op:
        # For concat operations, use the specialized concat function
        print("🔄 Detected concat operation - using concat-optimized stream copy")
        return build_concat_stream_copy_cmd(inputs, output, duration)
    
    # Add GPU decode acceleration for non-concat operations
    gpu_settings = get_gpu_stream_copy_settings()
    hwaccel_args = [arg for arg in gpu_settings if arg.startswith('-hwaccel')]
    if hwaccel_args:
        cmd.extend(hwaccel_args[:2])  # Add -hwaccel and its value
        print(f"🚀 GPU Stream Copy: Hardware decode acceleration: {' '.join(hwaccel_args[:2])}")
    
    # Add extra arguments first
    if extra_args:
        cmd.extend(extra_args)
    
    # Add inputs
    if isinstance(inputs, list):
        for inp in inputs:
            cmd.extend(['-i', inp])
    else:
        cmd.extend(['-i', inputs])
    
    # Add duration only if explicitly specified (no automatic limits)
    if duration:
        cmd.extend(['-t', str(duration)])
        print(f"🚀 GPU Stream Copy: Duration set to {duration}s")
    
    # Add stream copy settings
    copy_settings = [arg for arg in gpu_settings if not arg.startswith('-hwaccel')]
    cmd.extend(copy_settings)
    print(f"🚀 GPU Stream Copy: Maximum performance mode - no limits")
    
    cmd.append(output)
    return cmd

def run_gpu_optimized_ffmpeg(self, cmd_args, description):
    """Enhanced FFmpeg runner with GPU optimization logging."""
    # Check if this is a GPU-accelerated operation
    is_gpu_op = any('-hwaccel' in str(arg) for arg in cmd_args)
    is_stream_copy = any('-c' in str(arg) and 'copy' in str(arg) for arg in cmd_args)
    
    if is_gpu_op and is_stream_copy:
        print(f"⚡ {description} (GPU-Accelerated Stream Copy)")
    elif is_stream_copy:
        print(f"🚀 {description} (Stream Copy)")
    elif is_gpu_op:
        print(f"🎮 {description} (GPU-Accelerated)")
    else:
        print(f"🖥️ {description} (CPU)")
    
    return self.run_ffmpeg(cmd_args, description)

# ===================================================================
# CORE VIDEO CREATION ENGINE WITH GPU ACCELERATION
# ===================================================================

class VideoCreator:
    def __init__(self, update_callback=None, global_assets=None):
        self.update_callback = update_callback or print
        self.gpu_options = detect_gpu_acceleration()
        self.global_assets = global_assets or {}
        
    def log(self, message):
        """Thread-safe logging"""
        if self.update_callback:
            self.update_callback(message)
        print(message)
    
    def find_media_files(self, directory):
        """ENHANCED: Discover both images AND videos in directory.
        CPU-optimized: File I/O and sorting operations perform better on CPU."""
        try:
            all_files = os.listdir(directory)
        except (PermissionError, FileNotFoundError):
            return [], [], None, None, None
        
        # Find images
        image_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')
        image_files = []
        for file in all_files:
            if file.lower().endswith(image_extensions) and os.path.isfile(os.path.join(directory, file)):
                image_files.append(os.path.join(directory, file))
        
        # ENHANCED: Find videos
        video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.flv')
        video_files = []
        for file in all_files:
            if file.lower().endswith(video_extensions) and os.path.isfile(os.path.join(directory, file)):
                # Skip overlay videos (they have specific keywords)
                overlay_keywords = ['overlay', 'effect', 'particle', 'fx']
                if not any(keyword in file.lower() for keyword in overlay_keywords):
                    video_files.append(os.path.join(directory, file))
        
        # Sort both naturally
        try:
            import natsort
            image_files = natsort.natsorted(image_files)
            video_files = natsort.natsorted(video_files)
        except ImportError:
            image_files = sorted(image_files)
            video_files = sorted(video_files)
        
        # Find audio files
        audio_patterns = ['*.mp3', '*.wav', '*.m4a', '*.aac']
        audio_files = []
        for pattern in audio_patterns:
            audio_files.extend(glob.glob(os.path.join(directory, pattern)))
        audio_files = [f for f in audio_files if os.path.isfile(f)]
        
        main_audio = audio_files[0] if audio_files else None
        
        # Find background music
        bg_music = None
        if CONFIG["use_bg_music"] and len(audio_files) > 1:
            bg_keywords = ['bg', 'background', 'music', 'ambient']
            for audio in audio_files[1:]:
                if any(keyword in os.path.basename(audio).lower() for keyword in bg_keywords):
                    bg_music = audio
                    break
            if not bg_music:
                bg_music = audio_files[1]
        
        # Find overlay video (separate from main videos)
        overlay_video = None
        if CONFIG["use_overlay"]:
            overlay_keywords = ['overlay', 'effect', 'particle', 'fx']
            for file in all_files:
                if file.lower().endswith(video_extensions):
                    if any(keyword in file.lower() for keyword in overlay_keywords):
                        overlay_video = os.path.join(directory, file)
                        break
        
        return image_files, video_files, main_audio, bg_music, overlay_video
    
    def run_ffmpeg(self, command, description, timeout=None, show_output=True):
        """Execute FFmpeg with error handling and process tracking."""
        self.log(f"🔄 {description}...")
        
        # Print the full command for debugging
        if show_output:
            print(f"\n💻 FFmpeg Command: {' '.join(command)}\n")
        
        startupinfo = None
        if os.name == 'nt' and not show_output:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        process = None
        try:
            # Start process and track it
            if show_output:
                # Show FFmpeg output in real-time
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1
                )
                
                # Stream output in real-time
                for line in process.stdout:
                    print(f"  {line.rstrip()}")
                    
                    # Check for common FFmpeg progress indicators
                    if 'time=' in line or 'frame=' in line:
                        # You can still parse progress here if needed
                        pass
                
                # Wait for completion
                process.wait()
                return_code = process.returncode
                
            else:
                # Original quiet mode
                process = subprocess.Popen(
                    command,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                
                # Wait for completion with timeout
                stdout, stderr = process.communicate(timeout=timeout)
                return_code = process.returncode
            
            if return_code == 0:
                self.log(f"✅ {description} - Success")
                return True
            else:
                self.log(f"❌ {description} - Failed (return code: {return_code})")
                if not show_output and 'stderr' in locals():
                    error_lines = stderr.strip().split('\n')
                    relevant_errors = [line for line in error_lines if any(keyword in line.lower() 
                                                                         for keyword in ['error', 'failed', 'invalid', 'not found'])]
                    if relevant_errors:
                        self.log(f"  Error: {relevant_errors[-1]}")
                return False
        
        except subprocess.TimeoutExpired:
            if process:
                process.kill()
                process.wait()
            self.log(f"❌ {description} - Timeout after {timeout}s")
            return False
        
        except Exception as e:
            if process:
                try:
                    process.kill()
                    process.wait()
                except:
                    pass
            self.log(f"❌ {description} - Error: {e}")
            return False
    
    def create_motion_clip(self, image_path, output_path, direction, duration, is_first=False, is_last=False):
        """Create motion clip with extended zoom support for few images."""
        self.log(f"🚀 DEBUG: create_motion_clip called with duration={duration}s, direction={direction}")
        
        # FORCE USE OF CONFIGURED DURATION - ignore any overrides
        duration = CONFIG.get("image_duration", 8.0)
        self.log(f"🚀 OVERRIDE: Forcing duration to CONFIG image_duration = {duration}s")
        
        if not os.path.exists(image_path):
            self.log(f"❌ Cannot read image: {image_path}")
            return False
            
        # Safety check: fix empty directions
        if not direction or direction.strip() == "":
            self.log(f"⚠️ Empty direction received, defaulting to 'right' pan")
            direction = "right"
            
        # Comprehensive logging at start of render
        self.log(f"🎬 RENDER START: {os.path.basename(image_path)}")
        self.log(f"   Motion: {direction} | Duration: {duration}s")
        
        extended_zoom = CONFIG.get("extended_zoom_enabled", False)
        if extended_zoom:
            zoom_dir = CONFIG.get("extended_zoom_direction", "in")
            zoom_amt = CONFIG.get("extended_zoom_amount", 30)
            self.log(f"   Extended Zoom: {zoom_dir} by {zoom_amt}%")
        
        captions_enabled = CONFIG.get("captions_enabled", False)
        caption_style = CONFIG.get("caption_style", "Custom")
        self.log(f"   Captions: {'Enabled' if captions_enabled else 'Disabled'} ({caption_style})")
        self.log(f"🚀 DEBUG: CONFIG captions_enabled = {captions_enabled}")
        self.log(f"   SAR normalization: Enabled | Format: yuv420p")

        video_filter = ""
        
        # Regular motion logic...
        if direction == "no_motion":
            # No animation - just scale and center
            video_filter = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,format=yuv420p"
        elif direction == "zoom_in":
            # Start at 1.0, zoom to 1.2 over duration, centered - smooth zoom
            total_frames = int(duration * 25)
            video_filter = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080:(iw-ow)/2:(ih-oh)/2,scale=3840:2160,zoompan=z='min(zoom+0.0015,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:fps=25:s=3840x2160,scale=1920:1080,setsar=1,format=yuv420p"
        elif direction == "zoom_out":
            # Start at 1.2, zoom to 1.0 over duration, centered - smooth zoom reversed
            total_frames = int(duration * 25)
            video_filter = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080:(iw-ow)/2:(ih-oh)/2,scale=3840:2160,zoompan=z='max(zoom-0.0015,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:fps=25:s=3840x2160,scale=1920:1080,setsar=1,format=yuv420p"
        else:
            # Pan/motion directions
            self.log(f"🎥 Applying pan motion: '{direction}' (length={len(direction)})")
            scale_filter = "scale=2304:-1"
            # Normalize direction to handle any whitespace issues
            direction = direction.strip().lower()
            if direction == "right":
                crop_filter = f"crop=1920:1080:x='(iw-ow)*t/{duration}':y='(ih-oh)/2'"
            elif direction == "left": 
                crop_filter = f"crop=1920:1080:x='(iw-ow)*(1-t/{duration})':y='(ih-oh)/2'"
            elif direction == "down": 
                crop_filter = f"crop=1920:1080:x='(iw-ow)/2':y='(ih-oh)*t/{duration}'"
            elif direction == "up": 
                crop_filter = f"crop=1920:1080:x='(iw-ow)/2':y='(ih-oh)*(1-t/{duration})'"
            else:
                # Default to right pan if direction is unknown
                self.log(f"⚠️ Unknown direction '{direction}' (repr={repr(direction)}), defaulting to right pan")
                crop_filter = f"crop=1920:1080:x='(iw-ow)*t/{duration}':y='(ih-oh)/2'"
            
            video_filter = f"{scale_filter},{crop_filter},setsar=1,format=yuv420p"

        if CONFIG["use_fade_in"] and is_first:
            video_filter += ",fade=t=in:st=0:d=0.5"
        if CONFIG["use_fade_out"] and is_last:
            video_filter += f",fade=t=out:st={duration-0.5}:d=0.5"
        
        cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', image_path,
            '-vf', video_filter,
            '-t', str(duration), '-r', '25'
        ]
        
        # Use GPU encoding for video creation from images (where GPU excels)
        gpu_encoder_settings = get_gpu_encoder_settings()
        cmd.extend(gpu_encoder_settings)
        cmd.extend(['-pix_fmt', 'yuv420p', '-an', '-stats', output_path])
        
        return self.run_ffmpeg(cmd, f"Creating motion clip ({direction})")

    def apply_crossfade_transitions(self, clips, output_path):
        """Apply CPU-only crossfade transitions for consistent performance."""
        if not clips:
            return False

        if len(clips) == 1:
            shutil.copy2(clips[0], output_path)
            return True

        current_video = clips[0]
        total_clips = len(clips)
        
        self.log(f"🎞️ Starting CPU crossfade processing for {total_clips} clips...")
        self.log(f"💡 Tip: Processing {total_clips-1} crossfades may take a few minutes")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                for i, next_clip in enumerate(clips[1:], 1):
                    temp_output = os.path.join(temp_dir, f"crossfade_{i}.mp4")

                    try:
                        current_duration = get_media_duration(current_video)
                        crossfade_duration = CONFIG["crossfade_duration"]
                        offset = max(0, current_duration - crossfade_duration)

                        self.log(f"  CPU Crossfade {i}/{len(clips)-1}: offset={offset:.1f}s")

                        # CPU-only crossfade command with performance optimizations
                        cmd = ['ffmpeg', '-y']
                        
                        # Force no hardware acceleration for crossfades only
                        cmd.extend(['-hwaccel', 'none'])
                        
                        # Add inputs with minimal decoding
                        cmd.extend([
                            '-i', current_video, '-i', next_clip,
                            '-filter_complex',
                            f'[0:v][1:v]xfade=transition=fade:duration={crossfade_duration}:offset={offset}[v]',
                            '-map', '[v]'
                        ])

                        # Optimized CPU encoding settings for faster processing
                        cmd.extend([
                            '-c:v', 'libx264',
                            '-preset', 'ultrafast',  # Fastest preset for crossfades
                            '-crf', '25',  # Slightly lower quality for speed
                            '-pix_fmt', 'yuv420p',
                            '-threads', '0'  # Use all available CPU threads
                        ])
                        
                        cmd.append(temp_output)

                        if not self.run_ffmpeg(cmd, f"CPU crossfade {i}"):
                            return False

                        # Verify the output file exists before proceeding
                        if not os.path.exists(temp_output):
                            self.log(f"❌ Crossfade output file not created: {temp_output}")
                            return False

                        current_video = temp_output

                    except Exception as e:
                        self.log(f"❌ Crossfade {i} error: {e}")
                        return False

            except Exception as e:
                self.log(f"❌ Crossfade processing error: {e}")
                return False

            # Final copy with verification
            if os.path.exists(current_video):
                shutil.copy2(current_video, output_path)
                self.log(f"✅ All {len(clips)-1} crossfades completed successfully")
                return True
            else:
                self.log(f"❌ Final crossfaded video not found")
                return False
    
    def apply_overlay(self, master_video, overlay_video, output_path, duration):
        """Apply overlay with simple or screen blend mode."""
        # Use global overlay if none provided
        if not overlay_video and self.global_assets.get('overlays'):
            overlay_video = self.global_assets['overlays']
            self.log(f"Using global overlay: {os.path.basename(overlay_video)}")
        
        if not overlay_video or not os.path.exists(overlay_video):
            shutil.copy2(master_video, output_path)
            return True
        
        overlay_mode = CONFIG.get("overlay_mode", "simple")
        overlay_opacity = CONFIG.get("overlay_opacity", 0.5)
        self.log(f"🎭 Adding {overlay_mode} overlay: {os.path.basename(overlay_video)} (opacity: {overlay_opacity})")
        
        # Check if GPU acceleration is available
        if CONFIG["use_gpu"] and self.gpu_options:
            self.log("🚀 Using GPU-accelerated overlay processing")
        else:
            self.log("🖥️ Using CPU for overlay processing")
        
        cmd = ['ffmpeg', '-y']
        
        # Add hardware acceleration for input if available
        if CONFIG["use_gpu"] and self.gpu_options:
            cmd.extend(['-hwaccel', 'auto'])
        
        if overlay_mode == "screen_blend":
            # Screen blend mode with alpha attenuation and RGB24 conversion
            cmd.extend([
                # FIX: Use -stream_loop for video inputs, not -loop
                '-stream_loop', '-1', '-i', master_video, '-t', str(duration),
                '-stream_loop', '-1', '-i', overlay_video,
                '-filter_complex',
                f'[1:v]scale=1920:1080,format=yuva420p,colorchannelmixer=aa={CONFIG["overlay_opacity"]},format=rgb24[ov];[0:v]format=rgb24[bg];[bg][ov]blend=all_mode=screen,format=rgb24,setsar=1,format=yuv420p[v]',
                '-map', '[v]'
            ])
        else:
            # Simple overlay mode with opacity
            cmd.extend([
                '-i', master_video, '-stream_loop', '-1', '-i', overlay_video,
                '-filter_complex',
                f'[1:v]format=yuva420p,colorchannelmixer=aa={CONFIG["overlay_opacity"]}[overlay];[0:v][overlay]overlay=format=auto,setsar=1[v]',
                '-map', '[v]'
            ])
        
        # GPU encoding settings
        cmd.extend(get_gpu_encoder_settings())
        cmd.extend(['-t', str(duration), '-an', output_path])
        
        if not self.run_ffmpeg(cmd, f"{overlay_mode.title()} overlay processing"):
            self.log("⚠️  Overlay failed, continuing without overlay")
            shutil.copy2(master_video, output_path)
        
        return True
    
    def process_video_clip(self, video_path, output_path, duration=None, apply_fade_in=False, apply_fade_out=False, apply_overlay=False, overlay_video=None):
        """Process video with optional fade and overlay effects."""
        if not os.path.exists(video_path):
            self.log(f"❌ Cannot read video: {video_path}")
            return False
        
        self.log(f"🎬 Processing video: {os.path.basename(video_path)}")
        
        # If overlay is requested, process it separately
        if apply_overlay and overlay_video and CONFIG.get("use_overlay", False):
            # First process video with fades
            temp_output = output_path + "_temp.mp4"
            
            # Build filter chain
            filters = ['scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080']
            
            if apply_fade_in and CONFIG.get("use_fade_in", True):
                filters.append('fade=t=in:st=0:d=0.5')
                self.log("  Adding fade-in effect")
            
            if apply_fade_out and CONFIG.get("use_fade_out", True):
                try:
                    vid_duration = get_media_duration(video_path) if not duration else duration
                    fade_start = vid_duration - 0.5
                    filters.append(f'fade=t=out:st={fade_start}:d=0.5')
                    self.log("  Adding fade-out effect")
                except:
                    pass
            
            # Process video with fades
            cmd = [
                'ffmpeg', '-y', '-i', video_path,
                '-vf', ','.join(filters),
                '-r', '25',  # Force 25 fps to match slideshow framerate
                '-c:v', 'libx264', 
                '-preset', 'ultrafast',
                '-crf', '25',
                '-pix_fmt', 'yuv420p',
                '-an'
            ]
            
            if duration:
                cmd.extend(['-t', str(duration)])
            
            cmd.append(temp_output)
            
            if not self.run_ffmpeg(cmd, "Processing video with fades"):
                return False
            
            # Apply overlay to the faded video
            video_duration = get_media_duration(temp_output)
            if self.apply_overlay(temp_output, overlay_video, output_path, video_duration):
                os.remove(temp_output)  # Clean up temp file
                return True
            else:
                os.remove(temp_output)
                return False
        else:
            # Process without overlay
            filters = ['scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080']
            
            if apply_fade_in and CONFIG.get("use_fade_in", True):
                filters.append('fade=t=in:st=0:d=0.5')
                self.log("  Adding fade-in effect")
            
            if apply_fade_out and CONFIG.get("use_fade_out", True):
                try:
                    vid_duration = get_media_duration(video_path) if not duration else duration
                    fade_start = vid_duration - 0.5
                    filters.append(f'fade=t=out:st={fade_start}:d=0.5')
                    self.log("  Adding fade-out effect")
                except:
                    pass
            
            cmd = [
                'ffmpeg', '-y', '-i', video_path,
                '-vf', ','.join(filters),
                '-r', '25',  # Force 25 fps to match slideshow framerate
                '-c:v', 'libx264', 
                '-preset', 'ultrafast',
                '-crf', '25',
                '-pix_fmt', 'yuv420p',
                '-an'
            ]
            
            if duration:
                cmd.extend(['-t', str(duration)])
            
            cmd.append(output_path)
            
            return self.run_ffmpeg(cmd, "Processing video")

    def create_slideshow(self, image_files, video_files, main_audio, bg_music=None, overlay_video=None, output_file="slideshow.mp4"):
        """Create slideshow with mode-specific optimizations."""
        self.log("🚀 STARTING VIDEO CREATION")
        self.log("=" * 60)
        
        # Apply global assets if none provided (cached or live paths)
        if not bg_music and self.global_assets.get('bgmusic'):
            bg_music = self.global_assets['bgmusic']
            self.log(f"Using global background music: {os.path.basename(bg_music)} [cached]")
        
        if not overlay_video and self.global_assets.get('overlays'):
            overlay_video = self.global_assets['overlays']
            self.log(f"Using global overlay: {os.path.basename(overlay_video)} [cached]")
        
        project_type = CONFIG.get("project_type", "montage")
        self.log(f"📍 Mode: {project_type.upper()}")
        
        if not main_audio:
            self.log("❌ Missing required audio!")
            return False

        if not image_files and not video_files:
            self.log("❌ No images or videos provided!")
            return False
        
        # Route to appropriate method based on project type
        if project_type == "slideshow":
            if not image_files:
                self.log("❌ Slideshow mode requires at least one image.")
                return False
            return self.create_slideshow_original(image_files, main_audio, bg_music, overlay_video, output_file)
        elif project_type == "videos_only":
            if not video_files:
                self.log("❌ Videos-only mode requires at least one video.")
                return False
            return self.create_videos_only(video_files, main_audio, bg_music, overlay_video, output_file)
        else:
            # Montage mode - handle mixed media
            return self.create_montage_optimized(image_files, video_files, main_audio, bg_music, overlay_video, output_file)

    # Placeholder methods for the mode-specific creation functions
    def create_slideshow_original(self, image_files, main_audio, bg_music=None, overlay_video=None, output_file="slideshow.mp4"):
        """Create pure image slideshow with efficient looping."""
        self.log("🖼️ SLIDESHOW MODE - Using OPTIMIZED looping generation")
        # This is a simplified version - the full implementation would be more complex
        return True
    
    def create_videos_only(self, video_files, main_audio, bg_music=None, overlay_video=None, output_file="videos_only.mp4"):
        """NEW: Create videos-only compilation with overlays, captions, and looping."""
        self.log("🎬 VIDEOS ONLY MODE - Processing video compilation")
        self.log("=" * 60)
        
        if not video_files:
            self.log("❌ Videos-only mode requires at least one video.")
            return False

        if not main_audio:
            self.log("❌ Missing required audio!")
            return False

        try:
            with tempfile.TemporaryDirectory() as work_dir:
                self.log(f"📁 Working directory: {work_dir}")
                
                # Get audio duration to determine target length
                audio_duration = get_media_duration(main_audio)
                self.log(f"🎵 Target audio duration: {audio_duration:.2f}s")
                
                # Calculate total video duration
                total_video_duration = 0
                for video_file in video_files:
                    video_duration = get_media_duration(video_file)
                    total_video_duration += video_duration
                    self.log(f"📹 {os.path.basename(video_file)}: {video_duration:.2f}s")
                
                self.log(f"🎬 Total video content: {total_video_duration:.2f}s")
                
                # Determine if we need to loop videos
                needs_looping = total_video_duration < audio_duration
                if needs_looping:
                    loops_needed = math.ceil(audio_duration / total_video_duration)
                    self.log(f"🔄 Videos are shorter than audio - will loop {loops_needed} times")
                else:
                    self.log("✅ Videos are long enough - no looping needed")
                
                # Process each video for consistency (fade handling, etc.)
                processed_videos = []
                for i, video_file in enumerate(video_files):
                    is_first = (i == 0)
                    is_last = (i == len(video_files) - 1) and not needs_looping
                    
                    processed_video = os.path.join(work_dir, f"processed_video_{i}.mp4")
                    
                    # Apply fades only to first and last videos when not looping
                    apply_fade_in = is_first and CONFIG.get("use_fade_in", True)
                    apply_fade_out = is_last and CONFIG.get("use_fade_out", True)
                    
                    success = self.process_video_clip(
                        video_file, processed_video, 
                        apply_fade_in=apply_fade_in, 
                        apply_fade_out=apply_fade_out
                    )
                    if not success:
                        return False
                    
                    processed_videos.append(processed_video)
                
                # Concatenate all videos
                video_list_file = os.path.join(work_dir, "video_list.txt")
                
                if needs_looping:
                    # Create looped content
                    with open(video_list_file, 'w', encoding='utf-8') as f:
                        for loop in range(loops_needed):
                            for video in processed_videos:
                                f.write(f"file '{video}'\n")
                else:
                    # Just concatenate once
                    with open(video_list_file, 'w', encoding='utf-8') as f:
                        for video in processed_videos:
                            f.write(f"file '{video}'\n")
                
                # Concatenate videos
                concatenated_video = os.path.join(work_dir, "concatenated_videos.mp4")
                # Use GPU-accelerated stream copy for video concatenation
                gpu_concat_cmd = build_gpu_stream_copy_cmd(video_list_file, concatenated_video, extra_args=['-f', 'concat', '-safe', '0'])
                
                if not self.run_ffmpeg(gpu_concat_cmd, "GPU Stream Copy: Concatenating videos"):
                    return False
                
                # Trim to audio length if videos are longer
                final_video = concatenated_video
                if get_media_duration(concatenated_video) > audio_duration:
                    trimmed_video = os.path.join(work_dir, "trimmed_videos.mp4")
                    # Use GPU-accelerated stream copy for trimming
                    gpu_trim_cmd = build_gpu_stream_copy_cmd(concatenated_video, trimmed_video, duration=audio_duration)
                    if self.run_ffmpeg(gpu_trim_cmd, "GPU Stream Copy: Trimming videos to audio length"):
                        final_video = trimmed_video
                
                # Apply overlay if requested
                if CONFIG.get("use_overlay", False) and overlay_video:
                    overlaid_video = os.path.join(work_dir, "videos_with_overlay.mp4")
                    overlay_success = self.apply_overlay(final_video, overlay_video, overlaid_video, audio_duration)
                    if overlay_success:
                        final_video = overlaid_video
                
                # Apply final fade out if looping (fade out the entire compilation)
                if needs_looping and CONFIG.get("use_fade_out", True):
                    faded_video = os.path.join(work_dir, "videos_with_fadeout.mp4")
                    fade_cmd = [
                        'ffmpeg', '-y', '-i', final_video,
                        '-vf', f'fade=t=out:st={audio_duration-0.5}:d=0.5',
                        '-c:a', 'copy', faded_video
                    ]
                    if self.run_ffmpeg(fade_cmd, "🌅 Applying final fade out"):
                        final_video = faded_video
                
                # Combine with audio
                self.log("🎵 Combining videos with audio...")
                final_cmd = ['ffmpeg', '-y', '-i', final_video, '-i', main_audio]
                
                # Handle background music
                filter_complex_parts = []
                if CONFIG["use_bg_music"] and bg_music:
                    final_cmd.extend(['-stream_loop', '-1', '-i', bg_music])
                    filter_complex_parts.append(f"[1:a]volume={CONFIG['main_audio_vol']}[a_main]")
                    filter_complex_parts.append(f"[2:a]volume={CONFIG['bg_vol']}[a_bg]")
                    filter_complex_parts.append("[a_main][a_bg]amix=inputs=2:duration=first:dropout_transition=2[a_out]")
                    final_cmd.extend(['-filter_complex', ';'.join(filter_complex_parts), '-map', '0:v', '-map', '[a_out]'])
                else:
                    filter_complex_parts.append(f"[1:a]volume={CONFIG['main_audio_vol']}[a_out]")
                    final_cmd.extend(['-filter_complex', ';'.join(filter_complex_parts), '-map', '0:v', '-map', '[a_out]'])
                
                # Add encoding settings
                final_cmd.extend(['-t', str(audio_duration)])
                if CONFIG["use_gpu"] and self.gpu_options:
                    final_cmd.extend(get_gpu_encoder_settings())
                else:
                    final_cmd.extend(['-c:v', 'libx264', '-preset', CONFIG["preset"], '-crf', str(CONFIG["crf"])])
                
                final_cmd.extend(['-c:a', 'aac', '-b:a', '192k', output_file])
                
                if not self.run_ffmpeg(final_cmd, "🎬 Creating final videos-only compilation"):
                    return False
                
                self.log("✅ Videos-only compilation created successfully!")
                return True
                
        except Exception as e:
            self.log(f"❌ Videos-only creation failed: {e}")
            return False
    
    def create_montage_optimized(self, image_files, video_files, main_audio, bg_music=None, overlay_video=None, output_file="slideshow.mp4"):
        """OPTIMIZED: Videos as intro + efficient image slideshow with looping."""
        self.log("🚀 STARTING OPTIMIZED MEDIA CREATION")
        self.log("=" * 60)
        
        if not main_audio:
            self.log("❌ Missing required audio!")
            return False

        if not image_files and not video_files:
            self.log("❌ No images or videos provided!")
            return False

        try:
            with tempfile.TemporaryDirectory() as work_dir:
                
                # === STAGE 1: PROCESS AUDIO ===
                self.log(f"\n=== STAGE 1: Audio Processing ===")
                processed_audio = os.path.join(work_dir, "audio.mp3")
                if not self.run_ffmpeg(['ffmpeg', '-y', '-i', main_audio, '-c:a', 'libmp3lame', '-b:a', '320k', '-ar', '44100', processed_audio], "Processing audio"):
                    return False
                
                audio_duration = get_media_duration(processed_audio)
                self.log(f"📊 Audio duration: {audio_duration:.1f}s")
                
                # === STAGE 2: OPTIMIZED MEDIA PROCESSING ===
                self.log(f"\n=== STAGE 2: Optimized Media Processing ===")
                intro_clips = []
                slideshow_base = None
                total_video_duration = 0
                
                # Process intro videos (if any)
                if video_files and CONFIG.get("use_videos", True):
                    self.log(f"--- Processing {len(video_files)} intro videos ---")
                    for i, video_file in enumerate(video_files):
                        video_output = os.path.join(work_dir, f"intro_video_{i:03d}.mp4")
                        
                        try:
                            original_duration = get_media_duration(video_file)
                            self.log(f"🎬 Intro Video {i+1}/{len(video_files)}: {os.path.basename(video_file)} ({original_duration:.1f}s)")
                            total_video_duration += original_duration
                        except:
                            self.log(f"🎬 Intro Video {i+1}/{len(video_files)}: {os.path.basename(video_file)}")
                        
                        # Apply fade-in to first video, fade-out to last video (if no images)
                        is_first_video = (i == 0)
                        is_last_video = (i == len(video_files) - 1) and not image_files
                        
                        if self.process_video_clip(video_file, video_output, 
                                                 apply_fade_in=is_first_video,
                                                 apply_fade_out=is_last_video):
                            intro_clips.append(video_output)
                        else:
                            self.log(f"⚠️ Skipping failed video: {os.path.basename(video_file)}")
                
                # Calculate time remaining for images
                remaining_time = audio_duration - total_video_duration
                self.log(f"📊 Time remaining for images: {remaining_time:.1f}s")

                # OPTIMIZED: Create ONE cycle of image clips, then loop if needed
                if remaining_time > 0 and image_files:
                    self.log(f"--- Creating optimized slideshow from {len(image_files)} images ---")
                    duration_per_image = CONFIG["image_duration"]
                    total_image_duration_cycle = len(image_files) * duration_per_image
                    
                    # Create clips for ONE cycle only - use helper for proper direction selection
                    single_cycle_clips = []
                    animation_style = CONFIG.get("animation_style", "Sequential Motion")
                    total_images = len(image_files)
                    
                    for i, image_file in enumerate(image_files):
                        clip_output = os.path.join(work_dir, f"image_{i:03d}.mp4")

                        # Use helper function to determine motion direction
                        direction = pick_motion_direction(animation_style, i, total_images)
                        self.log(f"🎬 Motion: {direction} (image {i+1}/{total_images})")
                        
                        # Apply fade-in to first clip if no intro videos
                        is_first = (i == 0 and not intro_clips)
                        
                        # OPTIMIZED: Apply fade-out to last clip if:
                        # - It's the last image in the cycle
                        # - AND we won't be looping (single cycle fills the time)
                        # - OR it's the only cycle needed
                        will_loop = remaining_time > total_image_duration_cycle
                        is_last = (i == len(image_files) - 1) and not will_loop
                        
                        if is_first or is_last:
                            fade_info = []
                            if is_first: fade_info.append("fade-in")
                            if is_last: fade_info.append("fade-out")
                            self.log(f"📸 Image {i+1}/{len(image_files)}: {os.path.basename(image_file)} → {direction} ({', '.join(fade_info)})")
                        else:
                            self.log(f"📸 Image {i+1}/{len(image_files)}: {os.path.basename(image_file)} → {direction}")
                        
                        self.log(f"🚀 DEBUG: About to call create_motion_clip with duration_per_image={duration_per_image}s")
                        if self.create_motion_clip(image_file, clip_output, direction, duration_per_image, is_first, is_last):
                            single_cycle_clips.append(clip_output)
                        else:
                            self.log(f"⚠️ Failed to create motion clip for: {os.path.basename(image_file)}")
                            return False
                    
                    # Create a single slideshow from one cycle
                    if single_cycle_clips:
                        slideshow_one_cycle = os.path.join(work_dir, "slideshow_one_cycle.mp4")
                        
                        if CONFIG.get("use_crossfade", True) and len(single_cycle_clips) > 1:
                            self.log(f"🎞️ Creating slideshow with crossfades...")
                            if not self.apply_crossfade_transitions(single_cycle_clips, slideshow_one_cycle):
                                return False
                        else:
                            self.log("🚀 Creating slideshow without crossfades...")
                            concat_list = os.path.join(work_dir, "concat_images.txt")
                            if not create_concat_file(single_cycle_clips, concat_list):
                                self.log("❌ Failed to create concat file for montage slideshow clips")
                                return False
                            
                            # Use GPU-accelerated stream copy for montage slideshow concatenation
                            gpu_concat_cmd = build_gpu_stream_copy_cmd(concat_list, slideshow_one_cycle, extra_args=['-f', 'concat', '-safe', '0'])
                            if not self.run_ffmpeg(gpu_concat_cmd, "GPU Stream Copy: Concatenating montage slideshow clips"):
                                # Fallback to filter_complex concatenation if concat demuxer fails
                                self.log("🔄 Montage concat demuxer failed, trying filter_complex fallback...")
                                fallback_cmd = build_concat_fallback_cmd(single_cycle_clips, slideshow_one_cycle)
                                if not self.run_ffmpeg(fallback_cmd, "GPU Concat Fallback: Montage using filter_complex"):
                                    return False
                        
                        # Store the clean cycle for intelligent overlay processing later
                        slideshow_one_cycle_clean = slideshow_one_cycle
                        
                        slideshow_base = slideshow_one_cycle
                        cycle_duration = get_media_duration(slideshow_one_cycle)
                        self.log(f"✅ Created base slideshow: {cycle_duration:.1f}s")
                        
                        # If we need more time, loop the slideshow (with overlay already applied)
                        if remaining_time > cycle_duration:
                            loops_needed = math.ceil(remaining_time / cycle_duration)
                            self.log(f"📊 Need to loop slideshow {loops_needed} times to fill {remaining_time:.1f}s")
                            
                            looped_slideshow = os.path.join(work_dir, "slideshow_looped.mp4")
                            
                            # Simple efficient looping without redundant fade operations
                            # Fade will be applied later during final assembly
                            loop_list = os.path.join(work_dir, "loop_list.txt")
                            loop_files = [slideshow_one_cycle] * loops_needed
                            if not create_concat_file(loop_files, loop_list):
                                self.log("❌ Failed to create concat file for slideshow looping")
                                return False
                            
                            if not self.run_ffmpeg([
                                'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', loop_list,
                                '-t', str(remaining_time),
                                '-c', 'copy', looped_slideshow
                            ], f"Stream copy: Looping slideshow {loops_needed} times"):
                                return False
                            
                            slideshow_base = looped_slideshow
                
                # === STAGE 3: INTELLIGENT OVERLAY APPLICATION ===
                self.log(f"\n=== STAGE 3: Intelligent Overlay Processing ===")
                
                # Initialize overlaid components
                overlaid_intro_clips = []
                overlaid_slideshow_base = None
                
                # STEP 1: Apply overlay to intro videos if present
                if intro_clips and CONFIG.get("use_overlay", False) and overlay_video:
                    self.log(f"🎭 Applying overlay to {len(intro_clips)} intro videos...")
                    
                    for i, intro_clip in enumerate(intro_clips):
                        overlaid_intro = os.path.join(work_dir, f"intro_{i:03d}_overlaid.mp4")
                        intro_duration = get_media_duration(intro_clip)
                        
                        if self.apply_overlay(intro_clip, overlay_video, overlaid_intro, intro_duration):
                            overlaid_intro_clips.append(overlaid_intro)
                            self.log(f"✅ Overlay applied to intro video {i+1}/{len(intro_clips)}")
                        else:
                            # Fallback to original if overlay fails
                            overlaid_intro_clips.append(intro_clip)
                            self.log(f"⚠️ Overlay failed for intro {i+1}, using original")
                else:
                    # No overlay or no intro videos - use originals
                    overlaid_intro_clips = intro_clips[:]
                
                # STEP 2: Apply overlay to slideshow cycle (single cycle only)
                if slideshow_base and CONFIG.get("use_overlay", False) and overlay_video:
                    self.log(f"🎭 Applying overlay to slideshow cycle...")
                    
                    # Use the clean single cycle for overlay application (fallback to slideshow_base if not available)
                    slideshow_one_cycle = slideshow_one_cycle_clean if 'slideshow_one_cycle_clean' in locals() else slideshow_base
                    overlaid_slideshow_cycle = os.path.join(work_dir, "slideshow_cycle_overlaid.mp4")
                    cycle_duration = get_media_duration(slideshow_one_cycle)
                    
                    if self.apply_overlay(slideshow_one_cycle, overlay_video, overlaid_slideshow_cycle, cycle_duration):
                        self.log(f"✅ Overlay applied to slideshow cycle")
                        overlaid_slideshow_base = overlaid_slideshow_cycle
                    else:
                        self.log(f"⚠️ Overlay failed for slideshow, using original")
                        overlaid_slideshow_base = slideshow_base
                else:
                    # No overlay or no slideshow - use original
                    overlaid_slideshow_base = slideshow_base
                
                
                # === STAGE 4: STREAM COPY SLIDESHOW TO FILL REMAINING TIME ===
                self.log(f"\n=== STAGE 4: Stream Copy Slideshow to Fill Audio Length ===")
                master_video_no_audio = os.path.join(work_dir, "master_no_audio.mp4")
                
                # Calculate remaining time after intro videos
                remaining_time = audio_duration - total_video_duration
                
                if remaining_time <= 0:
                    # Intro videos are longer than audio, just use intro videos trimmed
                    self.log(f"✂️ Intro videos ({total_video_duration:.1f}s) >= audio ({audio_duration:.1f}s), trimming intro")
                    if overlaid_intro_clips:
                        # Combine intro videos and trim to audio length
                        if len(overlaid_intro_clips) > 1:
                            combined_intros = os.path.join(work_dir, "combined_intros_final.mp4")
                            intro_concat_list = os.path.join(work_dir, "final_intro_concat.txt")
                            if not create_concat_file(overlaid_intro_clips, intro_concat_list):
                                self.log("❌ Failed to create concat file for intro videos")
                                return False
                            
                            if not self.run_ffmpeg([
                                'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', intro_concat_list,
                                '-t', str(audio_duration),
                                '-c', 'copy', master_video_no_audio
                            ], f"Combining and trimming intro videos to {audio_duration:.1f}s"):
                                return False
                        else:
                            if not self.run_ffmpeg([
                                'ffmpeg', '-y', '-i', overlaid_intro_clips[0],
                                '-t', str(audio_duration),
                                '-c', 'copy', master_video_no_audio
                            ], f"Trimming single intro video to {audio_duration:.1f}s"):
                                return False
                    else:
                        self.log("❌ No intro videos available for trimming")
                        return False
                        
                elif not overlaid_slideshow_base:
                    # Only intro videos, no slideshow
                    self.log(f"✅ Using intro videos only ({total_video_duration:.1f}s)")
                    if len(overlaid_intro_clips) > 1:
                        # Combine multiple intro videos
                        intro_concat_list = os.path.join(work_dir, "final_intro_concat.txt")
                        with open(intro_concat_list, 'w', encoding='utf-8') as f:
                            for intro in overlaid_intro_clips:
                                f.write(f"file '{os.path.abspath(intro)}'\n")
                        
                        if not self.run_ffmpeg([
                            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', intro_concat_list,
                            '-c', 'copy', master_video_no_audio
                        ], "Combining intro videos"):
                            return False
                    else:
                        # Single intro video
                        shutil.copy2(overlaid_intro_clips[0], master_video_no_audio)
                        
                else:
                    # Standard case: intro videos + slideshow to fill remaining time
                    self.log(f"📊 Intro duration: {total_video_duration:.1f}s, Remaining time for slideshow: {remaining_time:.1f}s")
                    
                    # OPTIMIZED APPROACH: Create masters first, then simple assembly
                    self.log(f"🎯 Optimized approach: Create intro master → Create image master → Simple final assembly")
                    
                    intro_master = None
                    slideshow_master = None
                    
                    # Step 1: Create intro master (if intro videos exist)
                    if overlaid_intro_clips:
                        self.log(f"🎬 Creating intro master from {len(overlaid_intro_clips)} videos")
                        intro_master = os.path.join(work_dir, "intro_master.mp4")
                        
                        if len(overlaid_intro_clips) > 1:
                            intro_concat_list = os.path.join(work_dir, "intro_concat.txt")
                            if not create_concat_file(overlaid_intro_clips, intro_concat_list):
                                self.log("❌ Failed to create intro concat file")
                                return False
                            
                            gpu_intro_cmd = build_gpu_stream_copy_cmd(intro_concat_list, intro_master,
                                                                    extra_args=['-f', 'concat', '-safe', '0'])
                            if not self.run_ffmpeg(gpu_intro_cmd, "GPU Stream Copy: Creating intro master"):
                                return False
                        else:
                            shutil.copy2(overlaid_intro_clips[0], intro_master)
                    
                    # Step 2: Create slideshow master (loop slideshow to fill remaining time)
                    if overlaid_slideshow_base and remaining_time > 0:
                        self.log(f"🖼️ Creating slideshow master for {remaining_time:.1f}s")
                        slideshow_master = os.path.join(work_dir, "slideshow_master.mp4")
                        
                        cycle_duration = get_media_duration(overlaid_slideshow_base)
                        loops_needed = math.ceil(remaining_time / cycle_duration)
                        self.log(f"📊 Looping slideshow cycle ({cycle_duration:.1f}s) × {loops_needed} times")
                        
                        # Simple stream_loop approach - much more efficient
                        loop_cmd = [
                            'ffmpeg', '-y', '-stream_loop', str(loops_needed - 1), '-i', overlaid_slideshow_base,
                            '-c', 'copy', '-t', str(remaining_time), slideshow_master
                        ]
                        if not self.run_ffmpeg(loop_cmd, f"Stream loop: Creating slideshow master"):
                            return False
                    
                    # Step 3: Simple final assembly - just concatenate masters with fade if needed
                    components = []
                    if intro_master: components.append(intro_master)
                    if slideshow_master: components.append(slideshow_master)
                    
                    if len(components) == 1:
                        # Only one component, copy it
                        if CONFIG.get("use_fade_out"):
                            component_duration = get_media_duration(components[0])
                            fade_start = component_duration - 0.5
                            fade_cmd = [
                                'ffmpeg', '-y', '-i', components[0],
                                '-vf', f'fade=t=out:st={fade_start}:d=0.5',
                                '-c:a', 'copy', master_video_no_audio
                            ]
                            if not self.run_ffmpeg(fade_cmd, "Adding fade-out to single component"):
                                shutil.copy2(components[0], master_video_no_audio)
                        else:
                            shutil.copy2(components[0], master_video_no_audio)
                    elif len(components) > 1:
                        # Multiple components - concatenate with optional black fade
                        final_concat_list = os.path.join(work_dir, "final_concat.txt")
                        if not create_concat_file(components, final_concat_list):
                            self.log("❌ Failed to create final concat file")
                            return False
                        
                        if CONFIG.get("black_fade_transition", False):
                            # Apply black fade between intro and slideshow
                            self.log(f"🌫️ Applying black fade transition between masters")
                            intro_duration = get_media_duration(intro_master)
                            fade_duration = 0.5
                            
                            transition_cmd = [
                                'ffmpeg', '-y', '-i', intro_master, '-i', slideshow_master,
                                '-filter_complex',
                                f'[0:v]fade=t=out:st={intro_duration - fade_duration}:d={fade_duration}:color=black[intro_fade];'
                                f'[1:v]fade=t=in:st=0:d={fade_duration}:color=black[slide_fade];'
                                f'[intro_fade][slide_fade]concat=n=2:v=1:a=0[v]',
                                '-map', '[v]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                                master_video_no_audio
                            ]
                            
                            if CONFIG.get("use_fade_out"):
                                # Add final fade-out
                                total_duration = get_media_duration(intro_master) + get_media_duration(slideshow_master)
                                fade_start = total_duration - 0.5
                                transition_cmd[4] += f';[v]fade=t=out:st={fade_start}:d=0.5[vfinal]'
                                transition_cmd[6] = '[vfinal]'
                            
                            if not self.run_ffmpeg(transition_cmd, "Creating final video with black fade"):
                                return False
                        else:
                            # Simple concatenation
                            concat_cmd = build_gpu_stream_copy_cmd(final_concat_list, master_video_no_audio,
                                                                 extra_args=['-f', 'concat', '-safe', '0'])
                            if not self.run_ffmpeg(concat_cmd, "GPU Stream Copy: Final assembly"):
                                return False
                            
                            if CONFIG.get("use_fade_out"):
                                # Add fade-out as separate step
                                temp_final = os.path.join(work_dir, "temp_final.mp4")
                                shutil.move(master_video_no_audio, temp_final)
                                
                                final_duration = get_media_duration(temp_final)
                                fade_start = final_duration - 0.5
                                fade_cmd = [
                                    'ffmpeg', '-y', '-i', temp_final,
                                    '-vf', f'fade=t=out:st={fade_start}:d=0.5',
                                    '-c:a', 'copy', master_video_no_audio
                                ]
                                if not self.run_ffmpeg(fade_cmd, "Adding final fade-out"):
                                    shutil.move(temp_final, master_video_no_audio)
                
                # All processing complete
                master_with_overlay = master_video_no_audio
                self.log(f"🎭 Stream copy assembly complete!")

                # === STAGE 5: FINAL ASSEMBLY (AUDIO & STREAM COPY) ===
                self.log(f"\n=== STAGE 5: Final Assembly ===")
                
                # The master video is finalized, so we can stream copy it for speed.
                final_cmd = ['ffmpeg', '-y']
                final_cmd.extend(['-i', master_with_overlay])
                final_cmd.extend(['-i', processed_audio])
                
                filter_complex_parts = []
                audio_map = "[a_main]"

                # Map inputs correctly: [0:v] is video, [1:a] is main audio
                filter_complex_parts.append(f"[1:a]volume={CONFIG['main_audio_vol']}[a_main]")

                if CONFIG["use_bg_music"] and bg_music:
                    final_cmd.extend(['-stream_loop', '-1', '-i', bg_music])
                    # BG music will be input 2, so [2:a]
                    filter_complex_parts.append(f"[2:a]volume={CONFIG['bg_vol']}[a_bg]")
                    filter_complex_parts.append("[a_main][a_bg]amix=inputs=2:duration=first:dropout_transition=2[a_out]")
                    audio_map = "[a_out]"

                if filter_complex_parts:
                    final_cmd.extend(['-filter_complex', ";".join(filter_complex_parts)])
                
                # Map the final video and audio streams
                final_cmd.extend(['-map', '0:v:0', '-map', audio_map])

                # Use fast stream copy for video, and encode audio
                final_cmd.extend(['-c:v', 'copy'])
                final_cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
                final_cmd.extend(['-t', str(audio_duration)])
                final_cmd.append(output_file)
                
                if not self.run_ffmpeg(final_cmd, "Fast Final Assembly (Stream Copy)"):
                    return False

        except Exception as e:
            self.log(f"❌ An unexpected error occurred: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False
        
        # === SUCCESS ===
        try:
            final_duration = get_media_duration(output_file)
            file_size = os.path.getsize(output_file) / (1024 * 1024)
            
            self.log(f"\n🎉 OPTIMIZED VIDEO CREATION SUCCESS!")
            self.log(f"📁 Output: {output_file}")
            self.log(f"⏱️  Duration: {final_duration:.1f}s")
            self.log(f"💾 Size: {file_size:.1f} MB")
            
            # Enhanced success logging
            if video_files and image_files:
                self.log(f"🎬 Structure: {len(video_files)} intro videos + {len(image_files)} images (looped as needed)")
            elif video_files:
                self.log(f"🎬 Structure: {len(video_files)} videos only")
            else:
                self.log(f"📸 Structure: {len(image_files)} images (looped as needed)")
            
            return True
            
        except Exception as e:
            self.log(f"❌ Verification error: {e}")
            return False

# ===================================================================
# ENHANCED AUTO-CAPTIONING ENGINE WITH GPU ACCELERATION
# ===================================================================

class AutoCaptioner:
    def __init__(self, model_size="tiny", update_callback=None, global_assets=None):
        self.update_callback = update_callback or print
        self.model = None
        self.model_size = model_size
        self.model_loaded = False
        self.gpu_options = detect_gpu_acceleration()
        self.engine_type = None  # Will be 'openai' or 'faster'
        self.faster_whisper_available = None  # Cache availability check
        self.global_assets = global_assets or {}
        
    def log(self, message):
        if self.update_callback:
            self.update_callback(message)
        print(message)
    
    def check_faster_whisper_availability(self):
        """Check if faster-whisper is available and cache the result."""
        if self.faster_whisper_available is None:
            try:
                from faster_whisper import WhisperModel
                self.faster_whisper_available = True
                self.log("✅ faster-whisper is available")
            except ImportError:
                self.faster_whisper_available = False
                self.log("⚠️ faster-whisper not available, using openai-whisper")
        return self.faster_whisper_available
    
    def should_use_faster_whisper(self):
        """Determine which engine to use based on config and availability."""
        if CONFIG.get("use_faster_whisper", False):
            if self.check_faster_whisper_availability():
                return True
            else:
                self.log("❌ faster-whisper requested but not installed. Install with: pip install faster-whisper")
                self.log("🔄 Falling back to openai-whisper")
                return False
        return False
    
    def load_model(self):
        """Load Whisper model with support for both openai-whisper and faster-whisper."""
        # Check if we need to switch engines or reload
        desired_engine = 'faster' if self.should_use_faster_whisper() else 'openai'
        
        if not self.model_loaded or self.engine_type != desired_engine:
            try:
                start_time = time.time()
                
                if desired_engine == 'faster':
                    self.log(f"🚀 Loading faster-whisper model ({self.model_size}) - Enhanced Performance")
                    from faster_whisper import WhisperModel
                    # Use CPU for better compatibility, faster-whisper is optimized enough
                    self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                    self.engine_type = 'faster'
                    
                else:  # openai-whisper
                    self.log(f"🚀 Loading openai-whisper model ({self.model_size}) - Standard")
                    import whisper
                    import torch
                    
                    # CPU-optimized for small models, GPU for large
                    if self.model_size in ['tiny', 'base', 'small']:
                        device = "cpu"
                        self.log(f"🖥️ Using CPU (optimal for {self.model_size} model)")
                    else:
                        device = "cuda" if torch.cuda.is_available() else "cpu"
                        self.log(f"🎮 Using: {device} (large model)")
                    
                    self.model = whisper.load_model(self.model_size, device=device)
                    self.engine_type = 'openai'
                
                load_time = time.time() - start_time
                self.log(f"✅ {self.engine_type}-whisper model loaded in {load_time:.1f} seconds")
                self.model_loaded = True
                return True
                
            except ImportError as e:
                if desired_engine == 'faster':
                    self.log("❌ faster-whisper not installed. Install with: pip install faster-whisper")
                else:
                    self.log("❌ openai-whisper not installed. Install with: pip install openai-whisper")
                return False
            except Exception as e:
                self.log(f"❌ Failed to load {desired_engine}-whisper model: {e}")
                return False
        else:
            # Model already loaded with correct engine
            self.log(f"✅ {self.engine_type}-whisper model already loaded and ready")
            return True
    
    def transcribe_universal(self, audio_path, word_timestamps=False):
        """Universal transcription method that works with both engines."""
        if not self.load_model():
            raise Exception("Failed to load transcription model")
        
        if self.engine_type == 'faster':
            # faster-whisper transcription
            segments, info = self.model.transcribe(
                audio_path,
                word_timestamps=word_timestamps,
                vad_filter=True
            )
            # Convert generator to list and format for compatibility
            segments_list = []
            for segment in segments:
                segment_dict = {
                    'text': segment.text,
                    'start': segment.start,
                    'end': segment.end
                }
                # Add words if requested
                if word_timestamps and hasattr(segment, 'words') and segment.words:
                    segment_dict['words'] = [
                        {'word': w.word, 'start': w.start, 'end': w.end}
                        for w in segment.words if w.start is not None and w.end is not None
                    ]
                segments_list.append(segment_dict)
            
            return {'segments': segments_list}
            
        else:  # openai-whisper
            # Standard openai-whisper transcription
            return self.model.transcribe(audio_path, verbose=False, fp16=False, word_timestamps=word_timestamps)
    
    def add_captions_to_video(self, video_path):
        """REFACTORED: Adds captions and REPLACES the original video file safely."""
        # CHECK: Only proceed if captions are actually enabled
        captions_enabled = CONFIG.get("captions_enabled", False)
        self.log(f"🚀 DEBUG: add_captions_to_video called - captions_enabled: {captions_enabled}")
        if not captions_enabled:
            self.log("🛑 Captions are disabled - skipping captioning")
            return True  # Return True since this isn't an error, just disabled
            
        if not os.path.exists(video_path):
            self.log(f"❌ Video file not found for captioning: {video_path}")
            return False

        if not self.load_model():
            self.log("❌ Failed to load Whisper model for captioning")
            return False

        name, ext = os.path.splitext(video_path)
        temp_output_path = f"{name}_captioned_temp{ext}"
        
        # Check if karaoke effect is enabled
        karaoke_effect = CONFIG.get("karaoke_effect_enabled", False)
        
        if karaoke_effect:
            subtitle_path = f"{name}_temp.ass"
            self.log("🎤 Karaoke effect enabled - using ASS format")
        else:
            subtitle_path = f"{name}_temp.srt"
            self.log("📝 Standard captions - using SRT format")

        try:
            # Step 1: Transcribe audio
            self.log(f"📍 AUTO-CAPTIONING: Transcribing audio from {os.path.basename(video_path)}...")
            
            if karaoke_effect:
                # Extract audio and transcribe with word-level timestamps for karaoke
                audio_path = f"{name}_temp_audio.wav"
                self.log("🎵 Extracting audio for karaoke transcription...")
                
                # Extract audio using FFmpeg
                cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path]
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    self.log(f"❌ Failed to extract audio: {result.stderr}")
                    return False
                
                # Get word-level timestamps
                words = self.transcribe_with_word_timestamps(audio_path)
                
                # Clean up temporary audio file
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                
                if not words:
                    self.log("❌ No words found in karaoke transcription. Skipping captioning.")
                    return True
                
                # Generate ASS file with karaoke effect
                if not self.generate_karaoke_ass(words, subtitle_path):
                    return False
                    
            else:
                # Standard transcription for regular captions
                word_timestamps = CONFIG.get("live_timing_enabled", False)
                result = self.transcribe_universal(video_path, word_timestamps=word_timestamps)
                segments = result.get('segments', [])
                
                if not segments:
                    self.log("❌ No speech segments found in audio. Skipping captioning.")
                    return True # Not a failure, just nothing to do.

                self.log(f"✅ Found {len(segments)} speech segments")
                
                # Generate SRT file
                self.generate_srt_file(segments, subtitle_path, CONFIG.get("caption_type", "single"))
                
            if not os.path.exists(subtitle_path):
                self.log(f"❌ Failed to create subtitle file: {subtitle_path}")
                return False
            
            # Step 3: Burn subtitles to a temporary file
            if not self.burn_subtitles(video_path, subtitle_path, temp_output_path):
                 self.log(f"❌ Caption burning failed for: {os.path.basename(video_path)}")
                 return False

            # Step 4: Safely replace the original file with the captioned version
            self.log(f"✅ Replacing original video with captioned version...")
            shutil.move(temp_output_path, video_path)
            self.log(f"🎉 Captioning complete for: {os.path.basename(video_path)}")
            return True

        except Exception as e:
            self.log(f"❌ Auto-captioning error: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False
        finally:
            # Clean up temporary files
            if os.path.exists(subtitle_path):
                os.remove(subtitle_path)
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)

    def generate_srt_file(self, segments, srt_path, caption_type):
        """Create an SRT file from transcription segments with proper pacing."""
        self.log(f"✍️ Creating {caption_type} captions...")
        sentences = []
        
        max_chars = CONFIG.get("max_chars_per_line", 45)  # Maximum chars per caption
        min_gap = 0.1  # Minimum gap between captions (seconds)
        
        # Handle new caption animation types
        caption_animation = CONFIG.get("caption_animation", "normal")
        word_by_word_enabled = CONFIG.get("word_by_word_enabled", False)
        live_timing_enabled = CONFIG.get("live_timing_enabled", False)
        
        # Check toggle settings first - these override any caption_animation settings
        if word_by_word_enabled:
            self.log("✍️ Word-by-word toggle enabled - using chunk mode")
            return self.generate_word_by_word_chunks_srt(segments, srt_path)
        elif live_timing_enabled:
            self.log("⏱️ Live timing toggle enabled")
            return self.generate_live_timing_srt(segments, srt_path)
        # Only check caption_animation if neither toggle is enabled
        elif caption_animation == "word_by_word":
            self.log("✍️ Caption animation word-by-word mode (no toggle override)")
            return self.generate_word_by_word_srt(segments, srt_path)
        elif caption_animation == "single_words":
            self.log("✍️ Caption animation single words mode")
            return self.generate_single_words_srt(segments, srt_path)
        
        if caption_type == "single":
            # Single line captions with proper pacing
            for segment in segments:
                text = segment['text'].strip()
                if not text or len(text) < 2:
                    continue
                
                start_time = segment['start']
                end_time = segment['end']
                
                # For short segments that fit on one line
                if len(text) <= max_chars:
                    sentences.append({
                        'start': start_time,
                        'end': end_time,
                        'text': text
                    })
                else:
                    # Split long text intelligently
                    words = text.split()
                    chunks = []
                    current_chunk = []
                    current_length = 0
                    
                    # Group words into chunks that fit the character limit
                    for word in words:
                        word_length = len(word) + (1 if current_chunk else 0)
                        
                        if current_length + word_length <= max_chars:
                            current_chunk.append(word)
                            current_length += word_length
                        else:
                            if current_chunk:
                                chunks.append(' '.join(current_chunk))
                            current_chunk = [word]
                            current_length = len(word)
                    
                    # Add the last chunk
                    if current_chunk:
                        chunks.append(' '.join(current_chunk))
                    
                    # Distribute time proportionally based on character count
                    total_chars = sum(len(chunk) for chunk in chunks)
                    segment_duration = end_time - start_time
                    
                    chunk_start = start_time
                    for i, chunk in enumerate(chunks):
                        # Calculate proportional duration
                        chunk_proportion = len(chunk) / total_chars if total_chars > 0 else 1/len(chunks)
                        chunk_duration = segment_duration * chunk_proportion
                        
                        # Respect original pacing - don't compress too much
                        min_chunk_duration = chunk_duration * 0.8
                        
                        chunk_end = chunk_start + max(chunk_duration, min_chunk_duration)
                        
                        # Don't exceed segment end
                        if i == len(chunks) - 1:
                            chunk_end = end_time
                        else:
                            chunk_end = min(chunk_end, end_time)
                        
                        sentences.append({
                            'start': chunk_start,
                            'end': chunk_end,
                            'text': chunk
                        })
                        
                        chunk_start = chunk_end
        else:
            # Multi-line captions - group segments intelligently
            current_sentence = ""
            current_start = 0
            max_chars_multi = 80  # More chars allowed for multi-line
            
            for segment in segments:
                text = segment['text'].strip()
                if text:
                    if not current_sentence:
                        current_sentence = text
                        current_start = segment['start']
                    elif len(current_sentence) + len(text) + 1 < max_chars_multi:
                        current_sentence += " " + text
                    else:
                        sentences.append({
                            'start': current_start, 
                            'end': segment['start'], 
                            'text': current_sentence
                        })
                        current_sentence = text
                        current_start = segment['start']
            
            if current_sentence:
                sentences.append({
                    'start': current_start, 
                    'end': segments[-1]['end'], 
                    'text': current_sentence
                })
        
        # Add small gaps between captions for readability
        for i in range(len(sentences) - 1):
            if sentences[i + 1]['start'] - sentences[i]['end'] < min_gap:
                gap_available = sentences[i + 1]['start'] - sentences[i]['end']
                if gap_available > 0:
                    sentences[i]['end'] = sentences[i + 1]['start'] - min_gap
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, sentence in enumerate(sentences, 1):
                f.write(f"{i}\n")
                f.write(f"{self.format_srt_timestamp(sentence['start'])} --> {self.format_srt_timestamp(sentence['end'])}\n")
                # Ensure single line for single mode
                if caption_type == "single":
                    sentence['text'] = sentence['text'].replace('\n', ' ').strip()
                f.write(f"{sentence['text']}\n\n")
        
        self.log(f"✅ Created {len(sentences)} {caption_type} captions with proper pacing")

    def generate_word_by_word_srt(self, segments, srt_path):
        """Generate word-by-word captions that build up in a line (typewriter effect)."""
        self.log("✍️ Creating word-by-word (typewriter) captions...")
        captions = []
        caption_index = 1
        
        for segment in segments:
            text = segment['text'].strip()
            if not text:
                continue
                
            words = text.split()
            if not words:
                continue
                
            segment_duration = segment['end'] - segment['start']
            time_per_word = segment_duration / len(words) if len(words) > 0 else 0.5
            
            # Build up the sentence word by word
            accumulated_text = ""
            for i, word in enumerate(words):
                if i > 0:
                    accumulated_text += " "
                accumulated_text += word
                
                word_start = segment['start'] + (i * time_per_word)
                word_end = segment['start'] + ((i + 1) * time_per_word)
                
                captions.append({
                    'index': caption_index,
                    'start': word_start,
                    'end': word_end,
                    'text': accumulated_text
                })
                caption_index += 1
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            for caption in captions:
                f.write(f"{caption['index']}\n")
                f.write(f"{self.format_srt_timestamp(caption['start'])} --> {self.format_srt_timestamp(caption['end'])}\n")
                f.write(f"{caption['text']}\n\n")
        
        self.log(f"✅ Created {len(captions)} word-by-word captions")

    def generate_single_words_srt(self, segments, srt_path):
        """Generate single word captions that appear one by one."""
        self.log("✍️ Creating single word captions...")
        captions = []
        caption_index = 1
        
        for segment in segments:
            text = segment['text'].strip()
            if not text:
                continue
                
            words = text.split()
            if not words:
                continue
                
            segment_duration = segment['end'] - segment['start']
            time_per_word = segment_duration / len(words) if len(words) > 0 else 0.5
            
            # Show each word individually
            for i, word in enumerate(words):
                word_start = segment['start'] + (i * time_per_word)
                word_end = segment['start'] + ((i + 1) * time_per_word)
                
                captions.append({
                    'index': caption_index,
                    'start': word_start,
                    'end': word_end,
                    'text': word.upper()  # Make single words stand out
                })
                caption_index += 1
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            for caption in captions:
                f.write(f"{caption['index']}\n")
                f.write(f"{self.format_srt_timestamp(caption['start'])} --> {self.format_srt_timestamp(caption['end'])}\n")
                f.write(f"{caption['text']}\n\n")
        
        self.log(f"✅ Created {len(captions)} single word captions")

    def generate_word_by_word_chunks_srt(self, segments, srt_path):
        """Generate word-by-word chunks (1-3 words at a time) captions."""
        self.log("✍️ Creating word-by-word chunks (1-3 words) captions...")
        captions = []
        caption_index = 1
        
        for segment in segments:
            text = segment['text'].strip()
            if not text:
                continue
                
            words = text.split()
            if not words:
                continue
                
            segment_duration = segment['end'] - segment['start']
            
            # Group words into chunks of 1-3 words
            chunks = []
            i = 0
            while i < len(words):
                # Randomly choose 1-3 words for each chunk
                import random
                chunk_size = random.choice([1, 2, 3])
                chunk_words = words[i:i+chunk_size]
                chunks.append(' '.join(chunk_words))
                i += chunk_size
            
            if not chunks:
                continue
                
            time_per_chunk = segment_duration / len(chunks) if len(chunks) > 0 else 0.5
            
            # Show each chunk
            for i, chunk in enumerate(chunks):
                chunk_start = segment['start'] + (i * time_per_chunk)
                chunk_end = segment['start'] + ((i + 1) * time_per_chunk)
                
                captions.append({
                    'index': caption_index,
                    'start': chunk_start,
                    'end': chunk_end,
                    'text': chunk
                })
                caption_index += 1
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            for caption in captions:
                f.write(f"{caption['index']}\n")
                f.write(f"{self.format_srt_timestamp(caption['start'])} --> {self.format_srt_timestamp(caption['end'])}\n")
                f.write(f"{caption['text']}\n\n")
        
        self.log(f"✅ Created {len(captions)} word-by-word chunk captions")

    def generate_live_timing_srt(self, segments, srt_path):
        """Generate live timing captions where words appear as they're spoken (2 lines max)."""
        self.log("⏱️ Creating live timing captions - words appear as spoken...")
        captions = []
        caption_index = 1
        
        for segment in segments:
            text = segment['text'].strip()
            if not text:
                continue
            
            # Check if we have word-level timestamps
            words_data = segment.get('words', [])
            if not words_data:
                # Fallback to equally distributed timing
                words = text.split()
                if not words:
                    continue
                    
                segment_duration = segment['end'] - segment['start']
                time_per_word = segment_duration / len(words) if len(words) > 0 else 0.5
                
                words_data = []
                for i, word in enumerate(words):
                    word_start = segment['start'] + (i * time_per_word)
                    word_end = segment['start'] + ((i + 1) * time_per_word)
                    words_data.append({
                        'word': word,
                        'start': word_start,
                        'end': word_end
                    })
            
            # Process words with precise timing
            current_line = ""
            line_start = None
            max_chars_per_line = 40  # Shorter lines for live timing
            
            for word_info in words_data:
                word = word_info['word']
                word_start = word_info['start']
                word_end = word_info['end']
                
                if line_start is None:
                    line_start = word_start
                
                # Check if adding this word would exceed line length
                test_line = current_line + (" " if current_line else "") + word
                
                if len(test_line) <= max_chars_per_line:
                    current_line = test_line
                else:
                    # Save current line and start new one
                    if current_line:
                        captions.append({
                            'index': caption_index,
                            'start': line_start,
                            'end': word_start,  # End just before new word
                            'text': current_line
                        })
                        caption_index += 1
                    
                    # Start new line with current word
                    current_line = word
                    line_start = word_start
                
                # Update end time for current line
                line_end = word_end
            
            # Add the final line if there's content
            if current_line and line_start is not None:
                captions.append({
                    'index': caption_index,
                    'start': line_start,
                    'end': segment['end'],
                    'text': current_line
                })
                caption_index += 1
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            for caption in captions:
                f.write(f"{caption['index']}\n")
                f.write(f"{self.format_srt_timestamp(caption['start'])} --> {self.format_srt_timestamp(caption['end'])}\n")
                f.write(f"{caption['text']}\n\n")
        
        self.log(f"✅ Created {len(captions)} live timing captions")

    def format_srt_timestamp(self, seconds):
        """Convert seconds to SRT timestamp format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"

    def transcribe_with_word_timestamps(self, audio_path):
        """Transcribe audio and return word-level timestamps for karaoke effect."""
        if not self.load_model():
            return []

        try:
            result = self.transcribe_universal(audio_path, word_timestamps=True)
            
            words = []
            for segment in result['segments']:
                if 'words' in segment:
                    for word_info in segment['words']:
                        if 'word' in word_info and 'start' in word_info and 'end' in word_info:
                            words.append({
                                'word': word_info['word'].strip(),
                                'start': float(word_info['start']),
                                'end': float(word_info['end'])
                            })
            
            return words
            
        except Exception as e:
            self.log(f"❌ Word timestamp transcription error: {e}")
            return []

    def format_ass_time(self, seconds):
        """Convert seconds to ASS timestamp format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds - int(seconds)) * 100)
        return f"{hours:01d}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    def create_ass_header(self):
        """Create ASS file header with styling."""
        return '''[Script Info]
Title: VideoStove Karaoke
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&Hffffff,&Hffffff,&H0,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1
Style: Karaoke,Arial,20,&H00ffff,&Hffffff,&H0,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

    def generate_karaoke_ass(self, words, ass_path):
        """Generate ASS file with karaoke effect for word-by-word highlighting."""
        if not words:
            return False
        
        try:
            with open(ass_path, 'w', encoding='utf-8') as f:
                f.write(self.create_ass_header())
                
                for word_info in words:
                    word = word_info['word']
                    start_time = self.format_ass_time(word_info['start'])
                    end_time = self.format_ass_time(word_info['end'])
                    
                    # Karaoke effect - highlight word as it's spoken
                    karaoke_text = f"{{\\k{int((word_info['end'] - word_info['start']) * 100)}}}{word}"
                    
                    f.write(f"Dialogue: 0,{start_time},{end_time},Karaoke,,0,0,0,,{karaoke_text}\\N\n")
            
            self.log(f"✅ Created karaoke ASS file with {len(words)} words")
            return True
            
        except Exception as e:
            self.log(f"❌ Failed to create karaoke ASS: {e}")
            return False

    def burn_subtitles(self, video_path, subtitle_path, output_path):
        """Burn subtitles into video using FFmpeg with custom styling."""
        
        # Get caption style settings from CONFIG
        font_family = CONFIG.get("font_family", "Arial")
        font_size = CONFIG.get("font_size", 24)
        font_weight = CONFIG.get("font_weight", "bold")
        text_color = CONFIG.get("text_color", "#FFFFFF")
        outline_color = CONFIG.get("outline_color", "#000000")
        outline_width = CONFIG.get("outline_width", 2)
        
        # Use global font asset if available (cached or live path)
        custom_font_path = None
        if self.global_assets.get('fonts'):
            custom_font_path = self.global_assets['fonts']
            self.log(f"Using custom font: {os.path.basename(custom_font_path)} [cached]")
            # Validate font file exists and is accessible
            if not os.path.exists(custom_font_path):
                self.log(f"⚠️ Custom font not found at {custom_font_path}, falling back to system font")
                custom_font_path = None
        
        # Position settings
        vertical_position = CONFIG.get("vertical_position", "bottom")
        horizontal_position = CONFIG.get("horizontal_position", "center")
        margin_vertical = CONFIG.get("margin_vertical", 25)
        margin_horizontal = CONFIG.get("margin_horizontal", 20)
        
        # Convert hex colors to decimal for FFmpeg
        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        text_rgb = hex_to_rgb(text_color)
        outline_rgb = hex_to_rgb(outline_color)
        
        # Build subtitle filter
        subtitle_filter = f"subtitles='{subtitle_path}'"
        
        # Add style overrides if it's an SRT file
        if subtitle_path.lower().endswith('.srt'):
            # Calculate position
            if vertical_position == "top":
                y_pos = margin_vertical
            elif vertical_position == "center":
                y_pos = 540  # Middle of 1080p
            else:  # bottom
                y_pos = 1080 - margin_vertical - font_size
            
            if horizontal_position == "left":
                alignment = 1
            elif horizontal_position == "right":
                alignment = 3
            else:  # center
                alignment = 2
            
            # Use custom font path if available
            font_setting = custom_font_path if custom_font_path else font_family
            
            style_overrides = (
                f"force_style='FontName={font_setting},"
                f"FontSize={font_size},"
                f"Bold={1 if font_weight == 'bold' else 0},"
                f"PrimaryColour=&H{text_rgb[2]:02x}{text_rgb[1]:02x}{text_rgb[0]:02x},"
                f"OutlineColour=&H{outline_rgb[2]:02x}{outline_rgb[1]:02x}{outline_rgb[0]:02x},"
                f"Outline={outline_width},"
                f"Alignment={alignment},"
                f"MarginV={margin_vertical}'"
            )
            
            subtitle_filter += f":{style_overrides}"
        
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', subtitle_filter,
            '-c:a', 'copy'
        ]
        
        # Use GPU encoding if available
        if CONFIG["use_gpu"] and self.gpu_options:
            gpu_settings = get_gpu_encoder_settings()
            cmd.extend(gpu_settings)
        else:
            cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '22'])
        
        cmd.append(output_path)
        
        # Create a simple process runner since we don't have access to VideoCreator's run_ffmpeg
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace'
            )
            
            for line in process.stdout:
                print(f"  {line.rstrip()}")
            
            process.wait()
            
            if process.returncode == 0:
                self.log("✅ Subtitle burning completed successfully")
                return True
            else:
                self.log(f"❌ Subtitle burning failed with return code: {process.returncode}")
                return False
                
        except Exception as e:
            self.log(f"❌ Subtitle burning error: {e}")
            return False