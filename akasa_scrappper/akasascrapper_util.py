import logging
import time
import requests
import os  # Add os import for temp directory handling
from bs4 import BeautifulSoup
from datetime import datetime
from socket_logger import SocketLogger
from dom_utils import DOMChangeTracker
import html5lib  # Add this import

# Initialize logger directly instead of using utils.log
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
socket_logger = SocketLogger()

class AkasaScraper:
    def __init__(self, db_ops, socketio=None):
        # Add error handling for missing html5lib
        try:
            import html5lib
        except ImportError:
            raise ImportError("html5lib is required. Install it with: pip install html5lib")
        self.db_ops = db_ops
        self.socketio = socketio
        self.session = requests.Session()
        self.base_url = 'https://prod-bl.qp.akasaair.com/api/ibe/gst/invoice'
        self.timing_data = {}
        self.dom_changes = []
        self.current_stage = 'initialization'
        self.dom_tracker = DOMChangeTracker(db_ops)
        self.scraper_name = 'Akasa Air'
        self.success_threshold = 5  # Add retry threshold
        self.retry_delay = 2  # Add retry delay in seconds

        # Add missing error states
        self.error_states = {
            'AUTH_ERROR': 'Authentication failed',
            'API_ERROR': 'API request failed',
            'VALIDATION_ERROR': 'Invalid input data',
            'NETWORK_ERROR': 'Network connection failed',
            'PARSING_ERROR': 'Failed to parse response'
        }
        
        # Add result states
        self.result_states = {
            'success': 'INVOICE_FOUND',
            'failure': 'INVOICE_NOT_FOUND',
            'error': 'ERROR_OCCURRED'
        }

        # Add stage details for better tracking
        self.stages = {
            'initialization': {
                'steps': ['setup', 'validation', 'connection'],
                'current_step': 0
            },
            'request': {
                'steps': ['prepare', 'headers', 'connection', 'sending', 'waiting', 'received'],
                'current_step': 0
            },
            'processing': {
                'steps': ['parsing', 'validation', 'saving', 'cleanup'],
                'current_step': 0
            }
        }

    def emit_detailed_update(self, category, data):
        """Emit detailed updates for specific categories"""
        if self.socketio:
            try:
                self.socketio.emit(f'akasa_scraper_{category}', {
                    **data,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                })
            except Exception as e:
                logger.error(f"Error emitting detailed update: {e}")

    def emit_status(self, stage, status, message, timing=None, error=None):
        """Enhanced status emission with more detailed updates"""
        if self.socketio:
            try:
                current_time = time.time()
                elapsed = None
                if stage in self.timing_data:
                    elapsed = round(current_time - self.timing_data[stage + '_start'], 2)

                # Emit stage step update
                if stage in self.stages:
                    step_info = self.stages[stage]
                    current_step = step_info['steps'][step_info['current_step']]
                    self.emit_detailed_update('step', {
                        'stage': stage,
                        'step': current_step,
                        'total_steps': len(step_info['steps']),
                        'current_step_number': step_info['current_step'] + 1
                    })
                    step_info['current_step'] = min(step_info['current_step'] + 1, 
                                                  len(step_info['steps']) - 1)

                # Emit performance metrics
                self.emit_detailed_update('performance', {
                    'stage': stage,
                    'elapsed_time': elapsed,
                    'memory_usage': self.get_memory_usage(),
                    'stage_metrics': {
                        'start_time': self.timing_data.get(f'{stage}_start'),
                        'end_time': current_time
                    }
                })

                # Emit detailed state
                self.emit_detailed_update('state', {
                    'stage': stage,
                    'status': status,
                    'message': message,
                    'is_error': status == 'error',
                    'has_warning': status == 'warning',
                    'progress': self.calculate_progress(stage)
                })

                # Emit technical details
                if error:
                    self.emit_detailed_update('technical', {
                        'error_type': type(error).__name__,
                        'error_details': str(error),
                        'traceback': self.get_formatted_traceback(error),
                        'stage_context': {
                            'stage': stage,
                            'status': status,
                            'timing': elapsed
                        }
                    })

                # Original status update
                data = {
                    'stage': stage,
                    'status': status,
                    'message': message,
                    'timing': elapsed or timing,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'detail': {
                        'stage_name': stage.title(),
                        'elapsed_time': elapsed,
                        'current_status': status,
                        'stage_message': message,
                        'technical_details': {
                            'memory_usage': self.get_memory_usage(),
                            'stage_progress': self.calculate_progress(stage)
                        }
                    }
                }
                
                if error:
                    data['error'] = str(error)

                self.socketio.emit('akasa_scraper_status', data)
                
                # Enhanced event logging
                self.socketio.emit('akasa_scraper_event', {
                    'type': 'status' if status != 'error' else 'error',
                    'message': f"{stage.title()}: {message}",
                    'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                    'elapsed': elapsed,
                    'details': {
                        'stage': stage,
                        'status': status,
                        'progress': self.calculate_progress(stage)
                    }
                })

            except Exception as e:
                logger.error(f"Status emission error: {e}")

    def get_memory_usage(self):
        """Get current memory usage"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024  # MB
        except:
            return 0

    def get_formatted_traceback(self, error):
        """Get formatted traceback for error"""
        import traceback
        return traceback.format_exc()

    def calculate_progress(self, stage):
        """Calculate progress percentage for current stage"""
        if stage in self.stages:
            step_info = self.stages[stage]
            return (step_info['current_step'] + 1) / len(step_info['steps']) * 100
        return 0

    def split_name_recursive(self, name):
        name_parts = name.split()

        # Extract the individual parts
        parts = []
        for i in range(len(name_parts)):
            part = ' '.join(name_parts[i:])
            parts.append(part)

        return parts

    def process_request(self, pnr, lastName, traveller_name=None):
        """Process request with timing tracking"""
        self.current_stage = 'request'
        self.timing_data['request_start'] = time.time()
        self.emit_status(self.current_stage, 'starting', f'Processing request for PNR: {pnr} with lastName: {lastName}')

        try:
            lastName = lastName.replace(" ", "%20")
            
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
                'cookie': '_gcl_au=1.1.580655752.1728020651; _ga=GA1.1.1893813556.1728020652; _fbp=fb.1.1728020651768.903977696911174466; mf_33724b3c-cd82-4597-987a-ba5bd4c58a94=||1729858689641||0||||0|0|52.77882; _clck=1jvovm4%7C2%7Cfqb%7C0%7C1738; _uetsid=32c8a3d092cb11efa340f987aaaa5d6c; _uetvid=9c61e570458f11ef8192774cf2f5ca07; _clsk=1fl5i8x%7C1729859922633%7C11%7C1%7Cf.clarity.ms%2Fcollect; _ga_CJENG9N8NS=GS1.1.1729858689.2.1.1729859922.60.0.2061467983',
                'priority': 'u=0, i',
                'sec-ch-ua': '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'same-site',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
            }
            
            response = self.session.get(
                f"{self.base_url}/view?pnr={pnr}&lastName={lastName}",
                headers=headers
            )
            if response.status_code != 200:
                return {
                    "success": False,
                    "message": f"Request failed with status code: {response.status_code}",
                    "error": "Invalid status code",
                    "data": {
                        "status_code": response.status_code
                    }
                }

        
        
            if not response.content:
                raise Exception("Empty response received")

            request_time = time.time()
            elapsed = round(request_time - self.timing_data['request_start'], 2)
            self.timing_data['request_time'] = elapsed
            self.emit_status(self.current_stage, 'success', 'Request completed successfully url:'+f"{self.base_url}/view?pnr={pnr}&lastName={lastName}", elapsed)
            
            return response

        except Exception as e:
            elapsed = round(time.time() - self.timing_data['request_start'], 2)
            error_msg = f"Request failed: {str(e)}"
            self.emit_status(self.current_stage, 'error', error_msg, elapsed, error=e)
            raise Exception(error_msg)

    def process_response(self, response, pnr, lastName, traveller_name):
        """Process response with detailed status tracking"""
        self.current_stage = 'processing'
        self.timing_data['processing_start'] = time.time()
        self.emit_status(self.current_stage, 'starting', 'Processing response')
        
        try:
            # Create temp directory if it doesn't exist
            if not os.path.exists('temp'):
                os.makedirs('temp')

            # Use more lenient parser
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Basic validation of content
            if not soup.text.strip():
                raise Exception("Response contains no text content")

            # Check for basic invoice markers
            invoice_markers = ['Tax Invoice', 'SNV AVIATION', 'GSTIN']
            found_markers = [marker for marker in invoice_markers if marker in response.text]
            
            if not found_markers:
                self.emit_status(self.current_stage, 'warning', 'Response may not contain invoice content')
            else:
                self.emit_status(self.current_stage, 'info', f'Found invoice markers: {", ".join(found_markers)}')

            epoch_time = int(time.time())
            file_name = f"{pnr}_{epoch_time}.html"
            temp_path = os.path.join('temp', file_name)

            # Save response to temp file
            with open(temp_path, 'w', encoding='utf-8') as temp_file:
                temp_file.write(str(soup))

            processing_time = round(time.time() - self.timing_data['processing_start'], 2)
            self.timing_data['processing_time'] = processing_time
            self.emit_status(self.current_stage, 'success', 'Response processed and saved', processing_time)
            
            return {
                "success": True,
                "message": "FILE_SAVED",
                "data": {
                    "airline": 'akasa',
                    "timing": self.timing_data,
                    "dom_changes": self.dom_changes,
                    "lastName": lastName,
                    "traveller_name": traveller_name,
                    "file_path": temp_path,
                    "status_code": response.status_code,
                    "markers_found": found_markers,
                    "processing_time": processing_time
                }
            }

        except Exception as e:
            elapsed = round(time.time() - self.timing_data['processing_start'], 2)
            self.emit_status(self.current_stage, 'error', str(e), elapsed, error=e)
            return {
                "success": False,
                "message": str(e),
                "error": "PROCESSING_ERROR",
                "data": {
                    "status_code": getattr(response, 'status_code', None),
                    "content_length": len(getattr(response, 'content', b'')),
                    "processing_time": elapsed
                }
            }

        finally:
            # Clean up temp file
            if 'temp_path' in locals() and os.path.exists(temp_path):
                print("hello")
                # try:
                #     os.remove(temp_path)
                # except Exception as e:
                #     logger.error(f"Error removing temp file: {e}")

def handle_scraper_error(error, pnr, traveller_name, stage, db_ops, socketio):
    """Centralized error handling for Akasa scraper"""
    error_msg = str(error)
    logger.error(f"Akasa scraper error in {stage}: {error_msg}")
    
    # Update DB state
    db_ops.store_scraper_state(
        pnr=pnr,
        state='failed',
        message=error_msg,
        lastName=traveller_name
    )
    
    # Log error for monitoring
    db_ops.log_scraper_error(
        error_type=f'ERROR_{stage.upper()}',
        error_message=error_msg,
        context={
            'pnr': pnr,
            'lastName': traveller_name,
            'stage': stage
        }
    )
    
    # Emit error events
    socketio.emit('akasa_scraper_status', {
        'stage': stage,
        'status': 'error',
        'message': error_msg
    })
    
    socketio.emit('akasa_scraper_event', {
        'type': 'error',
        'message': f"Error in {stage}: {error_msg}"
    })

def run_scraper(data, db_ops, socketio=None):
    """Enhanced scraper with initialization timing"""
    # Create Akasa-specific DB ops instance
    from akasa_scrappper.akasa_db_ops import AkasaFirestoreDB
    akasa_db = AkasaFirestoreDB(db_ops.db)  # Pass the Firestore db instance
    
    scraper = AkasaScraper(akasa_db, socketio)  # Use Akasa-specific db ops
    
    try:
        start_time = time.time()
        scraper.timing_data['initialization_start'] = start_time
        scraper.emit_status('initialization', 'starting', 'Initializing scraper components')
        
        pnr = data['Ticket/PNR']
        traveller_name = data['Traveller Name']
        
        # Add initialization logging
        logger.info(f"Starting Akasa scraper for PNR: {pnr}")
        socketio.emit("akasa_scraper_started", {
            "airline": "akasa",
            "pnr": pnr
        })

        # Modify the last successful name check
        try:
            last_successful = akasa_db.get_last_successful_name(pnr)
        except AttributeError:
            logger.warning("get_last_successful_name not available, skipping last successful name check")
            last_successful = None

        if last_successful:
            try:
                response = scraper.process_request(pnr, last_successful, traveller_name)
                result = scraper.process_response(response, pnr, last_successful, traveller_name)
                if result['success']:
                    return result
            except Exception as e:
                logger.warning(f"Failed with last successful lastName: {str(e)}")
        
        # Try different name combinations
        name_variants = scraper.split_name_recursive(traveller_name.replace("/", " ").strip())
        
        for lastName in name_variants:
            try:
                response = scraper.process_request(pnr, lastName, traveller_name)
                result = scraper.process_response(response, pnr, lastName, traveller_name)
                
                if result['success']:
                    end_time = time.time()
                    scraper.timing_data['total_run'] = round(end_time - start_time, 3)
                    scraper.emit_status('completion', 'success', 'Scraping completed successfully')
                    
                    # Final state update
                    akasa_db.store_scraper_state(
                        pnr=pnr,
                        state='completed',
                        lastName=lastName,
                        traveller_name=traveller_name,
                        message="Scraping completed successfully"
                    )
                    # Add completion event
                    socketio.emit("akasa_scraper_completed", {
                        "airline": "akasa",
                        "pnr": pnr,
                        "success": True
                    })
                    return result
                    
            except Exception as e:
                logger.warning(f"Failed attempt with lastName '{lastName}': {str(e)}")
                # Track failed attempt
                akasa_db.store_scraper_state(
                    pnr=pnr,
                    state='failed',
                    lastName=lastName,
                    traveller_name=traveller_name,
                    message=f"Failed attempt: {str(e)}"
                )
                continue
        
        raise Exception("All name combinations failed")
        
    except Exception as e:
        error_message = str(e)
        scraper.emit_status('error', 'error', f"Scraper run failed: {error_message}", error=error_message)
        logger.error(f"Scraper failed: {error_message}")
        
        # Final error state with all details
        akasa_db.store_scraper_state(
            pnr=data['Ticket/PNR'],
            state='failed',
            lastName=None,
            traveller_name=data['Traveller Name'],
            message=error_message
        )
        
        # Add failure event
        socketio.emit("akasa_scraper_completed", {
            "airline": "akasa",
            "pnr": data.get('Ticket/PNR'),
            "success": False,
            "error": error_message
        })

        # Error notification with all context
        try:
            from email_utils import send_notification_email, generate_scraper_error_email
            html_content = generate_scraper_error_email(
                pnr=data.get('Ticket/PNR', 'N/A'),
                error_message=error_message,
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                stage=scraper.current_stage,
                scraper_name=scraper.scraper_name,
                lastName=data.get('lastName'),
                traveller_name=data.get('Traveller Name')
            )
            send_notification_email(
                subject=f"{scraper.scraper_name} Scraper Error - {scraper.current_stage}",
                html_content=html_content
            )
        except Exception as email_error:
            logger.error(f"Failed to send error notification email: {email_error}")
        
        return {
            "success": False,
            "message": error_message,
            "error": error_message,
            "data": {
                "lastName": data.get('lastName'),
                "traveller_name": data.get('Traveller Name')
            }
        }

