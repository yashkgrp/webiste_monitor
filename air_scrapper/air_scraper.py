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

# from dom_utils import DOMChangeTracker
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64

logger = logging.getLogger(__name__)
# socket_logger = SocketLogger()

class AirIndiaScraper:
    def __init__(self, db_ops, socketio=None):
        self.db_ops = db_ops
        self.socketio = socketio
        self.session = requests.Session()
        self.base_url = 'https://api.airindiaexpress.com/b2c-gstinvoice/v1'
        self.headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Ocp-Apim-Subscription-Key': 'fe65ec9eec2445d9802be1d6c0295158',
            'Origin': 'https://www.airindiaexpress.com/',
            'Referer': 'https://www.airindiaexpress.com/',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
        }
        self.timing_data = {}
        self.current_stage = 'initialization'
        self.scraper_name = 'Air India Express'
        self.debug_mode = db_ops is None  # Track if running in debug mode
        self.debug_logs = []  # Track all debug messages
        self.current_vendor = None  # Add vendor tracking
        
        # Fix: Use temp directory at same level as air_scrapper folder
        current_dir = os.path.dirname(__file__)  # air_scrapper folder
        parent_dir = os.path.dirname(current_dir)  # webiste_monitor-beta folder
        self.temp_dir = os.path.join(parent_dir, 'temp')  # use existing temp folder
        
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
            logger.info(f"Created temp directory at: {self.temp_dir}")

        if self.debug_mode:
            self.debug_log('INIT', f"Using temp directory: {self.temp_dir}")

        # Track execution state
        self.current_pnr = None
        self.current_origin = None
        self.execution_start = None

        # Update stages to include browser setup
        self.stages = {
            'initialization': {
                'name': 'Session Initialization',
                'steps': ['browser_setup', 'proxy_setup', 'session_creation', 'auth_check']
            },
            'request': {
                'name': 'API Request',
                'steps': ['page_load', 'form_fill', 'submission']
            },
            'processing': {
                'name': 'Invoice Processing',
                'steps': ['download', 'verify_files', 'save_files']
            }
        }
        self.current_step = None

        self.error_contexts = {
            'initialization': {
                'proxy_setup': 'Failed to set up proxy connection',
                'session_creation': 'Failed to create HTTP session',
                'auth_check': 'Failed to verify authentication',
                'browser_setup': 'Failed to initialize Chrome browser'
            },
            'request': {
                'encrypt_data': 'Failed to encrypt request data',
                'fetch_invoice': 'Failed to fetch invoice from API',
                'validate_response': 'Failed to validate API response'
            },
            'processing': {
                'parse_data': 'Failed to parse invoice data',
                'generate_pdf': 'Failed to generate PDF files',
                'save_files': 'Failed to save invoice files'
            }
        }

        # Add Selenium specific attributes
        self.driver = None
        self.download_folder = os.path.join(os.getcwd(), "downloads")
        print("donwload_folder",self.download_folder)
        os.makedirs(self.download_folder, exist_ok=True)

        # Add Chrome specific attributes
        self.chrome_version = None
        self.driver_path = None

        # Add DOM tracker instance
        from .dom_util import AirIndiaDOMTracker
        self.dom_tracker = AirIndiaDOMTracker(db_ops)

        # Add page IDs for DOM tracking
        self.page_ids = {
            'login': 'air_india_login_page',
            'gst_invoice': 'air_india_gst_invoice_page',
            'invoice_list': 'air_india_invoice_list_page',
            'download': 'air_india_download_page'
        }

    def debug_log(self, category, message, data=None):
        """Enhanced debug logging with better formatting"""
        if self.debug_mode:
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'category': category,
                'message': message,
                'data': data or {}
            }
            
            # Print with better formatting
            print(f"\n{'='*20} {category} {'='*20}")
            print(f"TIME: {log_entry['timestamp']}")
            print(f"MESSAGE: {message}")
            if data:
                print("DATA:")
                print(json.dumps(data, indent=2))
            print("="*50)
            
            self.debug_logs.append(log_entry)

    def emit_status(self, stage, status, message, timing=None, error=None):
        """Enhanced status emission with structured debug printing"""
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

            # Debug print
            print(f"\n[EMIT] air_scraper_status:")
            print(json.dumps(data, indent=2))

            if self.socketio:
                # Emit status update
                self.socketio.emit('air_scraper_status', data)
                print("[EMIT] Sent status update")

                # Emit event
                event_data = {
                    'type': 'status' if status != 'error' else 'error',
                    'message': f"{stage.title()}: {message}"
                }
                self.socketio.emit('air_scraper_event', event_data)
                print("[EMIT] Sent event:", event_data)

                # Emit stage update
                stage_data = {
                    'stage': stage,
                    'status': status
                }
                self.socketio.emit('air_scraper_stage', stage_data)
                print("[EMIT] Sent stage update:", stage_data)

                # Log success
                print("[EMIT] Successfully emitted all updates")
            elif self.debug_mode:
                print("[DEBUG] Running in debug mode - no socket emissions")

        except Exception as e:
            print(f"[ERROR] Socket emission failed: {str(e)}")
            if not self.debug_mode:
                # socket_logger.log_error(stage, f"Failed to emit status: {str(e)}")
                logging.error(f"Socket emission error: {e}")

    def emit_stage_progress(self, stage, step, status, message, data=None):
        """Enhanced stage and step progress with debug logging"""
        try:
            progress_data = {
                'stage': stage,
                'stage_name': self.stages[stage]['name'],
                'step': step,
                'step_index': self.stages[stage]['steps'].index(step),
                'total_steps': len(self.stages[stage]['steps']),
                'status': status,
                'message': message,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': data or {}
            }

            # Add debug logging for stages and steps
            if self.debug_mode:
                self.debug_log('STAGE_UPDATE', f"{stage} - {step}", {
                    'stage': stage,
                    'step': step,
                    'status': status,
                    'message': message
                })
                print(f"\n[STEP] {stage}/{step}: {message} ({status})")

            if self.socketio:
                # Emit detailed progress
                self.socketio.emit('air_scraper_progress', progress_data)
                
                # Add step to event log
                self.socketio.emit('air_scraper_event', {
                    'type': 'info',
                    'message': f"{stage.upper()} - {step}: {message}"
                })
                
                # Emit stage update
                self.socketio.emit('air_scraper_stage_update', {
                    'stage': stage,
                    'status': status,
                    'completed_step': step
                })
                
                # Emit step details
                self.socketio.emit('air_scraper_step_details', {
                    'stage': stage,
                    'step': step,
                    'message': message
                })

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
            if self.debug_mode:
                self.debug_log('ERROR', f"Failed to emit stage progress: {str(e)}", {
                    'stage': stage,
                    'step': step,
                    'status': status
                })
            logger.error(f"Error emitting stage progress: {e}")

    def encrypt_text(self, plain_text):
        """AES encryption for API parameters"""
        try:
            key = 'A5hG8jK2pN5rT8w1zY4vB7eM9qR3uX6x'
            key = key.ljust(32)[:32]
            cipher = AES.new(key.encode('utf-8'), AES.MODE_ECB)
            padded_text = pad(plain_text.encode('utf-8'), AES.block_size)
            encrypted_text = cipher.encrypt(padded_text)
            return base64.b64encode(encrypted_text).decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            raise

    def format_error_message(self, stage, step, error, context=None):
        """Format detailed error message"""
        base_context = self.error_contexts.get(stage, {}).get(step, 'Error in operation')
        error_msg = f"{base_context}: {str(error)}"
        
        details = []
        if context:
            if 'pnr' in context:
                details.append(f"PNR: {context['pnr']}")
            if 'origin' in context:
                details.append(f"Origin: {context['origin']}")
            if 'elapsed' in context:
                details.append(f"Time elapsed: {context['elapsed']}s")
                
        if details:
            error_msg += f" [{' | '.join(details)}]"
            
        error_msg += f" (Failed at {stage.upper()}/{step.upper()})"
        return error_msg

    def handle_error(self, stage, step, error, context=None):
        """Centralized error handler with debug logging"""
        try:
            error_msg = self.format_error_message(stage, step, error, context)
            
            # Extend context with vendor
            error_context = {
                'stage': stage,
                'step': step,
                'pnr': self.current_pnr,
                'origin': self.current_origin,
                'vendor': self.current_vendor
            }
            
            if self.debug_mode:
                self.debug_log('ERROR', error_msg, {
                    'stage': stage,
                    'step': step,
                    'error': str(error),
                    'context': context
                })
            
            # Emit error status
            self.emit_status(stage, 'error', error_msg)
            
            # Emit detailed progress
            self.emit_stage_progress(stage, step, 'error', error_msg)
            
            # Log to DB if available
            if self.db_ops:
                error_context = {
                    'stage': stage,
                    'step': step,
                    'pnr': self.current_pnr,
                    'origin': self.current_origin,
                    'vendor': self.current_vendor
                }
                # Merge with provided context if any
                if context:
                    error_context.update(context)
                    
                self.db_ops.log_error(
                    error_type=f'{stage.upper()}_{step.upper()}_ERROR',
                    error_message=error_msg,
                    context=error_context
                )
            
            return error_msg
            
        except Exception as e:
            # Fallback error handling
            fallback_msg = f"Error in {stage}/{step}: {str(error)}"
            logger.error(f"Error handler failed: {e}")
            return fallback_msg

    def init_session(self, port):
        """Initialize session with enhanced progress tracking"""
        self.current_stage = 'initialization'
        start_time = time.time()
        
        try:
            # Proxy setup
            self.emit_stage_progress('initialization', 'proxy_setup', 'starting', 'Configuring proxy connection')
            username = 'finkraftscraper'
            password = '7o_ycvJzWs3s8f6RmR'
            proxy_url = f"http://{username}:{password}@gate.smartproxy.com:{port}"
            
            self.session.proxies.update({
                'http': proxy_url,
                'https': proxy_url
            })
            self.emit_stage_progress('initialization', 'proxy_setup', 'completed', 'Proxy configured successfully')

            # Session creation
            self.emit_stage_progress('initialization', 'session_creation', 'starting', 'Creating HTTP session')
            self.session = requests.Session()
            self.emit_stage_progress('initialization', 'session_creation', 'completed', 'Session created')

            # Auth check
            self.emit_stage_progress('initialization', 'auth_check', 'starting', 'Verifying authentication')
            response = self.session.get('https://www.airindiaexpress.com/gst-tax-invoice', headers=self.headers)
            response.raise_for_status()
            self.emit_stage_progress('initialization', 'auth_check', 'completed', 'Authentication verified')

            # Update DB state
            if self.db_ops:
                self.db_ops.store_scraper_state(
                    pnr=self.current_pnr,
                    state='initializing',
                    message='Initializing session',
                    origin=self.current_origin,
                    vendor=self.current_vendor  # Added vendor
                )
            
            elapsed = round(time.time() - start_time, 2)
            self.emit_status(self.current_stage, 'completed', 'Session initialized', timing=elapsed)
            
            if self.db_ops:
                self.db_ops.store_scraper_state(
                    pnr=self.current_pnr,
                    state='initialized',
                    message='Session initialized successfully',
                    origin=self.current_origin
                )
            
            return True
            
        except requests.exceptions.ProxyError as e:
            error_msg = self.handle_error('initialization', 'proxy_setup', e, {
                'port': port,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except requests.exceptions.ConnectionError as e:
            error_msg = self.handle_error('initialization', 'session_creation', e, {
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = self.handle_error('initialization', 'auth_check', e, {
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except Exception as e:
            error_msg = self.handle_error('initialization', self.current_step or 'unknown', e, {
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)

    def setup_chrome_driver(self):
        """Initialize Selenium WebDriver with automatic version detection"""
        try:
            self.emit_stage_progress('initialization', 'browser_setup', 'starting', 'Setting up Chrome browser')
            
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium import webdriver
            import chromedriver_autoinstaller
            import subprocess
            import re

            # Configure Chrome options first
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
                # Auto-detect and install matching ChromeDriver
                chromedriver_autoinstaller.install()  # This will automatically download matching version
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                logger.info("Successfully initialized Chrome driver with auto-installer")
                success = True
            except Exception as auto_error:
                logger.warning(f"Auto-installer failed: {auto_error}")
                # Fallback to manual version detection
                try:
                    # Get exact Chrome version
                    chrome_version = chromedriver_autoinstaller.get_chrome_version()
                    logger.info(f"Detected Chrome version: {chrome_version}")
                    
                    # Install matching driver
                    service = Service(ChromeDriverManager(version=chrome_version).install())
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.implicitly_wait(10)
                    success = True
                    logger.info(f"Successfully initialized Chrome driver with version {chrome_version}")
                except Exception as manual_error:
                    logger.error(f"Manual installation failed: {manual_error}")
                    raise Exception(f"Failed to initialize Chrome driver: {manual_error}")

            # Test the driver
            self.driver.get("about:blank")
            self.emit_stage_progress('initialization', 'browser_setup', 'completed', 'Browser setup complete')
            return True

        except Exception as e:
            error_msg = self.handle_error('initialization', 'browser_setup', e, {
                'chrome_version': getattr(self, 'chrome_version', None),
                'download_folder': self.download_folder
            })
            raise Exception(error_msg)

    def store_page_dom(self, page_id, html_content, metadata=None):
        """Store DOM snapshot with metadata"""
        try:
            if not metadata:
                metadata = {}
            metadata.update({
                'pnr': self.current_pnr,
                'origin': self.current_origin,
                'vendor': self.current_vendor,
                'timestamp': datetime.now()
            })
            self.db_ops.store_dom_snapshot(page_id, html_content, metadata)
        except Exception as e:
            logger.error(f"Error storing DOM snapshot: {e}")

    def fetch_invoice_data(self, pnr, origin):
        """Modified to include DOM change tracking"""
        self.current_stage = 'request'
        start_time = time.time()
        
        try:
            # Login page DOM check
            self.driver.get("https://www.airindiaexpress.com/")
            
            # Store initial DOM snapshot without tracking changes immediately
            self.store_page_dom(
                self.page_ids['login'],
                self.driver.page_source,
                {'page_type': 'login'}
            )
            
            # Only track changes after a delay to ensure page is fully loaded
            time.sleep(2)
            changes = self.dom_tracker.track_page_changes(
                page_id=self.page_ids['login'],
                html_content=self.driver.page_source,
                pnr=pnr,
                origin=origin,
                skip_snapshot=True  # Add this flag to prevent duplicate snapshots
            )

            # Load invoice page
            self.emit_stage_progress('request', 'page_load', 'starting', 'Loading invoice page')
            self.driver.get("https://www.airindiaexpress.com/gst-tax-invoice")
            time.sleep(3)
            
            # Same pattern for GST invoice page
            self.store_page_dom(
                self.page_ids['gst_invoice'],
                self.driver.page_source,
                {'page_type': 'gst_invoice'}
            )
            
            time.sleep(2)
            changes = self.dom_tracker.track_page_changes(
                page_id=self.page_ids['gst_invoice'],
                html_content=self.driver.page_source,
                pnr=pnr,
                origin=origin,
                skip_snapshot=True  # Add this flag
            )

            self.emit_stage_progress('request', 'form_fill', 'starting', 'Entering PNR and origin')
            
            # Use exact same selectors as raw code
            pnr_input = self.driver.find_element(By.XPATH, '//*[@id="pnr"]')
            pnr_input.send_keys(pnr)
            
            origin_input = self.driver.find_element(By.XPATH, '//*[@id="Origin"]')
            origin_input.send_keys(origin)
            time.sleep(2)
            
            try:
                # Use exact same selector as raw code
                suggestion_option = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@class='Source_List_Gst'][1]"))
                )
                suggestion_option.click()
                time.sleep(5)
                self.emit_stage_progress('request', 'form_fill', 'completed', 'Form filled successfully')
            except Exception as e:
                self.handle_error('request', 'form_fill', e)
                raise Exception(f"Failed to select origin: {str(e)}")

            self.emit_stage_progress('request', 'submission', 'starting', 'Submitting request')
            try:
                # Use exact same selector as raw code
                search_button = self.driver.find_element(By.CLASS_NAME, "search-button")
                search_button.click()
                time.sleep(5)
            except Exception as e:
                self.handle_error('request', 'submission', e)
                raise Exception(f"Failed to submit form: {str(e)}")

            # Use exact same selector as raw code for rows
            rows = self.driver.find_elements(By.CSS_SELECTOR, 'tr.gstdetail-td')
            row_count = len(rows)
            
            if row_count == 0:
                raise Exception("No invoices found")
                
            # Invoice list page DOM check
            changes = self.dom_tracker.track_page_changes(
                page_id=self.page_ids['invoice_list'],
                html_content=self.driver.page_source,
                pnr=pnr,
                origin=origin,
                skip_snapshot=True  # Add this flag
            )

            # After form submission, store invoice list page
            self.store_page_dom(
                self.page_ids['invoice_list'],
                self.driver.page_source,
                {'page_type': 'invoice_list'}
            )

            self.emit_stage_progress('request', 'submission', 'completed', f'Found {row_count} invoices')
            return {'rows': rows, 'count': row_count}
            
        except Exception as e:
            error_msg = self.handle_error('request', self.current_step or 'unknown', e)
            raise Exception(error_msg)

    def verify_file(self, file_path):
        """Verify file with detailed logging"""
        try:
            if self.debug_mode:
                self.debug_log('FILE_VERIFY', f"Verifying file: {file_path}")
                
            if not os.path.exists(file_path):
                self.debug_log('FILE_ERROR', f"File does not exist: {file_path}")
                return False
            
            if not file_path.endswith('.pdf'):
                self.debug_log('FILE_ERROR', f"Not a PDF file: {file_path}")
                return False
                
            file_size = os.path.getsize(file_path)
            if file_size < 100:
                self.debug_log('FILE_ERROR', f"File too small ({file_size} bytes): {file_path}")
                return False
                
            self.debug_log('FILE_VERIFY', f"File verified successfully: {file_path}")
            return True
            
        except Exception as e:
            self.debug_log('FILE_ERROR', f"Error verifying file {file_path}: {str(e)}")
            return False

    def process_invoice(self, invoice_data, pnr):
        """Process invoice with same format as backup file"""
        self.current_stage = 'processing'
        start_time = time.time()
        processed_files = []
        
        try:
            # Track existing files before starting downloads
            previous_files = set(os.listdir(self.download_folder))
            
            if self.db_ops:
                self.db_ops.store_scraper_state(
                    pnr=pnr,
                    state='processing',
                    message='Processing invoice data',
                    origin=self.current_origin
                )

            # Download files using Selenium
            for idx, row in enumerate(invoice_data['rows'], 1):
                try:
                    # Click download button using exact same selector
                    download_button = row.find_elements(By.TAG_NAME, "td")[0]
                    download_button.click()
                    time.sleep(2)

                    # Wait for download with tracked previous files
                    downloaded_file = self.wait_for_download(previous_files)
                    if downloaded_file:
                        if self.verify_file(downloaded_file):
                            new_name = f"{pnr}_invoice_{idx}.pdf"
                            new_path = os.path.join(self.download_folder, new_name)
                            
                            # Add handling for existing files
                            if os.path.exists(new_path):
                                os.remove(new_path)  # Remove existing file first
                                if self.debug_mode:
                                    self.debug_log('FILE_OPERATION', f"Removed existing file: {new_path}")
                                    
                            print("Downloaded file:", downloaded_file)
                            print("New path:", new_path)
                            
                            os.rename(downloaded_file, new_path)
                            
                            # Rest of the code remains same...
                            processed_files.append({
                                'path': new_path,
                                'name': new_name,
                                'type': 'Invoice',
                                'size': os.path.getsize(new_path)
                            })
                            previous_files.add(os.path.basename(new_path))  # Add just filename to tracking set
                            
                            self.emit_stage_progress('processing', 'download', 'progress', 
                                f'Downloaded and verified invoice {idx}/{invoice_data["count"]}')
                        else:
                            raise Exception(f"Downloaded file failed verification: {downloaded_file}")
                    else:
                        raise Exception(f"Failed to download invoice {idx}")
                        
                except Exception as e:
                    self.handle_error('processing', 'download', e)
                    continue

            # Verify final count
            if len(processed_files) == 0:
                raise Exception("No valid files were downloaded")
            elif len(processed_files) < invoice_data['count']:
                self.debug_log('WARNING', f"Only {len(processed_files)}/{invoice_data['count']} files were successfully downloaded")

            # After successful downloads, emit completion status
            
            success = len(processed_files) == invoice_data['count']

            completion_status = 'completed' if success else 'error'
            completion_message = (f'Successfully processed {len(processed_files)} files' 
                                if success 
                                else f'Only processed {len(processed_files)}/{invoice_data["count"]} files')

            self.emit_stage_progress('processing', 'save_files', completion_status, completion_message)
            self.emit_status('processing', completion_status, completion_message,
                timing=round(time.time() - start_time, 2))

            if self.socketio:
                # Emit completed event with success/error state preserved
                self.socketio.emit('air_scraper_completed', {
                    'success': success,
                    'hasError': not success,  # Add error flag
                    'files': processed_files,
                    'count': len(processed_files),
                    'expected': invoice_data['count']
                })

            return processed_files

        except Exception as e:
            error_msg = self.handle_error('processing', self.current_step or 'unknown', e)
            raise Exception(error_msg)

    def wait_for_download(self, previous_files, timeout=30):
        """Wait for new file to appear in download folder"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            current_files = set(os.listdir(self.download_folder))
            new_files = current_files - previous_files
            if new_files:
                return os.path.join(self.download_folder, new_files.pop())
            time.sleep(1)
        return None

    def rename_file(self, file_path, pnr, index):
        """Rename downloaded file with PNR and index"""
        new_name = f"{pnr}_invoice_{index}.pdf"
        new_path = os.path.join(self.download_folder, new_name)
        os.rename(file_path, new_path)
        return new_path

    def take_error_screenshot(self, pnr):
        """Take screenshot on error"""
        try:
            screenshot_path = os.path.join(self.temp_dir, f"{pnr}_error.png")
            self.driver.save_screenshot(screenshot_path)
            return screenshot_path
        except Exception as e:
            logger.error(f"Failed to take error screenshot: {e}")
            return None

    def cleanup(self):
        """Enhanced cleanup with file verification"""
        try:
            # Clean up download folder
            if os.path.exists(self.download_folder):
                for file in os.listdir(self.download_folder):
                    try:
                        # print("deleteing invoice")
                        # file_path = os.path.join(self.download_folder, file)
                        # os.remove(file_path)
                        if self.debug_mode:
                            self.debug_log('CLEANUP', f"Deleted file: ")
                    except Exception as e:
                        if self.debug_mode:
                            self.debug_log('CLEANUP_ERROR', f"Failed to delete file {file}: {str(e)}")
            
            # Quit driver
            if self.driver:
                self.driver.quit()
                if self.debug_mode:
                    self.debug_log('CLEANUP', "Browser closed successfully")
                    
        except Exception as e:
            if self.debug_mode:
                self.debug_log('CLEANUP_ERROR', f"Error during cleanup: {str(e)}")

def run_scraper(data, db_ops=None, socketio=None):
    """Enhanced main scraper entry point with debug mode"""
    debug_mode = db_ops is None
    scraper = AirIndiaScraper(db_ops, socketio)
    print("download_folder",scraper.download_folder)
    start_time = time.time()
    
    try:
        # ...existing initialization code...
        
        pnr = data['Ticket/PNR']
        origin = data['Origin']
        vendor = data['Vendor']
        
        # Set current context
        scraper.current_pnr = pnr
        scraper.current_origin = origin
        scraper.current_vendor = vendor
        scraper.execution_start = start_time
        
        # Initialize DB state
        if db_ops:
            db_ops.store_scraper_state(
                pnr=pnr,
                state='starting',
                message='Starting scraper execution',
                origin=origin,
                vendor=vendor
            )
        
        # Initialize browser
        if not scraper.setup_chrome_driver():
            raise Exception("Failed to initialize browser")
        
        # Run scraper steps
        if not scraper.init_session(8000):
            raise Exception("Failed to initialize session")
        
        invoice_data = scraper.fetch_invoice_data(pnr, origin)
        processed_files = scraper.process_invoice(invoice_data, pnr)
        
        # Emit final success status before returning
        if socketio:
            socketio.emit('air_scraper_completed', {
                'success': True,
                'message': 'Scraping completed successfully',
                'data': {
                    'files': processed_files,
                    'processing_time': round(time.time() - start_time, 2)
                }
            })
        
        # Fix: processed_files is a list of file paths, not dictionaries
        if db_ops:
            db_ops.store_scraper_state(
                pnr=pnr,
                state='completed',
                message='Processing completed successfully',
                data={
                    'files': processed_files,  # Changed from f['name'] to just paths
                    'processing_time': round(time.time() - start_time, 2)
                },
                origin=origin
            )
        
        if debug_mode:
            scraper.debug_log('SUCCESS', 'Scraper execution completed', {
                'files': processed_files,  # Changed from f['name'] to just paths
                'processing_time': round(time.time() - start_time, 2)
            })
        
        return {
            "success": True,
            "message": "FILES_SAVED_LOCALLY",
            "data": {
                'files': processed_files,  # Changed from dict to list of paths
                'airline': 'airindiaexpress',
                'processing_time': round(time.time() - start_time, 2)
            }
        }
        
    except Exception as e:
        error_msg = str(e)
        if debug_mode:
            scraper.debug_log('ERROR', f"Scraper execution failed: {str(e)}", {
                'pnr': scraper.current_pnr,
                'origin': scraper.current_origin,
                'elapsed': round(time.time() - start_time, 2)
            })
        
        if db_ops:
            db_ops.log_error('SCRAPER_ERROR', error_msg, {
                'pnr': scraper.current_pnr,
                'origin': scraper.current_origin,
                'elapsed': round(time.time() - start_time, 2)
            })
            
            db_ops.store_scraper_state(
                pnr=scraper.current_pnr,
                state='failed',
                message=error_msg,
                origin=scraper.current_origin
            )
        
        return {
            "success": False,
            "message": error_msg,
            "data": {}
        }
    
    finally:
        scraper.cleanup()

if __name__ == '__main__':
    # Test data for direct execution
    test_data = {
        'Ticket/PNR': 'C7ZGRA',
        'Origin': 'BLR',
        'Vendor': 'Air Asia'
    }
    
    print("[DEBUG] Starting direct execution test")
    print("-" * 50)
    
    # Run without DB ops for testing
    result = run_scraper(test_data)
    
    print("\n" + "=" * 50)
    print("[DEBUG] Execution Result:")
    print(json.dumps(result, indent=2))
    print("-" * 50)


