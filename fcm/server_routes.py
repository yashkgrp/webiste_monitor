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
    },
    timezone=pytz.UTC 
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
            g.get('socketio').emit('fcm_run_completed')
        
        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Automated portal scrape failed: {error_msg}")
        if socketio:
            socketio.emit('portal_scraper_error', {
                'message': error_msg,
                'timestamp': datetime.now(pytz.UTC).isoformat()
            })
            g.get('socketio').emit('fcm_run_completed')
        return None

@portal_routes.route('/start_scraping', methods=['POST'])
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
        g.get('socketio').emit('fcm_run_completed')
    
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Portal scraping error: {error_msg}")
        g.get('socketio').emit('fcm_run_completed')
        return jsonify({
            'success': False,
            'message': error_msg
        })

@portal_routes.route('/last_state')
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

@portal_routes.route('/settings', methods=['GET', 'POST'])
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


def init_fcm_routes(app, db, socketio):
    """Initialize portal routes with dependencies"""

    def initialize_context():
        if not hasattr(g, 'db_ops'):
            g.db_ops = PortalFirestoreDB(db, 'portal')
        if not hasattr(g, 'socketio'):
            g.socketio = socketio

    @portal_routes.before_request
    def before_request():
        try:
            initialize_context()
        except Exception as e:
            logger.error(f"Failed to initialize request context: {e}")
            return jsonify({
                'success': False,
                'message': 'Failed to initialize database connection',
                'error': str(e)
            }), 500

    # Register blueprint without prefix since these are default routes
    app.register_blueprint(portal_routes,url_prefix='/fcm')

    # Initialize scheduler
    initialize_portal_scheduler(PortalFirestoreDB(db, 'portal'), socketio)

    return app
