import logging
import time
import requests
import json
import os
import tempfile
from datetime import datetime

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

        self.stages = {
            'initialization': {
                'name': 'Session Initialization',
                'steps': ['proxy_setup', 'session_creation', 'auth_check']
            },
            'request': {
                'name': 'API Request',
                'steps': ['encrypt_data', 'fetch_invoice', 'validate_response']
            },
            'processing': {
                'name': 'Invoice Processing',
                'steps': ['parse_data', 'generate_pdf', 'save_files']
            }
        }
        self.current_step = None

        self.error_contexts = {
            'initialization': {
                'proxy_setup': 'Failed to set up proxy connection',
                'session_creation': 'Failed to create HTTP session',
                'auth_check': 'Failed to verify authentication'
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

    def debug_log(self, category, message, data=None):
        """Centralized debug logging"""
        if self.debug_mode:
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'category': category,
                'message': message,
                'data': data or {}
            }
            print(f"\n[DEBUG] {category}: {message}")
            if data:
                print(json.dumps(data, indent=2))
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
        """Emit detailed stage and step progress"""
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

            if self.socketio:
                # Emit detailed progress
                self.socketio.emit('air_scraper_progress', progress_data)
                
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
            
        error_msg += f" (Stage: {stage}/{step})"
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

    def fetch_invoice_data(self, pnr, origin):
        """Fetch invoice data with detailed progress tracking"""
        self.current_stage = 'request'
        start_time = time.time()
        
        try:
            if self.db_ops:
                self.db_ops.store_scraper_state(
                    pnr=pnr,
                    state='fetching',
                    message='Fetching invoice data',
                    origin=origin
                )
            
            # Data encryption
            self.emit_stage_progress('request', 'encrypt_data', 'starting', 'Encrypting request data')
            enc_pnr = self.encrypt_text(pnr)
            enc_origin = self.encrypt_text(origin)
            self.emit_stage_progress('request', 'encrypt_data', 'completed', 'Data encrypted successfully')

            # API request
            self.emit_stage_progress('request', 'fetch_invoice', 'starting', 'Sending API request')
            payload = json.dumps({
                "pnr": enc_pnr,
                "originCode": enc_origin
            })
            response = self.session.post(
                f"{self.base_url}/invoice-data/gst",
                headers=self.headers,
                data=payload
            )
            print(f"hello hello bae chebbo bebo bae{str(response)}")
            self.emit_stage_progress('request', 'fetch_invoice', 'completed', 'Received API response')

            # Response validation
            self.emit_stage_progress('request', 'validate_response', 'starting', 'Validating response data')
            try:
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.HTTPError:
                error_content = response.text
                raise Exception(f"HTTP {response.status_code}: {error_content}")
            except json.JSONDecodeError:
                raise Exception(f"Invalid JSON response: {response.text}")

            if not data.get("data", {}).get("Invoices"):
                raise Exception(f"No invoices found in response: {json.dumps(data)}")
            
            self.emit_stage_progress('request', 'validate_response', 'completed', 'Response validated successfully')
            
            elapsed = round(time.time() - start_time, 2)
            self.emit_status(self.current_stage, 'completed', 'Invoice data fetched', timing=elapsed)
            
            if self.db_ops:
                self.db_ops.store_scraper_state(
                    pnr=pnr,
                    state='data_fetched',
                    message='Invoice data retrieved successfully',
                    origin=origin
                )
            
            return data
            
        except ValueError as e:
            error_msg = self.handle_error('request', 'encrypt_data', e, {
                'pnr': pnr,
                'origin': origin,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = self.handle_error('request', 'fetch_invoice', e, {
                'pnr': pnr,
                'origin': origin,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except KeyError as e:
            error_msg = self.handle_error('request', 'validate_response', "Invalid response structure", {
                'pnr': pnr,
                'origin': origin,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except Exception as e:
            
            error_msg = self.handle_error('request', self.current_step or 'unknown', e, {
                'pnr': pnr,
                'origin': origin,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)

    def verify_pdf_file(self, file_path):
        """Verify file exists, has size and is PDF format"""
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")
            
        file_size = os.path.getsize(file_path)
        if file_size < 100:  # Minimum size for valid PDF
            raise Exception(f"Invalid file size ({file_size} bytes)")
            
        with open(file_path, 'rb') as f:
            header = f.read(4)
            if header != b'%PDF':
                raise Exception("Not a valid PDF file")

    def process_invoice(self, invoice_data, pnr):
        """Process invoice with detailed step tracking"""
        self.current_stage = 'processing'
        start_time = time.time()
        processed_files = []
        temp_files = []
        
        try:
            if self.db_ops:
                self.db_ops.store_scraper_state(
                    pnr=pnr,
                    state='processing',
                    message='Processing invoice data',
                    origin=self.current_origin
                )
            
            # Parse invoice data
            self.emit_stage_progress('processing', 'parse_data', 'starting', 'Parsing invoice data')
            invoices = invoice_data["data"]["Invoices"]
            self.headers['token'] = invoice_data["data"]['token']
            self.emit_stage_progress('processing', 'parse_data', 'completed', 
                                   f'Found {len(invoices)} invoices to process')

            # Generate PDFs
            self.emit_stage_progress('processing', 'generate_pdf', 'starting', 'Generating PDF files')
            for idx, inv in enumerate(invoices, 1):
                invoice_number = inv.get("invoiceNumber", inv.get("creditNumber", ""))
                inv_type = inv.get("type", "")
                
                invoice_type = {
                    "BOS": "Bill of Supply",
                    "INV": "Tax Invoice",
                    "CR": "Credit Note"
                }.get(inv_type, "")

                pdf_payload = json.dumps({
                    "invoiceNumber": self.encrypt_text(invoice_number),
                    "type": self.encrypt_text(inv_type)
                })

                pdf_response = self.session.post(
                    f"{self.base_url}/invoice-pdf/gst",
                    headers=self.headers,
                    data=pdf_payload
                )
                pdf_response.raise_for_status()

                file_name = f'{invoice_number}_{pnr}_{invoice_type}_{int(time.time())}.pdf'
                file_path = os.path.join(self.temp_dir, file_name)
                temp_files.append(file_path)

                # Write file with proper sync
                with open(file_path, 'wb') as f:
                    f.write(pdf_response.content)
                    f.flush()
                    os.fsync(f.fileno())

                # Verify the saved PDF
                self.verify_pdf_file(file_path)

                processed_files.append({
                    'path': file_path,
                    'name': file_name,
                    'type': invoice_type,
                    'size': os.path.getsize(file_path)
                })
                self.emit_stage_progress('processing', 'generate_pdf', 'progress', 
                                       f'Processing invoice {idx}/{len(invoices)}',
                                       {'current': idx, 'total': len(invoices)})
            self.emit_stage_progress('processing', 'generate_pdf', 'completed', 'PDF generation completed')

            # Save files
            self.emit_stage_progress('processing', 'save_files', 'starting', 'Saving generated files')
            # Store invoice data in DB
            if self.db_ops:
                self.db_ops.store_invoice_data(pnr, invoice_data, processed_files)
            self.emit_stage_progress('processing', 'save_files', 'completed', 
                                   f'Successfully saved {len(processed_files)} files')
            
            elapsed = round(time.time() - start_time, 2)
            self.emit_status(self.current_stage, 'completed', 'Invoice processed', timing=elapsed)
            
            return processed_files
            
        except KeyError as e:
            error_msg = self.handle_error('processing', 'parse_data', f"Missing required field: {str(e)}", {
                'pnr': pnr,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = self.handle_error('processing', 'generate_pdf', e, {
                'pnr': pnr,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except IOError as e:
            error_msg = self.handle_error('processing', 'save_files', e, {
                'pnr': pnr,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)
        except Exception as e:
            error_msg = self.handle_error('processing', self.current_step or 'unknown', e, {
                'pnr': pnr,
                'elapsed': round(time.time() - start_time, 2)
            })
            raise Exception(error_msg)

        finally:
            # Clean up temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        # os.remove(temp_file)
                        print("deleted files")
                except Exception as e:
                    logger.error(f"Error removing temp file {temp_file}: {e}")

def run_scraper(data, db_ops=None, socketio=None):
    """Enhanced main scraper entry point with debug mode"""
    debug_mode = db_ops is None
    scraper = AirIndiaScraper(db_ops, socketio)
    start_time = time.time()
    
    if debug_mode:
        scraper.debug_log('INIT', 'Starting scraper execution', {
            'pnr': data.get('Ticket/PNR'),
            'origin': data.get('Origin'),
            'vendor': data.get('Vendor'),
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    
    try:
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
        
        # Run scraper steps
        if not scraper.init_session(8000):
            raise Exception("Failed to initialize session")
        
        invoice_data = scraper.fetch_invoice_data(pnr, origin)
        processed_files = scraper.process_invoice(invoice_data, pnr)
        
        # Update final state
        if db_ops:
            db_ops.store_scraper_state(
                pnr=pnr,
                state='completed',
                message='Processing completed successfully',
                data={
                    'files': [f['name'] for f in processed_files],
                    'processing_time': round(time.time() - start_time, 2)
                },
                origin=origin
            )
        
        if debug_mode:
            scraper.debug_log('SUCCESS', 'Scraper execution completed', {
                'files': [f['name'] for f in processed_files],
                'processing_time': round(time.time() - start_time, 2)
            })
        
        return {
            "success": True,
            "message": "FILES_SAVED_LOCALLY",
            "data": {
                'files': processed_files,
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

if __name__ == '__main__':
    # Test data for direct execution
    test_data = {
        'Ticket/PNR': 'C7ZGRA',
        'Origin': 'BR',
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
