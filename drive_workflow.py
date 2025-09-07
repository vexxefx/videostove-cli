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
    
    return parser

class DriveWorkflowRunner:
    """Complete workflow runner for Drive integration"""
    
    def __init__(self, credentials_path, verbose=False):
        self.verbose = verbose
        self.drive_processor = DriveVideoStove(credentials_path)
        self.workspace = None
        
        if not self.drive_processor.service:
            raise Exception("Failed to authenticate with Google Drive")
    
    def log(self, message, force=False):
        """Log message if verbose or forced"""
        if self.verbose or force:
            print(message)
    
    def run_complete_workflow(self, folder_id, output_folder_id=None, 
                            preset_name=None, dry_run=False, keep_workspace=False):
        """Run the complete Drive workflow"""
        
        try:
            # Step 1: Setup workspace
            self.log("Setting up workspace...", force=True)
            self.workspace = self.drive_processor.setup_workspace()
            
            # Step 2: Scan Drive folder
            self.log(f"Scanning Drive folder: {folder_id}", force=True)
            scan_results = self.drive_processor.scan_drive_folder(folder_id)
            
            if not scan_results:
                raise Exception("Failed to scan Drive folder")
            
            self.log(f"Found: {len(scan_results['projects'])} projects, "
                    f"{len(scan_results['presets'])} presets", force=True)
            
            # Step 3: Download and analyze presets
            if not scan_results['presets']:
                raise Exception("No presets found in Drive folder")
            
            self.log("Downloading presets...", force=True)
            downloaded_presets = self.drive_processor.download_presets(scan_results['presets'])
            
            if not downloaded_presets:
                raise Exception("No valid presets found")
            
            # Step 4: Select preset
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
            config = self.drive_processor.load_preset_config(selected_preset)
            
            if not config:
                raise Exception("Failed to load preset configuration")
            
            self.log(f"Loaded {len(config)} configuration settings", force=True)
            
            # Step 7: Display summary
            self._display_workflow_summary(downloaded_projects, selected_preset, config)
            
            if dry_run:
                self.log("Dry run mode - stopping before processing", force=True)
                return True
            
            # Step 8: Confirm processing
            if not self._confirm_processing():
                self.log("Processing cancelled by user", force=True)
                return False
            
            # Step 9: Process projects
            self.log("Starting batch processing...", force=True)
            self.drive_processor.batch_process_projects(config, output_folder_id)
            
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
    
    def _display_workflow_summary(self, projects, preset, config):
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
            keep_workspace=args.keep_workspace
        )
        
        return 0 if success else 1
        
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
