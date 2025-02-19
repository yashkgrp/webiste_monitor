import logging
import time
import requests
import json
import os
import tempfile
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys  # Add this for Keys.BACKSPACE
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import chromedriver_autoinstaller  # Add this for auto installation
import allure  # Add this for test reporting
import pandas as pd  # Add this for DataFrame operations
import pytest  # Add this for test fixtures
import random
import string
import re
import uuid  # Add this import at the top with other imports

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
                'steps': ['load_login', 'enter_credentials', 'verify_login']
            },
            'company_setup': {
                'name': 'Company Details',
                'steps': ['load_form', 'enter_details', 'save_company']
            },
            'tax_manager_setup': {
                'name': 'Tax Manager Details',
                'steps': ['load_form', 'enter_details', 'save_manager']
            },
            'travel_contact_setup': {
                'name': 'Travel Contact Details',
                'steps': ['load_form', 'enter_details', 'save_contact']
            },
            'preview': {
                'name': 'Preview & Submit',
                'steps': ['review_details', 'final_submission']
            }
        }

        # Remove hardcoded COMPANY_DETAILS and add generator methods
        def generate_company_name():
            """Generate unique company name with UUID"""
            prefixes = ['Tech', 'Global', 'India', 'Meta', 'Sky', 'Blue', 'Green', 'Red']
            suffixes = ['Systems', 'Solutions', 'Technologies', 'Services', 'Enterprises']
            random_num = ''.join(random.choices(string.digits, k=3))
            unique_id = str(uuid.uuid4())[:8].lower()  # Ensure lowercase for validation
            return f"{random.choice(prefixes)} {random.choice(suffixes)} {random_num}-{unique_id}"

        def generate_website(company_name):
            """Generate website with unique domain"""
            # Remove UUID part for cleaner domain
            base_name = company_name.split('-')[0]
            # Convert company name to URL-friendly format
            domain = base_name.lower().replace(' ', '').replace('_', '')
            tlds = ['.com', '.in', '.org', '.net']
            unique_id = str(uuid.uuid4())[:4]  # Use 4 chars of UUID for domain
            return f"www.{domain}{unique_id}{random.choice(tlds)}"

        def generate_pan():
            """Generate valid PAN number following Indian PAN card rules"""
            # First 5 chars: Letters
            first_five = ''.join(random.choices(string.ascii_uppercase, k=5))
            # Next 4 chars: Numbers
            numbers = ''.join(random.choices(string.digits, k=4))
            # Last char: Letter
            last_char = random.choice(string.ascii_uppercase)
            return f"{first_five}{numbers}{last_char}"

        # Generate validated details
        company_name = generate_company_name()
        self.COMPANY_DETAILS = {
            "name": company_name,
            "website": generate_website(company_name),
            "pan": generate_pan()
        }

        # Update validation patterns to accept UUID format
        self.validation_patterns = {
            'company_name': r'^[A-Za-z\s]+\s[A-Za-z\s]+\s\d{3}-[a-f0-9]{8}$',  # Updated to match UUID format
            'website': r'^www\.[a-z0-9-]+[a-f0-9]{4}\.[a-z]{2,}$',  # Updated to match UUID in domain
            'pan': r'^[A-Z]{5}[0-9]{4}[A-Z]$'
        }

        self.TAX_MANAGER_DETAILS = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "1234567890",
            "linkedin": "linkedin.com/johndoe"
        }

        self.TRAVEL_CONTACT_DETAILS = {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "9876543210",
            "linkedin": "linkedin.com/janedoe"
        }

        self.PORTAL_URLS = {
            'base': "https://qatarnew.finkraft.ai",
            'login': "https://qatarnew.finkraft.ai/login",
            'register': "https://qatarnew.finkraft.ai/register"
        }

        # Add error contexts mapping
        self.error_contexts = {
            'initialization': {
                'browser_setup': 'Failed to set up Chrome browser',
                'session_creation': 'Failed to create browser session'
            },
            'authentication': {
                'load_login': 'Failed to load login page',
                'enter_credentials': 'Failed to enter credentials',
                'verify_login': 'Failed to verify login'
            },
            'company_setup': {
                'load_form': 'Failed to load company form',
                'enter_details': 'Failed to enter company details',
                'save_company': 'Failed to save company details'
            },
            'tax_manager_setup': {
                'load_form': 'Failed to load tax manager form',
                'enter_details': 'Failed to enter tax manager details',
                'save_manager': 'Failed to save tax manager details'
            },
            'travel_contact_setup': {
                'load_form': 'Failed to load travel contact form',
                'enter_details': 'Failed to enter travel contact details',
                'save_contact': 'Failed to save travel contact details'
            },
            'preview': {
                'review_details': 'Failed to load preview',
                'final_submission': 'Failed to submit details'
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
            # Define stage colors with better mapping
            stage_colors = {
                'starting': '#fff3cd',     # Yellow
                'in_progress': '#fff3cd',  # Yellow
                'completed': '#d4edda',    # Green
                'error': '#f8d7da',        # Red
                'default': '#ffffff'        # White
            }

            # Map status to colors more explicitly
            color = stage_colors.get(status, stage_colors['default'])
            
            # For 'verify_login' step, use green when completed
            if step == 'verify_login' and status == 'completed':
                color = stage_colors['completed']
            
            progress_data = {
                'stage': stage,
                'stage_name': self.stages[stage]['name'],
                'step': step,
                'step_index': self.stages[stage]['steps'].index(step) if step in self.stages[stage]['steps'] else 0,
                'total_steps': len(self.stages[stage]['steps']),
                'status': status,
                'message': message,
                'color': color,  # Add explicit color
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': data or {}
            }

            if self.socketio:
                # Emit progress
                self.socketio.emit('portal_scraper_progress', progress_data)

                # Always emit event for every step
                self.socketio.emit('portal_scraper_event', {
                    'type': status,  # This will be 'starting', 'in_progress', 'completed', or 'error'
                    'message': f"{stage.upper()} - {step}: {message}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })

                # Emit error if status is error
                if status == 'error':
                    self.socketio.emit('portal_scraper_error', {
                        'stage': stage,
                        'step': step,
                        'message': message,
                        'data': data
                    })

            if self.db_ops:
                self.db_ops.update_scraper_progress(
                    username=self.current_username,
                    stage=stage,
                    step=step,
                    status=status,
                    message=message,
                    data={
                        'company_details': getattr(self, 'COMPANY_DETAILS', None),
                        **(data if data else {})
                    }
                )

        except Exception as e:
            logger.error(f"Error emitting stage progress: {e}")

    def setup_chrome_driver(self):
        """Initialize Chrome WebDriver with automatic version detection"""
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
            
            # Add headless mode
            options.add_argument("--headless")
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
                logging.info("Successfully initialized Chrome driver with auto-installer")
                
            except Exception as auto_error:
                logging.warning(f"Auto-installer failed: {auto_error}")
                # Fallback to manual version detection
                try:
                    chrome_version = chromedriver_autoinstaller.get_chrome_version()
                    logging.info(f"Detected Chrome version: {chrome_version}")
                    
                    service = Service(ChromeDriverManager(version=chrome_version).install())
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.implicitly_wait(10)
                    logging.info(f"Successfully initialized Chrome driver with version {chrome_version}")
                    
                except Exception as manual_error:
                    logging.error(f"Manual installation failed: {manual_error}")
                    raise Exception(f"Failed to initialize Chrome driver: {manual_error}")

            # Test the driver
            self.driver.get("about:blank")
            self.emit_stage_progress('initialization', 'browser_setup', 'completed', 'Browser setup complete')
            return True

        except Exception as e:
            self.handle_error('initialization', 'browser_setup', e)
            raise Exception(f"Failed to setup Chrome driver: {e}")

    def safe_send_keys(self, element, value):
        """Helper function to clear field using backspace and send keys safely"""
        try:
            current_value = element.get_attribute('value')
            if current_value:
                for _ in range(len(current_value) + 2):
                    element.send_keys(Keys.BACKSPACE)
                    time.sleep(0.1)
            
            time.sleep(0.5)
            
            if element.get_attribute('value'):
                for _ in range(20):
                    element.send_keys(Keys.BACKSPACE)
                    time.sleep(0.1)
            
            element.send_keys(value)
            return True
            
        except Exception as e:
            self.debug_log('INPUT_ERROR', f"Error sending keys: {str(e)}")
            return False

    def login_to_portal(self, credentials):
        """Implement portal login with enhanced tracking"""
        self.current_stage = 'authentication'
        try:
            self.emit_stage_progress('authentication', 'load_login', 'starting', 'Loading login page')
            self.driver.get(self.PORTAL_URLS['login'])
            time.sleep(2)

            self.emit_stage_progress('authentication', 'enter_credentials', 'starting', 'Entering credentials')
            
            # Find and fill login fields
            username_field = self.driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/div[1]/input')
            password_field = self.driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/div[2]/span/input')
            
            self.safe_send_keys(username_field, credentials['username'])
            time.sleep(2)
            self.safe_send_keys(password_field, credentials['password'])
            time.sleep(2)

            self.emit_stage_progress('authentication', 'verify_login', 'starting', 'Submitting login')
            
            self.driver.find_element(By.XPATH, '//*[@id="registration-page"]/div[2]/div/div[2]/div/div/form/button').click()
            time.sleep(5)

            if "app" in self.driver.current_url:
                self.emit_stage_progress('authentication', 'verify_login', 'completed', 'Login successful')
                return True
            else:
                raise Exception("Login failed - Invalid credentials or access denied")

        except Exception as e:
            self.handle_error('authentication', 'verify_login', e)
            raise

    def validate_company_details(self):
        """Validate generated company details"""
        try:
            # Validate company name
            if not re.match(self.validation_patterns['company_name'], self.COMPANY_DETAILS['name']):
                raise ValueError(f"Invalid company name format: {self.COMPANY_DETAILS['name']}")

            # Validate website
            if not re.match(self.validation_patterns['website'], self.COMPANY_DETAILS['website']):
                raise ValueError(f"Invalid website format: {self.COMPANY_DETAILS['website']}")

            # Validate PAN
            if not re.match(self.validation_patterns['pan'], self.COMPANY_DETAILS['pan']):
                raise ValueError(f"Invalid PAN format: {self.COMPANY_DETAILS['pan']}")

            return True

        except ValueError as e:
            self.debug_log('VALIDATION_ERROR', str(e))
            raise

    def process_company_details(self):
        """Process company details form with validation"""
        self.current_stage = 'company_setup'
        try:
            # Validate details before proceeding
            self.validate_company_details()
            
            self.emit_stage_progress('company_setup', 'load_form', 'starting', 'Loading company details form')
            
            # Log generated details in debug mode
            if self.debug_mode:
                self.debug_log('COMPANY_DETAILS', 'Using generated details', self.COMPANY_DETAILS)
            
            # Find form fields
            name_field = self.driver.find_element(By.ID, 'name')
            website_field = self.driver.find_element(By.ID, 'Company Website')
            pan_field = self.driver.find_element(By.ID, 'PAN Number')
            
            self.emit_stage_progress('company_setup', 'enter_details', 'starting', 'Entering company information')
            
            # Fill form with generated details
            self.safe_send_keys(name_field, self.COMPANY_DETAILS['name'])
            time.sleep(1)
            self.safe_send_keys(website_field, self.COMPANY_DETAILS['website'])
            time.sleep(1)
            self.safe_send_keys(pan_field, self.COMPANY_DETAILS['pan'])
            
            # Save details
            self.emit_stage_progress('company_setup', 'save_company', 'starting', 'Saving company details')
            self.driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/button').click()
            time.sleep(4)
            
            self.emit_stage_progress('company_setup', 'save_company', 'completed', 'Company details saved successfully')
            return True

        except Exception as e:
            self.handle_error('company_setup', self.current_step, e)
            raise

    def process_tax_manager_details(self):
        """Process tax manager details form"""
        self.current_stage = 'tax_manager_setup'
        try:
            self.emit_stage_progress('tax_manager_setup', 'load_form', 'starting', 'Loading tax manager form')
            
            # Find form fields
            name_field = self.driver.find_element(By.ID, 'Name')
            email_field = self.driver.find_element(By.ID, 'Email')
            mobile_field = self.driver.find_element(By.ID, 'Mobile')
            linkedin_field = self.driver.find_element(By.ID, 'LinkedIn profile link')
            
            self.emit_stage_progress('tax_manager_setup', 'enter_details', 'starting', 'Entering tax manager information')
            
            # Fill form
            self.safe_send_keys(name_field, self.TAX_MANAGER_DETAILS['name'])
            time.sleep(1)
            self.safe_send_keys(email_field, self.TAX_MANAGER_DETAILS['email'])
            time.sleep(1)
            self.safe_send_keys(mobile_field, self.TAX_MANAGER_DETAILS['phone'])
            time.sleep(1)
            self.safe_send_keys(linkedin_field, self.TAX_MANAGER_DETAILS['linkedin'])
            
            # Save and proceed
            self.emit_stage_progress('tax_manager_setup', 'save_manager', 'starting', 'Saving tax manager details')
            self.driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/div[7]/button[2]').click()
            time.sleep(5)
            
            self.emit_stage_progress('tax_manager_setup', 'save_manager', 'completed', 'Tax manager details saved successfully')
            return True

        except Exception as e:
            self.handle_error('tax_manager_setup', self.current_step, e)
            raise

    def process_travel_contact_details(self):
        """Process travel contact details form"""
        self.current_stage = 'travel_contact_setup'
        try:
            self.emit_stage_progress('travel_contact_setup', 'load_form', 'starting', 'Loading travel contact form')
            
            # Find form fields
            name_field = self.driver.find_element(By.ID, 'name')
            email_field = self.driver.find_element(By.ID, 'Email')
            mobile_field = self.driver.find_element(By.ID, 'Mobile')
            linkedin_field = self.driver.find_element(By.ID, 'LinkedIn profile link')
            
            self.emit_stage_progress('travel_contact_setup', 'enter_details', 'starting', 'Entering travel contact information')
            
            # Fill form
            self.safe_send_keys(name_field, self.TRAVEL_CONTACT_DETAILS['name'])
            time.sleep(1)
            self.safe_send_keys(email_field, self.TRAVEL_CONTACT_DETAILS['email'])
            time.sleep(1)
            self.safe_send_keys(mobile_field, self.TRAVEL_CONTACT_DETAILS['phone'])
            time.sleep(1)
            self.safe_send_keys(linkedin_field, self.TRAVEL_CONTACT_DETAILS['linkedin'])
            time.sleep(4)
            
            # Navigate to next
            self.emit_stage_progress('travel_contact_setup', 'save_contact', 'starting', 'Saving travel contact details')
            next_button = self.driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/form/div[7]/button[2]')
            next_button.click()
            time.sleep(5)
            
            self.emit_stage_progress('travel_contact_setup', 'save_contact', 'completed', 'Travel contact details saved successfully')
            return True

        except Exception as e:
            self.handle_error('travel_contact_setup', self.current_step, e)
            raise

    def preview_and_submit(self):
        """Preview and submit final details"""
        self.current_stage = 'preview'
        try:
            self.emit_stage_progress('preview', 'review_details', 'starting', 'Loading preview page')
            
            # Click preview button
            preview_button = self.driver.find_element(By.XPATH, '//*[@id="root"]/div/div[2]/div[2]/div/div[2]/div/div[2]/button')
            preview_button.click()
            time.sleep(5)
            
            self.emit_stage_progress('preview', 'final_submission', 'completed', 'Details submitted successfully')
            return True

        except Exception as e:
            self.handle_error('preview', self.current_step, e)
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

    def format_error_message(self, stage, step, error, context=None):
        """Format detailed error message"""
        base_context = self.error_contexts.get(stage, {}).get(step, 'Error in operation')
        error_msg = f"{base_context}: {str(error)}"
        
        details = []
        if context:
            if 'username' in context:
                details.append(f"Username: {context['username']}")
            if 'portal' in context:
                details.append(f"Portal: {context['portal']}")
                
        if details:
            error_msg += f" [{' | '.join(details)}]"
            
        error_msg += f" (Failed at {stage.upper()}/{step.UPPER()})"
        return error_msg

    def handle_error(self, stage, step, error, context=None):
        """Centralized error handler with debug logging"""
        try:
            if isinstance(error, ValueError) and "Invalid company name format" in str(error):
                # Special handling for company name validation errors
                error_msg = f"Invalid format: Company name must be in format 'Name Type 123-uuid'"
            else:
                error_msg = self.format_error_message(stage, step, error, context)
            
            if self.debug_mode:
                self.debug_log('ERROR', error_msg, {
                    'stage': stage,
                    'step': step,
                    'error': str(error),
                    'context': context
                })
            
            # Emit error status
            self.emit_status(stage, 'error', error_msg)
            
            # Emit error event
            if self.socketio:
                self.socketio.emit('portal_scraper_error', {
                    'stage': stage,
                    'step': step,
                    'message': error_msg,
                    'context': context,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
                # Also emit as event log entry
                self.socketio.emit('portal_scraper_event', {
                    'type': 'error',
                    'message': f"ERROR in {stage.upper()}/{step}: {error_msg}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            
            # Emit detailed progress
            self.emit_stage_progress(stage, step, 'error', error_msg)
            
            # Log to DB if available
            if self.db_ops:
                error_context = {
                    'stage': stage,
                    'step': step,
                    'username': self.current_username,
                    'portal': self.current_portal
                }
                # Merge with provided context if any
                if context:
                    error_context.update(context)
                    
                self.db_ops.log_error(
                    error_type=f'{stage.UPPER()}_{step.UPPER()}_ERROR',
                    error_message=error_msg,
                    context=error_context
                )
            
            # Take screenshot if webdriver exists
            if hasattr(self, 'driver'):
                self.capture_screenshot(error_msg)
            
            return error_msg
            
        except Exception as e:
            # Fallback error handling
            fallback_msg = f"Error in {stage}/{step}: {str(error)}"
            logger.error(f"Error handler failed: {e}")
            return fallback_msg

    def capture_screenshot(self, error_msg):
        """Capture screenshot on error"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"error_{timestamp}.png"
            screenshot_path = os.path.join(self.temp_dir, filename)
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Screenshot saved: {screenshot_path}")
            return screenshot_path
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None

def run_scraper(data, db_ops=None, socketio=None):
    """Main scraper execution function"""
    scraper = PortalScraper(db_ops, socketio)
    start_time = time.time()
    
    try:
        # Setup and login
        scraper.setup_chrome_driver()
        scraper.login_to_portal({
            'username': data.get('username'),
            'password': data.get('password')
        })
        
        # Process all forms
        scraper.process_company_details()
        scraper.process_tax_manager_details()
        scraper.process_travel_contact_details()
        scraper.preview_and_submit()

        # Create success result
        result = {
            "success": True,
            "message": "Portal setup completed successfully",
            "data": {
                'processing_time': round(time.time() - start_time, 2),
                'company_details': scraper.COMPANY_DETAILS  # Include company details
            }
        }

        # Emit completion event on success
        if socketio:
            socketio.emit('portal_scraper_completed', {
                'success': True,
                'message': 'Setup completed successfully',
                'data': result['data']
            })

        return result
        
    except Exception as e:
        error_result = {
            "success": False,
            "message": str(e),
            "data": {}
        }

        # Emit completion event on error
        if socketio:
            socketio.emit('portal_scraper_completed', {
                'success': False,
                'message': str(e),
                'data': error_result['data']
            })

        return error_result
    finally:
        scraper.cleanup()

if __name__ == '__main__':
    # Updated test data
    test_data = {
        'username': 'airways@yopmail.com',
        'password': 'NXY0BmgW',
        'portal': 'TestPortal',
        'date_range': {'start': '2024-01-01', 'end': '2024-01-31'}
    }
    
    print("[DEBUG] Starting portal scraper test")
    result = run_scraper(test_data)
    print("\nExecution Result:")
    print(json.dumps(result, indent=2))
