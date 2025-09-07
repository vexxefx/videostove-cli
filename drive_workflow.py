#!/usr/bin/env python3
"""
Complete Google Drive VideoStove Workflow
This script handles the full workflow: download, process, upload
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Add source directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))

from drive_integration import DriveVideoStove

def setup_argument_parser():
    """Setup command line argument parser"""
    parser = argparse.ArgumentParser(description='VideoStove Google Drive Workflow')
    
    parser.add_argument('--folder-id', required=True, 
                       help='Google Drive folder ID containing projects and presets')
    parser.add_argument('--output-folder-id', 
                       help='Google Drive folder ID for output videos')
    parser.add_argument('--credentials', default='credentials.json',
                       help='Path to Google Drive credentials file')
    parser.add_argument('--preset-name', 
                       help='Specific preset name to use (skips selection)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Download and analyze but don\'t process')
    parser.add_argument('--keep-workspace', action='store_true',
                       help='Keep temporary workspace after completion')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--force-asset-update', action='store_true',
                       help='Force re-download of assets even if cache is current')
    parser.add_argument('--clear-cache', action='store_true',
                       help='Clear local asset cache before processing')
    
    return parser

class DriveWorkflowRunner:
    """Complete workflow runner for Drive integration"""
    
    def __init__(self, credentials_path, verbose=False):
        self.verbose = verbose
        self.drive_processor = DriveVideoStove(credentials_path)
        self.workspace = None
        self.force_asset_update = False
        
        if not self.drive_processor.service:
            raise Exception("Failed to authenticate with Google Drive")
    
    def log(self, message, force=False):
        """Log message if verbose or forced"""
        if self.verbose or force:
            print(message)
    
    def run_complete_workflow(self, folder_id, output_folder_id=None, 
                            preset_name=None, dry_run=False, keep_workspace=False, 
                            force_asset_update=False, clear_cache=False):
        """Run the complete Drive workflow"""
        
        try:
            # Handle cache commands first
            if clear_cache:
                self.log("Clearing asset cache...", force=True)
                self.drive_processor.asset_cache.clear_cache()
            
            self.force_asset_update = force_asset_update
            
            # Step 1: Setup workspace
            self.log("Setting up workspace...", force=True)
            self.workspace = self.drive_processor.setup_workspace()
            
            # Step 2: Scan Drive folder for projects (assets handled separately)
            self.log(f"Scanning Drive folder: {folder_id}", force=True)
            scan_results = self.drive_processor.scan_drive_folder(folder_id)
            
            if not scan_results:
                raise Exception("Failed to scan Drive folder")
            
            self.log(f"Found: {len(scan_results['projects'])} projects, "
                    f"{len(scan_results['presets'])} presets", force=True)
            
            # Step 3: Ensure assets are available (smart sync)
            available_assets = self._ensure_assets_available(folder_id)
            
            # Step 4: Select preset from cached assets (if available)
            selected_preset = None
            if available_assets.get('presets'):
                selected_preset = self._select_preset_from_cache(available_assets['presets'], preset_name)
            
            # Fallback to regular preset selection if no cached presets
            if not selected_preset:
                if not scan_results['presets']:
                    raise Exception("No presets found in Drive folder or cache")
                
                self.log("Downloading presets...", force=True)
                downloaded_presets = self.drive_processor.download_presets(scan_results['presets'])
                
                if not downloaded_presets:
                    raise Exception("No valid presets found")
                
                selected_preset = self._select_preset(downloaded_presets, preset_name)
                if not selected_preset:
                    raise Exception("No preset selected")
            
            # Step 5: Download projects
            if not scan_results['projects']:
                raise Exception("No projects found in Drive folder")
            
            self.log("Downloading projects...", force=True)
            downloaded_projects = self.drive_processor.download_projects(scan_results['projects'])
            
            if not downloaded_projects:
                raise Exception("No valid projects downloaded")
            
            # Step 6: Load configuration
            self.log("Loading preset configuration...", force=True)
            
            if selected_preset.get('type') == 'cached_preset':
                config = selected_preset.get('config', {})
            else:
                config = self.drive_processor.load_preset_config(selected_preset)
            
            if not config:
                raise Exception("Failed to load preset configuration")
            
            self.log(f"Loaded {len(config)} configuration settings", force=True)
            
            # Step 7: Select assets from cache
            selected_assets = {}
            if available_assets:
                self.log("Assets available for selection...", force=True)
                selected_assets = self._select_assets_from_cache(available_assets)
                self.log(f"Selected {len(selected_assets)} asset types from cache", force=True)
            
            # Step 8: Display summary
            self._display_workflow_summary(downloaded_projects, selected_preset, config, selected_assets)
            
            if dry_run:
                self.log("Dry run mode - stopping before processing", force=True)
                return True
            
            # Step 9: Confirm processing
            if not self._confirm_processing():
                self.log("Processing cancelled by user", force=True)
                return False
            
            # Step 10: Process projects
            self.log("Starting batch processing...", force=True)
            # Convert cached asset paths to the format expected by batch_process_projects
            asset_paths = {}
            for asset_type, asset_info in selected_assets.items():
                if isinstance(asset_info, dict) and 'path' in asset_info:
                    asset_paths[asset_type] = asset_info['path']
                elif isinstance(asset_info, str):
                    asset_paths[asset_type] = asset_info
            
            self.drive_processor.batch_process_projects(config, output_folder_id, asset_paths if asset_paths else None)
            
            self.log("Workflow completed successfully!", force=True)
            return True
            
        except Exception as e:
            self.log(f"Workflow error: {e}", force=True)
            return False
            
        finally:
            if not keep_workspace:
                self.drive_processor.cleanup()
            else:
                self.log(f"Workspace preserved at: {self.workspace}", force=True)
    
    def _select_preset(self, presets, preset_name=None):
        """Select preset either by name or user input"""
        
        if preset_name:
            # Find preset by name
            for preset in presets:
                if preset['name'].lower() == preset_name.lower():
                    self.log(f"Using specified preset: {preset['name']}", force=True)
                    return preset
            
            self.log(f"Preset '{preset_name}' not found", force=True)
            return None
        
        # Interactive selection
        return self.drive_processor.display_preset_selection()
    
    def _select_assets(self, available_assets):
        """Interactive CLI for asset selection"""
        if not available_assets or not any(len(files) > 0 for files in available_assets.values()):
            return {}
        
        print("\nAsset Selection")
        print("=" * 50)
        
        selected_assets = {}
        
        for asset_type in ['fonts', 'overlays', 'bgmusic']:
            files = available_assets.get(asset_type, [])
            if files:
                print(f"\n{asset_type.upper()} Assets Available:")
                selected = self._display_asset_options(asset_type, files)
                if selected and selected != 'skip':
                    selected_assets[asset_type] = selected
            else:
                self.log(f"No {asset_type} assets found", force=True)
        
        return selected_assets
    
    def _display_asset_options(self, asset_type, files):
        """Format asset choices for user"""
        print(f"Available {asset_type}:")
        for i, file in enumerate(files, 1):
            size_mb = float(file.get('size', 0)) / (1024 * 1024)
            print(f"  {i}. {file['name']} ({size_mb:.1f} MB)")
        
        print(f"  0. Skip {asset_type}")
        
        while True:
            try:
                choice = input(f"Select {asset_type} (0-{len(files)}) or 'q' to quit: ").strip()
                
                if choice.lower() == 'q':
                    return None
                
                choice_num = int(choice)
                if choice_num == 0:
                    return 'skip'
                elif 1 <= choice_num <= len(files):
                    selected = files[choice_num - 1]
                    print(f"Selected {asset_type}: {selected['name']}")
                    return selected
                else:
                    print("Invalid selection. Please try again.")
                    
            except ValueError:
                print("Please enter a number or 'q' to quit.")
    
    def _validate_asset_selection(self, choice, file_count):
        """Validate user input for asset selection"""
        try:
            choice_num = int(choice)
            return 0 <= choice_num <= file_count
        except ValueError:
            return False
    
    def _ensure_assets_available(self, folder_id):
        """Smart asset sync before selection"""
        if not self.drive_processor.assets_folder_id:
            self.log("No assets folder found in Drive", force=True)
            return {}
        
        # Sync assets with cache awareness
        available_assets = self.drive_processor.sync_assets_folder(
            force_update=self.force_asset_update
        )
        
        if available_assets:
            cache_status = self.drive_processor.asset_cache.get_cache_status()
            self._display_cache_status(cache_status)
        
        return available_assets
    
    def _select_preset_from_cache(self, cached_presets, preset_name=None):
        """Select preset from cached presets folder"""
        if not cached_presets:
            return None
        
        if preset_name:
            # Find preset by name
            for preset_info in cached_presets:
                if preset_info['name'].lower().replace('.json', '') == preset_name.lower():
                    self.log(f"Using cached preset: {preset_info['name']}", force=True)
                    # Load and return preset configuration
                    return self._load_cached_preset_config(preset_info)
            
            self.log(f"Cached preset '{preset_name}' not found", force=True)
            return None
        
        # Interactive selection
        return self._interactive_cached_preset_selection(cached_presets)
    
    def _interactive_cached_preset_selection(self, cached_presets):
        """Interactive selection from cached presets"""
        print("\nCached Presets Available:")
        print("=" * 50)
        
        for i, preset in enumerate(cached_presets, 1):
            print(f"{i}. {preset['name']}")
            print(f"   Size: {preset.get('size', 0) / 1024:.1f} KB (cached)")
            print()
        
        while True:
            try:
                choice = input(f"Select preset (1-{len(cached_presets)}) or 'q' to quit: ").strip()
                
                if choice.lower() == 'q':
                    return None
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(cached_presets):
                    selected = cached_presets[choice_num - 1]
                    print(f"Selected cached preset: {selected['name']}")
                    return self._load_cached_preset_config(selected)
                else:
                    print("Invalid selection. Please try again.")
                    
            except ValueError:
                print("Please enter a number or 'q' to quit.")
    
    def _load_cached_preset_config(self, preset_info):
        """Load configuration from cached preset"""
        try:
            with open(preset_info['path'], 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Return preset info structure similar to drive presets
            return {
                'type': 'cached_preset',
                'name': preset_info['name'].replace('.json', ''),
                'path': preset_info['path'],
                'config': data
            }
            
        except Exception as e:
            print(f"Error loading cached preset: {e}")
            return None
    
    def _select_assets_from_cache(self, available_assets):
        """Select from cached assets folders"""
        selected_assets = {}
        
        for asset_type in ['fonts', 'overlays', 'bgmusic']:
            assets = available_assets.get(asset_type, [])
            if assets:
                print(f"\n{asset_type.upper()} Assets (Cached):")
                selected = self._display_cached_asset_options(asset_type, assets)
                if selected and selected != 'skip':
                    selected_assets[asset_type] = selected
            else:
                self.log(f"No cached {asset_type} assets found", force=True)
        
        return selected_assets
    
    def _display_cached_asset_options(self, asset_type, assets):
        """Display cached asset choices"""
        print(f"Available cached {asset_type}:")
        for i, asset in enumerate(assets, 1):
            size_mb = asset.get('size', 0) / (1024 * 1024)
            print(f"  {i}. {asset['name']} ({size_mb:.1f} MB) [cached]")
        
        print(f"  0. Skip {asset_type}")
        
        while True:
            try:
                choice = input(f"Select {asset_type} (0-{len(assets)}) or 'q' to quit: ").strip()
                
                if choice.lower() == 'q':
                    return None
                
                choice_num = int(choice)
                if choice_num == 0:
                    return 'skip'
                elif 1 <= choice_num <= len(assets):
                    selected = assets[choice_num - 1]
                    print(f"Selected cached {asset_type}: {selected['name']}")
                    return selected
                else:
                    print("Invalid selection. Please try again.")
                    
            except ValueError:
                print("Please enter a number or 'q' to quit.")
    
    def _display_cache_status(self, cache_info):
        """Show asset cache status to user"""
        if cache_info['assets_cached']:
            self.log(f"📊 Cache Status: {cache_info['total_assets']} assets "
                    f"({cache_info['cache_size_bytes'] / 1024 / 1024:.1f} MB)", force=True)
            if cache_info['last_updated']:
                self.log(f"🕐 Last updated: {cache_info['last_updated']}", force=True)
    
    def _display_workflow_summary(self, projects, preset, config, selected_assets=None):
        """Display workflow summary before processing"""
        
        print("\nWorkflow Summary")
        print("=" * 50)
        print(f"Selected Preset: {preset['name']}")
        print(f"Preset Type: {preset['type']}")
        print(f"Configuration Settings: {len(config)} items")
        print(f"Projects to Process: {len(projects)}")
        print()
        
        print("Projects:")
        for i, project in enumerate(projects, 1):
            print(f"  {i}. {project['name']} ({project['type']})")
            print(f"     Images: {len(project['images'])}, Videos: {len(project['videos'])}")
            print(f"     Audio: {'Yes' if project['audio'] else 'No'}")
        
        print()
        
        # Display selected assets
        if selected_assets:
            print("Selected Assets:")
            for asset_type, asset_file in selected_assets.items():
                if asset_file != 'skip':
                    print(f"  {asset_type}: {asset_file['name'] if isinstance(asset_file, dict) else asset_file}")
            print()
        
        print("Key Settings:")
        key_settings = ['image_duration', 'project_type', 'quality_preset', 'animation_style']
        for setting in key_settings:
            if setting in config:
                print(f"  {setting}: {config[setting]}")
        print()
    
    def _confirm_processing(self):
        """Ask user to confirm processing"""
        while True:
            response = input("Proceed with processing? (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' or 'n'")

def main():
    """Main entry point"""
    parser = setup_argument_parser()
    args = parser.parse_args()
    
    # Check credentials file
    if not os.path.exists(args.credentials):
        print(f"Error: Credentials file not found: {args.credentials}")
        print("Run 'python3 setup_drive_auth.py' first")
        return 1
    
    try:
        # Initialize workflow runner
        runner = DriveWorkflowRunner(args.credentials, args.verbose)
        
        # Run workflow
        success = runner.run_complete_workflow(
            folder_id=args.folder_id,
            output_folder_id=args.output_folder_id,
            preset_name=args.preset_name,
            dry_run=args.dry_run,
            keep_workspace=args.keep_workspace,
            force_asset_update=args.force_asset_update,
            clear_cache=args.clear_cache
        )
        
        return 0 if success else 1
        
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
