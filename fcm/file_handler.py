import os
import uuid
import logging
from werkzeug.utils import secure_filename
from datetime import datetime

logger = logging.getLogger(__name__)

class FileHandler:
    def __init__(self, base_dir):
        """Initialize file handler with base directory"""
        self.base_dir = base_dir
        self.upload_dir = os.path.join(base_dir, 'uploads')
        self.temp_dir = os.path.join(base_dir, 'temp')
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure required directories exist"""
        for directory in [self.upload_dir, self.temp_dir]:
            os.makedirs(directory, exist_ok=True)

    def _generate_unique_filename(self, original_filename):
        """Generate a unique filename while preserving extension"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        filename = secure_filename(original_filename)
        name, ext = os.path.splitext(filename)
        return f"{name}_{timestamp}_{unique_id}{ext}"

    def save_upload(self, file, category='csv'):
        """Save uploaded file securely"""
        try:
            if not file:
                raise ValueError("No file provided")

            filename = self._generate_unique_filename(file.filename)
            category_dir = os.path.join(self.upload_dir, category)
            os.makedirs(category_dir, exist_ok=True)
            
            file_path = os.path.join(category_dir, filename)
            file.save(file_path)
            
            logger.info(f"File saved successfully: {file_path}")
            return {
                'success': True,
                'path': file_path,
                'filename': filename
            }

        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_file_info(self, file_path):
        """Get information about a stored file"""
        try:
            if not os.path.exists(file_path):
                return None

            return {
                'path': file_path,
                'size': os.path.getsize(file_path),
                'modified': datetime.fromtimestamp(os.path.getmtime(file_path)),
                'filename': os.path.basename(file_path)
            }

        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return None

    def cleanup_old_files(self, max_age_hours=24):
        """Clean up old temporary files"""
        try:
            current_time = datetime.now().timestamp()
            max_age_seconds = max_age_hours * 3600

            for directory in [self.temp_dir, self.upload_dir]:
                for root, _, files in os.walk(directory):
                    for filename in files:
                        file_path = os.path.join(root, filename)
                        if current_time - os.path.getmtime(file_path) > max_age_seconds:
                            os.remove(file_path)
                            logger.info(f"Removed old file: {file_path}")

        except Exception as e:
            logger.error(f"Error cleaning up files: {e}")

    def move_to_permanent(self, temp_path, category='processed'):
        """Move file from temporary to permanent storage"""
        try:
            if not os.path.exists(temp_path):
                raise FileNotFoundError(f"File not found: {temp_path}")

            permanent_dir = os.path.join(self.base_dir, category)
            os.makedirs(permanent_dir, exist_ok=True)

            filename = os.path.basename(temp_path)
            new_path = os.path.join(permanent_dir, filename)

            os.rename(temp_path, new_path)
            logger.info(f"File moved to permanent storage: {new_path}")

            return {
                'success': True,
                'path': new_path
            }

        except Exception as e:
            logger.error(f"Error moving file to permanent storage: {e}")
            return {
                'success': False,
                'error': str(e)
            }