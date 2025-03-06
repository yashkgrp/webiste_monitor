import logging
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from PIL import Image
from io import BytesIO
import base64
import os
import chromedriver_autoinstaller
from selenium.webdriver.chrome.options import Options
import json
import shutil
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from html import unescape
from datetime import datetime
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import traceback

# Conditional imports for testing
# try:
from .dom_util import AllianceDOMTracker
# except ImportError:
#     # Mock class for testing
#     class AllianceDOMTracker:
#         def __init__(self, db_ops):
#             pass
#         def track_page_changes(self, **kwargs):
#             logging.warning(" not into the main function track_page_changes")
#             pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('alliance_scraper.log'),
        logging.StreamHandler()
    ]
)

class AllianceScraper:
    def __init__(self, db_ops=None, socketio=None):
        self.db_ops = db_ops
        self.socketio = socketio
        self.debug_mode = db_ops is None
        self.current_pnr = None
        self.current_stage = 'initialization'
        self.scraper_name = 'Alliance Air'
        self.download_folder = os.path.join(os.getcwd(), "downloads")
        self.temp_dir = os.path.join(os.getcwd(), "temp")
        self.current_step = None  # Add current step tracking
        self.driver = None
        self.chrome_version = None
        self.driver_path = None
        self.execution_start = None
        self.current_vendor = None
        self.timing_data = {}
        self.debug_logs = []
        
        # Create required directories
        for dir_path in [self.download_folder, self.temp_dir]:
            os.makedirs(dir_path, exist_ok=True)

        # Simplified page tracking - only GST portal page needed
        self.page_ids = {
            'gst_portal': 'alliance_gst_portal'  # Single page to track
        }

        # Define stages specific to Alliance Air
        self.stages = {
            'initialization': {
                'name': 'Session Initialization',
                'steps': ['browser_setup']
            },
            'request': {
                'name': 'Invoice Request',
                'steps': ['page_load', 'form_fill', 'captcha_solving', 'submission']
            },
            'processing': {
                'name': 'Invoice Processing',
                'steps': ['download', 'verify_files', 'save_files']
            }
        }

        # Add DOM change tracking - only if not in debug mode
        if not self.debug_mode and db_ops:
            self.dom_tracker = AllianceDOMTracker(db_ops)
        else:
            # Mock DOM tracker for debug/test mode
            class MockDOMTracker:
                def __init__(self):
                    pass
                def track_page_changes(self, **kwargs):   
                        logging.warning("not not into the main function track_page_changes")
                        return []  # Return empty changes list
                    
            self.dom_tracker = MockDOMTracker()

        self.error_contexts = {
            'captcha': {
                'unsolvable': 'CAPTCHA could not be solved',
                'validation_failed': 'CAPTCHA validation failed',
                'service_error': '2captcha service error'
            },
            'form': {
                'invalid_pnr': 'Invalid PNR format or not found',
                'invalid_date': 'Invalid date format',
                'session_expired': 'Session expired'
            },
            'download': {
                'link_missing': 'Download link not found',
                'file_corrupt': 'Downloaded file is corrupt',
                'save_failed': 'Failed to save file'
            }
        }

        # Add tracking for execution state
        self.execution_start = None
        self.current_vendor = None
        self.timing_data = {}
        self.debug_logs = []

        # Enhanced error contexts specific to Alliance
        self.error_contexts = {
            'initialization': {
                'browser_setup': 'Failed to initialize Chrome browser',
                'session_creation': 'Failed to create browser session'
            },
            'request': {
                'page_load': 'Failed to load Alliance GST portal',
                'form_fill': 'Failed to fill PNR/date form',
                'captcha_solving': {
                    'image_capture': 'Failed to capture CAPTCHA image',
                    'api_error': 'Failed to connect to CAPTCHA solving service',
                    'validation': 'CAPTCHA validation failed',
                    'unsolvable': 'CAPTCHA could not be solved'
                },
                'submission': {
                    'button_click': 'Failed to submit form',
                    'response_validation': 'Invalid response after submission'
                }
            },
            'processing': {
                'download': {
                    'link_missing': 'Download link not found',
                    'click_error': 'Failed to click download link',
                    'timeout': 'Download timeout exceeded'
                },
                'verify_files': {
                    'not_found': 'Downloaded file not found',
                    'corrupt': 'File verification failed',
                    'invalid_size': 'File size validation failed'
                },
                'save_files': {
                    'rename_error': 'Failed to rename downloaded file',
                    'move_error': 'Failed to move file to destination'
                }
            }
        }

        # Update status mapping to better handle progress states
        self.status_mapping = {
            'starting': 'warning',
            'progress': 'info',
            'processing': 'info',
            'completed': 'success',
            'error': 'danger'
        }

    def mark_captcha(self, captcha_id, success):
        """Mark CAPTCHA as good or bad"""
        try:
            action = 'reportgood' if success else 'reportbad'
            requests.get(f'http://2captcha.com/{action}.php', params={
                'key': "53c6618ef94876268350965f59bf3e50",
                'id': captcha_id
            })
        except Exception as e:
            logging.error(f"Failed to mark CAPTCHA: {e}")

    def emit_status(self, stage, status, message, timing=None, error=None):
        try:
            data = {
                'stage': stage,
                'status': status,
                'status_color': self.status_mapping.get(status, 'info'),
                'message': message,
                'timing': timing,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            if error:
                data['error'] = str(error)

            if self.debug_mode:
                print(f"\n[STATUS] {stage} - {status}: {message}")

            # Only emit status event, remove duplicate event emission
            if self.socketio:
                self.socketio.emit('alliance_scraper_status', data)

        except Exception as e:
            logging.error(f"Error emitting status: {e}")

    def emit_stage_progress(self, stage, step, status, message, data=None):
        """Enhanced progress emission with detailed stage tracking"""
        try:
            if self.debug_mode:
                print(f"\n[STEP] {stage}/{step}: {message} ({status})")

            # Determine final status color based on stage completion
            status_color = self.status_mapping.get(status, 'info')
            if status == 'completed' and step == self.stages[stage]['steps'][-1]:
                status_color = 'success'  # Force success color on stage completion

            progress_data = {
                'stage': stage,
                'stage_name': self.stages[stage]['name'],
                'step': step,
                'step_index': self.stages[stage]['steps'].index(step),
                'total_steps': len(self.stages[stage]['steps']),
                'status': status,
                'status_color': status_color,
                'message': message,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': data or {}
            }

            # Only emit progress event
            if self.socketio:
                self.socketio.emit('alliance_scraper_progress', progress_data)

            if self.db_ops:
                self.db_ops.update_scraper_progress(
                    pnr=self.current_pnr,
                    stage=stage,
                    step=step,
                    status=status,
                    message=message,
                    data=data
                )

        except Exception as e:
            logging.error(f"Error emitting stage progress: {e}")

    # Remove emit_detailed_progress method as it's redundant
    # def emit_detailed_progress(self, stage, step, status, message, data=None):
    #     ...

    def store_execution_time(self, stage, step, duration):
        """Track execution timing for performance monitoring"""
        if stage not in self.timing_data:
            self.timing_data[stage] = {}
        self.timing_data[stage][step] = round(duration, 2)

    def debug_log(self, category, message, data=None):
        """Enhanced debug logging aligned with air_scraper"""
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
                print("DATA:")
                print(json.dumps(data, indent=2))
            print("="*50)
            self.debug_logs.append(log_entry)

    def setup_chrome_driver(self):
        """Initialize Selenium WebDriver with enhanced error handling and progress tracking"""
        self.current_step = 'browser_setup'
        start_time = time.time()
        
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
            options.add_argument("--headless=new")
            options.add_argument("--disable-blink-features=AutomationControlled")

            try:
                # First attempt: Auto-detect and install matching ChromeDriver
                chromedriver_autoinstaller.install()
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                logging.info("Successfully initialized Chrome driver with auto-installer")
                
                # Store successful initialization
                self.chrome_version = chromedriver_autoinstaller.get_chrome_version()
                elapsed_time = round(time.time() - start_time, 2)
                self.emit_stage_progress('initialization', 'browser_setup', 'completed', 
                                         f'Chrome initialized (version {self.chrome_version})',
                                         {'timing': elapsed_time})
                
                return True
                
            except Exception as auto_error:
                logging.warning(f"Auto-installer failed: {auto_error}")
                # Second attempt: Manual version detection
                try:
                    chrome_version = chromedriver_autoinstaller.get_chrome_version()
                    logging.info(f"Detected Chrome version: {chrome_version}")
                    
                    # Install matching driver
                    service = Service(ChromeDriverManager(version=chrome_version).install())
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.implicitly_wait(10)
                    
                    self.chrome_version = chrome_version
                    elapsed_time = round(time.time() - start_time, 2)
                    self.emit_stage_progress('initialization', 'browser_setup', 'completed', 
                                             f'Chrome initialized (version {chrome_version})',
                                             {'timing': elapsed_time})
                    
                    return True
                    
                except Exception as manual_error:
                    error_msg = f"Failed to initialize Chrome driver: {manual_error}"
                    logging.error(error_msg)
                    elapsed_time = round(time.time() - start_time, 2)
                    self.emit_stage_progress('initialization', 'browser_setup', 'error', 
                                             error_msg, {'timing': elapsed_time})
                    return False

        except Exception as e:
            error_msg = f"Browser setup failed: {str(e)}"
            logging.error(error_msg)
            elapsed_time = round(time.time() - start_time, 2)
            self.emit_stage_progress('initialization', 'browser_setup', 'error', 
                                     error_msg, {'timing': elapsed_time})
            return False

    def get_captcha_base64(self, data):
        """Get captcha result from base64 string"""
        self.current_step = 'captcha_solving'
        
        try:
            response = requests.post('http://2captcha.com/in.php', data={
                'key': "53c6618ef94876268350965f59bf3e50",
                'method': 'base64',
                'body': data,
                'json': 1,
                'regsense': 1
            }).json()

            captcha_id = response['request']

            # Wait for captcha to be solved
            for i in range(1,4,1):
                time.sleep(10)
                response = requests.post('http://2captcha.com/res.php', data={
                    'key': "53c6618ef94876268350965f59bf3e50",
                    'action': 'get',
                    'id': int(captcha_id)
                }).text
                
                if response == 'ERROR_CAPTCHA_UNSOLVABLE':
                    logging.error("CAPTCHA unsolvable error")
                    return '000000'

                if '|' in response:
                    _, captcha_text = unescape(response).split('|')
                    self.emit_stage_progress('request', 'captcha_solving', 'completed', f'CAPTCHA solved: {captcha_text}')
                    return (captcha_id, captcha_text)

        except Exception as e:
            error_msg = f"CAPTCHA solving failed: {str(e)}"
            logging.error(error_msg)
            self.emit_stage_progress('request', 'captcha_solving', 'error', error_msg)
            return '000000'

    def store_dom_snapshot(self, html_content, context=None):
        """Store DOM snapshot with context"""
        if not self.debug_mode:  # Only store if not in debug mode
            try:
                if not context:
                    context = {}
                context.update({
                    'pnr': self.current_pnr,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'page_id': self.page_ids['gst_portal']
                })
                
                if self.db_ops:
                    self.db_ops.store_dom_snapshot(
                        page_id=self.page_ids['gst_portal'],
                        html_content=html_content,
                        metadata=context
                    )
                    
            except Exception as e:
                logging.error(f"Failed to store DOM snapshot: {e}")

    def validate_form_fields(self, pnr, date):
        """Validate form input fields"""
        errors = []
        if not pnr or len(pnr) < 6:
            errors.append("Invalid PNR format")
        try:
            datetime.strptime(date, '%d-%m-%Y')
        except ValueError:
            errors.append("Invalid date format (required: DD-MM-YYYY)")
        return errors

    def wait_for_file_download(self, filename, timeout=30):
        """Wait for file download with timeout"""
        start_time = time.time()
        expected_file = os.path.join(self.download_folder, filename + ".pdf")
        
        while time.time() - start_time < timeout:
            if os.path.exists(expected_file):
                if os.path.getsize(expected_file) > 0:
                    return expected_file
            time.sleep(1)
        return None

    def fetch_invoice_data(self, pnr, date):
        start_time = time.time()
        self.current_stage = 'request'
        self.current_step = 'page_load'
        filename = None
        
        try:
            # Validate inputs
            errors = self.validate_form_fields(pnr, date)
            if errors:
                raise Exception(f"Validation failed: {', '.join(errors)}")

            self.emit_stage_progress('request', 'page_load', 'starting', 'Loading Alliance Air GST portal')
            self.driver.get('https://allianceair.co.in/gst/')
            time.sleep(5)

            # Track initial page load state with transaction_date
            try:
                initial_page = self.driver.page_source
                
            except Exception as dom_error:
                logging.warning(f"DOM tracking error (non-critical): {dom_error}")
                # Continue execution - DOM tracking is non-critical

            self.current_step = 'form_fill'
            self.emit_stage_progress('request', 'form_fill', 'progress', 'Filling form details')
            
            # Fill form with explicit waits
            wait = WebDriverWait(self.driver, 10)
            
            date_input = wait.until(EC.presence_of_element_located((By.ID, "txtDOJ")))
            date_input.click()
            date_input.clear()
            date_input.send_keys(date)
            time.sleep(2)

            pnr_input = wait.until(EC.presence_of_element_located((By.ID, "txtPNR")))
            pnr_input.click()
            pnr_input.clear()
            pnr_input.send_keys(pnr)
            time.sleep(2)

            # Track DOM after form fill
            

            elapsed_form = round(time.time() - start_time, 2)
            self.emit_stage_progress('request', 'form_fill', 'completed', 
                                     'Form filled successfully', {'timing': elapsed_form})

            self.current_step = 'captcha_solving'
            captcha_start = time.time()
            self.emit_stage_progress('request', 'captcha_solving', 'starting', 'Processing CAPTCHA')
            
            # Handle CAPTCHA
            captcha_image = wait.until(EC.presence_of_element_located((By.ID, "Image1")))
            captcha_image_data = captcha_image.screenshot_as_png
            
            image = Image.open(BytesIO(captcha_image_data))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

            captcha_result = self.get_captcha_base64(base64_image)
            
            if not isinstance(captcha_result, tuple):  # Check if captcha_result is valid
                raise Exception("CAPTCHA solving failed - invalid response")
                
            captcha_id, captcha_text = captcha_result
            if not captcha_text or captcha_text == '000000':
                raise Exception("CAPTCHA could not be solved")

            elapsed_captcha = round(time.time() - captcha_start, 2)
            self.emit_stage_progress('request', 'captcha_solving', 'completed', 
                                     f'CAPTCHA solved: {captcha_text}', {'timing': elapsed_captcha})

            self.current_step = 'submission'
            self.emit_stage_progress('request', 'submission', 'progress', 'Submitting form')

            # Fill CAPTCHA and submit
            captcha_input = wait.until(EC.presence_of_element_located((By.ID, "txtVerificationCodeNew")))
            captcha_input.send_keys(captcha_text)
            
            submit_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="btnSearch"]')))
            submit_button.click()
            time.sleep(5)

            # Track post-submission state
            try:
                
                self.dom_tracker.track_page_changes(
                    page_id=self.page_ids['gst_portal'],
                    html_content=self.driver.page_source,
                    pnr=pnr,
                    transaction_date=date
                )
                logging.warning(f"DOM tracking")
            except Exception as dom_error:
                logging.warning(f"DOM tracking error (non-critical): {dom_error}")

            # Enhanced error and invoice link detection using DOM changes
            try:
                error_element = self.driver.find_elements(By.CLASS_NAME, "error-message")
                if error_element:
                    error_text = error_element[0].text
                    self.mark_captcha(captcha_id, False)
                    raise Exception(f"Error after submission: {error_text}")

                # Check for invoice download link
                download_link = wait.until(EC.presence_of_element_located((By.ID, "lnkdownload")))
                filename = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="lbl"]'))).text
                
                if filename:
                    self.mark_captcha(captcha_id, True)
                    self.emit_stage_progress('request', 'submission', 'completed', 'Form submitted successfully')
                    return True, filename
                else:
                    self.mark_captcha(captcha_id, False)
                    raise Exception("Invoice filename not found")

            except TimeoutException:
                self.mark_captcha(captcha_id, False)
                raise Exception("Download link not found after form submission")

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            error_context = {
                'pnr': pnr,
                'stage': self.current_stage,
                'step': self.current_step,
                'elapsed': elapsed
            }
            
            # Send error notification
            if self.db_ops:
                try:
                    from notification_handler import NotificationHandler
                    notification_handler = NotificationHandler(self.db_ops)
                    notification_data = {
                        'Ticket/PNR': pnr,
                        'Traveller Name': date,
                        'Stage': self.current_stage,
                        'Step': self.current_step,
                        
                    }
                    notification_handler.send_scraper_notification(
                        str(e), 
                        notification_data, 
                        f"{self.current_stage}/{self.current_step}", 
                        airline="Alliance Air"
                    )
                except Exception as notify_error:
                    logging.error(f"Failed to send error notification: {notify_error}")

            # Log detailed error
            logging.error(f"Alliance Scraper Error in {self.current_stage}/{self.current_step}:")
            logging.error(f"Original error: {str(e)}")
            logging.error(f"Context: {error_context}")
            logging.error(traceback.format_exc())  # Log full stack trace

            # Raise with complete context
            raise Exception(f"Error in {self.current_stage}/{self.current_step}: {str(e)}") from e

    def process_invoice(self, pnr, filename):
        if not filename:
            raise Exception("No filename provided to process_invoice")
            
        start_time = time.time()
        self.current_stage = 'processing'
        self.current_step = 'download'
        
        try:
            self.emit_stage_progress('processing', 'download', 'starting', 'Initiating download')
            
            # Download with retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    wait = WebDriverWait(self.driver, 10)
                    download_link = wait.until(EC.element_to_be_clickable((By.ID, "lnkdownload")))
                    download_link.click()

                    # Wait for file download
                    downloaded_file = self.wait_for_file_download(filename, timeout=30)
                    if downloaded_file:
                        break
                    
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                        
                    raise Exception("Download timeout - file not found after retries")
                    
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logging.warning(f"Download attempt {attempt + 1} failed: {str(e)}")

            elapsed_download = round(time.time() - start_time, 2)
            self.emit_stage_progress('processing', 'download', 'completed', 
                                     'File downloaded successfully', {'timing': elapsed_download})

            self.current_step = 'verify_files'
            verify_start = time.time()
            self.emit_stage_progress('processing', 'verify_files', 'starting', 'Verifying downloaded file')
            
            # Enhanced file verification
            if not os.path.exists(downloaded_file):
                raise Exception("Downloaded file not found")
            
            file_size = os.path.getsize(downloaded_file)
            if file_size < 100:
                raise Exception(f"File too small ({file_size} bytes)")

            if not downloaded_file.endswith('.pdf'):
                raise Exception("Invalid file format")

            elapsed_verify = round(time.time() - verify_start, 2)
            self.emit_stage_progress('processing', 'verify_files', 'completed', 
                                     'File verified successfully', {'timing': elapsed_verify})

            self.current_step = 'save_files'
            save_start = time.time()
            self.emit_stage_progress('processing', 'save_files', 'starting', 'Saving and organizing files')

            # Enhanced file organization
            new_filename = f"{pnr}_invoice.pdf"
            new_filepath = os.path.join(self.download_folder, new_filename)
            
            if os.path.exists(new_filepath):
                backup_path = os.path.join(self.temp_dir, f"{pnr}_invoice_backup.pdf")
                shutil.copy2(new_filepath, backup_path)
                os.remove(new_filepath)
                
            os.rename(downloaded_file, new_filepath)

            elapsed_save = round(time.time() - save_start, 2)
            self.emit_stage_progress('processing', 'save_files', 'completed', 
                                     'File processed successfully', {'timing': elapsed_save})
            
            return [{
                'path': new_filepath,
                'name': new_filename,
                'type': 'Invoice',
                'size': os.path.getsize(new_filepath),
                'processing_time': round(time.time() - start_time, 2)
            }]

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            error_context = {
                'pnr': pnr,
                'filename': filename,
                'stage': self.current_stage,
                'step': self.current_step,
                'elapsed': elapsed
            }

            # Send error notification
            if self.db_ops:
                try:
                    from notification_handler import NotificationHandler
                    notification_handler = NotificationHandler(self.db_ops)
                    notification_data = {
                        'Ticket/PNR': pnr,
                        'Filename': filename,
                        'Stage': self.current_stage,
                        'Step': self.current_step
                    }
                    notification_handler.send_scraper_notification(
                        str(e), 
                        notification_data, 
                        f"{self.current_stage}/{self.current_step}", 
                        airline="Alliance Air"
                    )
                except Exception as notify_error:
                    logging.error(f"Failed to send error notification: {notify_error}")

            # Log detailed error
            logging.error(f"Alliance Scraper Error in {self.current_stage}/{self.current_step}:")
            logging.error(f"Original error: {str(e)}")
            logging.error(f"Context: {error_context}")
            logging.error(traceback.format_exc())  # Log full stack trace

            # Raise with complete context
            raise Exception(f"Error processing invoice: {str(e)}") from e

    def cleanup(self):
        """Enhanced cleanup with state management"""
        try:
            if self.debug_mode:
                print("[DEBUG] Starting cleanup process")

            # Store final execution state if available
            if not self.debug_mode and self.db_ops and self.current_pnr:
                self.db_ops.store_scraper_state(

                    pnr=self.current_pnr,
                    state='completed',
                    message='Scraper execution completed',
                    data={
                        'timing_data': self.timing_data,
                        'execution_time': round(time.time() - (self.execution_start or time.time()), 2)
                    }
                    
                )

            # Clean up temporary files if not in debug mode
            if not self.debug_mode:
                for folder in [self.temp_dir]:
                    if os.path.exists(folder):
                        try:
                            shutil.rmtree(folder)
                            if self.debug_mode:
                                print(f"[DEBUG] Cleaned up folder: {folder}")
                        except Exception as e:
                            logging.error(f"Failed to clean up folder {folder}: {e}")

            # Close browser
            if self.driver:
                self.driver.quit()
                if self.debug_mode:
                    print("[DEBUG] Browser closed successfully")
                    
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")

    def handle_error(self, stage, step, error, context=None):
        print('Comprehensive error handler specific to Alliance Air scraper')
        try:
            # Format base error message
            error_msg = str(error)
            context = context or {}

            # Add execution timing if available
            if hasattr(self, 'execution_start'):
                elapsed = round(time.time() - self.execution_start, 2)
                context['elapsed_time'] = f"{elapsed}s"

            # Build detailed error message with context
            error_details = []
            if hasattr(self, 'current_pnr'):
                error_details.append(f"PNR: {self.current_pnr}")
            if context.get('filename'):
                error_details.append(f"File: {context['filename']}")
            if context.get('elapsed'):
                error_details.append(f"Time: {context['elapsed']}")

            # Add error location
            error_msg = f"[{stage.upper()}/{step.upper()}] {error_msg}"
            if error_details:
                error_msg += f" ({' | '.join(error_details)})"

            # Add debug logging
            logging.error(f"Alliance Scraper Error: {error_msg}")
            if context:
                logging.error(f"Error Context: {json.dumps(context, indent=2)}")

            # Emit error status
            self.emit_status(stage, 'error', error_msg)
            self.emit_stage_progress(stage, step, 'error', error_msg)
            if self.db_ops:
                try:
                    from notification_handler import NotificationHandler
                    notification_handler = NotificationHandler(self.db_ops)
                    notification_data = {
                        'Ticket/PNR': getattr(self, 'current_pnr', 'N/A'),
                        'Traveller Name': getattr(self, 'current_vendor', 'Alliance Air')
                    }
                    stage_info = f"{stage.upper()}{' - ' + step if step else ''}"
                    notification_handler.send_scraper_notification(error_msg, notification_data, stage_info, airline="Alliance Air")
                except Exception as notify_error:
                    logging.error(f"Failed to send error notification: {notify_error}")

            # Log to external systems if available
            if self.db_ops:
                error_data = {
                    'stage': stage,
                    'step': step,
                    'pnr': getattr(self, 'current_pnr', None),
                    'vendor': 'ALLIANCE AIR',
                    'context': context
                }
                self.db_ops.log_error(
                    error_type=f'ALLIANCE_{stage.upper()}_{step.upper()}_ERROR',
                    message=error_msg,
                    context=error_data
                )

                # Update scraper state
                self.db_ops.store_scraper_state(
                    pnr=self.current_pnr,
                    state='error',
                    message=error_msg,
                    data=error_data
                )

            return error_msg

        except Exception as e:
            # Fallback error handling if main error handler fails
            fallback_msg = f"Error in {stage}/{step}: {str(error)} (Error handler failed: {str(e)})"
            logging.error(fallback_msg)
            return fallback_msg

def run_scraper(data, db_ops=None, socketio=None):
    """Enhanced main scraper entry point with state management"""
    debug_mode = db_ops is None
    scraper = AllianceScraper(db_ops, socketio)
    start_time = time.time()
    
    try:
        pnr = data['Ticket/PNR']
        date = data['Transaction_Date']
        vendor = data.get('Vendor', 'ALLIANCE AIR')
        
        # Set execution context
        scraper.current_pnr = pnr
        scraper.current_vendor = vendor
        scraper.execution_start = start_time
        
        # Only store state if db_ops is available
        if not debug_mode and db_ops:
            db_ops.store_scraper_state(
                pnr=pnr,
                state='starting',
                message='Starting scraper execution',
                vendor=vendor
            )
        
        # Initialize browser with error handling
        if not scraper.setup_chrome_driver():
            raise Exception("Failed to initialize browser")
        
        # Fetch invoice with retries and proper error handling
        max_attempts = 1
        status = False
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                status, filename = scraper.fetch_invoice_data(pnr, date)
                if status:
                    break
                if attempt < max_attempts - 1:
                    time.sleep(5)
            except Exception as e:
                last_error = e
                if attempt == max_attempts - 1:
                    raise
                logging.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(5)
        
        if last_error:
            raise Exception(f"Failed to fetch invoice data after {max_attempts} attempts: {str(last_error)}")
            
        # Process invoice with enhanced error handling
        processed_files = scraper.process_invoice(pnr, filename)
        
        # Update final state only if db_ops available
        if not debug_mode and db_ops:
            db_ops.store_scraper_state(
                pnr=pnr,
                state='completed',
                message='Processing completed successfully',
                data={
                    'files': processed_files,
                    'processing_time': round(time.time() - start_time, 2)
                }
            )
        
        return {
            "success": True,
            "message": "FILES_SAVED_LOCALLY",
            "data": {
                'files': processed_files,
                'airline': 'alliance',
                'processing_time': round(time.time() - start_time, 2),
                'timing_data': scraper.timing_data
            }
        }
        
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Scraper execution failed: {error_msg}")
        
        if not debug_mode and db_ops:
            db_ops.store_scraper_state(
                pnr=scraper.current_pnr,
                state='failed',
                message=error_msg
            )
        
        return {
            "success": False,
            "message": error_msg,
            "data": {
                'timing_data': scraper.timing_data if hasattr(scraper, 'timing_data') else {}
            }
        }
    
    finally:
        scraper.cleanup()

if __name__ == '__main__':
    # Test data for debugging
    test_data = {
        'Ticket/PNR': 'P6CZDL',
        'Transaction_Date': '06-06-2024',
        'Vendor': 'ALLIANCE AIR'
    }
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("\n=== Alliance Air Scraper Test Mode ===")
    print("Test Parameters:")
    print(json.dumps(test_data, indent=2))
    print("=" * 50)
    
    try:
        # Run in debug mode (no db_ops)
        result = run_scraper(test_data)
        
        print("\nTest Execution Complete")
        print("-" * 30)
        if result['success']:
            print("✅ Status: Success")
            if 'data' in result and 'files' in result['data']:
                print("\nProcessed Files:")
                for file in result['data']['files']:
                    print(f"- {file['name']} ({file['size']} bytes)")
            print(f"\nProcessing Time: {result['data'].get('processing_time', 'N/A')}s")
        else:
            print("❌ Status: Failed")
            print(f"Error: {result['message']}")
            
        print("\nDetailed Timing:")
        if 'timing_data' in result.get('data', {}):
            for stage, steps in result['data']['timing_data'].items():
                print(f"\n{stage.upper()}:")
                for step, time in steps.items():
                    print(f"- {step}: {time}s")
                    
    except Exception as e:
        print(f"\n❌ Test Execution Failed:")
        print(f"Error: {str(e)}")
        traceback.print_exc()
    
    print("\n" + "="*50)

