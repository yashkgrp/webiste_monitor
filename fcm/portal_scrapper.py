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
import chromedriver_autoinstaller
import pandas as pd
import pytz

logger = logging.getLogger(__name__)

class PortalScraper:
    def __init__(self, db_ops, socketio=None):
        self.db_ops = db_ops
        self.socketio = socketio
        self.session = requests.Session()
        self.debug_mode = db_ops is None
        self.debug_logs = []
        self.base_url = "https://fcm.finkraft.ai"
        
        # Scraper state tracking
        self.current_stage = 'initialization'
        self.current_step = None
        self.current_username = None
        self.current_portal = None
        self.execution_start = None
        
        # Setup directories
        current_dir = os.path.dirname(__file__)
        parent_dir = os.path.dirname(current_dir)
        self.temp_dir = os.path.join(parent_dir, 'temp')
        self.download_folder = os.path.join(parent_dir, "downloads")
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.download_folder, exist_ok=True)

        # Define scraping stages with member management as required
        self.stages = {
            'initialization': {
                'name': 'Setup',
                'steps': ['browser_setup', 'session_creation'],
                'required': True,
                'next': 'authentication'
            },
            'authentication': {
                'name': 'Login',
                'steps': ['load_login', 'enter_email', 'enter_password', 'verify_login'],
                'required': True,
                'next': 'member_management'
            },
            'member_management': {
                'name': 'Member Management',
                'steps': ['navigate_members', 'add_member', 'assign_workspace'],
                'required': True,
                'next': 'workspace_navigation',
                'blocking': True  # This stage must complete before next stages
            },
            'workspace_navigation': {
                'name': 'Workspace Navigation',
                'steps': ['navigate_flights', 'select_workspace'],
                'required': True,
                'requires': ['member_management'],
                'next': None  # No next stage after workspace navigation
            }
        }

        # Add constant configurations
        self.CONSTANT_MEMBER_DATA = {
            'name': 'mayuri',
            'email': 'sushu@yopmail.com',
            'workspace': 'Haldia tech',
            'role': 'User'
        }
        
        # Fixed CSV path in workspace
        self.CSV_PATH = os.path.join(os.path.dirname(__file__), 'data', 'invoice_list.csv')
        os.makedirs(os.path.dirname(self.CSV_PATH), exist_ok=True)

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
                'timestamp': datetime.now().isoformat()  # Use ISO format directly
            }
            if error:
                data['error'] = str(error)

            if self.debug_mode:
                self.debug_log('STATUS_EMIT', f"{stage} - {status}", data)

            if self.socketio:
                self.socketio.emit('portal_scraper_status', data)
                self.socketio.emit('portal_scraper_event', {
                    'type': 'status' if status != 'error' else 'error',
                    'message': f"{stage.title()}: {message}",
                    'timestamp': data['timestamp']  # Use the same ISO formatted timestamp
                })

        except Exception as e:
            logger.error(f"Socket emission error: {e}")

    def emit_stage_progress(self, stage, step, status, message, data=None):
        try:
            # Add stage color based on status
            status_colors = {
                'starting': '#fff3cd',  # yellow
                'in_progress': '#fff',  # white
                'completed': '#d4edda',  # green
                'error': '#f8d7da'  # red
            }

            current_time = datetime.now().isoformat()  # Use ISO format string

            progress_data = {
                'stage': stage,
                'stage_name': self.stages[stage]['name'],
                'step': step,
                'status': status,
                'message': message,
                'timestamp': current_time,
                'color': status_colors.get(status, '#fff'),
                'data': data or {}
            }

            if self.debug_mode:
                self.debug_log('STAGE_UPDATE', f"{stage} - {step}", progress_data)

            if self.socketio:
                # Emit stage progress
                self.socketio.emit('portal_scraper_progress', progress_data)
                
                # Also emit event log entry
                self.socketio.emit('portal_scraper_event', {
                    'type': 'info' if status != 'error' else 'error',
                    'stage': stage,
                    'step': step,
                    'message': f"{stage.title()}: {step} - {message}",
                    'timestamp': current_time
                })

            if self.db_ops:
                self.db_ops.update_scraper_progress(
                    username=self.current_username,
                    stage=stage,
                    step=step,
                    status=status,
                    message=message,
                    data=data
                )

        except Exception as e:
            logger.error(f"Error emitting stage progress: {e}")

    def emit_file_progress(self, file_type, status, message, data=None):
        """Emit file operation progress"""
        try:
            if self.socketio:
                self.socketio.emit('portal_file_progress', {
                    'type': file_type,
                    'status': status,
                    'message': message,
                    'data': data,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
        except Exception as e:
            logger.error(f"Error emitting file progress: {e}")

    def setup_chrome_driver(self):
        """Initialize Selenium WebDriver with automatic version detection"""
        try:
            self.emit_stage_progress('initialization', 'browser_setup', 'starting', 'Setting up Chrome browser')
            
            options = Options()
            prefs = {
                "download.default_directory": self.download_folder,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False
            }
            options.add_experimental_option("prefs", prefs)
            
            options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--window-size=1920,1400")
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument("--disable-blink-features=AutomationControlled")

            try:
                # Auto-detect and install matching ChromeDriver
                chromedriver_autoinstaller.install()
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                logger.info("Successfully initialized Chrome driver with auto-installer")
                
            except Exception as auto_error:
                logger.warning(f"Auto-installer failed: {auto_error}")
                # Fallback to manual version detection
                try:
                    chrome_version = chromedriver_autoinstaller.get_chrome_version()
                    logger.info(f"Detected Chrome version: {chrome_version}")
                    
                    service = Service(ChromeDriverManager(version=chrome_version).install())
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.implicitly_wait(10)
                    logger.info(f"Successfully initialized Chrome driver with version {chrome_version}")
                    
                except Exception as manual_error:
                    logger.error(f"Manual installation failed: {manual_error}")
                    raise Exception(f"Failed to initialize Chrome driver: {manual_error}")

            # Test the driver with base URL
            self.driver.get(f"{self.base_url}/auth/signin")
            self.emit_stage_progress('initialization', 'browser_setup', 'completed', 'Browser setup complete')
            return True

        except Exception as e:
            self.handle_error('initialization', 'browser_setup', e)
            raise Exception(f"Failed to setup Chrome driver: {e}")

    def login_to_portal(self, credentials):
        """Implement actual portal login logic using login.py's exact approach"""
        self.current_stage = 'authentication'
        try:
            self.emit_stage_progress('authentication', 'load_login', 'starting', 'Loading login page')
            
            # Store credentials for state tracking
            self.current_username = credentials.get('username')
            self.current_portal = credentials.get('portal', 'fcm')
            
            # Navigate to login page - using same sleep timing as login.py
            self.driver.get(f"{self.base_url}/auth/signin")
            time.sleep(2)
            
            # Enter email - exact xpath from login.py
            email_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="basic"]/div[1]/div/div/div/div/div/div/input'))
            )
            email_input.clear()
            email_input.send_keys(credentials['username'])
            time.sleep(1)
            
            # Click Sign in with password - exact xpath from login.py
            self.driver.find_element(By.XPATH, '//*[@id="basic"]/div[2]/button').click()
            time.sleep(2)
            
            # Enter password - exact xpath from login.py
            password_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="basic"]/div[2]/div/div/div/div/div/div/input'))
            )
            password_field.send_keys(credentials['password'])
            
            # Click login - exact xpath from login.py
            self.driver.find_element(By.XPATH, '//*[@id="basic"]/div[3]/button').click()
            time.sleep(25)  # Same 8 second wait as login.py
            
            # Verify login success
            if 'dashboard' in self.driver.current_url:
                self.emit_stage_progress('authentication', 'verify_login', 'completed', 'Login successful')
                time.sleep(5)  # Additional wait from login.py
                return True
            else:
                raise Exception("Login failed - Dashboard not loaded")

        except Exception as e:
            self.handle_error('authentication', self.current_step, e)
            raise

    def validate_stage_progression(self, stage):
        """Validate that required previous stages are completed"""
        if stage not in self.stages:
            raise ValueError(f"Invalid stage: {stage}")
            
        stage_config = self.stages[stage]
        required_stages = stage_config.get('requires', [])
        
        if required_stages:
            for required_stage in required_stages:
                if not hasattr(self, f'_{required_stage}_completed'):
                    raise ValueError(f"Stage {stage} cannot start: {required_stage} must be completed first")
        
        return True

    def manage_members(self, member_data=None):
        """Member management is now a required step"""
        self.current_stage = 'member_management'
        self.validate_stage_progression(self.current_stage)
        try:
            if not member_data:
                member_data = self.CONSTANT_MEMBER_DATA  # Use default data if none provided

            self.emit_stage_progress('member_management', 'navigate_members', 'starting', 'Navigating to members section')
            
            # Navigate to members - exact xpath from login.py
            self.driver.find_element(By.XPATH, '//*[@id="root"]/div/div[1]/div/div/div[2]/div[2]').click()
            time.sleep(1)

            self.emit_stage_progress('member_management', 'add_member', 'starting', 'Adding new member')
            
            # Click add button - exact xpath from login.py
            add = self.driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[1]/div/button')
            add.click()
            time.sleep(1)

            # Enter name - exact selector from login.py
            input_element = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Name"]'))
            )
            input_element.send_keys(member_data.get('name', 'New Member'))
            time.sleep(2)

            # Enter email - exact selector from login.py
            input_element = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Email"]'))
            )
            input_element.send_keys(member_data.get('email', 'test@example.com'))
            time.sleep(2)

            self.emit_stage_progress('member_management', 'assign_workspace', 'starting', 'Assigning workspace')

            # Search workspace - exact selector from login.py
            search_box = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[placeholder="Search Workspace"]'))
            )
            search_box.clear()
            search_box.send_keys(member_data.get('workspace', self.current_portal))
            time.sleep(2)

            # Select workspace - exact xpath from login.py
            first_workspace = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "(//p[contains(@class, 'sc-blHHSb kwGAvL')])[1]"))
            )
            first_workspace.click()
            time.sleep(1)

            # Select checkbox - exact xpath from login.py
            first_checkbox_label = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "(//label[contains(@class, 'ant-checkbox-wrapper')])[1]"))
            )
            first_checkbox_label.click()

            # Switch back to main page as in login.py
            self.driver.switch_to.default_content()
            time.sleep(3)

            # Select role - exact xpath from login.py
            dropdown = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/div/div[4]/div/div[1]/div[2]/div/div/span/span[2]'))
            )
            dropdown.click()
            time.sleep(1)

            option_xpath = f"//div[contains(@class, 'ant-select-item-option') and text()='{member_data.get('role', 'User')}']"
            selected_option = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, option_xpath))
            )
            selected_option.click()
            time.sleep(3)

            # Click Add - exact xpath from login.py
            self.driver.find_element(By.XPATH, '/html/body/div[4]/div/div[2]/div/div[1]/div/div[2]/div/div[5]/button[2]').click()
            time.sleep(3)

            self.emit_stage_progress('member_management', 'assign_workspace', 'completed', f"Member {member_data.get('email')} added successfully")
            print(f"✅ Member/User added successful for {member_data.get('email')}")
            
            # Mark member management as completed
            setattr(self, '_member_management_completed', True)
            return True

        except Exception as e:
            self.handle_error('member_management', self.current_step, e)
            raise

    def navigate_to_workspace(self):
        """Workspace navigation requires member management"""
        self.current_stage = 'workspace_navigation'
        self.validate_stage_progression(self.current_stage)
        try:
            self.emit_stage_progress('workspace_navigation', 'navigate_flights', 'starting', 'Navigating to flights section')
            
            # Click on Flights section
            flights_menu = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="root"]/div/div[1]/div/div/div[1]/div[2]/div[3]'))
            )
            flights_menu.click()
            time.sleep(3)
            
            # Select workspace
            self.emit_stage_progress('workspace_navigation', 'select_workspace', 'starting', 'Selecting workspace')
            
            dropdown = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="root"]/div/div[2]/div/div/div/div[1]/div[2]/div[2]/div'))
            )
            dropdown.click()
            time.sleep(1)
            
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search workspaces']"))
            )
            search_input.clear()
            search_input.send_keys(self.CONSTANT_MEMBER_DATA.get('workspace','Haldia tech'))
            time.sleep(2)
            print("code reached here ")
            
            workspace_option = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f"//span[@class='ant-dropdown-menu-title-content']//p[contains(text(),'{self.CONSTANT_MEMBER_DATA.get('workspace','Haldia tech')}')]"))
            )
            print(workspace_option)
            self.driver.execute_script("arguments[0].click();", workspace_option)
            time.sleep(2)
            
            dropdown.click() 
            print("code reached here ") # Close dropdown
            self.emit_stage_progress('workspace_navigation', 'select_workspace', 'completed', 'Workspace selected')
            
            setattr(self, '_workspace_navigation_completed', True)
            return True

        except Exception as e:
            self.handle_error('workspace_navigation', self.current_step, e)
            raise

    def _verify_downloads(self):
        """Helper method to verify downloaded files"""
        downloaded_files = []
        for file in os.listdir(self.download_folder):
            if file.endswith('.pdf') or file.endswith('.xlsx'):
                file_path = os.path.join(self.download_folder, file)
                if self.verify_file(file_path):
                    downloaded_files.append(file_path)
                    file_type = 'invoice' if file.endswith('.pdf') else 'report'
                    self.emit_file_progress(file_type, 'completed', f'{file_type.title()} downloaded successfully')
        return downloaded_files

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

    def handle_error(self, stage, step, error):
        """Handle errors with detailed frontend messages and proper notification format"""
        try:
            import traceback
            stack_trace = traceback.format_exc()
            
            # Get stage description
            stage_info = get_stage_description(stage, step)
            
            # Create detailed frontend-friendly error message
            frontend_message = (
                f"Error during {stage_info}\n"
                f"Type: {type(error).__name__}\n"
                f"Details: {str(error)}\n"
                f"Location: {stage}/{step}"
            )
            
            # Log the error
            logger.error(f"{frontend_message}\n{stack_trace}")
            
            # Emit frontend status with detailed message
            self.emit_status(stage, 'error', frontend_message)
            
            # Send notification if DB ops available
            if hasattr(self, 'db_ops') and self.db_ops:
                try:
                    from notification_handler import NotificationHandler
                    notification_handler = NotificationHandler(self.db_ops)
                    
                    # Format notification data according to handler's expected format
                    notification_data = {
                        'Ticket/PNR': self.current_username or 'Unknown',
                        'Traveller Name': self.current_portal or 'FCM Portal',
                    }
                    
                    # Send notification with proper format
                    notification_handler.send_scraper_notification(
                        error=str(error),  # Original error message
                        data=notification_data,
                        stage=f"{stage}/{step}",
                        airline="FCM Portal"
                    )
                    
                except Exception as notify_error:
                    logger.error(f"Failed to send notification: {notify_error}")
            
            # Store error state with detailed message for frontend
            if hasattr(self, 'db_ops') and self.db_ops:
                try:
                    self.db_ops.store_scraper_state(
                        username=self.current_username,
                        state='error',
                        message=frontend_message,  # Use detailed message for frontend
                        data={
                            'stage': stage,
                            'step': step,
                            'error': str(error),
                            'stack_trace': stack_trace,
                            'error_type': type(error).__name__
                        }
                    )
                except Exception as db_error:
                    logger.error(f"Failed to store error state: {db_error}")
                    
        except Exception as handler_error:
            logger.critical(f"Error handler failed: {handler_error}")
            # Ensure frontend gets some error message even if handler fails
            self.emit_status(stage, 'error', f"Critical error in {stage}/{step}: {str(error)}")

    def cleanup(self):
        """Cleanup resources"""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    def cleanup_downloads(self):
        """Clean up downloaded files after processing"""
        try:
            if not hasattr(self, 'driver'):
                return
                
            for file in os.listdir(self.download_folder):
                file_path = os.path.join(self.download_folder, file)
                try:
                    if os.path.isfile(file_path):
                        if self.verify_file(file_path):
                            # Move to permanent storage
                            file_type = 'invoices' if file.endswith('.pdf') else 'reports'
                            if self.db_ops and hasattr(self.db_ops, 'file_handler'):
                                self.db_ops.file_handler.move_to_permanent(file_path, file_type)
                            else:
                                os.remove(file_path)
                        else:
                            os.remove(file_path)
                except Exception as e:
                    logger.error(f"Error cleaning up file {file}: {e}")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

def get_stage_description(stage, step=None):
    """Get human-readable stage and step description"""
    stage_descriptions = {
        'initialization': {
            'name': 'System Initialization',
            'browser_setup': 'Setting up Chrome browser',
            'session_creation': 'Creating browser session'
        },
        'authentication': {
            'name': 'Portal Authentication',
            'load_login': 'Loading login page',
            'enter_email': 'Entering email address',
            'enter_password': 'Entering password',
            'verify_login': 'Verifying login success'
        },
        'member_management': {
            'name': 'Member Management',
            'navigate_members': 'Navigating to members section',
            'add_member': 'Adding new member',
            'assign_workspace': 'Assigning workspace to member'
        },
        'workspace_navigation': {
            'name': 'Workspace Management',
            'navigate_flights': 'Navigating to flights section',
            'select_workspace': 'Selecting workspace'
        }
    }
    
    if step:
        return f"{stage_descriptions.get(stage, {}).get('name', stage)} - {stage_descriptions.get(stage, {}).get(step, step)}"
    return stage_descriptions.get(stage, {}).get('name', stage)

def serialize_state(state):
    """Helper function to make state JSON serializable, including nested objects"""
    from google.cloud import firestore
    
    if not state:
        return None
        
    def _is_firebase_timestamp(obj):
        """Check if object is a Firebase timestamp"""
        return hasattr(obj, 'timestamp') and callable(obj.timestamp)
        
    def _convert_timestamp(timestamp_obj):
        """Convert Firebase timestamp to ISO string"""
        try:
            return datetime.fromtimestamp(timestamp_obj.timestamp()).isoformat()
        except:
            return str(timestamp_obj)
            
    def _handle_dict(d):
        """Handle dictionary with potential nested timestamps"""
        # Handle immutable objects by converting to dict first
        if hasattr(d, '_mapping'):
            d = dict(d._mapping)
        elif not isinstance(d, dict):
            try:
                d = dict(d)
            except:
                return str(d)
                
        result = {}
        for k, v in d.items():
            key = str(k)  # Convert all keys to strings
            if _is_firebase_timestamp(v):
                result[key] = _convert_timestamp(v)
            elif isinstance(v, dict):
                result[key] = _handle_dict(v)
            elif isinstance(v, (list, tuple)):
                result[key] = [_handle_value(item) for item in v]
            else:
                result[key] = _handle_value(v)
        return result
        
    def _handle_value(v):
        """Handle any value type"""
        if _is_firebase_timestamp(v):
            return _convert_timestamp(v)
        elif isinstance(v, dict):
            return _handle_dict(v)
        elif isinstance(v, (list, tuple)):
            return [_handle_value(item) for item in v]
        elif isinstance(v, datetime):
            return v.isoformat()
        elif hasattr(v, 'to_dict'):
            try:
                return _handle_dict(v.to_dict())
            except:
                return str(v)
        elif hasattr(v, '_document'):
            try:
                return _handle_dict(dict(v._document))
            except:
                return str(v)
        elif hasattr(v, '_mapping'):
            try:
                return _handle_dict(dict(v._mapping))
            except:
                return str(v)
        return v
        
    # Main conversion
    if isinstance(state, dict) or hasattr(state, '_mapping'):
        return _handle_dict(state)
    return _handle_value(state)

def run_scraper(data, db_ops=None, socketio=None):
    """Main scraper execution function with complete workflow and error handling"""
    scraper = PortalScraper(db_ops, socketio)
    start_time = time.time()
    notification_handler = None
    if db_ops:
        from notification_handler import NotificationHandler
        notification_handler = NotificationHandler(db_ops)
    
    # Initialize result data
    result_data = {
        'username': data.get('username'),
        'portal': data.get('portal', 'fcm'),
        'start_time': int(start_time * 1000),
        'stages_completed': []
    }
    
    try:
        # Setup browser
        scraper.setup_chrome_driver()
        result_data['stages_completed'].append('initialization')
        
        # Store initial state
        if db_ops:
            db_ops.store_scraper_state(
                username=data['username'],
                state='running',
                message='Initializing scraper',
                portal=data.get('portal', 'fcm'),
                password=data['password']
            )
        
        # Login to portal
        credentials = {
            'username': data['username'],
            'password': data['password'],
            'portal': data.get('portal', 'fcm')
        }
        login_success = scraper.login_to_portal(credentials)
        # login_success = True  # Skip login for testing
        if not login_success:
            raise Exception("Login failed - Could not access portal")
        result_data['stages_completed'].append('authentication')
        
        # Always perform member management first
        member_data = data.get('member_data', scraper.CONSTANT_MEMBER_DATA)
        scraper.manage_members(member_data)
        result_data['stages_completed'].append('member_management')
        result_data['member_added'] = member_data['email']
        
        if db_ops:
            db_ops.store_member_operation(
                username=credentials['username'],
                member_data=member_data
            )
        
        # After member management, proceed with workspace navigation
        scraper.navigate_to_workspace()
        result_data['stages_completed'].append('workspace_navigation')
        
        # Complete processing
        processing_time = round(time.time() - start_time, 2)
        result_data['processing_time'] = processing_time
        
        # Get current state data and serialize entire response
        if db_ops:
            last_state = db_ops.get_last_scraper_state()
            scheduler_settings = db_ops.get_scheduler_settings()
            
            # Store final success state
            db_ops.store_scraper_state(
                username=data['username'],
                state='completed',
                message='Portal operations completed successfully',
                data=result_data
            )
            
            # Serialize the entire response object
            response_data = {
                'success': True,
                'message': 'Portal operations completed successfully',
                'data': result_data,
                'lastState': last_state,
                'schedulerSettings': scheduler_settings,
                'timestamp': datetime.now()
            }
            
            if scraper.socketio:
                scraper.socketio.emit('portal_scraper_completed', serialize_state(response_data))

        return {
            "success": True,
            "message": "Portal operations completed successfully",
            "data": serialize_state(result_data)
        }
        
    except Exception as e:
        error_msg = f"Error in {scraper.current_stage}/{scraper.current_step}: {str(e)}"
        logger.error(f"Scraper error: {error_msg}")
        
        error_data = serialize_state({
            'username': data.get('username'),
            'portal': data.get('portal'),
            'error': error_msg,
            'stage': scraper.current_stage,
            'step': scraper.current_step,
            'start_time': int(start_time * 1000),
            'end_time': int(time.time() * 1000),
            'stages_completed': result_data.get('stages_completed', [])
        })
        
        # Send notification with proper format
        if notification_handler:
            try:
                notification_data = {
                    'Ticket/PNR': data.get('username', 'N/A'),
                    'Traveller Name': data.get('portal', 'FCM Portal'),
                }
                stage_info = f"{scraper.current_stage}/{scraper.current_step}"
                notification_handler.send_scraper_notification(
                    error=str(e),
                    data=notification_data,
                    stage=stage_info,
                    airline="FCM Portal"
                )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
        
        # Store error state with detailed message
        if db_ops:
            db_ops.store_scraper_state(
                username=data.get('username'),
                state='failed',
                message=error_msg,  # Use detailed message for frontend
                data=error_data
            )
            
            # Get current state with serialization
            last_state = db_ops.get_last_scraper_state()
            scheduler_settings = db_ops.get_scheduler_settings()
            
            error_response = {
                'success': False,
                'message': f"[{error_data['stage'].title()}{' - ' + error_data['step'] if error_data['step'] else ''}] {error_msg}",
                'data': error_data,
                'lastState': last_state,
                'schedulerSettings': scheduler_settings,
                'timestamp': datetime.now()
            }
            
            if scraper.socketio:
                scraper.socketio.emit('portal_scraper_completed', serialize_state(error_response))
        
        return {
            "success": False,
            "message": f"[{error_data['stage'].title()}{' - ' + error_data['step'] if error_data['step'] else ''}] {error_msg}",
            "data": error_data
        }
        
    finally:
        try:
            scraper.cleanup_downloads()
            scraper.cleanup()
        except Exception as cleanup_error:
            logger.error(f"Cleanup error: {cleanup_error}")

if __name__ == '__main__':
    # Test data with mandatory member management
    test_data = {
        'username': 'sushmitha@kgrp.in',
        'password': 'euMgvJFL',
        'portal': 'TestPortal',
        'member_data': {
            'name': 'mayuri',
            'email': 'sushu@yopmail.com',
            'workspace': 'Haldia tech',
            'role': 'User'
        }
    }
    
    print("[DEBUG] Starting portal scraper test with mandatory member management")
    result = run_scraper(test_data)
    print("\nExecution Result:")
    print(json.dumps(result, indent=2))

