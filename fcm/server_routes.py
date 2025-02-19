from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
import pytz
import logging
import os
from .portal_scrapper import run_scraper
from .db_util import PortalFirestoreDB
from .file_handler import FileHandler
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
portal_routes = Blueprint('fcm_routes', __name__)

# Initialize scheduler
scheduler = BackgroundScheduler(
    job_defaults={
        'coalesce': False,
        'max_instances': 3
    }
)
scheduler.start()

# Initialize file handler
current_dir = os.path.dirname(os.path.abspath(__file__))
file_handler = FileHandler(current_dir)

def initialize_portal_scheduler(db_ops, socketio):
    """Initialize portal scheduler with same behavior as air_india"""
    try:
        settings = db_ops.get_scheduler_settings()
        if not settings or not settings.get('auto_run'):
            return

        current_time = datetime.now(pytz.UTC)
        stored_next_run = settings.get('next_run')
        
        if stored_next_run:
            try:
                if isinstance(stored_next_run, (int, float)):
                    stored_next_run = datetime.fromtimestamp(stored_next_run/1000, pytz.UTC)
            except Exception as e:
                logger.error(f"Error parsing next_run time: {e}")
                stored_next_run = None

            if stored_next_run and stored_next_run <= current_time:
                # Run immediately if we missed the schedule
                scheduler.add_job(
                    run_automated_scrape,
                    'date',
                    run_date=current_time + timedelta(seconds=10),
                    args=[db_ops, socketio],
                    id=f'portal_scrape_immediate_{current_time.timestamp()}'
                )

        # Schedule next run
        interval_minutes = settings.get('interval', 60)
        next_run = current_time + timedelta(minutes=interval_minutes)
        
        scheduler.add_job(
            run_automated_scrape,
            'interval',
            minutes=interval_minutes,
            next_run_time=next_run,
            args=[db_ops, socketio],
            id='portal_scrape_scheduled',
            replace_existing=True
        )
        
        logger.info(f"Scheduled portal scraper for every {interval_minutes} minutes")
        return True

    except Exception as e:
        logger.error(f"Error initializing portal scheduler: {e}")
        return False

def run_automated_scrape(db_ops, socketio):
    """Run automated scrape with company details handling"""
    try:
        last_state = db_ops.get_last_scraper_state()
        settings = db_ops.get_scheduler_settings()
        
        if not last_state or not settings.get('auto_run'):
            return

        # Get stored credentials
        credentials = db_ops.get_credentials(last_state.get('username'))
        if not credentials:
            raise Exception("No stored credentials found")

        data = {
            'username': credentials['username'],
            'password': credentials['password'],
            'portal': last_state.get('portal')
        }

        # Run scraper
        result = run_scraper(data, db_ops, socketio)
        
        if socketio:
            socketio.emit('portal_scraper_completed', {
                'success': result['success'],
                'message': result.get('message'),
                'data': {
                    'files': result.get('data', {}).get('files', []),
                    'processing_time': result.get('data', {}).get('processing_time')
                }
            })
        
        # Schedule next run if auto-run enabled
        if settings.get('auto_run'):
            current_time = datetime.now(pytz.UTC)
            interval_minutes = settings.get('interval', 60)
            next_run = current_time + timedelta(minutes=interval_minutes)
            
            db_ops.update_scheduler_settings(
                auto_run=True,
                interval=interval_minutes,
                next_run=next_run
            )
        
        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Automated portal scrape failed: {error_msg}")
        if socketio:
            socketio.emit('portal_scraper_error', {
                'message': error_msg,
                'timestamp': datetime.now(pytz.UTC).isoformat()
            })
        return None

@portal_routes.route('/fcm/start_scraping', methods=['POST'])
def start_portal_scraping():
    """Start portal scraping with secure credential handling"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'})
            
        required_fields = ['username', 'password']
        if not all(field in data for field in required_fields):
            return jsonify({'success': False, 'message': 'Missing required fields'})

        # Store credentials securely
        db_ops = g.get('db_ops')
        if db_ops:
            db_ops.store_credentials(data['username'], data['password'])

        # Run scraper with simplified data
        result = run_scraper(data, db_ops, g.get('socketio'))
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Portal scraping error: {error_msg}")
        return jsonify({
            'success': False,
            'message': error_msg
        })

@portal_routes.route('/fcm/last_state')
def get_portal_last_state():
    """Get last state with secure credential handling"""
    try:
        db_ops = g.get('db_ops')
        if not db_ops:
            raise Exception("Database connection not available")
            
        last_state = db_ops.get_last_scraper_state()
        if not last_state:
            return jsonify({
                'success': True,
                'data': {'state': 'new'}
            })
            
        # Get credentials if available
        username = last_state.get('username')
        if username:
            credentials = db_ops.get_credentials(username)
            if credentials:
                last_state['password'] = credentials['password']
        
        return jsonify({
            'success': True,
            'data': last_state
        })
        
    except Exception as e:
        logger.error(f"Error getting last state: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@portal_routes.route('/fcm/settings', methods=['GET', 'POST'])
def portal_scheduler_settings():
    """Handle portal scheduler settings"""
    try:
        db_ops = g.get('db_ops')
        if not db_ops:
            raise Exception("Database connection not available")
            
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                raise Exception("No settings data provided")
                
            auto_run = data.get('auto_run', False)
            interval = data.get('interval', 60)
            
            if interval < 1:
                raise Exception("Interval must be at least 1 minute")
                
            # Calculate next run time
            current_time = datetime.now(pytz.UTC)
            next_run = current_time + timedelta(minutes=interval)
            
            # Update settings
            success = db_ops.update_scheduler_settings(
                auto_run=auto_run,
                interval=interval,
                next_run=next_run
            )
            
            if success:
                # Reinitialize scheduler
                initialize_portal_scheduler(db_ops, g.get('socketio'))
                
                # Emit scheduler update event
                if g.get('socketio'):
                    g.get('socketio').emit('scheduler_update', {
                        'settings': {
                            'auto_run': auto_run,
                            'interval': interval,
                            'next_run': int(next_run.timestamp() * 1000)
                        }
                    })
                
                return jsonify({
                    'success': True,
                    'message': 'Settings updated successfully',
                    'settings': {
                        'auto_run': auto_run,
                        'interval': interval,
                        'next_run': int(next_run.timestamp() * 1000)
                    }
                })
            else:
                raise Exception("Failed to update settings")
                
        else:  # GET request
            settings = db_ops.get_scheduler_settings()
            return jsonify({
                'success': True,
                'settings': settings
            })
            
    except Exception as e:
        logger.error(f"Settings error: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@portal_routes.route('/fcm/member', methods=['POST'])
def manage_portal_member():
    """Handle member management operations"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'})
            
        required_fields = ['username', 'password', 'member_data']
        if not all(field in data for field in required_fields):
            return jsonify({'success': False, 'message': 'Missing required fields'})
            
        # Add member management flag
        data['manage_members'] = True
        
        # Run scraper with member management
        result = run_scraper(data, g.get('db_ops'), g.get('socketio'))
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Member management error: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@portal_routes.route('/upload', methods=['POST'])
def upload_file():
    """Handle file uploads for CSV invoice lists"""
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file provided'
            })
            
        file = request.files['file']
        if not file.filename:
            return jsonify({
                'success': False,
                'message': 'No file selected'
            })
            
        if not file.filename.endswith('.csv'):
            return jsonify({
                'success': False,
                'message': 'Only CSV files are allowed'
            })
            
        result = file_handler.save_upload(file, 'invoice_lists')
        if not result['success']:
            raise Exception(result.get('error', 'Failed to save file'))
            
        return jsonify({
            'success': True,
            'path': result['path']
        })
        
    except Exception as e:
        logger.error(f"File upload error: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@portal_routes.route('/fcm/files', methods=['GET'])
def get_portal_files():
    """Get processed file records with filtering"""
    try:
        db_ops = g.get('db_ops')
        if not db_ops:
            raise Exception("Database connection not available")
            
        # Parse query parameters
        username = request.args.get('username')
        file_type = request.args.get('type')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Convert date strings to datetime if provided
        if start_date:
            start_date = datetime.fromtimestamp(int(start_date)/1000, pytz.UTC)
        if end_date:
            end_date = datetime.fromtimestamp(int(end_date)/1000, pytz.UTC)
            
        records = db_ops.get_file_records(
            username=username,
            file_type=file_type,
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify({
            'success': True,
            'data': records
        })
        
    except Exception as e:
        logger.error(f"Error retrieving file records: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

def init_fcm_routes(app, db, socketio):
    """Initialize routes with dependencies"""
    app.register_blueprint(portal_routes)
    
    # Add dependencies to request context
    @app.before_request
    def before_request():
        g.db_ops = PortalFirestoreDB(db, 'fcm')
        g.socketio = socketio
        # g.file_handler = file_handler
    
    # Initialize scheduler
    # initialize_portal_scheduler(PortalFirestoreDB(db, 'portal'), socketio)
    
    # Schedule cleanup of old files
    # scheduler.add_job(
    #     file_handler.cleanup_old_files,
    #     'interval',
    #     hours=24,
    #     id='file_cleanup'
    # )
    
    return app
