from datetime import datetime
import firebase_admin
import requests
from requests import JSONDecodeError, Session
import json
import os
import time
import string
import random
import base64
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import logging
from logging.handlers import TimedRotatingFileHandler
import chromedriver_autoinstaller
import pytz
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from requests.exceptions import SSLError, ConnectionError, ProxyError
import traceback
from notification_handler import NotificationHandler
from flask_socketio import SocketIO

# Configure logging
ist = pytz.timezone('Asia/Kolkata')
folder_path = "log/"
if not os.path.exists(folder_path):
    os.makedirs(folder_path)

log_handler = TimedRotatingFileHandler(
    folder_path + 'indigo_scraper.log',
    when='D',
    interval=1,
    backupCount=7,
    encoding='utf-8',
    delay=False
)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(lineno)d - %(message)s')
log_handler.setFormatter(formatter)
logging.basicConfig(
    level=logging.INFO,
    handlers=[log_handler, logging.StreamHandler()]
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/112.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.goindigo.in/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "TE": "trailers"
}

COOLDOWN_SECS = 10

class IndigoScraper:
    def __init__(self, db_ops=None, socketio=None):
        self.db_ops = db_ops
        self.socketio = socketio
        self.debug_mode = db_ops is None
        print(f"[DEBUG] Initializing IndigoScraper - debug_mode: {self.debug_mode}")
        self.current_pnr = None
        self.current_stage = 'initialization'
        self.scraper_name = 'Indigo'
        self.download_folder = os.path.join(os.getcwd(), "downloads")
        self.temp_dir = os.path.join(os.getcwd(), "temp")
        self.screenshots_folder = os.path.join(os.getcwd(), "screenshots")
        self.current_step = None
        self.driver = None
        self.chrome_version = None
        self.driver_path = None
        self.execution_start = None
        self.timing_data = {}
        self.debug_logs = []
        self.session = None
        self.notification_handler = NotificationHandler(db_ops) if db_ops else None
        
        # Create required directories
        for dir_path in [self.download_folder, self.temp_dir, self.screenshots_folder]:
            os.makedirs(dir_path, exist_ok=True)

        # Page tracking for Indigo
        self.page_ids = {
            'gst_portal': 'indigo_gst_portal'
        }

        # Update stages to be more granular like Alliance
        self.stages = {
            'initialization': {
                'name': 'Session Initialization',
                'steps': ['proxy_setup', 'session_setup', 'environment_check']
            },
            'validation': {
                'name': 'Input Validation',
                'steps': ['pnr_validation', 'email_validation', 'session_validation']
            },
            'request': {
                'name': 'Invoice Request',
                'steps': ['prepare_request', 'get_invoice_ids', 'validate_invoice_ids', 'get_auth_token']
            },
            'processing': {
                'name': 'Invoice Processing',
                'steps': ['fetch_invoice', 'format_html', 'process_images', 'validate_content', 'save_file']
            },
            'completion': {
                'name': 'Task Completion',
                'steps': ['verify_files', 'prepare_response', 'cleanup']
            }
        }
        print("[DEBUG] Registered stages:", list(self.stages.keys()))
        for stage, info in self.stages.items():
            print(f"[DEBUG] Stage {stage} has steps:", info['steps'])
            
        # Status mapping for progress tracking
        self.status_mapping = {
            'starting': {'color': 'warning', 'emoji': '⏳'},
            'progress': {'color': 'warning', 'emoji': '🔄'},
            'completed': {'color': 'success', 'emoji': '✅'},
            'error': {'color': 'danger', 'emoji': '❌'},
            'info': {'color': 'info', 'emoji': 'ℹ️'}
        }
        print("[DEBUG] Registered status types:", list(self.status_mapping.keys()))

    def set_current_step(self, step):
        """Set current step and validate it exists in current stage"""
        self.current_step = step
        if self.current_stage and step != 'unknown':
            if self.current_stage not in self.stages:
                logging.warning(f"Stage {self.current_stage} not found in registered stages")
                return False
            if step not in self.stages[self.current_stage]['steps']:
                logging.warning(f"Step {step} not found in stage {self.current_stage}")
                return False
        return True

    def emit_status(self, stage, status, message, timing=None, error=None):
        """Emit status with Alliance-matching color scheme and debug output"""
        try:
            status_info = self.status_mapping.get(status, self.status_mapping['info'])
            
            data = {
                'stage': stage,
                'status': status,
                'status_color': status_info['color'],
                'message': message,
                'timing': timing,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            if error:
                data['error'] = str(error)

            if self.debug_mode:
                print("\n[SOCKET EVENT: indigo_scraper_status]")
                # print("Payload:")
                # print(json.dumps(data, indent=2))
                print(f"\n{status_info['emoji']} {message}")
                if timing:
                    print(f"⏱️  Time: {timing}s")
                if error:
                    print(f"❌ Error: {error}")

            if self.socketio:
                self.socketio.emit('indigo_scraper_status', data)

        except Exception as e:
            logging.error(f"Error emitting status: {e}")

    def emit_stage_progress(self, stage, step, status, message, data=None):
        """Emit stage progress with Alliance-matching color scheme and detailed debug output"""
        try:
            # Update current step
            self.set_current_step(step)
            
            # Validate input parameters
            if not stage or not step or not status or not message:
                print(f"[DEBUG] Invalid parameters: stage={stage}, step={step}, status={status}, message={message}")
                return

            # Validate stage exists
            if stage not in self.stages:
                print(f"[DEBUG] Invalid stage: {stage}. Available stages: {list(self.stages.keys())}")
                return

            # Validate step exists in stage
            if step not in self.stages[stage]['steps']:
                print(f"[DEBUG] Invalid step '{step}' for stage '{stage}'. Available steps: {self.stages[stage]['steps']}")
                return

            status_info = self.status_mapping.get(status, self.status_mapping['info'])
            print(f"[DEBUG] Using status_info: {status_info} for status: {status}")
            
            # Calculate step progress like Alliance
            try:
                total_stages = len(self.stages)
                current_stage_idx = list(self.stages.keys()).index(stage)
                current_step_idx = self.stages[stage]['steps'].index(step)
                total_steps = len(self.stages[stage]['steps'])
            except Exception as e:
                print(f"[DEBUG] Error calculating progress: {e}")
                return
            
            progress_data = {
                'stage': stage,
                'stage_name': self.stages[stage]['name'],
                'step': step,
                'step_index': current_step_idx,
                'total_steps': total_steps,
                'status': status,
                'status_color': status_info['color'],
                'message': message,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': data or {},
                'progress': {
                    'stage': ((current_stage_idx + 1) / total_stages) * 100,
                    'step': ((current_step_idx + 1) / total_steps) * 100,
                    'overall': (((current_stage_idx * 100) + 
                              ((current_step_idx + 1) / total_steps * 100)) / total_stages)
                }
            }

            # Debug output
            if self.debug_mode:
                print("\n" + "="*50)
                print("🔌 SOCKET EVENT: indigo_scraper_progress")
                print("=" * 50)
                print(f"Stage: {stage} ({progress_data['progress']['stage']}%)")
                print(f"Step: {step} ({progress_data['progress']['step']}%)")
                print(f"Status: {status} ({status_info['color']})")
                print(f"Message: {message}")
                print(f"Overall Progress: {progress_data['progress']['overall']}%")
                # if data:
                #     print("\nAdditional Data:")
                #     print(json.dumps(data, indent=2))
                print("=" * 50)

            # Emit socket event if socketio available
            if self.socketio:
                print("[DEBUG] Emitting socket event")
                self.socketio.emit('indigo_scraper_progress', progress_data)
            elif self.debug_mode:
                print("[DEBUG] No socketio available - would emit:")

            # Update DB if available
            if self.db_ops:
                print("[DEBUG] Updating DB")
                self.db_ops.update_scraper_progress(
                    pnr=self.current_pnr,
                    stage=stage,
                    step=step,
                    status=status,
                    message=message,
                    data=progress_data
                )
            elif self.debug_mode:
                print("[DEBUG] No db_ops available - would store in DB:")

        except Exception as e:
            print(f"[DEBUG] Error in emit_stage_progress: {str(e)}")
            print(f"[DEBUG] Full error: {traceback.format_exc()}")
            logging.error(f"Error emitting stage progress: {e}")

    def store_execution_time(self, stage, step, duration=None):
        """Store execution time with proper stage/step tracking"""
        try:
            if stage not in self.timing_data:
                self.timing_data[stage] = {}
            
            if duration is None:
                # If no duration provided, calculate from stage start time
                stage_start = getattr(self, f'{stage}_start_time', None)
                if stage_start:
                    duration = round(time.time() - stage_start, 2)
                else:
                    duration = 0
                    
            self.timing_data[stage][step] = duration
            
            # Log timing in debug mode
            if self.debug_mode:
                print(f"⏱️ {stage}/{step} took {duration}s")
                
        except Exception as e:
            logging.error(f"Error storing execution time: {e}")
            if self.debug_mode:
                print(f"Failed to store timing: {str(e)}")

    def debug_log(self, category, message, data=None):
        """Log debug information with proper test mode formatting"""
        if self.debug_mode:
            # Color codes for debug output
            color_codes = {
                'INFO': '\033[36m',    # Cyan
                'WARNING': '\033[33m',  # Yellow  
                'ERROR': '\033[31m',    # Red
                'SUCCESS': '\033[32m',  # Green
                'DEFAULT': '\033[0m'    # Reset
            }
            reset = '\033[0m'

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            category_color = color_codes.get(category.upper(), color_codes['DEFAULT'])
            
            print(f"\n{'='*20} {category_color}{category}{reset} {'='*20}")
            print(f"⏰ Time: {timestamp}")
            print(f"📝 Message: {message}")
            
            if data:
                print("\n📊 Data:")
                if isinstance(data, dict):
                    for key, value in data.items():
                        print(f"{key}: {value}")
                else:
                    print(data)
            print("=" * 60)
            
            # Store debug log entry
            log_entry = {
                'timestamp': timestamp,
                'category': category,
                'message': message,
                'data': data or {}
            }
            self.debug_logs.append(log_entry)

    def log_api_request(self, method, url, params=None, data=None, headers=None):
        """Log API request details for debugging"""
        if self.debug_mode:
            self.debug_log("API Request", f"{method} {url}", {
                "params": params,
                "data": data,
                "headers": headers
            })

    def log_api_response(self, response, error=None):
        """Log API response details for debugging"""
        if self.debug_mode:
            try:
                content = response.json() if response else None
            except:
                content = response.text if response else None
                
            self.debug_log("API Response", f"Status: {response.status_code if response else 'N/A'}", {
                "content": content,
                "error": str(error) if error else None
            })

    def setup_chrome_driver(self):
        self.current_step = 'browser_setup'
        start_time = time.time()
        
        try:
            print("event called")
            
            self.emit_stage_progress('initialization', 'browser_setup', 'starting', 'Setting up Chrome browser')
            print("after event called")
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
                chromedriver_autoinstaller.install()
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                self.chrome_version = chromedriver_autoinstaller.get_chrome_version()
                elapsed_time = round(time.time() - start_time, 2)
                self.emit_stage_progress('initialization', 'browser_setup', 'completed', 
                                     f'Chrome initialized (version {self.chrome_version})',
                                     {'timing': elapsed_time})
                return True
                
            except Exception as auto_error:
                logging.warning(f"Auto-installer failed: {auto_error}")
                try:
                    chrome_version = chromedriver_autoinstaller.get_chrome_version()
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

    def take_screenshot(self, name):
        try:
            screenshot_path = os.path.join(self.screenshots_folder, f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            self.driver.save_screenshot(screenshot_path)
            return screenshot_path
        except Exception as e:
            logging.error(f"Failed to take screenshot: {e}")
            return None

    def validate_form_fields(self, pnr, ssr_email):
        errors = []
        if not pnr or len(pnr) != 6:
            errors.append("Invalid PNR format")
        if not ssr_email or '@' not in ssr_email:
            errors.append("Invalid email format")
        return errors

    def wait_for_file_download(self, filename, timeout=30):
        start_time = time.time()
        expected_file = os.path.join(self.download_folder, filename)
        
        while time.time() - start_time < timeout:
            if os.path.exists(expected_file):
                if os.path.getsize(expected_file) > 0:
                    return expected_file
            time.sleep(1)
        return None

    # Update fetch_invoice_data to completely remove browser form filling
    def fetch_invoice_data(self, pnr, ssr_email):
        """Fetch invoice data using only API calls like indigo_raw"""
        start_time = time.time()
        self.current_stage = 'request'
        self.current_step = 'page_load'
        error_screenshot = None
        
        try:
            errors = self.validate_form_fields(pnr, ssr_email)
            if errors:
                raise Exception(f"Validation failed: {', '.join(errors)}")

            # Initialize session with proxy - no browser needed
            session, session_msg = self.init_session(24000)  # Default PORT from indigo_raw
            if session_msg != 'ok':
                raise Exception(f"Failed to initialize session: {session_msg}")

            # Get invoice IDs using API
            invoice_ids, msg = self.get_invoice_ids(session, pnr, ssr_email)
            logging.info(f"invoice_ids: {invoice_ids}")
            if msg != 'ok':
                if msg == '403':
                    raise Exception("IP BLOCKED PORTAL ISSUE")
                raise Exception(f"ERROR INVOICE ID PORTAL ISSUE: {msg}")

            # Get auth token using API
            auth_token, msg = self.get_auth_token(session, ssr_email, pnr)
            logging.info(f"auth_token obtained: {bool(auth_token)}")
            if msg != 'ok':
                raise Exception(f"ERROR AUTH TOKEN PORTAL ISSUE: {msg}")

            # Process invoices using API
            html_links = []
            inv_status = []
            
            for invoice_id in invoice_ids:
                invoice_html, msg = self.get_invoice_html(session, auth_token, invoice_id)
                logging.info(f"Processing invoice {invoice_id}")

                if msg != 'ok':
                    logging.info(f"Invoice fetch failed: {msg}")
                    inv_status.append(f'InvoiceID:{invoice_id} - ERROR INVOICE FETCH PORTAL ISSUE')
                    continue

                invoice_html_render, msg = self.format_html(session, invoice_html)
                if msg != 'ok':
                    logging.info(f"HTML formatting failed: {msg}")
                    inv_status.append(f'InvoiceID:{invoice_id} - ERROR INVOICE FORMATTING ISSUE')
                    continue

                # Save HTML file
                html_status, html_path = self.save_file(
                    invoice_html_render.encode('utf-8'),
                    f'{pnr}-{invoice_id}.html'
                )

                if html_status:
                    html_links.append(html_path)
                    logging.info(f"Saved invoice {invoice_id} to {html_path}")

            if len(html_links) > 0:
                return True, invoice_ids, None
            else:
                raise Exception("NO RECORD FOUND")

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            error_msg = str(e)
            logging.error(f"Fetch invoice data failed: {error_msg}")
            self.emit_stage_progress(self.current_stage, self.current_step or 'unknown', 
                                 'error', error_msg, {'timing': elapsed})
            raise Exception(error_msg)

    def process_invoice(self, session, pnr, invoice_data):
        """Process invoice with retries and validation"""
        start_time = time.time()
        self.current_stage = 'processing'
        self.current_step = 'download'
        processed_files = []
        
        try:
            self.emit_stage_progress('processing', 'download', 'starting', 'Processing invoices')
            
            ssr_email = invoice_data.get('ssr_email')
            invoice_ids = invoice_data.get('invoices', [])
            
            auth_token, auth_msg = self.get_auth_token(session, ssr_email, pnr)
            if auth_msg != 'ok':
                raise Exception(f"Authentication failed: {auth_msg}")

            for invoice_id in invoice_ids:
                try:
                    html_content, html_msg = self.get_invoice_html(session, auth_token, invoice_id)
                    if html_msg != 'ok':
                        logging.error(f"Failed to get invoice {invoice_id}: {html_msg}")
                        continue

                    formatted_html, format_msg = self.format_html(session, html_content)
                    if format_msg != 'ok':
                        logging.error(f"Failed to format invoice {invoice_id}: {format_msg}")
                        continue

                    # Save formatted HTML with exact naming convention from indigo_raw
                    filename = f'{pnr}-{invoice_id}.html'
                    save_status, file_path = self.save_file(
                        formatted_html.encode('utf-8'), 
                        filename
                    )

                    if save_status:
                        processed_files.append({
                            'path': file_path,
                            'name': filename,
                            'invoice_id': invoice_id,
                            'type': 'Invoice',
                            'format': 'html',
                            'size': os.path.getsize(file_path) if os.path.exists(file_path) else 0
                        })

                except Exception as e:
                    logging.error(f"Failed to process invoice {invoice_id}: {str(e)}")
                    continue

            if not processed_files:
                raise Exception("No invoices were successfully processed")

            elapsed_time = round(time.time() - start_time, 2)
            self.emit_stage_progress('processing', 'download', 'completed', 
                                 f'Processed {len(processed_files)} invoices', 
                                 {'timing': elapsed_time})
            
            return processed_files

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            error_msg = f"Failed to process invoices: {str(e)}"
            self.emit_stage_progress('processing', 'download', 'error', 
                                 error_msg, {'timing': elapsed})
            raise Exception(error_msg)

    def cleanup(self):
        """Clean up resources based on API-only approach"""
        try:
            if self.debug_mode:
                print("[DEBUG] Starting cleanup process")

            if not self.debug_mode and self.db_ops and self.current_pnr:
                self.db_ops.store_scraper_state(
                    pnr=self.current_pnr,
                    state='completed',
                    message='Scraper execution completed',
                    data={
                        'timing_data': self.timing_data,
                        'execution_time': round(time.time() - (self.execution_start or time.time()), 2)
                    },
                    ssr_email=getattr(self, 'ssr_email', None)
                )

            if not self.debug_mode:
                for folder in [self.temp_dir, self.screenshots_folder]:
                    if os.path.exists(folder):
                        try:
                            shutil.rmtree(folder)
                        except Exception as e:
                            logging.error(f"Failed to clean up folder {folder}: {e}")

            # Close session if it exists
            if self.session:
                try:
                    self.session.close()
                except:
                    pass
                
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")

    def handle_error(self, stage, step, error, context=None, send_email=False):
        """Comprehensive error handler for error broadcasting with optional email notification"""
        try:
            if not step or step == 'unknown':
                step = self.current_step or 'unknown'

            # Save current context    
            self.current_stage = stage
            self.current_step = step
            self.context = context or {}
            
            error_msg = str(error)
            error_data = {
                'error': error_msg,
                'stage': stage,
                'step': step,
                'context': context,
                'error_path': f"{stage}/{step}"
            }

            # Add traceback if available
            if context and 'traceback' in context:
                error_data['traceback'] = context['traceback']

            # Add error trail if available
            if context and 'error_trail' in context:
                error_data['error_trail'] = context['error_trail']

            # Update timing data
            self.store_execution_time(stage, step, None)

            # Take error screenshot if browser is available
            if self.driver:
                error_screenshot = self.take_screenshot(f'error_{stage}_{step}')
                if error_screenshot:
                    error_data['screenshot'] = error_screenshot

            # Log error details with full context if available
            error_log_msg = f"Error in {stage}/{step}: {error_msg}"
            if context and 'error_trail' in context:
                error_log_msg += f"\nError Trail:\n" + "\n".join([f"- {err}" for err in context['error_trail']])
            if context and 'traceback' in context:
                error_log_msg += f"\nTraceback:\n{context['traceback']}"
            logging.error(error_log_msg)

            # Emit error progress
            self.emit_stage_progress(
                stage=stage,
                step=step,
                status='error',
                message=f"Error: {error_msg}",
                data=error_data
            )

            # Send error notification if handler available and send_email is True
            if send_email and self.notification_handler and not self.debug_mode:
                detailed_error = f"Error in {stage}/{step}: {error_msg}"
                if context and 'error_trail' in context:
                    detailed_error += "\n\nError Trail:\n" + "\n".join([f"- {err}" for err in context['error_trail']])
                
                self.notification_handler.send_scraper_notification(
                    error=detailed_error,
                    data={
                        'Ticket/PNR': self.current_pnr,
                        'SSR_Email': getattr(self, 'ssr_email', 'N/A'),
                        'Error_Path': f"{stage}/{step}",
                        'Error_Trail': context.get('error_trail', []) if context else []
                    },
                    stage=f"{stage}/{step}",
                    airline="Indigo Air"
                )
                error_data['error'] = detailed_error
                error_msg = detailed_error

            # Update DB state if available
            if not self.debug_mode and self.db_ops and self.current_pnr:
                self.db_ops.store_scraper_state(
                    pnr=self.current_pnr,
                    state='failed',
                    message=error_msg,
                    data=error_data,
                    ssr_email=context.get('ssr_email') if context and 'ssr_email' in context else getattr(self, 'ssr_email', None)
                )

            return error_data

        except Exception as e:
            # Failsafe error logging if error handler itself fails
            logging.error(f"Error handler failed: {str(e)}")
            logging.error(f"Original error was: {str(error)}")
            return {
                'error': str(error),
                'stage': stage,
                'step': step or 'unknown',
                'handler_error': str(e)
            }

    # Update init_session to use error handler
    def init_session(self, port):
        """Initialize session with proper error handling"""
        PROXY_URL = f'https://user-finkraftscraper-sessionduration-1:7o_ycvJzWs3s8f6RmR@gate.smartproxy.com:{port}'
        proxies = {
            'http': PROXY_URL,
            'https': PROXY_URL
        }
        
        try:
            self.session = requests.Session()
            self.session.proxies.update(proxies)
            url = 'https://www.goindigo.in/view-gst-invoice.html'
            response = self.session.get(url, headers=HEADERS)
            return self.session, 'ok'
        except requests.exceptions.RequestException as e:
            error_data = self.handle_error(
                'initialization', 
                'session_setup',
                e,
                context={'proxy_url': PROXY_URL},
                send_email=False
            )
            self.session = None
            return None, f'FAILED_TO_INIT_WEBSESSION - {str(e)}'
        except Exception as e:
            error_data = self.handle_error(
                'initialization', 
                'session_setup',
                e,
                context={'proxy_url': PROXY_URL},
                send_email=False
            )
            return None, f'FAILED_TO_INIT_WEBSESSION - {str(e)}'

    def get_invoice_ids(self, session, pnr, ssr_email):
        """Get invoice IDs with proper error handling"""
        self.set_current_step('get_invoice_ids')
        url = 'https://book.goindigo.in/booking/ValidateGSTInvoiceDetails'
        params = {
            'indigoGSTDetails.PNR': pnr,
            'indigoGSTDetails.email': ssr_email
        }

        try:
            r = session.get(url, params=params, headers=HEADERS)
            if r.status_code != 200:
                error_data = self.handle_error(
                    'request',
                    'get_invoice_ids',
                    f'HTTP {r.status_code}',
                    context={'response': r.text[:500]},
                    send_email=False
                )
                return None, f'FAILED_TO_GET_INVOICEID - Status: {r.status_code}'

            try:
                r_obj = r.json()
                if gst_details := r_obj.get("indigoGSTDetails"):
                    if msg := gst_details.get('errorMessage'):
                        error_data = self.handle_error(
                            'request',
                            'get_invoice_ids',
                            msg,
                            context={'response': r_obj},
                            send_email=False
                        )
                        return None, f'FAILED_TO_GET_INVOICEID - {msg}'
                    
                    invoice_numbers = set()
                    if invoice_details := gst_details.get("invoiceDetails", {}).get("objInvoiceDetails", []):
                        for x in invoice_details:
                            if invoice_num := x.get("invoiceNumber"):
                                invoice_numbers.add(invoice_num)
                        if invoice_numbers:
                            return list(invoice_numbers), 'ok'
                        
                    error_data = self.handle_error(
                        'request',
                        'get_invoice_ids',
                        'No invoice numbers found',
                        context={'response': r_obj},
                        send_email=False
                    )
                    return None, "No invoice numbers found in response"
                return None, "Invalid response format"
                    
            except JSONDecodeError as e:
                error_data = self.handle_error(
                    'request',
                    'get_invoice_ids',
                    e,
                    context={'response_text': r.text[:500]},
                    send_email=False
                )
                return None, f'Invalid JSON response - {r.text[:200]}'
                    
        except ConnectionError as e:
            error_data = self.handle_error(
                'request',
                'get_invoice_ids',
                e,
                context={'url': url, 'params': params},
                send_email=False
            )
            return None, f'Connection error: {str(e)}'
        except Exception as e:
            error_data = self.handle_error(
                'request',
                'get_invoice_ids',
                e,
                context={'url': url, 'params': params},
                send_email=False
            )
            return None, f'Unexpected error: {str(e)}'

    def get_auth_token(self, session, email, pnr):
        """Get authentication token using exact indigo_raw implementation"""
        self.set_current_step('get_auth_token')
        url = 'https://book.goindigo.in/Booking/GSTInvoiceDetails'
        data = {
            'indigoGSTDetails.PNR': pnr,
            'indigoGSTDetails.CustEmail': email,
            'indigoGSTDetails.InvoiceNumber': '',
            'indigoGSTDetails.InvoiceEmail': ''
        }

        try:
            r = session.post(url, data=data, headers=HEADERS)
        except ConnectionError as e:
            return None, f'FAILED_TO_CONNECT_TO_AUTH - {e}'

        if r.status_code != 200:
            return None, f'FAILED_AUTH_TOKEN_REQUEST - HTTP_STATUS:{r.status_code} - TEXT:{r.text}'

        soup = BeautifulSoup(r.content, "html.parser")
        try:
            request_verification_token = soup.find(
                "input", attrs={"name": "__RequestVerificationToken"})['value']
        except AttributeError as e:
            return None, 'FAILED_SEARCH_AUTH_TOKEN_IN_FORM'
        return request_verification_token, 'ok'

    def get_invoice_html(self, session, auth_token, invoice_id):
        """Get invoice HTML content with exact indigo_raw retry mechanism and proper error handling"""
        self.set_current_step('fetch_invoice')
        url = 'https://book.goindigo.in/Booking/GSTInvoice'
        data = {
            '__RequestVerificationToken': auth_token,
            'IndigoGSTInvoice.InvoiceNumber': invoice_id,
            'IndigoGSTInvoice.IsPrint': 'false',
            'IndigoGSTInvoice.isExempted': '',
            'IndigoGSTInvoice.ExemptedMsg': ''
        }

        retry_attempts = 3
        last_error = None
        
        for attempt in range(1, retry_attempts + 1):
            try:
                r = session.post(url, data=data, headers=HEADERS)
                if r.status_code != 200:
                    error_msg = f'HTTP {r.status_code} - {r.text[:200]}'
                    last_error = error_msg
                    error_data = self.handle_error(
                        'processing',
                        'fetch_invoice',
                        error_msg,
                        context={
                            'invoice_id': invoice_id,
                            'attempt': attempt,
                            'url': url
                        },
                        send_email=False
                    )
                    if attempt < retry_attempts:
                        time.sleep(3)
                        continue
                    return None, error_data.get('error', f'FAILED_INVOICE_FETCH_REQUEST - {error_msg}')
                else:
                    if not r.content:
                        raise Exception("Empty response received")
                    return r.content, 'ok'

            except (SSLError, ProxyError) as proxy_ssl_error:
                last_error = str(proxy_ssl_error)
                if attempt < retry_attempts:
                    logging.info(f"Retrying API for the {attempt+1} time due to proxy/SSL error: {last_error}")
                    time.sleep(3)
                    continue
                error_data = self.handle_error(
                    'processing',
                    'fetch_invoice',
                    proxy_ssl_error,
                    context={
                        'invoice_id': invoice_id,
                        'attempts_made': retry_attempts,
                        'url': url,
                        'error_type': type(proxy_ssl_error).__name__
                    },
                    send_email=False
                )
                return None, error_data.get('error', f"Proxy/SSL Error after {retry_attempts} retries: {last_error}")
            
            except Exception as e:
                last_error = str(e)
                error_data = self.handle_error(
                    'processing',
                    'fetch_invoice',
                    e,
                    context={
                        'invoice_id': invoice_id,
                        'attempt': attempt,
                        'url': url,
                        'error_type': type(e).__name__
                    },
                    send_email=False
                )
                if attempt < retry_attempts:
                    time.sleep(3)
                    continue
                return None, error_data.get('error', f"Error fetching invoice: {last_error}")

        return None, f"Failed after {retry_attempts} attempts. Last error: {last_error}"

    def format_html(self, session, html):
        """Format HTML content using exact indigo_raw implementation with error handling"""
        self.set_current_step('format_html')
        try:
            soup = BeautifulSoup(html, "html.parser")
            for x in soup.find_all("div", {"role": "dialog"}):
                x.decompose()
            for x in soup.find_all("noscript"):
                x.decompose()
            for x in soup.find_all("script"):
                x.decompose()
            
            if loader := soup.find("div", {"class": "imgloaderGif"}):
                loader.decompose()
            
            imgs = soup.find_all("img")
            resource_url = "https://book.goindigo.in/"
            
            for x in imgs:
                try:
                    img_url = resource_url + x.attrs["src"]
                    response = session.get(img_url, headers=HEADERS)
                    if response.status_code != 200:
                        raise Exception(f"Failed to load image: HTTP {response.status_code}")
                        
                    b64_img = base64.b64encode(response.content)
                    x.attrs["src"] = "data:image/png;base64," + b64_img.decode()
                except Exception as img_error:
                    error_data = self.handle_error(
                        'processing',
                        'format_html',
                        img_error,
                        context={'image_url': img_url if 'img_url' in locals() else None},
                        send_email=False
                    )
                    return None, f'FAILED_TO_LOAD_IMAGES_INVOICE - {str(img_error)}'

            return str(soup), 'ok'
            
        except Exception as e:
            error_data = self.handle_error(
                'processing',
                'format_html',
                e,
                context={'html_length': len(html) if html else 0},
                send_email=False
            )
            return None, f'FAILED_TO_FORMAT_HTML - {str(e)}'

    def save_file(self, byte_content, object_name):
        """Save file following indigo_raw.py implementation"""
        file_path = 'pdf_folder/'
        os.makedirs(file_path, exist_ok=True)

        full_path = os.path.join(file_path, object_name)
        with open(full_path, 'wb') as f:
            f.write(byte_content)

        logging.info(f"Saving file to: {full_path}")

        try:
            # Call upload function if exists
            from . import upload
            status, s3link = upload.upload_file(full_path, object_name, 'indigo')
            logging.info(f"Upload result - Status: {status}, S3 Link: {s3link}")
            return status, s3link
        except ImportError:
            # If upload module not available, return local file path
            return True, full_path

def save_files_locally(files, base_path="downloaded_tickets"):
    """Save files to local directory"""
    os.makedirs(base_path, exist_ok=True)
    saved_paths = []
    
    for file in files:
        filename = os.path.basename(file)
        destination = os.path.join(base_path, filename)
        with open(destination, 'wb') as f:
            f.write(file)
        logging.info(f"Saved file locally: {destination}")
        saved_paths.append(destination)
    
    return saved_paths

def setup_chrome_options(download_folder):
    """
    Sets up Chrome options for downloading PDFs with improved driver automation support.
    """
    print("Creating Selenium WebDriver instance...")
    
    options = Options()
    prefs = {
        "download.default_directory": download_folder,
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
        chromedriver_autoinstaller.install()
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(10)
        print("Successfully initialized Chrome driver with auto-installer")
        return driver
    except Exception as auto_error:
        print(f"Auto-installer failed: {auto_error}")
        try:
            chrome_version = chromedriver_autoinstaller.get_chrome_version()
            print(f"Detected Chrome version: {chrome_version}")
            service = Service(ChromeDriverManager(version=chrome_version).install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.implicitly_wait(10)
            print(f"Successfully initialized Chrome driver with version {chrome_version}")
            return driver
        except Exception as manual_error:
            print(f"Manual installation failed: {manual_error}")
            raise Exception(f"Failed to initialize Chrome driver: {manual_error}")

def save_html_locally(html_content, filename, base_path="downloaded_tickets"):
    """Save HTML content to local directory"""
    os.makedirs(base_path, exist_ok=True)
    file_path = os.path.join(base_path, filename)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    logging.info(f"Saved HTML file locally: {file_path}")
    return True, file_path

# Update run_scraper to handle errors properly
def run_scraper(data, db_ops=None, socketio=None, count=0, PORT=24000):
    """Run scraper with enhanced progress tracking and detailed error tracing"""
    debug_mode = db_ops is None
    scraper = IndigoScraper(db_ops, socketio)
    start_time = time.time()
    failed_invoices = []
    any_success = False
    error_trail = []  # List to track error progression
    
    try:
        # Initialization stage
        scraper.current_stage = 'initialization'
        
        # Step tracking for proxy setup
        scraper.set_current_step('proxy_setup')
        scraper.emit_stage_progress('initialization', 'proxy_setup', 'starting', 'Setting up proxy connection')
        
        pnr = data['Ticket/PNR']
        ssr_email = data['SSR_Email']
        port = PORT
        scraper.current_pnr = pnr
        scraper.ssr_email = ssr_email
        scraper.execution_start = start_time

        try:
            scraper.emit_stage_progress('initialization', 'proxy_setup', 'completed', 'Proxy configuration ready')
        except Exception as e:
            error_trail.append(f"[initialization/proxy_setup] Proxy setup failed: {str(e)}")
            raise

        # Session setup with step tracking
        try:
            scraper.set_current_step('session_setup')
            scraper.emit_stage_progress('initialization', 'session_setup', 'starting', 'Initializing network session')
            current_session, current_session_mssg = scraper.init_session(port)
            if current_session_mssg != 'ok':
                error_trail.append(f"[initialization/session_setup] Session initialization failed: {current_session_mssg}")
                raise Exception("ERROR INIT PORTAL ISSUE")
            scraper.emit_stage_progress('initialization', 'session_setup', 'completed', 'Session initialized successfully')
        except Exception as e:
            error_trail.append(f"[initialization/session_setup] Session setup error: {str(e)}")
            raise

        # Environment check with step tracking
        try:
            scraper.set_current_step('environment_check')
            scraper.emit_stage_progress('initialization', 'environment_check', 'starting', 'Verifying environment')
            if not debug_mode and db_ops:
                db_ops.store_scraper_state(pnr=pnr, state='starting', message='Starting scraper execution', ssr_email=ssr_email)
            scraper.session = current_session
            scraper.emit_stage_progress('initialization', 'environment_check', 'completed', 'Environment verified')
        except Exception as e:
            error_trail.append(f"[initialization/environment_check] Environment check failed: {str(e)}")
            raise

        # Validation stage with step tracking
        scraper.current_stage = 'validation'
        
        try:
            scraper.set_current_step('pnr_validation')
            scraper.emit_stage_progress('validation', 'pnr_validation', 'starting', 'Validating PNR format')
            if not pnr or len(pnr) != 6:
                error_trail.append("[validation/pnr_validation] Invalid PNR format")
                raise Exception("Invalid PNR format")
            scraper.emit_stage_progress('validation', 'pnr_validation', 'completed', 'PNR format valid')
        except Exception as e:
            error_trail.append(f"[validation/pnr_validation] PNR validation failed: {str(e)}")
            raise

        try:
            scraper.set_current_step('email_validation')
            scraper.emit_stage_progress('validation', 'email_validation', 'starting', 'Validating email format')
            if not ssr_email or '@' not in ssr_email:
                error_trail.append("[validation/email_validation] Invalid email format")
                raise Exception("Invalid email format")
            scraper.emit_stage_progress('validation', 'email_validation', 'completed', 'Email format valid')
        except Exception as e:
            error_trail.append(f"[validation/email_validation] Email validation failed: {str(e)}")
            raise

        try:
            scraper.set_current_step('session_validation')
            scraper.emit_stage_progress('validation', 'session_validation', 'starting', 'Validating session state')
            if not current_session:
                error_trail.append("[validation/session_validation] Invalid session state")
                raise Exception("Invalid session state")
            scraper.emit_stage_progress('validation', 'session_validation', 'completed', 'Session state valid')
        except Exception as e:
            error_trail.append(f"[validation/session_validation] Session validation failed: {str(e)}")
            raise

        # Request stage with step tracking
        scraper.current_stage = 'request'
        
        try:
            scraper.set_current_step('prepare_request')
            scraper.emit_stage_progress('request', 'prepare_request', 'starting', 'Preparing API request')
            scraper.emit_stage_progress('request', 'prepare_request', 'completed', 'Request preparation complete')
        except Exception as e:
            error_trail.append(f"[request/prepare_request] Request preparation failed: {str(e)}")
            raise

        try:
            scraper.set_current_step('get_invoice_ids')
            scraper.emit_stage_progress('request', 'get_invoice_ids', 'starting', 'Fetching invoice IDs')
            invoice_ids, msg = scraper.get_invoice_ids(current_session, pnr, ssr_email)
            if msg != 'ok':
                if msg == '403':
                    error_trail.append("[request/get_invoice_ids] IP blocked by portal")
                    raise Exception("IP BLOCKED PORTAL ISSUE")
                error_trail.append(f"[request/get_invoice_ids] Failed to fetch invoice IDs: {msg}")
                raise Exception("ERROR INVOICE ID PORTAL ISSUE")
        except Exception as e:
            error_trail.append(f"[request/get_invoice_ids] Invoice IDs fetch failed: {str(e)}")
            raise
        
        try:
            scraper.set_current_step('validate_invoice_ids')
            scraper.emit_stage_progress('request', 'validate_invoice_ids', 'starting', 'Validating retrieved invoice IDs')
            if not invoice_ids:
                error_trail.append("[request/validate_invoice_ids] No invoice IDs found")
                raise Exception("No invoice IDs found")
            scraper.emit_stage_progress('request', 'validate_invoice_ids', 'completed', f'Found {len(invoice_ids)} valid invoice(s)')
        except Exception as e:
            error_trail.append(f"[request/validate_invoice_ids] Invoice IDs validation failed: {str(e)}")
            raise

        try:
            scraper.set_current_step('get_auth_token')
            scraper.emit_stage_progress('request', 'get_auth_token', 'starting', 'Retrieving authentication token')
            auth_token, msg = scraper.get_auth_token(current_session, ssr_email, pnr)
            if msg != 'ok':
                error_trail.append(f"[request/get_auth_token] Failed to get auth token: {msg}")
                raise Exception("ERROR AUTH TOKEN PORTAL ISSUE")
            scraper.emit_stage_progress('request', 'get_auth_token', 'completed', 'Authentication token obtained')
        except Exception as e:
            error_trail.append(f"[request/get_auth_token] Auth token retrieval failed: {str(e)}")
            raise

        # Processing stage with step tracking
        scraper.current_stage = 'processing'
        html_links = []
        inv_status = []
        all_errors = []

        for idx, invoice_id in enumerate(invoice_ids, 1):
            try:
                scraper.set_current_step('fetch_invoice')
                scraper.emit_stage_progress('processing', 'fetch_invoice', 'progres', 
                                          f'Fetching invoice {idx}/{len(invoice_ids)} - ID: {invoice_id}')
                invoice_html, msg = scraper.get_invoice_html(current_session, auth_token, invoice_id)
                if msg != 'ok':
                    error_msg = f'Failed to fetch invoice {invoice_id}: {msg}'
                    error_trail.append(f"[processing/fetch_invoice] {error_msg}")
                    all_errors.append(error_msg)
                    failed_invoices.append({
                        'invoice_id': invoice_id,
                        'error': error_msg,
                        'stage': 'processing',
                        'step': 'fetch_invoice'
                    })
                    inv_status.append(f'InvoiceID:{invoice_id} - ERROR INVOICE FETCH PORTAL ISSUE')
                    continue

                scraper.set_current_step('format_html')
                scraper.emit_stage_progress('processing', 'format_html', 'progres', 
                                          f'Formatting invoice {invoice_id}')
                invoice_html_render, msg = scraper.format_html(current_session, invoice_html)
                if msg != 'ok':
                    error_msg = f'Failed to format invoice {invoice_id}: {msg}'
                    error_trail.append(f"[processing/format_html] {error_msg}")
                    all_errors.append(error_msg)
                    failed_invoices.append({
                        'invoice_id': invoice_id,
                        'error': error_msg,
                        'stage': 'processing',
                        'step': 'format_html'
                    })
                    inv_status.append(f'InvoiceID:{invoice_id} - ERROR INVOICE FORMATTING ISSUE')
                    continue

                scraper.set_current_step('save_file')
                scraper.emit_stage_progress('processing', 'save_file', 'progres', 
                                          f'Saving invoice {invoice_id}')
                html_status, html_s3link = scraper.save_file(
                    invoice_html_render.encode('utf-8'),
                    f'{pnr}-{invoice_id}.html'
                )

                if html_status:
                    html_links.append(html_s3link)
                    any_success = True
                    scraper.emit_stage_progress('processing', 'save_file', 'completed', 
                                              f'Successfully saved invoice {invoice_id}')
                else:
                    error_msg = f'Failed to save invoice {invoice_id}'
                    error_trail.append(f"[processing/save_file] {error_msg}")
                    all_errors.append(error_msg)
                    failed_invoices.append({
                        'invoice_id': invoice_id,
                        'error': error_msg,
                        'stage': 'processing',
                        'step': 'save_file'
                    })
                    scraper.emit_stage_progress('processing', 'save_file', 'error', error_msg)

            except Exception as e:
                error_msg = f'Error processing invoice {invoice_id}: {str(e)}'
                error_trail.append(f"[processing/{scraper.current_step}] {error_msg}")
                all_errors.append(error_msg)
                failed_invoices.append({
                    'invoice_id': invoice_id,
                    'error': str(e),
                    'stage': 'processing',
                    'step': scraper.current_step
                })
                scraper.handle_error('processing', scraper.current_step, e, 
                                   {'invoice_id': invoice_id}, send_email=False)

        # Completion stage with step tracking
        scraper.current_stage = 'completion'

        # Determine final success status and prepare response
        if not any_success:
            error_response = {
                "success": False,
                "message": "Failed to process all invoices",
                "data": {
                    "errors": all_errors,
                    "error_trail": error_trail,
                    "failed_invoices": failed_invoices,
                    "processing_time": round(time.time() - start_time, 2)
                }
            }
            if not debug_mode and db_ops:
                db_ops.store_scraper_state(
                    pnr=pnr,
                    state='failed',
                    message='All invoice processing failed',
                    data=error_response,
                    ssr_email=ssr_email
                )
            return error_response

        # If some invoices succeeded but others failed, include both success and error info
        response_data = {
            "success": True,
            "message": "Some files processed successfully" if failed_invoices else "FILE SAVED TO S3",
            "data": {
                's3_link': html_links,
                'airline': 'indigo',
                'processing_time': round(time.time() - start_time, 2)
            }
        }

        # Include error information if there were any failures
        if failed_invoices:
            response_data["data"]["failures"] = {
                "failed_invoices": failed_invoices,
                "errors": all_errors,
                "error_trail": error_trail
            }

        if not debug_mode and db_ops:
            db_ops.store_scraper_state(
                pnr=pnr,
                state='completed_with_errors' if failed_invoices else 'completed',
                message='Processing completed with some failures' if failed_invoices else 'Processing completed successfully',
                data=response_data,
                ssr_email=ssr_email
            )

        return response_data

    except Exception as e:
        error_msg = str(e)
        logging.error(f"Scraper error: {error_msg}")
        
        # Get full traceback
        tb = traceback.format_exc()
        
        # Create detailed error context
        error_context = {
            'stage': scraper.current_stage or 'unknown',
            'step': scraper.current_step or 'unknown',
            'error_trail': error_trail,
            'traceback': tb,
            'last_error': error_msg
        }
        
        # Use proper error handling with send_email=True for final error
        if hasattr(scraper, 'handle_error'):
            error_data = scraper.handle_error(
                error_context['stage'],
                error_context['step'],
                e,
                context={
                    'data': data,
                    'ssr_email': data.get('SSR_Email'),
                    'error_trail': error_trail,
                    'traceback': tb
                },
                send_email=True  # Enable email for final error
            )
            
            # Use the detailed error message that includes the error trail
            detailed_error_msg = (
                f"Error in {error_context['stage']}/{error_context['step']}: {error_msg}\n"
                f"Error Trail:\n" + "\n".join([f"- {err}" for err in error_trail]) +
                f"\n\nTraceback:\n{tb}"
            )
            error_msg = detailed_error_msg

        else:
            # Fallback error emission if scraper not properly initialized
            if hasattr(scraper, 'emit_stage_progress'):
                scraper.emit_stage_progress(
                    error_context['stage'],
                    error_context['step'],
                    'error',
                    f'Error: {detailed_error_msg}'
                )

        # DB update uses the detailed error message
        if not debug_mode and db_ops:
            db_ops.store_scraper_state(
                pnr=getattr(scraper, 'current_pnr', None),
                state='failed',
                message=error_msg,
                data=error_context,  # Store full error context
                ssr_email=data.get('SSR_Email')
            )
            
        return {
            "success": False,
            "message": error_msg,
            "data": {
                **getattr(scraper, 'timing_data', {}),
                'error_context': error_context  # Include error context in response
            }
        }
    
    finally:
        scraper.cleanup()

if __name__ == '__main__':
    import argparse

    # Configure logging for tests
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(lineno)d - %(message)s'
    )

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Run Indigo Scraper')
    parser.add_argument('--with-db', action='store_true', help='Run with database initialization')
    args = parser.parse_args()

    # Test data
    test_data = {
        'Ticket/PNR': 'RZ429P',
        'SSR_Email': 'sbtinvoice@gail.co.in',
        'Port': 10020
    }

    if args.with_db:
        print("Running with database initialization...")
        try:
                import firebase_admin
                from firebase_admin import credentials, firestore
                import json
                import time
                from datetime import datetime, timedelta
                import pytz
                from db_util import IndigoFirestoreDB
                try:
                    if not firebase_admin._apps:
                        cred = credentials.Certificate("../firebase-adminsdk.json")
                        firebase_admin.initialize_app(cred)
                    db = firestore.client()
                    print("✅ Successfully connected to Firestore")
                    db_ops = IndigoFirestoreDB(db)
                    run_scraper(data=test_data, db_ops=db_ops, PORT=10020)
                except Exception as e:
                    print(f"❌ Failed to initialize Firebase: {e}")
                    print("Please ensure firebase-adminsdk.json is present in the parent directory")
                    exit(1)
                    
        except ImportError:
            print("Failed to import database modules. Please ensure db_util.py is present.")
            exit(1)
    else:
        print("Running without database initialization...")
        run_scraper(data=test_data, PORT=10020)

    print("\nScraper Response:")
    # print(json.dumps(response, indent=2))
