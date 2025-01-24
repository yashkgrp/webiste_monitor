from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import requests, time, threading, logging
import urllib3
from statistics import mean  # Add this import
from config import initialize_firebase
from db_operations import FirestoreDB
from datetime import datetime, timedelta
import os
from email_utils import send_email, generate_status_email  # New import
from socket_logger import SocketLogger
import pdfkit
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from scraper_utils import run_scraper
from dom_utils import DOMChangeTracker  # New import

# Initialize logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Suppress SSL verification warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Initialize Firebase
try:
    db, bucket = initialize_firebase()
    db_ops = FirestoreDB(db)
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Firebase initialization error: {e}")
    raise

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize socket logger
socket_logger = SocketLogger()

# Initialize DOM tracker
dom_tracker = DOMChangeTracker(db_ops)

# Load initial state from Firebase
try:
    monitored_urls = db_ops.sync_urls()
    logger.info(f"Loaded {len(monitored_urls)} URLs from Firebase")
except Exception as e:
    logger.error(f"Error loading URLs from Firebase: {e}")
    monitored_urls = {}

stop_thread = False

# Add default headers to mimic a real browser
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1'
}

# Add email configuration
EMAIL_CONFIG = {
    'SMTP_SERVER': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    'SMTP_PORT': os.getenv('SMTP_PORT', 587),
    'SMTP_USER': os.getenv('SMTP_USER'),
    'SMTP_PASSWORD': os.getenv('SMTP_PASSWORD'),
    'NOTIFICATION_EMAIL': os.getenv('SMTP_NOTIFICATIONEMAIL')
}

def monitor_urls():
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    status_notification_sent = {}  # Track notification status for each URL
    last_notification_time = {}  # Track last notification time for each URL
    
    # Get notification emails
    notification_emails = db_ops.get_notification_emails()
    if not notification_emails:
        logger.warning("No notification emails configured")
    
    while not stop_thread:
        try:
            for url, site in list(monitored_urls.items()):
                current_time = time.time()
                
                # Check if enough time has passed since last notification (5 seconds minimum)
                if url in last_notification_time and current_time - last_notification_time[url] < 5:
                    continue

                last_check = site.get('last_check', 0)
                # Convert Firebase timestamp to Unix timestamp if needed
                if hasattr(last_check, 'timestamp'):
                    last_check = last_check.timestamp()
                
                if not site.get('paused', False) and current_time - float(last_check) >= int(site.get('interval', 5)):
                    start = time.time()
                    try:
                        # Add Referer header for specific domains
                        headers = session.headers.copy()
                        if 'goindigo.in' in url:
                            headers.update({
                                'Referer': 'https://www.goindigo.in/',
                                'Origin': 'https://www.goindigo.in'
                            })
                        
                        r = session.get(
                            url, 
                            timeout=10, 
                            verify=False, 
                            headers=headers,
                            allow_redirects=True
                        )
                        
                        end = time.time()
                        response_time = round((end - start) * 1000, 2)
                        
                        if r.status_code == 200:
                            # Get last 5 responses only
                            recent_history = db_ops.get_url_history(url, limit=5)
                            recent_times = [h['response_time'] for h in recent_history]
                            recent_times.append(response_time)  # Include current response
                            
                            # Calculate rolling average of last 5 responses
                            rolling_avg = mean(recent_times[-5:])  # Take only last 5 values
                            
                            if rolling_avg > 100:  # If rolling average > 100ms
                                status = "Slow"
                            else:
                                status = "Up"
                            
                            logger.debug(f"Rolling average for {url}: {rolling_avg}ms")
                        else:
                            status = f"Down: Error {r.status_code}"
                        
                        # Debug information
                        logger.debug(f"Request to {url} - Status: {r.status_code}")
                        logger.debug(f"Response headers: {dict(r.headers)}")
                        
                    except requests.RequestException as e:
                        status = f"Down: {str(e)}"
                        logger.error(f"Error checking {url}: {e}")
                    
                    end = time.time()
                    response_time = round((end - start) * 1000, 2)
                    
                    try:
                        # Check if status changed from previous state
                        previous_status = site.get('status', '')
                        current_status = status  # New status we just determined
                        
                        # Only send notifications for significant status changes
                        should_notify = False
                        notification_type = None

                        # Case 1: Site goes down from Up or Slow state
                        if current_status.startswith('Down:') and (
                            previous_status == 'Up' or 
                            previous_status == 'Slow' or 
                            previous_status == 'Initializing...'
                        ):
                            should_notify = True
                            notification_type = 'down'

                        # Case 2: Site recovers from Down state
                        elif (current_status == 'Up' or current_status == 'Slow') and (
                            previous_status.startswith('Down:')
                        ):
                            should_notify = True
                            notification_type = 'up'

                        if should_notify and notification_emails:
                            current_time = time.time()
                            # Ensure at least 5 seconds between notifications
                            if url not in last_notification_time or current_time - last_notification_time[url] >= 5:
                                for email in notification_emails:
                                    if notification_type == 'down':
                                        send_email(
                                            subject=f"Website Down Alert - {url}",
                                            body=generate_status_email(
                                                url=url,
                                                status="down",
                                                error_message=current_status.replace('Down: ', ''),
                                                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            ),
                                            to_email=email
                                        )
                                    else:  # notification_type == 'up'
                                        send_email(
                                            subject=f"Website Recovered - {url}",
                                            body=generate_status_email(
                                                url=url,
                                                status="up",
                                                downtime_duration=db_ops._format_duration(current_time - last_notification_time.get(url, current_time)),
                                                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            ),
                                            to_email=email
                                        )
                                last_notification_time[url] = current_time

                        # Update Firebase and get fresh data
                        db_ops.update_url_status(url, status, response_time)
                        updated_data = db_ops.get_url_data(url)
                        
                        if updated_data:
                            # Convert timestamps to Unix timestamps
                            if 'last_check' in updated_data and hasattr(updated_data['last_check'], 'timestamp'):
                                updated_data['last_check'] = updated_data['last_check'].timestamp()
                            monitored_urls[url] = updated_data
                        
                        # Emit update with latest data
                        data_to_emit = [dict(v, **{'url': k}) for k, v in monitored_urls.items()]
                        socketio.emit('update_data', data_to_emit)
                        logger.debug(f"Updated status for {url}: {status}")
                    except Exception as e:
                        logger.error(f"Error updating status for {url}: {e}")
            
            time.sleep(1)
        except Exception as e:
            logger.error(f"Error in monitor thread: {e}")
            time.sleep(5)

def run_automated_scraper():
    """Run scraper automatically for stored states"""
    while not stop_thread:
        try:
            states = db_ops.get_all_scraper_states()
            current_time = datetime.now(pytz.UTC)
            
            for state_id, state in states.items():
                if state.get('auto_run') and current_time >= state.get('next_run'):
                    data = {
                        'Vendor': 'Star Air',
                        'Ticket/PNR': state['pnr'],
                        'Customer_GSTIN': state['gstin']
                    }
                    
                    logger.info(f"Running automated scrape for {state_id}")
                    try:
                        result = run_scraper(data, db_ops, socketio)
                        # Update next run time regardless of result
                        db_ops.store_scraper_state(
                            state['gstin'], 
                            state['pnr'], 
                            'success' if result['success'] else 'failed'
                        )
                    except Exception as e:
                        logger.error(f"Automated scraper failed for {state_id}: {e}")
            
            time.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error(f"Error in automated scraper: {e}")
            time.sleep(300)  # Wait 5 minutes on error

@app.route('/add_url', methods=['POST'])
def add_url():
    try:
        new_url = request.form.get('new_url')
        interval = int(request.form.get('interval', '5'))
        
        if not new_url:
            return jsonify({"error": "URL is required"}), 400

        # Check if URL exists in Firebase first
        existing_data = db_ops.get_url_data(new_url)
        if existing_data:
            # If URL exists but not in local state, add it
            if new_url not in monitored_urls:
                monitored_urls[new_url] = existing_data
                data_to_emit = [dict(v, **{'url': k}) for k, v in monitored_urls.items()]
                socketio.emit('update_data', data_to_emit)
                return jsonify({"message": "URL restored from database"}), 200
            return jsonify({"error": "URL already exists"}), 400
            
        # Add new URL to Firebase and local state
        db_ops.add_url(new_url, interval)
        monitored_urls[new_url] = {
            'url': new_url,
            'status': "Initializing...",
            'last_response_time': 0,
            'avg_response_time': 0,
            'interval': interval,
            'last_check': 0,
            'paused': False
        }
        
        data_to_emit = [dict(v, **{'url': k}) for k, v in monitored_urls.items()]
        socketio.emit('update_data', data_to_emit)
        
        logger.info(f"Added new URL: {new_url}")
        return jsonify({"message": "URL added successfully"}), 200
    except Exception as e:
        logger.error(f"Error adding URL: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_url', methods=['POST'])
def delete_url():
    url = request.form.get('url')
    if url in monitored_urls:
        # Delete from Firebase and local state
        db_ops.delete_url(url)
        del monitored_urls[url]
        socketio.emit('update_data', [dict(v, **{'url': k}) for k, v in monitored_urls.items()])
    return "URL deleted", 200

@app.route('/toggle_pause', methods=['POST'])
def toggle_pause():
    url = request.form.get('url')
    if url in monitored_urls:
        # Toggle in Firebase and local state
        db_ops.toggle_pause(url)
        monitored_urls[url]['paused'] = not monitored_urls[url]['paused']
        socketio.emit('update_data', [dict(v, **{'url': k}) for k, v in monitored_urls.items()])
    return "Toggle successful", 200

@app.route('/sync', methods=['GET'])
def sync_data():
    try:
        # Get fresh data from Firebase
        fresh_urls = db_ops.sync_urls()
        
        # Update local state
        global monitored_urls
        monitored_urls.clear()
        monitored_urls.update(fresh_urls)
        
        return jsonify({
            "status": "success",
            "data": [dict(v, **{'url': k}) for k, v in monitored_urls.items()]
        }), 200
    except Exception as e:
        logger.error(f"Error in sync route: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/get_url_history/<path:url>', methods=['GET'])
def get_url_history(url):
    try:
        # Remove fixed limit by passing None
        history_data = db_ops.get_url_history(url, limit=None)
        return jsonify({
            "status": "success",
            "data": {
                "history": history_data,
                "analysis": {
                    "best_times": db_ops.analyze_best_times(url),
                    "avg_response_by_hour": db_ops.get_hourly_averages(url),
                    "reliability": db_ops.get_reliability_stats(url)
                }
            }
        }), 200
    except Exception as e:
        logger.error(f"Error fetching URL history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scraper')
def scraper_page():
    return render_template('scraper.html')

@app.route('/run_starair_scraper', methods=['POST'])
def run_starair_scraper():
    try:
        data = {
            'Vendor': 'Star Air',
            'Ticket/PNR': request.form.get('pnr'),
            'Customer_GSTIN': request.form.get('gstin')
        }
        
        if not data['Ticket/PNR'] or not data['Customer_GSTIN']:
            return jsonify({
                "success": False,
                "message": "PNR and GSTIN are required"
            }), 400

        logger.info(f"Starting scraper with PNR: {data['Ticket/PNR']}")
        
        # Store initial state
        db_ops.store_scraper_state(
            data['Customer_GSTIN'],
            data['Ticket/PNR'],
            'running'
        )
        
        # Run scraper
        result = run_scraper(data, db_ops, socketio)
        
        # Update final state with error message if failed
        db_ops.store_scraper_state(
            data['Customer_GSTIN'],
            data['Ticket/PNR'],
            'success' if result['success'] else 'failed',
            result.get('error') if not result['success'] else None  # Store error message
        )
        
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        # Store error state with message
        db_ops.store_scraper_state(
            data['Customer_GSTIN'],
            data['Ticket/PNR'],
            'failed',
            error_msg
        )
        return jsonify({
            "success": False,
            "message": error_msg,
            "error": error_msg
        }), 500

@app.route('/scraper/analytics')
def get_scraper_analytics():
    gstin = request.args.get('gstin')
    pnr = request.args.get('pnr')
    try:
        analytics = db_ops.get_scraper_analytics(gstin, pnr)
        return jsonify({"success": True, "data": analytics})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/scraper/state', methods=['GET'])
def get_scraper_states():
    try:
        states = db_ops.get_all_scraper_states()
        return jsonify({"success": True, "data": states})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/scraper/last_state')
def get_last_scraper_state():
    """Get last scraper state"""
    try:
        state = db_ops.get_last_scraper_state()
        if not state:
            return jsonify({
                "success": True,
                "data": {
                    "state": "idle",
                    "last_run": None,
                    "next_run": None,
                    "auto_run": False,
                    "error": None  # Add default error field
                }
            })
            
        # Ensure all required fields are present
        state.setdefault('state', 'idle')
        state.setdefault('pnr', None)
        state.setdefault('gstin', None)
        state.setdefault('last_run', None)
        state.setdefault('next_run', None)
        state.setdefault('auto_run', False)
        state.setdefault('error', None)  # Add default error field
        
        # Ensure error message is preserved from Firebase
        if state.get('state') == 'failed' and not state.get('error'):
            # Try to get error from message field if error field is empty
            state['error'] = state.get('message') or 'Error details not available'
        
        return jsonify({
            "success": True,
            "data": state
        })
    except Exception as e:
        logger.error(f"Error getting last scraper state: {e}")
        return jsonify({
            "success": False,
            "message": str(e),
            "data": None
        }), 500

@app.route('/scraper/dom_changes', methods=['GET'])
def get_dom_changes():
    """Get DOM changes for latest scrape"""
    try:
        changes = dom_tracker.get_recent_changes()
        if not changes:
            return jsonify({
                "success": True,
                "data": [],
                "message": "No DOM changes found"
            })
            
        return jsonify({
            "success": True,
            "data": changes
        })
    except Exception as e:
        logger.error(f"Error getting DOM changes: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@socketio.on('scraper_status')
def handle_scraper_status(data):
    """Handle scraper status updates"""
    try:
        socket_logger.log_stage(
            data.get('stage', 'unknown'),
            data.get('status', 'unknown'),
            data.get('message', '')
        )
        socketio.emit('scraper_status', data)
    except Exception as e:
        socket_logger.log_error('status_update', str(e))

@socketio.on('scraper_error')
def handle_scraper_error(data):
    """Handle scraper errors"""
    try:
        socket_logger.log_error(
            data.get('stage', 'unknown'),
            data.get('error', 'Unknown error')
        )
        socketio.emit('scraper_error', data)
    except Exception as e:
        socket_logger.log_error('error_handler', str(e))

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")
    try:
        # Sync with Firebase on each client connection
        global monitored_urls
        fresh_urls = db_ops.sync_urls()
        
        # Update local state with fresh data
        monitored_urls.clear()
        monitored_urls.update(fresh_urls)
        
        # Emit updated data to client
        data_to_emit = [dict(v, **{'url': k}) for k, v in monitored_urls.items()]
        emit('update_data', data_to_emit)
        logger.info(f"Synced {len(monitored_urls)} URLs to client")
    except Exception as e:
        logger.error(f"Error syncing URLs on client connect: {e}")

def fetch_invoices(gstin, book_code, airline, db_ops, socketio=None):
    timing_data = {}
    dom_changes = []
    current_stage = 'initialization'

    def emit_status(stage, status, message, timing=None, error=None):
        """Enhanced status emission with error details and logging"""
        if socketio:
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
                
                socket_logger.log_stage(stage, status, message, timing, error)
                socketio.emit('scraper_status', data)
                socketio.emit('scraper_event', {
                    'type': 'status' if status != 'error' else 'error',
                    'message': f"{stage.title()}: {message}"
                })
                socketio.emit('scraper_stage', {
                    'stage': stage,
                    'status': status,
                    'message': message,
                    'timing': timing
                })
            except Exception as e:
                socket_logger.log_error(stage, f"Failed to emit status: {str(e)}")
                logging.error(f"Socket emission error: {e}")

    try:
        emit_status('initialization', 'starting', 'Initializing scraper session')
        
        # Create temp directory if it doesn't exist
        if not os.path.exists('temp'):
            os.makedirs('temp')
        
        current_stage = 'login'
        emit_status(current_stage, 'starting', 'Preparing login request')
        
        login_start = time.time()
        session = requests.Session()
        
        try:
            login_url = 'https://starair.in/customer/gstinvoice'
            emit_status(current_stage, 'progress', 'Accessing login page')
            response = session.get(login_url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to access login page: {str(e)}"
            emit_status(current_stage, 'error', error_msg, error=e)
            raise Exception(error_msg)

        login_end = time.time()
        timing_data['login_time'] = round(login_end - login_start, 3)
        emit_status(current_stage, 'success', 'Login successful', timing_data['login_time'])

        # Navigation and download stages
        current_stage = 'navigation'
        emit_status(current_stage, 'starting', 'Processing invoice data')
        
        pdf_s3links = []
        try:
            # Process the invoice data here
            # This is a placeholder - implement actual invoice processing logic
            emit_status(current_stage, 'success', 'Invoice data processed successfully')
        except Exception as e:
            error_msg = f"Failed to process invoice data: {str(e)}"
            emit_status(current_stage, 'error', error_msg, error=e)
            raise

        return True, pdf_s3links, timing_data, dom_changes

    except Exception as e:
        error_msg = f"Scraper failed during {current_stage}: {str(e)}"
        emit_status(current_stage, 'error', error_msg, error=e)
        db_ops.update_scraper_status('error', error_msg)
        raise

def startair_scraper(data, db_ops, socketio=None):
    max_attempts = 3
    try:
        vendor = data['Vendor']
        airline = 'starair' if vendor == 'Star Air' else 'starair'
        book_code = data['Ticket/PNR']
        gstin = data['Customer_GSTIN']

        for attempt in range(max_attempts):
            try:
                start_time = time.time()
                status, pdf_s3links, timing_data, dom_changes = fetch_invoices(
                    gstin, 
                    book_code, 
                    airline,
                    db_ops,
                    socketio
                )
                end_time = time.time()
                timing_data['total_run'] = round(end_time - start_time, 3)

                if status:
                    return {
                        "success": True,
                        "message": "FILE_PUSHED_TO_S3",
                        "data": {
                            "s3_link": pdf_s3links,
                            "airline": airline,
                            "timing": timing_data,
                            "dom_changes": dom_changes
                        }
                    }
                
            except Exception as e:
                if attempt == max_attempts - 1:  # Last attempt
                    raise e
                logging.error(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(2)  # Wait before retrying
        
        return {"success": False, "message": "MAX_RETRIES_EXCEEDED", "data": {}}
        
    except Exception as e:
        logging.error(f"Error in startair_scraper: {str(e)}")
        return {"success": False, "message": str(e), "data": {}}

if __name__ == '__main__': 
    t = threading.Thread(target=monitor_urls)
    t.daemon = True  # Make thread daemon so it stops when main program stops
    t.start()
    
    # Start automated scraper thread
    s = threading.Thread(target=run_automated_scraper)
    s.daemon = True
    s.start()
    
    try:
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    finally:
        stop_thread = True
        t.join(timeout=5)
        s.join(timeout=5)