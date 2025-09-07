# Google Drive Integration for VideoStove
# Complete workflow: Download -> Detect Presets -> Select -> Batch Process -> Upload

import os
import json
import tempfile
import shutil
import base64
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
import datetime
from asset_cache import AssetCache

class DriveVideoStove:
    """Google Drive integrated VideoStove processor"""
    
    def __init__(self, credentials_path=None):
        # Support environment variables for RunPod deployment
        if not credentials_path:
            credentials_path = os.environ.get('GOOGLE_CREDENTIALS_PATH', 'credentials.json')
        
        # Support base64 encoded credentials in environment
        encoded_creds = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        if encoded_creds:
            credentials_path = self._decode_credentials(encoded_creds)
        
        self.service = self._authenticate(credentials_path)
        self.work_dir = None
        self.downloaded_presets = []
        self.discovered_projects = []
        self.available_assets = {}
        self.selected_assets = {}
        self.asset_cache = AssetCache()
        self.assets_folder_id = None
        
    def _decode_credentials(self, encoded_creds):
        """Decode base64 encoded credentials and save to temp file"""
        try:
            decoded = base64.b64decode(encoded_creds)
            temp_creds = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
            temp_creds.write(decoded.decode('utf-8'))
            temp_creds.close()
            print("Using base64 encoded credentials from environment")
            return temp_creds.name
        except Exception as e:
            print(f"ERROR: Failed to decode credentials: {e}")
            return None
    
    def _authenticate(self, credentials_path):
        """Authenticate with Google Drive API supporting both OAuth and Service Account"""
        SCOPES = ['https://www.googleapis.com/auth/drive']
        
        # Detect credential type by examining the file content
        try:
            with open(credentials_path, 'r') as f:
                creds_data = json.load(f)
        except FileNotFoundError:
            print(f"ERROR: {credentials_path} not found!")
            return None
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON in {credentials_path}")
            return None
        
        # Service Account authentication (for headless environments)
        if creds_data.get('type') == 'service_account':
            print("Using Service Account authentication (headless mode)")
            return self._authenticate_service_account(credentials_path, SCOPES)
        
        # OAuth authentication (for interactive environments)
        elif 'client_id' in creds_data:
            print("Using OAuth authentication (interactive mode)")
            return self._authenticate_oauth(credentials_path, SCOPES)
        
        else:
            print("ERROR: Unrecognized credential format")
            return None
    
    def _authenticate_service_account(self, credentials_path, scopes):
        """Service account authentication for headless environments"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=scopes
            )
            
            service = build('drive', 'v3', credentials=credentials)
            
            # Test the connection
            service.about().get(fields="user").execute()
            print("Service account authentication successful")
            return service
            
        except Exception as e:
            print(f"Service account authentication failed: {e}")
            return None
    
    def _authenticate_oauth(self, credentials_path, scopes):
        """OAuth authentication for interactive environments"""
        creds = None
        
        # Check for existing token
        if os.path.exists('token.json'):
            try:
                creds = Credentials.from_authorized_user_file('token.json', scopes)
            except Exception as e:
                print(f"Warning: Could not load existing token: {e}")
        
        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    print("OAuth token refreshed successfully")
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    creds = None
            
            if not creds:
                # Check if running in an interactive environment
                if self._is_interactive_environment():
                    creds = self._interactive_oauth_flow(credentials_path, scopes)
                else:
                    print("ERROR: OAuth requires interactive environment")
                    print("For headless deployment, use Service Account credentials")
                    return None
            
            # Save credentials for next run
            if creds:
                try:
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
                    print("OAuth credentials saved")
                except Exception as e:
                    print(f"Warning: Could not save token: {e}")
        
        if creds:
            return build('drive', 'v3', credentials=creds)
        return None
    
    def _is_interactive_environment(self):
        """Detect if running in an interactive environment"""
        try:
            # Check for Colab
            import google.colab
            return True
        except ImportError:
            pass
        
        # Check if we have a display
        import os
        return bool(os.environ.get('DISPLAY'))
    
    def _interactive_oauth_flow(self, credentials_path, scopes):
        """Handle OAuth flow for interactive environments"""
        try:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
            
            # Try local server first (works in most environments)
            try:
                creds = flow.run_local_server(port=0, open_browser=False)
                return creds
            except Exception:
                # Fallback to manual flow
                print("Local server authentication failed, using manual flow")
                return self._manual_oauth_flow(flow)
                
        except Exception as e:
            print(f"OAuth flow failed: {e}")
            return None
    
    def _manual_oauth_flow(self, flow):
        """Manual OAuth flow for environments without local server"""
        flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
        
        auth_url, _ = flow.authorization_url(prompt='consent')
        
        print("\nManual OAuth Authentication Required:")
        print("=" * 50)
        print(f"1. Visit this URL: {auth_url}")
        print("2. Authorize the application")
        print("3. Copy the authorization code")
        print("4. Paste it below")
        print("=" * 50)
        
        auth_code = input("Enter authorization code: ").strip()
        
        try:
            flow.fetch_token(code=auth_code)
            print("Manual OAuth authentication successful")
            return flow.credentials
        except Exception as e:
            print(f"Manual OAuth failed: {e}")
            return None
    
    def setup_workspace(self):
        """Create temporary workspace for processing (projects only, assets are cached)"""
        self.work_dir = tempfile.mkdtemp(prefix='videostove_drive_')
        print(f"Created workspace: {self.work_dir}")
        
        # Create subdirectories (no assets - they are cached persistently)
        os.makedirs(os.path.join(self.work_dir, 'projects'), exist_ok=True)
        os.makedirs(os.path.join(self.work_dir, 'outputs'), exist_ok=True)
        
        # Display cache status
        cache_status = self.asset_cache.get_cache_status()
        if cache_status['assets_cached']:
            print(f"🗄️ Asset cache available: {cache_status['total_assets']} assets ({cache_status['cache_size_bytes'] / 1024 / 1024:.1f} MB)")
        
        return self.work_dir
    
    def scan_drive_folder(self, folder_id):
        """Scan Google Drive folder for projects and presets"""
        print(f"Scanning Drive folder: {folder_id}")
        
        try:
            # Get folder contents
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            
            projects = []
            presets = []
            other_files = []
            
            assets_folder = None
            for file in files:
                if file['mimeType'] == 'application/vnd.google-apps.folder':
                    # Check if it's a project folder
                    if self._is_project_folder(file['id']):
                        projects.append(file)
                    # Check if it's assets folder (store for smart caching)
                    elif file['name'].lower() in ['assets', 'asset']:
                        assets_folder = file
                        self.assets_folder_id = file['id']
                elif file['name'].endswith('.json'):
                    # Check if it's a preset file
                    print(f"Checking JSON file for preset: {file['name']}")
                    if self._is_preset_file(file['id']):
                        presets.append(file)
                        print(f"✅ Valid preset found: {file['name']}")
                    else:
                        print(f"❌ Not a preset: {file['name']}")
                else:
                    other_files.append(file)
            
            # Handle assets separately through cache system
            assets_info = {}
            if assets_folder:
                print(f"📁 Assets folder found: {assets_folder['name']}")
                # Note: Assets will be handled through smart sync, not immediate scan
            
            print(f"Found: {len(projects)} projects, {len(presets)} presets, {len(other_files)} other files")
            
            return {
                'projects': projects,
                'presets': presets,
                'other_files': other_files,
                'assets': assets_info
            }
            
        except Exception as e:
            print(f"Error scanning folder: {e}")
            return None
    
    def _is_project_folder(self, folder_id):
        """Check if folder contains project files (images + audio)"""
        try:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(name, mimeType)"
            ).execute()
            
            files = results.get('files', [])
            
            has_audio = False
            has_images = False
            
            audio_exts = ['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg']
            image_exts = ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp']
            
            for file in files:
                name = file['name'].lower()
                if any(name.endswith(ext) for ext in audio_exts):
                    has_audio = True
                if any(name.endswith(ext) for ext in image_exts):
                    has_images = True
            
            return has_audio and has_images
            
        except Exception:
            return False
    
    def _is_preset_file(self, file_id):
        """Check if file is a VideoStove preset"""
        try:
            # Download file content
            request = self.service.files().get_media(fileId=file_id)
            content = request.execute()
            
            # Parse as JSON and check structure
            data = json.loads(content.decode('utf-8'))
            
            # Check for valid preset structures
            if 'preset' in data and isinstance(data['preset'], dict):
                return True  # UI export format
            elif 'metadata' in data and 'settings' in data:
                return True  # Full config export format
            elif 'presets' in data:
                return True  # Preset collection format
            elif 'image_duration' in data or 'main_audio_vol' in data:
                return True  # Single preset format
            
            return False
            
        except Exception as e:
            # Fallback: check if it's a JSON file by name
            return False
    
    def find_parent_folder(self, folder_id):
        """Find parent folder of given folder ID"""
        try:
            folder_info = self.service.files().get(
                fileId=folder_id, 
                fields="parents,name"
            ).execute()
            
            parents = folder_info.get('parents', [])
            if parents:
                parent_id = parents[0]
                parent_info = self.service.files().get(
                    fileId=parent_id,
                    fields="name,id"
                ).execute()
                
                print(f"Found parent folder: {parent_info['name']} ({parent_id})")
                return parent_id
            else:
                print("No parent folder found (root level)")
                return None
                
        except Exception as e:
            print(f"Error finding parent folder: {e}")
            return None
    
    def find_projects_from_assets_parent(self, assets_folder_id):
        """Find project folders in the parent of the assets folder"""
        try:
            # Find parent folder
            parent_folder_id = self.find_parent_folder(assets_folder_id)
            if not parent_folder_id:
                print("Cannot find projects - no parent folder")
                return []
            
            # Scan parent folder for project folders
            print(f"Scanning parent folder for projects: {parent_folder_id}")
            return self.scan_project_folders(parent_folder_id)
            
        except Exception as e:
            print(f"Error finding projects from assets parent: {e}")
            return []
    
    def scan_assets_folder(self, assets_folder_id):
        """Scan assets folder and categorize available resources including presets"""
        print(f"Scanning assets folder: {assets_folder_id}")
        
        try:
            assets_info = {
                'presets': [],
                'fonts': [],
                'overlays': [],
                'bgmusic': []
            }
            
            # Get subfolder contents for ALL asset types including presets
            for asset_type in ['presets', 'fonts', 'overlays', 'bgmusic']:
                assets_info[asset_type] = self._get_subfolder_contents(assets_folder_id, asset_type)
            
            # Add logging to show what was found
            preset_count = len(assets_info['presets'])
            font_count = len(assets_info['fonts'])
            overlay_count = len(assets_info['overlays'])
            bgmusic_count = len(assets_info['bgmusic'])
            
            print(f"Found assets: {preset_count} presets, {font_count} fonts, {overlay_count} overlays, {bgmusic_count} bgmusic files")
            
            self.available_assets = assets_info
            return assets_info
            
        except Exception as e:
            print(f"Error scanning assets folder: {e}")
            return {}
    
    def _get_subfolder_contents(self, assets_folder_id, subfolder_name):
        """Get contents of a specific asset subfolder"""
        try:
            # Find subfolder
            results = self.service.files().list(
                q=f"'{assets_folder_id}' in parents and name='{subfolder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            subfolders = results.get('files', [])
            if not subfolders:
                return []
            
            subfolder_id = subfolders[0]['id']
            
            # Get files in subfolder
            results = self.service.files().list(
                q=f"'{subfolder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType, size, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            
            # For presets, filter for JSON files and analyze them
            if subfolder_name == 'presets':
                valid_presets = []
                for file in files:
                    if file['mimeType'] != 'application/vnd.google-apps.folder' and file['name'].endswith('.json'):
                        # Add preset analysis
                        preset_info = self._analyze_preset_file_from_drive(file['id'], file['name'])
                        if preset_info:
                            preset_info['drive_file'] = file
                            valid_presets.append(preset_info)
                return valid_presets
            
            # For other asset types, return file info directly
            valid_files = []
            for file in files:
                if file['mimeType'] != 'application/vnd.google-apps.folder':
                    if self._is_valid_asset_file(file['name'], subfolder_name):
                        file['subfolder'] = subfolder_name
                        valid_files.append(file)
            
            return valid_files
            
        except Exception as e:
            print(f"Error getting {subfolder_name} contents: {e}")
            return []
    
    def _analyze_preset_file_from_drive(self, file_id, filename):
        """Analyze preset file directly from Drive without downloading to disk"""
        try:
            # Download file content to memory
            request = self.service.files().get_media(fileId=file_id)
            content = request.execute()
            
            # Parse JSON
            data = json.loads(content.decode('utf-8'))
            
            # Analyze preset data directly (no method call)
            if 'preset' in data and isinstance(data['preset'], dict):
                # Extract the inner preset object
                preset_data = next(iter(data['preset'].values()))
                preset_name = list(data['preset'].keys())[0]
                metadata = data.get('metadata', {})
                
                return {
                    'type': 'ui_export',
                    'name': preset_name,
                    'date': metadata.get('export_date', 'Unknown'),
                    'project_type': preset_data.get('project_type', 'montage'),
                    'description': f"UI exported preset: {preset_name}",
                    'settings': preset_data,
                    'file_id': file_id
                }
            else:
                print(f"Invalid preset format in {filename}")
                return None
                
        except Exception as e:
            print(f"Error analyzing preset file {filename}: {e}")
            return None
    
    def _is_valid_asset_file(self, filename, asset_type):
        """Check if file is a valid asset for the given type"""
        filename_lower = filename.lower()
        
        if asset_type == 'fonts':
            return filename_lower.endswith(('.ttf', '.otf', '.woff', '.woff2'))
        elif asset_type == 'overlays':
            return filename_lower.endswith(('.mp4', '.mov', '.avi', '.webm', '.mkv'))
        elif asset_type == 'bgmusic':
            return filename_lower.endswith(('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'))
        elif asset_type == 'presets':
            return filename_lower.endswith('.json')
        
        return False
    
    def download_selected_assets(self, assets_selection):
        """Download only the selected assets to local workspace"""
        if not assets_selection:
            return {}
        
        print("Downloading selected assets...")
        assets_dir = os.path.join(self.work_dir, 'assets')
        downloaded_assets = {}
        
        for asset_type, selected_file in assets_selection.items():
            if selected_file and selected_file != 'skip':
                try:
                    # Create type-specific directory
                    type_dir = os.path.join(assets_dir, asset_type)
                    os.makedirs(type_dir, exist_ok=True)
                    
                    # Download the file
                    local_path = os.path.join(type_dir, selected_file['name'])
                    self._download_asset_file(selected_file, local_path)
                    
                    downloaded_assets[asset_type] = local_path
                    print(f"  Downloaded {asset_type}: {selected_file['name']}")
                    
                except Exception as e:
                    print(f"  Error downloading {asset_type} asset: {e}")
        
        self.selected_assets = downloaded_assets
        return downloaded_assets
    
    def _download_asset_file(self, file_info, local_path):
        """Download individual asset file"""
        request = self.service.files().get_media(fileId=file_info['id'])
        
        with open(local_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
    
    def check_assets_cache(self, folder_id=None):
        """Compare local cache timestamp vs Drive assets folder"""
        if not folder_id:
            folder_id = self.assets_folder_id
        
        if not folder_id:
            return {'cache_valid': False, 'reason': 'No assets folder found'}
        
        try:
            # Get Drive folder modification time
            drive_modified_time = self._get_folder_modified_time(folder_id)
            
            # Check cache validity
            cache_valid = self.asset_cache.is_cache_valid(folder_id, drive_modified_time)
            
            return {
                'cache_valid': cache_valid,
                'drive_modified': drive_modified_time,
                'folder_id': folder_id,
                'cache_status': self.asset_cache.get_cache_status(folder_id)
            }
        except Exception as e:
            print(f"Error checking asset cache: {e}")
            return {'cache_valid': False, 'reason': f'Cache check failed: {e}'}
    
    def _get_folder_modified_time(self, folder_id):
        """Get Drive folder last modified timestamp"""
        try:
            file_info = self.service.files().get(
                fileId=folder_id,
                fields='modifiedTime'
            ).execute()
            
            return file_info.get('modifiedTime')
        except Exception as e:
            print(f"Error getting folder modified time: {e}")
            return None
    
    def _find_assets_folder_in(self, main_folder_id):
        """Find assets folder within the main folder"""
        if not main_folder_id:
            return None
            
        try:
            # Check if the folder_id is already an assets folder (direct assets folder ID case)
            # Try scanning it directly first
            results = self.service.files().list(
                q=f"'{main_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            subfolder_names = [f['name'].lower() for f in results.get('files', [])]
            if any(name in ['presets', 'fonts', 'overlays', 'bgmusic'] for name in subfolder_names):
                # This looks like an assets folder already
                print(f"📁 Using direct assets folder: {main_folder_id}")
                self.assets_folder_id = main_folder_id
                return main_folder_id
            
            # Otherwise, look for assets subfolder
            results = self.service.files().list(
                q=f"'{main_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            for folder in results.get('files', []):
                if folder['name'].lower() in ['assets', 'asset']:
                    print(f"📁 Found assets folder: {folder['name']} ({folder['id']})")
                    self.assets_folder_id = folder['id']
                    return folder['id']
            
            print(f"⚠️ No assets folder found in {main_folder_id}")
            return None
            
        except Exception as e:
            print(f"Error finding assets folder: {e}")
            return None
    
    def sync_assets_folder(self, folder_id=None, force_update=False):
        """Download assets only if needed (smart sync)"""
        if not folder_id:
            folder_id = self.assets_folder_id
        
        if not folder_id:
            print("No assets folder to sync")
            return {}
        
        # If we received a main folder ID, find the assets subfolder
        assets_folder_id = self._find_assets_folder_in(folder_id)
        
        if not assets_folder_id:
            print("No assets folder found in specified folder")
            return {}
        
        print("🔄 Checking asset cache...")
        
        # Check if cache is valid (use assets folder ID for cache check)
        cache_check = self.check_assets_cache(assets_folder_id)
        
        if not force_update and cache_check.get('cache_valid'):
            print("✅ Asset cache is current, using cached assets")
            return self.get_cached_assets()
        
        print("📥 Downloading assets from Drive...")
        
        try:
            # Get fresh asset information from Drive
            assets_info = self.scan_assets_folder(assets_folder_id)
            
            # Download and cache assets
            cached_assets = {}
            for asset_type, files in assets_info.items():
                cached_assets[asset_type] = []
                for file_info in files:
                    cached_path = self._download_and_cache_asset(file_info, asset_type)
                    if cached_path:
                        cached_assets[asset_type].append({
                            'name': file_info['name'],
                            'path': cached_path,
                            'size': file_info.get('size', 0),
                            'cached': True,
                            'drive_info': file_info
                        })
            
            # Update cache metadata
            drive_modified_time = self._get_folder_modified_time(assets_folder_id)
            self.asset_cache.update_folder_cache_info(
                assets_folder_id, 
                drive_modified_time, 
                [f"{k}/{f['name']}" for k, v in assets_info.items() for f in v]
            )
            
            print(f"✅ Assets cached: {sum(len(v) for v in cached_assets.values())} files")
            self.available_assets = cached_assets
            return cached_assets
            
        except Exception as e:
            print(f"Error syncing assets: {e}")
            # Fallback to cached assets if available
            cached_assets = self.get_cached_assets()
            if cached_assets:
                print("⚠️ Using cached assets due to sync error")
                return cached_assets
            return {}
    
    def _download_and_cache_asset(self, file_info, asset_type):
        """Download asset file and store in cache"""
        try:
            # Download file content
            request = self.service.files().get_media(fileId=file_info['id'])
            content = request.execute()
            
            # Save to cache
            cached_path = self.asset_cache.save_asset(
                asset_type, 
                file_info['name'], 
                content, 
                file_info
            )
            
            return cached_path
            
        except Exception as e:
            print(f"Error caching asset {file_info['name']}: {e}")
            return None
    
    def get_cached_assets(self):
        """Load assets from cache"""
        return self.asset_cache.get_cached_assets(self.assets_folder_id)
    
    def download_presets(self, preset_files):
        """Download and analyze preset files"""
        self.downloaded_presets = []
        presets_dir = os.path.join(self.work_dir, 'presets')
        
        for preset_file in preset_files:
            try:
                print(f"Downloading preset: {preset_file['name']}")
                
                # Download file
                local_path = os.path.join(presets_dir, preset_file['name'])
                self._download_file(preset_file['id'], local_path)
                
                # Analyze preset
                preset_info = self._analyze_preset_file(local_path)
                if preset_info:
                    preset_info['drive_file'] = preset_file
                    preset_info['local_path'] = local_path
                    self.downloaded_presets.append(preset_info)
                    print(f"  Valid preset: {preset_info['name']}")
                else:
                    print(f"  Invalid preset file: {preset_file['name']}")
                    
            except Exception as e:
                print(f"Error downloading preset {preset_file['name']}: {e}")
        
        return self.downloaded_presets
    
    def _analyze_preset_file(self, file_path):
        """Analyze preset file and extract metadata"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle nested preset structure from UI exports
            if 'preset' in data and isinstance(data['preset'], dict):
                # Extract the inner preset object
                preset_data = next(iter(data['preset'].values()))
                preset_name = list(data['preset'].keys())[0]
                metadata = data.get('metadata', {})
                
                return {
                    'type': 'ui_export',
                    'name': preset_name,
                    'date': metadata.get('export_date', 'Unknown'),
                    'project_type': preset_data.get('project_type', 'montage'),
                    'description': f"UI exported preset: {preset_name}",
                    'settings': preset_data,
                    'preset_count': 1
                }
            
            # Check if it's a VideoStove export (full config)
            elif 'metadata' in data and 'settings' in data:
                settings = data['settings']
                return {
                    'type': 'full_config',
                    'name': data['metadata'].get('export_name', 'Unknown Config'),
                    'date': data['metadata'].get('export_date', 'Unknown'),
                    'project_type': settings.get('project_type', 'montage'),
                    'settings': settings,
                    'preset_count': 1,
                    'description': f"Full configuration export"
                }
            
            # Check if it's preset collection
            elif 'presets' in data:
                metadata = data.get('metadata', {})
                preset_count = len(data['presets'])
                # Get project_type from first preset
                first_preset = next(iter(data['presets'].values())) if data['presets'] else {}
                return {
                    'type': 'preset_collection',
                    'name': metadata.get('export_name', f'Preset Collection'),
                    'date': metadata.get('export_date', 'Unknown'),
                    'project_type': first_preset.get('project_type', 'montage'),
                    'settings': first_preset,
                    'preset_count': preset_count,
                    'description': f"Collection of {preset_count} presets"
                }
            
            # Check if it's single preset
            elif 'image_duration' in data or 'main_audio_vol' in data:
                return {
                    'type': 'single_preset',
                    'name': os.path.basename(file_path).replace('.json', ''),
                    'date': 'Unknown',
                    'project_type': data.get('project_type', 'montage'),
                    'settings': data,
                    'preset_count': 1,
                    'description': "Single preset configuration"
                }
            
            return None
            
        except Exception as e:
            print(f"Error analyzing preset: {e}")
            return None
    
    def _download_file(self, file_id, local_path):
        """Download a file from Google Drive"""
        request = self.service.files().get_media(fileId=file_id)
        
        with open(local_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
    
    def download_projects(self, project_folders):
        """Download project folders from Google Drive"""
        projects_dir = os.path.join(self.work_dir, 'projects')
        self.discovered_projects = []
        
        for project_folder in project_folders:
            try:
                print(f"Downloading project: {project_folder['name']}")
                
                # Create local project directory
                project_path = os.path.join(projects_dir, project_folder['name'])
                os.makedirs(project_path, exist_ok=True)
                
                # Download all files in project folder
                files_downloaded = self._download_folder_contents(project_folder['id'], project_path)
                
                if files_downloaded > 0:
                    # Analyze project structure
                    project_info = self._analyze_project(project_path, project_folder['name'])
                    self.discovered_projects.append(project_info)
                    print(f"  Downloaded {files_downloaded} files")
                else:
                    print(f"  No files downloaded for {project_folder['name']}")
                    
            except Exception as e:
                print(f"Error downloading project {project_folder['name']}: {e}")
        
        return self.discovered_projects
    
    def _download_folder_contents(self, folder_id, local_path):
        """Download all contents of a folder"""
        try:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType)"
            ).execute()
            
            files = results.get('files', [])
            downloaded_count = 0
            
            for file in files:
                if file['mimeType'] != 'application/vnd.google-apps.folder':
                    file_path = os.path.join(local_path, file['name'])
                    self._download_file(file['id'], file_path)
                    downloaded_count += 1
            
            return downloaded_count
            
        except Exception as e:
            print(f"Error downloading folder contents: {e}")
            return 0
    
    def _analyze_project(self, project_path, project_name):
        """Analyze downloaded project and categorize files"""
        image_files = []
        video_files = []
        audio_files = []
        
        image_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')
        video_exts = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.flv')
        audio_exts = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg')
        
        for file in os.listdir(project_path):
            file_path = os.path.join(project_path, file)
            if os.path.isfile(file_path):
                file_lower = file.lower()
                
                if file_lower.endswith(image_exts):
                    image_files.append(file_path)
                elif file_lower.endswith(video_exts):
                    # Skip overlay videos
                    if not any(keyword in file_lower for keyword in ['overlay', 'effect', 'particle']):
                        video_files.append(file_path)
                elif file_lower.endswith(audio_exts):
                    audio_files.append(file_path)
        
        # Sort files naturally
        try:
            import natsort
            image_files = natsort.natsorted(image_files)
            video_files = natsort.natsorted(video_files)
            audio_files = natsort.natsorted(audio_files)
        except ImportError:
            image_files = sorted(image_files)
            video_files = sorted(video_files)
            audio_files = sorted(audio_files)
        
        return {
            'name': project_name,
            'path': project_path,
            'images': image_files,
            'videos': video_files,
            'audio': audio_files[0] if audio_files else None,
            'bg_music': audio_files[1] if len(audio_files) > 1 else None,
            'type': 'mixed' if video_files and image_files else ('video_only' if video_files else 'slideshow')
        }
    
    def display_preset_selection(self):
        """Display available presets for selection"""
        if not self.downloaded_presets:
            print("No presets available for selection")
            return None
        
        print("\nAvailable Presets:")
        print("=" * 50)
        
        for i, preset in enumerate(self.downloaded_presets, 1):
            print(f"{i}. {preset['name']}")
            print(f"   Type: {preset['type']}")
            print(f"   Date: {preset['date']}")
            print(f"   Description: {preset['description']}")
            print()
        
        while True:
            try:
                choice = input(f"Select preset (1-{len(self.downloaded_presets)}) or 'q' to quit: ").strip()
                
                if choice.lower() == 'q':
                    return None
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(self.downloaded_presets):
                    selected = self.downloaded_presets[choice_num - 1]
                    print(f"Selected preset: {selected['name']}")
                    return selected
                else:
                    print("Invalid selection. Please try again.")
                    
            except ValueError:
                print("Please enter a number or 'q' to quit.")
    
    def load_preset_config(self, preset_info):
        """Load configuration from selected preset"""
        try:
            # If settings are already extracted in preset_info, use them
            if 'settings' in preset_info and preset_info['settings']:
                return preset_info['settings']
            
            # Otherwise load from file
            with open(preset_info['local_path'], 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract settings based on preset type
            if preset_info['type'] == 'ui_export':
                # Handle UI exported nested structure
                preset_data = next(iter(data['preset'].values()))
                return preset_data
            elif preset_info['type'] == 'full_config':
                return data.get('settings', {})
            elif preset_info['type'] == 'preset_collection':
                # For collections, use the first preset or prompt for selection
                presets = data.get('presets', {})
                if presets:
                    first_preset = next(iter(presets.values()))
                    return first_preset
            elif preset_info['type'] == 'single_preset':
                return data
            
            return {}
            
        except Exception as e:
            print(f"Error loading preset config: {e}")
            return {}
    
    def filter_projects_by_mode(self, projects, project_type):
        """Filter projects based on selected preset's project_type"""
        if not projects:
            return []
        
        if project_type == "slideshow":
            # Only process projects with images and no videos
            return [p for p in projects if p.get('images', []) and not p.get('videos', [])]
        elif project_type == "videos_only":
            # Only process projects with videos
            return [p for p in projects if p.get('videos', [])]
        elif project_type == "montage":
            # Process projects with videos OR mixed content
            return [p for p in projects if p.get('videos', []) or p.get('images', [])]
        else:
            # Process all projects for unknown types
            return projects
    
    def scan_project_folders(self, main_folder_id):
        """Scan for project folders (separate from assets)"""
        try:
            results = self.service.files().list(
                q=f"'{main_folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            projects = []
            
            for file in files:
                if file['mimeType'] == 'application/vnd.google-apps.folder':
                    # Skip assets folder
                    if file['name'].lower() not in ['assets', 'asset']:
                        # Check if it's a project folder
                        if self._is_project_folder(file['id']):
                            projects.append(file)
            
            return projects
            
        except Exception as e:
            print(f"Error scanning project folders: {e}")
            return []
    
    def get_project_compatibility_info(self, project, project_type):
        """Get compatibility information for a project"""
        has_images = bool(project.get('images', []))
        has_videos = bool(project.get('videos', []))
        
        if project_type == "slideshow":
            compatible = has_images and not has_videos
            reason = None if compatible else (
                "No images found" if not has_images else "Contains videos (slideshow mode is images-only)"
            )
        elif project_type == "videos_only": 
            compatible = has_videos
            reason = None if compatible else "No videos found"
        elif project_type == "montage":
            compatible = has_images or has_videos
            reason = None if compatible else "No media content found"
        else:
            compatible = True
            reason = None
        
        return {
            'compatible': compatible,
            'reason': reason,
            'has_images': has_images,
            'has_videos': has_videos
        }
    
    def batch_process_projects(self, config, output_folder_id, selected_assets=None):
        """Process all downloaded projects using selected configuration"""
        if not self.discovered_projects:
            print("No projects to process")
            return
        
        print(f"\nProcessing {len(self.discovered_projects)} projects...")
        outputs_dir = os.path.join(self.work_dir, 'outputs')
        
        # Import VideoCreator (assuming it's available)
        try:
            from videostove_core import VideoCreator, CONFIG
            
            # Update global config
            CONFIG.update(config)
            
            creator = VideoCreator(update_callback=print, global_assets=selected_assets)
            
            for i, project in enumerate(self.discovered_projects, 1):
                print(f"\nProcessing project {i}/{len(self.discovered_projects)}: {project['name']}")
                
                try:
                    output_file = os.path.join(outputs_dir, f"{project['name']}.mp4")
                    
                    success = creator.create_slideshow(
                        image_files=project['images'],
                        video_files=project['videos'],
                        main_audio=project['audio'],
                        bg_music=project.get('bg_music'),
                        overlay_video=None,  # Could be enhanced to support overlays
                        output_file=output_file
                    )
                    
                    if success and os.path.exists(output_file):
                        print(f"✅ Success: {project['name']}")
                        
                        # Upload to Drive
                        if output_folder_id:
                            self._upload_result(output_file, output_folder_id, project['name'])
                    else:
                        print(f"❌ Failed: {project['name']}")
                        
                except Exception as e:
                    print(f"❌ Error processing {project['name']}: {e}")
        
        except ImportError:
            print("VideoCreator not available - would process projects here")
            # Simulation mode for testing
            for project in self.discovered_projects:
                print(f"Would process: {project['name']} ({project['type']})")
    
    def _upload_result(self, local_file, folder_id, project_name):
        """Upload processed video to Google Drive"""
        try:
            filename = f"{project_name}_processed.mp4"
            
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            
            media = MediaFileUpload(local_file, resumable=True)
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            print(f"📤 Uploaded: {filename} (ID: {file.get('id')})")
            
        except Exception as e:
            print(f"Upload failed for {project_name}: {e}")
    
    def cleanup(self, preserve_cache=True):
        """Clean up temporary workspace (preserve asset cache by default)"""
        if self.work_dir and os.path.exists(self.work_dir):
            shutil.rmtree(self.work_dir)
            print(f"Cleaned up workspace: {self.work_dir}")
        
        if preserve_cache:
            cache_status = self.asset_cache.get_cache_status()
            if cache_status['assets_cached']:
                print(f"🗄️ Asset cache preserved: {cache_status['total_assets']} assets")

# Main workflow function
def main_drive_workflow():
    """Main workflow for Drive integration testing"""
    print("Google Drive VideoStove Integration Test")
    print("=" * 40)
    
    # Get Drive folder ID from user
    folder_id = input("Enter Google Drive folder ID: ").strip()
    output_folder_id = input("Enter output folder ID (optional): ").strip() or None
    
    # Initialize Drive processor
    drive_processor = DriveVideoStove()
    
    if not drive_processor.service:
        print("Failed to authenticate with Google Drive")
        return
    
    try:
        # Setup workspace
        drive_processor.setup_workspace()
        
        # Scan Drive folder
        scan_results = drive_processor.scan_drive_folder(folder_id)
        if not scan_results:
            print("Failed to scan Drive folder")
            return
        
        # Download presets
        if scan_results['presets']:
            print("\nDownloading presets...")
            drive_processor.download_presets(scan_results['presets'])
        else:
            print("No presets found in Drive folder")
            return
        
        # Download projects
        if scan_results['projects']:
            print("\nDownloading projects...")
            drive_processor.download_projects(scan_results['projects'])
        else:
            print("No projects found in Drive folder")
            return
        
        # Display and select preset
        selected_preset = drive_processor.display_preset_selection()
        if not selected_preset:
            print("No preset selected, exiting")
            return
        
        # Load configuration
        config = drive_processor.load_preset_config(selected_preset)
        print(f"Loaded configuration: {len(config)} settings")
        
        # Download and select assets if available
        selected_assets = {}
        if scan_results.get('assets'):
            print("\nAssets found in Drive folder!")
            assets_info = scan_results['assets']
            if any(len(assets_info[key]) > 0 for key in assets_info):
                # Simple asset selection (could be enhanced)
                print("Available assets:")
                for asset_type, files in assets_info.items():
                    if files:
                        print(f"  {asset_type}: {len(files)} files")
                
                # For now, automatically use first asset of each type
                assets_selection = {}
                for asset_type, files in assets_info.items():
                    if files:
                        assets_selection[asset_type] = files[0]
                
                selected_assets = drive_processor.download_selected_assets(assets_selection)
        
        # Process projects
        drive_processor.batch_process_projects(config, output_folder_id, selected_assets)
        
        print("\nWorkflow completed!")
        
    finally:
        # Cleanup
        drive_processor.cleanup()

if __name__ == "__main__":
    main_drive_workflow()
