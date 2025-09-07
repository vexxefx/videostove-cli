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
    parser = argparse.ArgumentParser(
        description='VideoStove Google Drive Workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Assets-First Workflow (Recommended):
  Provide the assets folder ID directly for reliable preset detection.
  The assets folder should contain: presets/, fonts/, overlays/, bgmusic/

Authentication Methods:
  OAuth: For local development and testing (requires browser)
  Service Account: For headless deployment (RunPod, servers)

Environment Variables:
  GOOGLE_CREDENTIALS_PATH: Path to credentials file
  GOOGLE_CREDENTIALS_BASE64: Base64 encoded credentials JSON

Examples:
  # Use assets folder ID directly (RECOMMENDED)
  python drive_workflow.py --folder-id 1ordCteHj7H0vSmPvTaClR9juAHIwDWPS --preset twovet
  
  # With custom output folder
  python drive_workflow.py --folder-id 1ordCteHj7H0vSmPvTaClR9juAHIwDWPS --output-folder-id 1aELjJPrOf2u6EKy18WQY2lc_aSekXXhQ
  
  # Service Account authentication (headless)
  python drive_workflow.py --folder-id 1ordCteHj7H0vSmPvTaClR9juAHIwDWPS --credentials service_account.json --preset science
        """
    )
    
    parser.add_argument('--folder-id', required=True, 
                       help='Assets folder ID (contains presets/, fonts/, overlays/, bgmusic/)')
    parser.add_argument('--output-folder-id', 
                       help='Google Drive folder ID for output videos')
    parser.add_argument('--credentials', default='credentials.json',
                       help='Path to Google Drive credentials file')
    
    # Authentication options
    parser.add_argument('--auth-method', choices=['auto', 'oauth', 'service'],
                       default='auto', help='Authentication method (auto-detects by default)')
    parser.add_argument('--service-account', 
                       help='Path to service account JSON file (overrides --credentials)')
    
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
        """Run complete workflow using assets-first approach
        
        Args:
            folder_id: Assets folder ID (contains presets/, fonts/, overlays/, bgmusic/)
            output_folder_id: Optional folder for outputs (defaults to parent of assets folder)
            preset_name: Specific preset to use
            dry_run: Test mode without processing
            keep_workspace: Keep temp files for debugging
            force_asset_update: Force re-download assets
            clear_cache: Clear asset cache first
        """
        
        try:
            # Handle cache commands first
            if clear_cache:
                self.log("Clearing asset cache...", force=True)
                self.drive_processor.asset_cache.clear_cache()
            
            self.force_asset_update = force_asset_update
            
            # Step 1: Setup workspace
            self.log("Setting up workspace...", force=True)
            self.workspace = self.drive_processor.setup_workspace()
            
            # Step 2: Set assets folder ID directly (assets-first approach)
            self.log(f"Using assets folder directly: {folder_id}", force=True)
            self.drive_processor.assets_folder_id = folder_id
            
            # Step 3: Sync assets (this should work since we're using assets folder directly)
            self.log("Syncing assets...", force=True)
            available_assets = self.drive_processor.sync_assets_folder(
                folder_id=folder_id,
                force_update=self.force_asset_update
            )
            
            # Step 4: Find and select preset
            self.log("Loading presets...", force=True)
            available_presets = available_assets.get('presets', [])
            
            if not available_presets:
                raise Exception("No presets found in assets folder")
            
            self.log(f"Found {len(available_presets)} presets", force=True)
            for preset in available_presets:
                self.log(f"  - {preset.get('name', 'Unknown')}", force=True)
            
            # Select preset
            if preset_name:
                selected_preset = None
                for preset in available_presets:
                    if preset.get('name', '').lower() == preset_name.lower():
                        selected_preset = preset
                        break
                
                if not selected_preset:
                    raise Exception(f"Preset '{preset_name}' not found")
            else:
                # Interactive selection
                selected_preset = self._select_preset(available_presets, preset_name)
            
            if not selected_preset:
                raise Exception("No preset selected")
            
            project_type = selected_preset.get('project_type', 'montage')
            self.log(f"Selected preset: {selected_preset['name']} (Mode: {project_type})", force=True)
            
            # Step 5: Find projects from parent folder (assets-first approach)
            self.log("Finding projects from parent folder...", force=True)
            all_projects = self.drive_processor.find_projects_from_assets_parent(folder_id)
            
            if not all_projects:
                raise Exception("No projects found in parent folder")
            
            # Analyze compatibility before filtering
            project_analysis = []
            for project in all_projects:
                # Download to analyze content (minimal download for analysis)
                temp_project = self._analyze_project_for_compatibility(project, project_type)
                project_analysis.append(temp_project)
            
            # Filter compatible projects
            compatible_projects = self.drive_processor.filter_projects_by_mode(project_analysis, project_type)
            
            self.log(f"Found {len(all_projects)} total projects, {len(compatible_projects)} compatible with {project_type} mode", force=True)
            
            # Display compatibility analysis
            self._display_project_compatibility(project_analysis, compatible_projects, project_type)
            
            if not compatible_projects:
                raise Exception(f"No projects compatible with {project_type} mode")
            
            # Step 6: Select other assets (fonts, overlays, bgmusic)
            selected_assets = {}
            if available_assets:
                self.log("Selecting other assets...", force=True)
                selected_assets = self._select_other_assets(available_assets)
            
            # Step 7: Download compatible projects only
            self.log("Downloading compatible projects...", force=True)
            downloaded_projects = self.drive_processor.download_projects(compatible_projects)
            
            if not downloaded_projects:
                raise Exception("Failed to download compatible projects")
            
            # Step 8: Load configuration
            self.log("Loading preset configuration...", force=True)
            
            if selected_preset.get('type') == 'cached_preset':
                config = selected_preset.get('config', {})
            elif 'settings' in selected_preset and selected_preset['settings']:
                config = selected_preset['settings']
            else:
                config = self.drive_processor.load_preset_config(selected_preset)
            
            if not config:
                raise Exception("Failed to load preset configuration")
            
            self.log(f"Loaded {len(config)} configuration settings", force=True)
            
            # Step 9: Determine output folder
            if not output_folder_id:
                # Use parent of assets folder as default output location
                output_folder_id = self.drive_processor.find_parent_folder(folder_id)
                if output_folder_id:
                    self.log(f"Using parent folder for outputs: {output_folder_id}", force=True)
                else:
                    self.log("Warning: No output folder specified and no parent folder found", force=True)
            
            # Step 10: Display summary
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
        """Select preset either by name or user input with mode information"""
        
        if preset_name:
            # Find preset by name
            for preset in presets:
                if preset['name'].lower() == preset_name.lower():
                    project_type = preset.get('project_type', 'montage')
                    self.log(f"Using specified preset: {preset['name']} (Mode: {project_type})", force=True)
                    return preset
            
            self.log(f"Preset '{preset_name}' not found", force=True)
            return None
        
        # Enhanced interactive selection with mode information
        return self._display_preset_selection_with_mode(presets)
    
    def _display_preset_selection_with_mode(self, presets):
        """Display preset selection with project mode information"""
        print("\nAvailable Presets:")
        print("=" * 70)
        
        for i, preset in enumerate(presets, 1):
            project_type = preset.get('project_type', 'montage')
            mode_description = self._get_mode_description(project_type)
            
            print(f"{i}. {preset['name']} (Mode: {project_type})")
            print(f"   Type: {preset.get('type', 'unknown')}")
            print(f"   Description: {preset.get('description', 'No description')}")
            print(f"   Project Mode: {mode_description}")
            if preset.get('date') and preset['date'] != 'Unknown':
                print(f"   Date: {preset['date']}")
            print()
        
        while True:
            try:
                choice = input(f"Select preset (1-{len(presets)}) or 'q' to quit: ").strip()
                
                if choice.lower() == 'q':
                    return None
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(presets):
                    selected = presets[choice_num - 1]
                    project_type = selected.get('project_type', 'montage')
                    print(f"Selected preset: {selected['name']} (Mode: {project_type})")
                    return selected
                else:
                    print("Invalid selection. Please try again.")
                    
            except ValueError:
                print("Please enter a number or 'q' to quit.")
    
    def _get_mode_description(self, project_type):
        """Get description of what each project mode does"""
        descriptions = {
            'slideshow': 'Images only - Creates slideshow from images with crossfades',
            'montage': 'Mixed content - Handles videos as intro + images, or pure montage',
            'videos_only': 'Videos only - Compiles and processes video files only',
        }
        return descriptions.get(project_type, f'Custom mode: {project_type}')
    
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
        # Sync assets with cache awareness (will find assets folder within main folder)
        available_assets = self.drive_processor.sync_assets_folder(
            folder_id=folder_id,  # Pass the main folder ID
            force_update=self.force_asset_update
        )
        
        if not available_assets:
            self.log("No assets folder found in Drive", force=True)
            return {}
        
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
        """Interactive selection from cached presets with mode information"""
        print("\nCached Presets Available:")
        print("=" * 70)
        
        for i, preset in enumerate(cached_presets, 1):
            # Try to extract project_type from cached preset
            project_type = 'unknown'
            try:
                with open(preset['path'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Handle different preset formats to extract project_type
                if 'preset' in data and isinstance(data['preset'], dict):
                    inner_preset = next(iter(data['preset'].values()))
                    project_type = inner_preset.get('project_type', 'montage')
                elif 'project_type' in data:
                    project_type = data['project_type']
                elif 'settings' in data:
                    project_type = data['settings'].get('project_type', 'montage')
            except:
                project_type = 'montage'
            
            mode_description = self._get_mode_description(project_type)
            
            print(f"{i}. {preset['name']} (Mode: {project_type})")
            print(f"   Size: {preset.get('size', 0) / 1024:.1f} KB (cached)")
            print(f"   Project Mode: {mode_description}")
            print()
        
        while True:
            try:
                choice = input(f"Select preset (1-{len(cached_presets)}) or 'q' to quit: ").strip()
                
                if choice.lower() == 'q':
                    return None
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(cached_presets):
                    selected = cached_presets[choice_num - 1]
                    project_type = 'montage'  # Default fallback
                    try:
                        with open(selected['path'], 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if 'preset' in data and isinstance(data['preset'], dict):
                            inner_preset = next(iter(data['preset'].values()))
                            project_type = inner_preset.get('project_type', 'montage')
                    except:
                        pass
                    
                    print(f"Selected cached preset: {selected['name']} (Mode: {project_type})")
                    cached_preset_config = self._load_cached_preset_config(selected)
                    if cached_preset_config:
                        cached_preset_config['project_type'] = project_type
                    return cached_preset_config
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
    
    def _analyze_project_for_compatibility(self, project_info, project_type):
        """Analyze project for compatibility without full download"""
        # This would ideally just peek at folder contents, but for now we'll use existing analysis
        # In a real implementation, you'd want to minimize the data transfer here
        return project_info
    
    def _select_other_assets(self, available_assets):
        """Select fonts, overlays, and bgmusic from available assets"""
        selected_assets = {}
        
        for asset_type in ['fonts', 'overlays', 'bgmusic']:
            assets = available_assets.get(asset_type, [])
            if assets:
                selected = self._display_cached_asset_options(asset_type, assets)
                if selected and selected != 'skip':
                    selected_assets[asset_type] = selected
        
        return selected_assets
    
    def _display_project_compatibility(self, all_projects, compatible_projects, project_type):
        """Display project compatibility analysis"""
        print(f"\nProject Compatibility Analysis (Mode: {project_type})")
        print("=" * 60)
        
        compatible_names = [p['name'] for p in compatible_projects]
        
        for project in all_projects:
            is_compatible = project['name'] in compatible_names
            status = "✅ Compatible" if is_compatible else "❌ Skipped"
            print(f"{project['name']}: {status}")
            
            if not is_compatible:
                reason = self._get_incompatibility_reason(project, project_type)
                print(f"   Reason: {reason}")
            else:
                content_info = self._get_project_content_info(project)
                print(f"   Content: {content_info}")
        print()
    
    def _get_incompatibility_reason(self, project, project_type):
        """Get reason why project is incompatible with project_type"""
        # Note: This would need to be enhanced to actually check project contents
        # For now, we'll provide general guidance
        if project_type == "slideshow":
            return "Project contains videos or no images (slideshow mode requires images only)"
        elif project_type == "videos_only":
            return "Project contains no videos (videos_only mode requires videos)"
        elif project_type == "montage":
            return "Project contains no media content"
        return "Unknown incompatibility"
    
    def _get_project_content_info(self, project):
        """Get brief description of project content"""
        # This is a placeholder - would need actual content analysis
        return "Images and/or videos detected"
    
    def _display_workflow_summary(self, projects, preset, config, selected_assets=None):
        """Display workflow summary before processing"""
        
        print("\nWorkflow Summary")
        print("=" * 50)
        print(f"Selected Preset: {preset['name']}")
        print(f"Preset Type: {preset['type']}")
        print(f"Project Mode: {preset.get('project_type', 'montage')}")
        print(f"Configuration Settings: {len(config)} items")
        print(f"Compatible Projects: {len(projects)}")
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
    
    # Determine credentials path based on arguments
    credentials_path = args.credentials
    if args.service_account:
        credentials_path = args.service_account
    
    # Check if credentials exist (skip if using environment variables)
    if not os.path.exists(credentials_path) and not os.environ.get('GOOGLE_CREDENTIALS_BASE64'):
        print(f"Error: Credentials file not found: {credentials_path}")
        print("Options:")
        print("1. Create credentials.json (OAuth) or service_account.json")
        print("2. Set GOOGLE_CREDENTIALS_PATH environment variable")
        print("3. Set GOOGLE_CREDENTIALS_BASE64 environment variable")
        print("4. Run 'python3 setup_drive_auth.py' for OAuth setup")
        return 1
    
    try:
        # Initialize workflow runner with credentials path
        runner = DriveWorkflowRunner(credentials_path, args.verbose)
        
        # Validate authentication before proceeding
        if not runner.drive_processor.service:
            print("ERROR: Authentication failed")
            return 1
        
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
