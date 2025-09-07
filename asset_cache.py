"""
Asset Cache Management for VideoStove CLI
Handles intelligent caching of assets from Google Drive with timestamp-based sync
"""

import os
import json
import shutil
import datetime
from pathlib import Path
import hashlib
import tempfile

class AssetCache:
    """Manages persistent asset caching with smart synchronization"""
    
    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or os.path.expanduser("~/.videostove/cache")
        self.assets_dir = os.path.join(self.cache_dir, "assets")
        self.metadata_file = os.path.join(self.cache_dir, "metadata.json")
        
        # Create cache directory structure
        self._ensure_cache_structure()
    
    def _ensure_cache_structure(self):
        """Create cache directory structure if it doesn't exist"""
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(os.path.join(self.assets_dir, "presets"), exist_ok=True)
        os.makedirs(os.path.join(self.assets_dir, "fonts"), exist_ok=True)
        os.makedirs(os.path.join(self.assets_dir, "overlays"), exist_ok=True)
        os.makedirs(os.path.join(self.assets_dir, "bgmusic"), exist_ok=True)
    
    def load_metadata(self):
        """Load cache metadata from file"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load cache metadata: {e}")
                return {}
        return {}
    
    def save_metadata(self, metadata):
        """Save cache metadata to file"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving cache metadata: {e}")
    
    def is_cache_valid(self, drive_folder_id, drive_modified_time):
        """Check if cache is valid compared to Drive folder timestamp"""
        metadata = self.load_metadata()
        
        if drive_folder_id not in metadata:
            return False
        
        cache_info = metadata[drive_folder_id]
        cached_timestamp = cache_info.get('last_modified')
        
        if not cached_timestamp:
            return False
        
        # Parse timestamps for comparison
        try:
            if isinstance(cached_timestamp, str):
                cached_dt = datetime.datetime.fromisoformat(cached_timestamp.replace('Z', '+00:00'))
            else:
                cached_dt = cached_timestamp
            
            if isinstance(drive_modified_time, str):
                drive_dt = datetime.datetime.fromisoformat(drive_modified_time.replace('Z', '+00:00'))
            else:
                drive_dt = drive_modified_time
            
            # Cache is valid if it's newer than or equal to Drive version
            return cached_dt >= drive_dt
            
        except Exception as e:
            print(f"Error comparing timestamps: {e}")
            return False
    
    def get_cached_assets(self, drive_folder_id=None):
        """Load assets from cache"""
        if not os.path.exists(self.assets_dir):
            return {}
        
        cached_assets = {
            'presets': [],
            'fonts': [],
            'overlays': [],
            'bgmusic': []
        }
        
        for asset_type in cached_assets.keys():
            type_dir = os.path.join(self.assets_dir, asset_type)
            if os.path.exists(type_dir):
                for file in os.listdir(type_dir):
                    file_path = os.path.join(type_dir, file)
                    if os.path.isfile(file_path):
                        cached_assets[asset_type].append({
                            'name': file,
                            'path': file_path,
                            'size': os.path.getsize(file_path),
                            'cached': True
                        })
        
        return cached_assets
    
    def save_asset(self, asset_type, asset_name, content, drive_file_info=None):
        """Save asset content to cache"""
        type_dir = os.path.join(self.assets_dir, asset_type)
        os.makedirs(type_dir, exist_ok=True)
        
        asset_path = os.path.join(type_dir, asset_name)
        
        try:
            if isinstance(content, bytes):
                with open(asset_path, 'wb') as f:
                    f.write(content)
            else:
                with open(asset_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            
            # Update metadata for this asset
            metadata = self.load_metadata()
            if 'assets' not in metadata:
                metadata['assets'] = {}
            
            metadata['assets'][f"{asset_type}/{asset_name}"] = {
                'cached_at': datetime.datetime.now().isoformat(),
                'size': os.path.getsize(asset_path),
                'drive_info': drive_file_info
            }
            
            self.save_metadata(metadata)
            return asset_path
            
        except Exception as e:
            print(f"Error saving asset {asset_name}: {e}")
            return None
    
    def update_folder_cache_info(self, drive_folder_id, drive_modified_time, file_list=None):
        """Update cache metadata for a Drive folder"""
        metadata = self.load_metadata()
        
        metadata[drive_folder_id] = {
            'last_modified': drive_modified_time.isoformat() if hasattr(drive_modified_time, 'isoformat') else str(drive_modified_time),
            'cached_at': datetime.datetime.now().isoformat(),
            'file_count': len(file_list) if file_list else 0,
            'files': file_list or []
        }
        
        self.save_metadata(metadata)
    
    def get_cache_status(self, drive_folder_id=None):
        """Get comprehensive cache status information"""
        metadata = self.load_metadata()
        cached_assets = self.get_cached_assets(drive_folder_id)
        
        status = {
            'cache_exists': os.path.exists(self.cache_dir),
            'assets_cached': any(len(assets) > 0 for assets in cached_assets.values()),
            'cache_size_bytes': self._get_cache_size(),
            'last_updated': None,
            'total_assets': sum(len(assets) for assets in cached_assets.values()),
            'asset_breakdown': {k: len(v) for k, v in cached_assets.items()},
            'metadata': metadata.get(drive_folder_id, {}) if drive_folder_id else metadata
        }
        
        # Find most recent cache update
        if metadata:
            timestamps = []
            for folder_info in metadata.values():
                if isinstance(folder_info, dict) and 'cached_at' in folder_info:
                    try:
                        timestamps.append(datetime.datetime.fromisoformat(folder_info['cached_at']))
                    except:
                        pass
            
            if timestamps:
                status['last_updated'] = max(timestamps).isoformat()
        
        return status
    
    def _get_cache_size(self):
        """Calculate total cache size in bytes"""
        total_size = 0
        if os.path.exists(self.assets_dir):
            for root, dirs, files in os.walk(self.assets_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)
                    except:
                        pass
        return total_size
    
    def clear_cache(self, asset_type=None):
        """Clear cache (all or specific asset type)"""
        try:
            if asset_type:
                # Clear specific asset type
                type_dir = os.path.join(self.assets_dir, asset_type)
                if os.path.exists(type_dir):
                    shutil.rmtree(type_dir)
                    os.makedirs(type_dir, exist_ok=True)
                    
                # Update metadata
                metadata = self.load_metadata()
                if 'assets' in metadata:
                    keys_to_remove = [k for k in metadata['assets'].keys() if k.startswith(f"{asset_type}/")]
                    for key in keys_to_remove:
                        del metadata['assets'][key]
                    self.save_metadata(metadata)
                
                print(f"Cleared {asset_type} cache")
            else:
                # Clear all cache
                if os.path.exists(self.assets_dir):
                    shutil.rmtree(self.assets_dir)
                if os.path.exists(self.metadata_file):
                    os.remove(self.metadata_file)
                
                self._ensure_cache_structure()
                print("Cleared all asset cache")
                
        except Exception as e:
            print(f"Error clearing cache: {e}")
    
    def validate_cache_integrity(self):
        """Validate integrity of cached assets"""
        issues = []
        cached_assets = self.get_cached_assets()
        
        for asset_type, assets in cached_assets.items():
            for asset in assets:
                path = asset['path']
                if not os.path.exists(path):
                    issues.append(f"Missing cached file: {path}")
                elif os.path.getsize(path) == 0:
                    issues.append(f"Empty cached file: {path}")
                elif not self._is_valid_asset_file(asset['name'], asset_type):
                    issues.append(f"Invalid asset type: {path}")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'assets_checked': sum(len(assets) for assets in cached_assets.values())
        }
    
    def _is_valid_asset_file(self, filename, asset_type):
        """Validate asset file by type"""
        filename_lower = filename.lower()
        
        if asset_type == 'presets':
            return filename_lower.endswith('.json')
        elif asset_type == 'fonts':
            return filename_lower.endswith(('.ttf', '.otf', '.woff', '.woff2'))
        elif asset_type == 'overlays':
            return filename_lower.endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv'))
        elif asset_type == 'bgmusic':
            return filename_lower.endswith(('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'))
        
        return False
    
    def get_asset_paths(self, drive_folder_id=None):
        """Get dictionary of asset type to file paths"""
        cached_assets = self.get_cached_assets(drive_folder_id)
        
        asset_paths = {}
        for asset_type, assets in cached_assets.items():
            if assets:
                # Return path to first asset of each type
                asset_paths[asset_type] = assets[0]['path']
        
        return asset_paths
    
    def cleanup_old_cache(self, days_old=30):
        """Clean up cache entries older than specified days"""
        try:
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
            metadata = self.load_metadata()
            
            # Remove old folder entries
            folders_to_remove = []
            for folder_id, folder_info in metadata.items():
                if isinstance(folder_info, dict) and 'cached_at' in folder_info:
                    try:
                        cached_at = datetime.datetime.fromisoformat(folder_info['cached_at'])
                        if cached_at < cutoff_date:
                            folders_to_remove.append(folder_id)
                    except:
                        pass
            
            for folder_id in folders_to_remove:
                del metadata[folder_id]
            
            # Remove old asset entries
            if 'assets' in metadata:
                assets_to_remove = []
                for asset_key, asset_info in metadata['assets'].items():
                    try:
                        cached_at = datetime.datetime.fromisoformat(asset_info['cached_at'])
                        if cached_at < cutoff_date:
                            assets_to_remove.append(asset_key)
                            # Remove actual file
                            asset_path = os.path.join(self.assets_dir, asset_key)
                            if os.path.exists(asset_path):
                                os.remove(asset_path)
                    except:
                        pass
                
                for asset_key in assets_to_remove:
                    del metadata['assets'][asset_key]
            
            self.save_metadata(metadata)
            print(f"Cleaned up cache entries older than {days_old} days")
            
        except Exception as e:
            print(f"Error during cache cleanup: {e}")

def main():
    """CLI interface for asset cache management"""
    import argparse
    
    parser = argparse.ArgumentParser(description='VideoStove Asset Cache Manager')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Status command
    subparsers.add_parser('status', help='Show cache status')
    
    # Clear command
    clear_parser = subparsers.add_parser('clear', help='Clear cache')
    clear_parser.add_argument('--type', help='Asset type to clear (all if not specified)')
    
    # Validate command
    subparsers.add_parser('validate', help='Validate cache integrity')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old cache entries')
    cleanup_parser.add_argument('--days', type=int, default=30, help='Remove entries older than N days')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    cache = AssetCache()
    
    if args.command == 'status':
        status = cache.get_cache_status()
        print("Asset Cache Status")
        print("=" * 50)
        print(f"Cache exists: {status['cache_exists']}")
        print(f"Assets cached: {status['assets_cached']}")
        print(f"Total assets: {status['total_assets']}")
        print(f"Cache size: {status['cache_size_bytes'] / 1024 / 1024:.1f} MB")
        print(f"Last updated: {status['last_updated'] or 'Never'}")
        print(f"Asset breakdown: {status['asset_breakdown']}")
    
    elif args.command == 'clear':
        cache.clear_cache(args.type)
    
    elif args.command == 'validate':
        validation = cache.validate_cache_integrity()
        print("Cache Validation Results")
        print("=" * 50)
        print(f"Valid: {validation['valid']}")
        print(f"Assets checked: {validation['assets_checked']}")
        if validation['issues']:
            print("Issues found:")
            for issue in validation['issues']:
                print(f"  - {issue}")
    
    elif args.command == 'cleanup':
        cache.cleanup_old_cache(args.days)

if __name__ == "__main__":
    main()