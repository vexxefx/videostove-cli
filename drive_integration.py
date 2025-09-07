# Google Drive Integration for VideoStove
# Complete workflow: Download -> Detect Presets -> Select -> Batch Process -> Upload

import os
import json
import tempfile
import shutil
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import datetime

class DriveVideoStove:
    """Google Drive integrated VideoStove processor"""
    
    def __init__(self, credentials_path='credentials.json'):
        self.service = self._authenticate(credentials_path)
        self.work_dir = None
        self.downloaded_presets = []
        self.discovered_projects = []
        
    def _authenticate(self, credentials_path):
        """Authenticate with Google Drive API"""
        SCOPES = ['https://www.googleapis.com/auth/drive']
        creds = None
        
        # Check for existing token
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(credentials_path):
                    print(f"ERROR: {credentials_path} not found!")
                    print("Download credentials from Google Cloud Console")
                    return None
                
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
        return build('drive', 'v3', credentials=creds)
    
    def setup_workspace(self):
        """Create temporary workspace for processing"""
        self.work_dir = tempfile.mkdtemp(prefix='videostove_drive_')
        print(f"Created workspace: {self.work_dir}")
        
        # Create subdirectories
        os.makedirs(os.path.join(self.work_dir, 'projects'), exist_ok=True)
        os.makedirs(os.path.join(self.work_dir, 'presets'), exist_ok=True)
        os.makedirs(os.path.join(self.work_dir, 'outputs'), exist_ok=True)
        
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
            
            for file in files:
                if file['mimeType'] == 'application/vnd.google-apps.folder':
                    # Check if it's a project folder
                    if self._is_project_folder(file['id']):
                        projects.append(file)
                elif file['name'].endswith('.json'):
                    # Check if it's a preset file
                    if self._is_preset_file(file['id']):
                        presets.append(file)
                else:
                    other_files.append(file)
            
            print(f"Found: {len(projects)} projects, {len(presets)} presets, {len(other_files)} other files")
            
            return {
                'projects': projects,
                'presets': presets,
                'other_files': other_files
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
            # Download first 1KB to check structure
            request = self.service.files().get_media(fileId=file_id)
            content = request.execute()[:1024].decode('utf-8', errors='ignore')
            
            # Quick check for VideoStove preset structure
            return '"videostove" in content.lower() or "presets" in content.lower()'
            
        except Exception:
            return False
    
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
            
            # Check if it's a VideoStove export (full config)
            if 'metadata' in data and 'settings' in data:
                return {
                    'type': 'full_config',
                    'name': data['metadata'].get('export_name', 'Unknown Config'),
                    'date': data['metadata'].get('export_date', 'Unknown'),
                    'preset_count': 1,
                    'description': f"Full configuration export"
                }
            
            # Check if it's preset collection
            elif 'presets' in data:
                metadata = data.get('metadata', {})
                preset_count = len(data['presets'])
                return {
                    'type': 'preset_collection',
                    'name': metadata.get('export_name', f'Preset Collection'),
                    'date': metadata.get('export_date', 'Unknown'),
                    'preset_count': preset_count,
                    'description': f"Collection of {preset_count} presets"
                }
            
            # Check if it's single preset
            elif 'image_duration' in data or 'main_audio_vol' in data:
                return {
                    'type': 'single_preset',
                    'name': os.path.basename(file_path).replace('.json', ''),
                    'date': 'Unknown',
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
            with open(preset_info['local_path'], 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract settings based on preset type
            if preset_info['type'] == 'full_config':
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
    
    def batch_process_projects(self, config, output_folder_id):
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
            
            creator = VideoCreator(update_callback=print)
            
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
    
    def cleanup(self):
        """Clean up temporary workspace"""
        if self.work_dir and os.path.exists(self.work_dir):
            shutil.rmtree(self.work_dir)
            print(f"Cleaned up workspace: {self.work_dir}")

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
        
        # Process projects
        drive_processor.batch_process_projects(config, output_folder_id)
        
        print("\nWorkflow completed!")
        
    finally:
        # Cleanup
        drive_processor.cleanup()

if __name__ == "__main__":
    main_drive_workflow()
