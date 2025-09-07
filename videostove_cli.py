#!/usr/bin/env python3
"""
VideoStove CLI - Command Line Interface Version
GPU-Accelerated Video Automation for Cloud and Headless Environments
"""

import os
import sys
import json
import argparse
import tempfile
import shutil
import subprocess
import threading
import queue
import glob
import datetime
import math
from pathlib import Path

# Keep only the core processing imports
import natsort

# Copy DEFAULT_CONFIG from run-main.py (same config structure)
DEFAULT_CONFIG = {
    "image_duration": 8.0,
    "main_audio_vol": 1.0,
    "bg_vol": 0.15,
    "crossfade_duration": 0.6,
    "use_crossfade": True,
    "use_overlay": False,
    "use_bg_music": True,
    "use_gpu": True,
    "use_fade_in": True,
    "use_fade_out": True,
    "overlay_opacity": 0.5,
    "crf": 22,
    "preset": "fast",
    "project_type": "montage",
    "overlay_mode": "simple",
    "extended_zoom_enabled": False,
    "extended_zoom_direction": "in",
    "extended_zoom_amount": 30,
    "captions_enabled": False,
    "caption_style": "Basic",
    "whisper_model": "base",
    "font_size": 24,
    "font_family": "Arial",
    "font_weight": "bold",
    "text_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 2,
    "vertical_position": "bottom",
    "horizontal_position": "center",
    "margin_vertical": 25,
    "margin_horizontal": 20,
    "animation_style": "Sequential Motion",
    "quality_preset": "High Quality",
    "use_faster_whisper": True,
    "gpu_mode": "auto"
}

CONFIG = DEFAULT_CONFIG.copy()

class CLIVideoStove:
    """Command Line Interface for VideoStove"""
    
    def __init__(self, config_file=None, verbose=False):
        self.verbose = verbose
        self.config = CONFIG.copy()
        self.work_dir = None
        
        if config_file and os.path.exists(config_file):
            self.load_config(config_file)
    
    def log(self, message, force=False):
        """Log message with timestamp"""
        if self.verbose or force:
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            print(f"[{timestamp}] {message}")
    
    def load_config(self, config_file):
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                data = json.load(f)
            
            # Handle different config formats
            if 'settings' in data:
                # Full config export format
                settings = data['settings']
            elif 'presets' in data:
                # Preset collection format - use first preset
                presets = data['presets']
                settings = next(iter(presets.values())) if presets else {}
            else:
                # Direct settings format
                settings = data
            
            # Update config with loaded settings
            for key, value in settings.items():
                if key in DEFAULT_CONFIG:
                    self.config[key] = value
                    CONFIG[key] = value
            
            self.log(f"Loaded {len(settings)} settings from {config_file}", force=True)
            
        except Exception as e:
            self.log(f"Error loading config: {e}", force=True)
    
    def scan_directory_for_projects(self, directory):
        """Scan directory for VideoStove projects"""
        projects = []
        
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                if os.path.isdir(item_path):
                    project = self.analyze_project_folder(item_path, item)
                    if project:
                        projects.append(project)
            
            return sorted(projects, key=lambda x: x['name'])
            
        except Exception as e:
            self.log(f"Error scanning directory: {e}", force=True)
            return []
    
    def analyze_project_folder(self, folder_path, folder_name):
        """Analyze a folder to determine if it's a valid project"""
        try:
            files = os.listdir(folder_path)
            
            # Categorize files
            images = []
            videos = []
            audio_files = []
            
            image_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')
            video_exts = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.flv')
            audio_exts = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg')
            
            for file in files:
                file_path = os.path.join(folder_path, file)
                if os.path.isfile(file_path):
                    file_lower = file.lower()
                    
                    if file_lower.endswith(image_exts):
                        images.append(file_path)
                    elif file_lower.endswith(video_exts):
                        # Skip overlay videos
                        if not any(keyword in file_lower for keyword in ['overlay', 'effect', 'particle']):
                            videos.append(file_path)
                    elif file_lower.endswith(audio_exts):
                        audio_files.append(file_path)
            
            # Sort files naturally
            images = natsort.natsorted(images)
            videos = natsort.natsorted(videos)
            audio_files = natsort.natsorted(audio_files)
            
            # Validate project (needs audio and either images or videos)
            if audio_files and (images or videos):
                return {
                    'name': folder_name,
                    'path': folder_path,
                    'images': images,
                    'videos': videos,
                    'audio': audio_files[0],
                    'bg_music': audio_files[1] if len(audio_files) > 1 else None,
                    'type': self.determine_project_type(images, videos)
                }
            
            return None
            
        except Exception as e:
            self.log(f"Error analyzing folder {folder_name}: {e}")
            return None
    
    def determine_project_type(self, images, videos):
        """Determine project type based on content"""
        if videos and images:
            return "mixed"
        elif videos:
            return "videos_only"
        else:
            return "slideshow"
    
    def process_single_project(self, project_folder, output_file, config_file=None, assets=None):
        """Process a single project folder"""
        self.log(f"Processing single project: {project_folder}", force=True)
        
        # Load config if provided
        if config_file:
            self.load_config(config_file)
        
        # Validate assets if provided
        validated_assets = {}
        if assets:
            from config_manager import ConfigManager
            config_mgr = ConfigManager()
            validated_assets = config_mgr.validate_asset_paths(assets)
            if validated_assets:
                self.log(f"Using assets: {', '.join(validated_assets.keys())}", force=True)
        
        # Analyze project
        project_name = os.path.basename(project_folder)
        project = self.analyze_project_folder(project_folder, project_name)
        
        if not project:
            self.log("Invalid project folder", force=True)
            return False
        
        self.log(f"Project type: {project['type']}", force=True)
        self.log(f"Images: {len(project['images'])}, Videos: {len(project['videos'])}", force=True)
        
        # Import and use VideoCreator
        from videostove_core import VideoCreator
        creator = VideoCreator(update_callback=self.log, global_assets=validated_assets)
        
        # Process project
        success = creator.create_slideshow(
            image_files=project['images'],
            video_files=project['videos'],
            main_audio=project['audio'],
            bg_music=project.get('bg_music'),
            overlay_video=None,
            output_file=output_file
        )
        
        if success:
            self.log(f"✅ Successfully created: {output_file}", force=True)
        else:
            self.log("❌ Processing failed", force=True)
        
        return success
    
    def process_batch(self, source_folder, output_folder, config_file=None, assets=None):
        """Process multiple projects in batch"""
        self.log(f"Starting batch processing", force=True)
        self.log(f"Source: {source_folder}", force=True)
        self.log(f"Output: {output_folder}", force=True)
        
        # Load config if provided
        if config_file:
            self.load_config(config_file)
        
        # Validate assets if provided
        validated_assets = {}
        if assets:
            from config_manager import ConfigManager
            config_mgr = ConfigManager()
            validated_assets = config_mgr.validate_asset_paths(assets)
            if validated_assets:
                self.log(f"Using assets: {', '.join(validated_assets.keys())}", force=True)
        
        # Scan for projects
        projects = self.scan_directory_for_projects(source_folder)
        
        if not projects:
            self.log("No valid projects found", force=True)
            return False
        
        self.log(f"Found {len(projects)} projects to process", force=True)
        
        # Create output directory
        os.makedirs(output_folder, exist_ok=True)
        
        # Process each project
        successful = 0
        failed = 0
        
        from videostove_core import VideoCreator
        creator = VideoCreator(update_callback=self.log, global_assets=validated_assets)
        
        for i, project in enumerate(projects, 1):
            self.log(f"\nProcessing {i}/{len(projects)}: {project['name']}", force=True)
            
            try:
                output_file = os.path.join(output_folder, f"{project['name']}.mp4")
                
                success = creator.create_slideshow(
                    image_files=project['images'],
                    video_files=project['videos'],
                    main_audio=project['audio'],
                    bg_music=project.get('bg_music'),
                    overlay_video=None,
                    output_file=output_file
                )
                
                if success:
                    self.log(f"✅ Success: {project['name']}", force=True)
                    successful += 1
                else:
                    self.log(f"❌ Failed: {project['name']}", force=True)
                    failed += 1
                    
            except Exception as e:
                self.log(f"❌ Error processing {project['name']}: {e}", force=True)
                failed += 1
        
        self.log(f"\nBatch processing complete!", force=True)
        self.log(f"Successful: {successful}, Failed: {failed}", force=True)
        
        return successful > 0

def handle_cache_command(args):
    """Handle cache management commands"""
    from asset_cache import AssetCache
    
    if not args.cache_command:
        print("Cache command required. Use --help for options.")
        return 1
    
    cache = AssetCache()
    
    if args.cache_command == 'status':
        status = cache.get_cache_status()
        print("Asset Cache Status")
        print("=" * 50)
        print(f"Cache exists: {status['cache_exists']}")
        print(f"Assets cached: {status['assets_cached']}")
        print(f"Total assets: {status['total_assets']}")
        print(f"Cache size: {status['cache_size_bytes'] / 1024 / 1024:.1f} MB")
        print(f"Last updated: {status['last_updated'] or 'Never'}")
        print(f"Asset breakdown: {status['asset_breakdown']}")
        
    elif args.cache_command == 'clear':
        cache.clear_cache()
        
    elif args.cache_command == 'validate':
        validation = cache.validate_cache_integrity()
        print("Cache Validation Results")
        print("=" * 50)
        print(f"Valid: {validation['valid']}")
        print(f"Assets checked: {validation['assets_checked']}")
        if validation['issues']:
            print("Issues found:")
            for issue in validation['issues']:
                print(f"  - {issue}")
        
    elif args.cache_command == 'cleanup':
        days = getattr(args, 'days', 30)
        cache.cleanup_old_cache(days)
    
    return 0

def create_argument_parser():
    """Create command line argument parser"""
    parser = argparse.ArgumentParser(
        description='VideoStove CLI - GPU-Accelerated Video Automation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single project
  python videostove_cli.py single /path/to/project /path/to/output.mp4
  
  # Batch processing
  python videostove_cli.py batch /path/to/projects /path/to/outputs
  
  # With custom config
  python videostove_cli.py single /path/to/project output.mp4 --config my_preset.json
  
  # With custom assets
  python videostove_cli.py batch /path/to/projects /path/to/outputs --font custom.ttf --overlay effect.mp4 --bg-music music.mp3
  
  # Cache management
  python videostove_cli.py cache status
  python videostove_cli.py cache clear
  
  # Verbose output
  python videostove_cli.py batch /path/to/projects /path/to/outputs --verbose
        """
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Single project command
    single_parser = subparsers.add_parser('single', help='Process single project')
    single_parser.add_argument('project_folder', help='Path to project folder')
    single_parser.add_argument('output_file', help='Output video file path')
    single_parser.add_argument('--config', help='Configuration JSON file')
    single_parser.add_argument('--font', help='Custom font file path')
    single_parser.add_argument('--overlay', help='Overlay video file path')
    single_parser.add_argument('--bg-music', help='Background music file path')
    
    # Batch processing command
    batch_parser = subparsers.add_parser('batch', help='Process multiple projects')
    batch_parser.add_argument('source_folder', help='Folder containing project folders')
    batch_parser.add_argument('output_folder', help='Output folder for processed videos')
    batch_parser.add_argument('--config', help='Configuration JSON file')
    batch_parser.add_argument('--font', help='Custom font file path')
    batch_parser.add_argument('--overlay', help='Overlay video file path')
    batch_parser.add_argument('--bg-music', help='Background music file path')
    
    # Cache management commands
    cache_parser = subparsers.add_parser('cache', help='Asset cache management')
    cache_subparsers = cache_parser.add_subparsers(dest='cache_command', help='Cache commands')
    
    cache_subparsers.add_parser('status', help='Show cache status')
    cache_subparsers.add_parser('clear', help='Clear all cache')
    cache_subparsers.add_parser('validate', help='Validate cache integrity')
    
    cleanup_parser = cache_subparsers.add_parser('cleanup', help='Clean old cache entries')
    cleanup_parser.add_argument('--days', type=int, default=30, help='Remove entries older than N days')
    
    # Global options
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--version', action='version', version='VideoStove CLI 1.0')
    
    return parser

def main():
    """Main entry point"""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        # Handle cache commands early (they don't need CLI processor)
        if args.command == 'cache':
            return handle_cache_command(args)
        
        # Initialize CLI processor for other commands
        cli = CLIVideoStove(config_file=getattr(args, 'config', None), verbose=args.verbose)
        
        # Parse asset arguments
        assets = {}
        if hasattr(args, 'font') and args.font:
            assets['fonts'] = args.font
        if hasattr(args, 'overlay') and args.overlay:
            assets['overlays'] = args.overlay  
        if hasattr(args, 'bg_music') and args.bg_music:
            assets['bgmusic'] = args.bg_music
        
        if args.command == 'single':
            success = cli.process_single_project(
                args.project_folder, 
                args.output_file, 
                args.config,
                assets if assets else None
            )
        elif args.command == 'batch':
            success = cli.process_batch(
                args.source_folder, 
                args.output_folder, 
                args.config,
                assets if assets else None
            )
        else:
            parser.print_help()
            return 1
        
        return 0 if success else 1
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 1
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())