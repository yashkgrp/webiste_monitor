import logging
import time
import requests
import json
import os
import tempfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

class PortalScraper:
    def __init__(self, db_ops, socketio=None):
        self.db_ops = db_ops
        self.socketio = socketio
        self.session = requests.Session()
        self.debug_mode = db_ops is None
        self.debug_logs = []
        
        # Scraper state tracking
        self.current_stage = 'initialization'
        self.current_step = None
        self.current_username = None  # Replace PNR
        self.current_portal = None    # Replace vendor
        self.execution_start = None
        
        # Setup temp directory
        current_dir = os.path.dirname(__file__)
        parent_dir = os.path.dirname(current_dir)
        self.temp_dir = os.path.join(parent_dir, 'temp')
        self.download_folder = os.path.join(parent_dir, "downloads")
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.download_folder, exist_ok=True)

        # Define scraping stages
        self.stages = {
            'initialization': {
                'name': 'Setup',
                'steps': ['browser_setup', 'session_creation']
            },
            'authentication': {
                'name': 'Login',
                'steps': ['load_login', 'enter_credentials', 'submit_login']
            },
            'navigation': {
                'name': 'Workspace Navigation',
                'steps': ['load_workspace', 'navigate_menu']
            },
            'processing': {
                'name': 'Invoice Processing',
                'steps': ['search_invoices', 'download_files', 'verify_files']
            }
        }

    def debug_log(self, category, message, data=None):
        if self.debug_mode:
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'category': category,
                'message': message,
                'data': data or {}
            }
            print(f"\n{'='*20} {category} {'='*20}")
            print(f"TIME: {log_entry['timestamp']}")
            print(f"MESSAGE: {message}")
            if data:
                print("DATA:", json.dumps(data, indent=2))
            print("="*50)
            self.debug_logs.append(log_entry)

    def emit_status(self, stage, status, message, timing=None, error=None):
        try:
            data = {
                'stage': stage,
                'status': status,
                'message': message,
                'timing': timing,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            if error:
                data['error'] = str(error)

            if self.debug_mode:
                self.debug_log('STATUS_EMIT', f"{stage} - {status}", data)

            if self.socketio:
                self.socketio.emit('portal_scraper_status', data)
                self.socketio.emit('portal_scraper_event', {
                    'type': 'status' if status != 'error' else 'error',
                    'message': f"{stage.title()}: {message}"
                })

        except Exception as e:
            logger.error(f"Socket emission error: {e}")

    def emit_stage_progress(self, stage, step, status, message, data=None):
        try:
            progress_data = {
                'stage': stage,
                'stage_name': self.stages[stage]['name'],
                'step': step,
                'status': status,
                'message': message,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': data or {}
            }

            if self.debug_mode:
                self.debug_log('STAGE_UPDATE', f"{stage} - {step}", progress_data)

            if self.socketio:
                self.socketio.emit('portal_scraper_progress', progress_data)

            if self.db_ops:
                self.db_ops.update_scraper_progress(
                    username=self.current_username,  # Changed from pnr
                    stage=stage,
                    step=step,
                    status=status,
                    message=message,
                    data=data
                )

        except Exception as e:
            logger.error(f"Error emitting stage progress: {e}")

    def setup_chrome_driver(self):
        """Initialize Selenium WebDriver with configuration"""
        try:
            self.emit_stage_progress('initialization', 'browser_setup', 'starting', 'Setting up Chrome browser')
            
            options = Options()
            prefs = {
                "download.default_directory": self.download_folder,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True
            }
            options.add_experimental_option("prefs", prefs)
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            self.driver.implicitly_wait(10)
            
            # Test the driver
            self.driver.get("about:blank")
            self.emit_stage_progress('initialization', 'browser_setup', 'completed', 'Browser setup complete')
            return True

        except Exception as e:
            self.handle_error('initialization', 'browser_setup', e)
            raise

    def login_to_portal(self, credentials):
        """Portal specific login logic"""
        self.current_stage = 'authentication'
        try:
            self.emit_stage_progress('authentication', 'load_login', 'starting', 'Loading login page')
            
            # Store credentials for state tracking
            self.current_username = credentials.get('username')
            self.current_portal = credentials.get('portal', 'unknown')
            
            # DEMO IMPLEMENTATION - Replace with actual portal logic
            self.driver.get("https://example.com/login")
            time.sleep(2)
            
            self.emit_stage_progress('authentication', 'enter_credentials', 'starting', 'Entering credentials')
            # Add actual credential entry logic here
            
            self.emit_stage_progress('authentication', 'submit_login', 'starting', 'Submitting login')
            # Add actual login submission logic here
            
            return True

        except Exception as e:
            self.handle_error('authentication', self.current_step, e)
            raise

    def navigate_to_workspace(self):
        """TO BE IMPLEMENTED: Portal specific navigation logic"""
        self.current_stage = 'navigation'
        try:
            self.emit_stage_progress('navigation', 'load_workspace', 'starting', 'Loading workspace')
            
            # DEMO IMPLEMENTATION
            self.driver.get("https://example.com/workspace")
            time.sleep(2)
            
            self.emit_stage_progress('navigation', 'navigate_menu', 'starting', 'Navigating to invoices')
            # Simulated menu navigation
            time.sleep(1)
            
            return True

        except Exception as e:
            self.handle_error('navigation', self.current_step, e)
            raise

    def process_invoices(self, search_criteria):
        """TO BE IMPLEMENTED: Portal specific invoice processing logic"""
        self.current_stage = 'processing'
        try:
            self.emit_stage_progress('processing', 'search_invoices', 'starting', 'Searching for invoices')
            
            # DEMO IMPLEMENTATION
            time.sleep(2)
            
            self.emit_stage_progress('processing', 'download_files', 'starting', 'Downloading invoice files')
            # Simulate file downloads
            time.sleep(2)
            
            # Create a dummy file for testing
            test_file = os.path.join(self.download_folder, "test_invoice.pdf")
            with open(test_file, "w") as f:
                f.write("Test invoice content")
            
            return [test_file]

        except Exception as e:
            self.handle_error('processing', self.current_step, e)
            raise

    def verify_file(self, file_path):
        """Verify downloaded file integrity"""
        try:
            if not os.path.exists(file_path):
                return False
            if os.path.getsize(file_path) < 100:  # Minimum size check
                return False
            return True
        except Exception as e:
            logger.error(f"File verification error: {e}")
            return False

    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
            # Optionally cleanup downloaded files
            # if os.path.exists(self.download_folder):
            #     for file in os.listdir(self.download_folder):
            #         os.remove(os.path.join(self.download_folder, file))
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

def run_scraper(data, db_ops=None, socketio=None):
    """Main scraper execution function"""
    scraper = PortalScraper(db_ops, socketio)
    start_time = time.time()
    
    try:
        # Initialize scraper context with username/portal instead of PNR/vendor
        scraper.current_username = data.get('username')
        scraper.current_portal = data.get('portal', 'unknown')
        
        # Setup browser
        scraper.setup_chrome_driver()
        
        # Login to portal with credentials
        credentials = {
            'username': data.get('username'),
            'password': data.get('password'),
            'portal': data.get('portal')
        }
        scraper.login_to_portal(credentials)
        
        # Navigate to workspace
        scraper.navigate_to_workspace()
        
        # Process invoices
        search_criteria = {
            'reference': scraper.current_pnr,
            'date_range': data.get('date_range')
        }
        processed_files = scraper.process_invoices(search_criteria)
        
        return {
            "success": True,
            "message": "Files downloaded successfully",
            "data": {
                'files': processed_files,
                'processing_time': round(time.time() - start_time, 2)
            }
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Scraper error: {error_msg}")
        return {
            "success": False,
            "message": error_msg,
            "data": {}
        }
        
    finally:
        scraper.cleanup()

if __name__ == '__main__':
    # Updated test data
    test_data = {
        'username': 'test_user',
        'password': 'test_pass',
        'portal': 'TestPortal',
        'date_range': {'start': '2024-01-01', 'end': '2024-01-31'}
    }
    
    print("[DEBUG] Starting portal scraper test")
    result = run_scraper(test_data)
    print("\nExecution Result:")
    print(json.dumps(result, indent=2))
