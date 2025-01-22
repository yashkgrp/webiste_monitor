from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import requests, time, threading, logging
import urllib3
from config import initialize_firebase
from db_operations import FirestoreDB

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

# Load initial state from Firebase
try:
    monitored_urls = db_ops.sync_urls()
    logger.info(f"Loaded {len(monitored_urls)} URLs from Firebase")
except Exception as e:
    logger.error(f"Error loading URLs from Firebase: {e}")
    monitored_urls = {}

stop_thread = False

def monitor_urls():
    session = requests.Session()
    while not stop_thread:
        try:
            for url, site in list(monitored_urls.items()):
                current_time = time.time()
                last_check = site.get('last_check', 0)
                # Convert Firebase timestamp to Unix timestamp if needed
                if hasattr(last_check, 'timestamp'):
                    last_check = last_check.timestamp()
                
                if not site.get('paused', False) and current_time - float(last_check) >= int(site.get('interval', 5)):
                    start = time.time()
                    try:
                        r = session.get(url, timeout=5, verify=False)
                        status = "Up" if r.status_code == 200 else f"Error {r.status_code}"
                    except requests.RequestException as e:
                        status = f"Down: {str(e)}"
                        logger.error(f"Error checking {url}: {e}")
                    
                    end = time.time()
                    response_time = round((end - start) * 1000, 2)
                    
                    try:
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
        history_data = db_ops.get_url_history(url)
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

if __name__ == '__main__': 
    t = threading.Thread(target=monitor_urls)
    t.daemon = True  # Make thread daemon so it stops when main program stops
    t.start()
    try:
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    finally:
        stop_thread = True
        t.join(timeout=5)