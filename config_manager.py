"""
Configuration management for VideoStove CLI
"""

import os
import json
from pathlib import Path
import datetime
from videostove_core import DEFAULT_CONFIG

class ConfigManager:
    """Manage VideoStove configurations and presets"""
    
    def __init__(self, config_dir=None):
        self.config_dir = config_dir or os.path.expanduser("~/.videostove")
        os.makedirs(self.config_dir, exist_ok=True)
        
        self.presets_file = os.path.join(self.config_dir, "presets.json")
        self.settings_file = os.path.join(self.config_dir, "settings.json")
    
    def list_presets(self):
        """List available presets"""
        try:
            if os.path.exists(self.presets_file):
                with open(self.presets_file, 'r', encoding='utf-8') as f:
                    presets = json.load(f)
                return list(presets.keys())
            return []
        except Exception as e:
            print(f"Error loading presets: {e}")
            return []
    
    def load_preset(self, name):
        """Load a specific preset"""
        try:
            if os.path.exists(self.presets_file):
                with open(self.presets_file, 'r', encoding='utf-8') as f:
                    presets = json.load(f)
                
                if name in presets:
                    return presets[name]
                else:
                    print(f"Preset '{name}' not found")
                    return None
            else:
                print("No presets file found")
                return None
        except Exception as e:
            print(f"Error loading preset '{name}': {e}")
            return None
    
    def save_preset(self, name, config):
        """Save a configuration as preset"""
        try:
            # Load existing presets
            presets = {}
            if os.path.exists(self.presets_file):
                with open(self.presets_file, 'r', encoding='utf-8') as f:
                    presets = json.load(f)
            
            # Filter config to only include valid settings
            filtered_config = {}
            for key, value in config.items():
                if key in DEFAULT_CONFIG:
                    filtered_config[key] = value
            
            # Save preset
            presets[name] = filtered_config
            
            with open(self.presets_file, 'w', encoding='utf-8') as f:
                json.dump(presets, f, indent=2)
            
            print(f"Preset '{name}' saved successfully")
            return True
            
        except Exception as e:
            print(f"Error saving preset '{name}': {e}")
            return False
    
    def delete_preset(self, name):
        """Delete a preset"""
        try:
            if not os.path.exists(self.presets_file):
                print("No presets file found")
                return False
            
            with open(self.presets_file, 'r', encoding='utf-8') as f:
                presets = json.load(f)
            
            if name not in presets:
                print(f"Preset '{name}' not found")
                return False
            
            del presets[name]
            
            with open(self.presets_file, 'w', encoding='utf-8') as f:
                json.dump(presets, f, indent=2)
            
            print(f"Preset '{name}' deleted successfully")
            return True
            
        except Exception as e:
            print(f"Error deleting preset '{name}': {e}")
            return False
    
    def export_config(self, config, output_file):
        """Export configuration to file"""
        try:
            # Create export data structure
            export_data = {
                "metadata": {
                    "export_type": "videostove_config",
                    "export_date": datetime.datetime.now().isoformat(),
                    "videostove_version": "CLI 1.0"
                },
                "settings": config
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"Configuration exported to: {output_file}")
            return True
            
        except Exception as e:
            print(f"Error exporting configuration: {e}")
            return False
    
    def export_all_presets(self, output_file):
        """Export all presets to file"""
        try:
            if not os.path.exists(self.presets_file):
                print("No presets file found")
                return False
            
            with open(self.presets_file, 'r', encoding='utf-8') as f:
                presets = json.load(f)
            
            if not presets:
                print("No presets to export")
                return False
            
            # Create export data structure
            export_data = {
                "metadata": {
                    "export_type": "videostove_presets",
                    "export_date": datetime.datetime.now().isoformat(),
                    "videostove_version": "CLI 1.0",
                    "preset_count": len(presets)
                },
                "presets": presets
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"Exported {len(presets)} presets to: {output_file}")
            return True
            
        except Exception as e:
            print(f"Error exporting presets: {e}")
            return False
    
    def import_presets(self, import_file):
        """Import presets from file"""
        try:
            with open(import_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle different import formats
            if 'presets' in data:
                # Preset export format
                import_presets = data['presets']
            elif 'settings' in data:
                # Single config format - convert to preset
                preset_name = f"imported_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                import_presets = {preset_name: data['settings']}
            else:
                # Direct preset format or single config
                if any(key in DEFAULT_CONFIG for key in data.keys()):
                    # Single config
                    preset_name = f"imported_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    import_presets = {preset_name: data}
                else:
                    # Preset collection
                    import_presets = data
            
            if not import_presets:
                print("No valid presets found in import file")
                return False
            
            # Load existing presets
            existing_presets = {}
            if os.path.exists(self.presets_file):
                with open(self.presets_file, 'r', encoding='utf-8') as f:
                    existing_presets = json.load(f)
            
            # Merge presets
            imported_count = 0
            overwritten_count = 0
            
            for preset_name, preset_data in import_presets.items():
                # Filter to only valid settings
                filtered_preset = {}
                for key, value in preset_data.items():
                    if key in DEFAULT_CONFIG:
                        filtered_preset[key] = value
                
                if preset_name in existing_presets:
                    overwritten_count += 1
                else:
                    imported_count += 1
                
                existing_presets[preset_name] = filtered_preset
            
            # Save merged presets
            with open(self.presets_file, 'w', encoding='utf-8') as f:
                json.dump(existing_presets, f, indent=2)
            
            print(f"Import successful!")
            print(f"New presets: {imported_count}, Updated presets: {overwritten_count}")
            print(f"Total presets imported: {imported_count + overwritten_count}")
            
            return True
            
        except Exception as e:
            print(f"Error importing presets: {e}")
            return False
    
    def load_config_from_file(self, config_file):
        """Load configuration from any supported file format"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
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
            
            # Filter to only valid settings
            filtered_config = DEFAULT_CONFIG.copy()
            for key, value in settings.items():
                if key in DEFAULT_CONFIG:
                    filtered_config[key] = value
            
            return filtered_config
            
        except Exception as e:
            print(f"Error loading config from file: {e}")
            return DEFAULT_CONFIG.copy()
    
    def create_sample_configs(self):
        """Create sample configuration files"""
        configs_dir = os.path.join(self.config_dir, "configs")
        os.makedirs(configs_dir, exist_ok=True)
        
        # Basic slideshow config
        basic_config = DEFAULT_CONFIG.copy()
        basic_config.update({
            "image_duration": 5.0,
            "use_crossfade": True,
            "crossfade_duration": 0.5,
            "use_gpu": True,
            "crf": 23,
            "preset": "medium"
        })
        
        # High quality config
        hq_config = DEFAULT_CONFIG.copy()
        hq_config.update({
            "image_duration": 8.0,
            "use_crossfade": True,
            "crossfade_duration": 1.0,
            "use_gpu": True,
            "crf": 18,
            "preset": "slow",
            "quality_preset": "High Quality"
        })
        
        # Fast processing config
        fast_config = DEFAULT_CONFIG.copy()
        fast_config.update({
            "image_duration": 3.0,
            "use_crossfade": False,
            "use_gpu": True,
            "crf": 28,
            "preset": "ultrafast"
        })
        
        # Video montage config
        montage_config = DEFAULT_CONFIG.copy()
        montage_config.update({
            "project_type": "montage",
            "use_crossfade": True,
            "crossfade_duration": 0.8,
            "use_gpu": True,
            "crf": 20,
            "preset": "fast"
        })
        
        configs = {
            "basic.json": basic_config,
            "high_quality.json": hq_config,
            "fast_processing.json": fast_config,
            "montage.json": montage_config
        }
        
        for filename, config in configs.items():
            config_path = os.path.join(configs_dir, filename)
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)
                print(f"Created sample config: {config_path}")
            except Exception as e:
                print(f"Error creating {filename}: {e}")
        
        return configs_dir

def main():
    """CLI interface for config manager"""
    import argparse
    
    parser = argparse.ArgumentParser(description='VideoStove Configuration Manager')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List presets
    subparsers.add_parser('list', help='List all presets')
    
    # Show preset
    show_parser = subparsers.add_parser('show', help='Show preset details')
    show_parser.add_argument('name', help='Preset name')
    
    # Save preset
    save_parser = subparsers.add_parser('save', help='Save current config as preset')
    save_parser.add_argument('name', help='Preset name')
    save_parser.add_argument('config_file', help='Configuration file to save')
    
    # Delete preset
    delete_parser = subparsers.add_parser('delete', help='Delete preset')
    delete_parser.add_argument('name', help='Preset name')
    
    # Export presets
    export_parser = subparsers.add_parser('export', help='Export all presets')
    export_parser.add_argument('output_file', help='Output file path')
    
    # Import presets
    import_parser = subparsers.add_parser('import', help='Import presets')
    import_parser.add_argument('import_file', help='Import file path')
    
    # Create samples
    subparsers.add_parser('create-samples', help='Create sample configuration files')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    config_mgr = ConfigManager()
    
    if args.command == 'list':
        presets = config_mgr.list_presets()
        if presets:
            print("Available presets:")
            for preset in presets:
                print(f"  - {preset}")
        else:
            print("No presets found")
    
    elif args.command == 'show':
        preset = config_mgr.load_preset(args.name)
        if preset:
            print(f"Preset '{args.name}':")
            print(json.dumps(preset, indent=2))
    
    elif args.command == 'save':
        config = config_mgr.load_config_from_file(args.config_file)
        config_mgr.save_preset(args.name, config)
    
    elif args.command == 'delete':
        config_mgr.delete_preset(args.name)
    
    elif args.command == 'export':
        config_mgr.export_all_presets(args.output_file)
    
    elif args.command == 'import':
        config_mgr.import_presets(args.import_file)
    
    elif args.command == 'create-samples':
        configs_dir = config_mgr.create_sample_configs()
        print(f"Sample configurations created in: {configs_dir}")

if __name__ == "__main__":
    main()
