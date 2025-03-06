from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
from .indigo_scrapper import run_scraper
from .db_util import IndigoFirestoreDB
import logging
import os
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
import traceback
import atexit

logger = logging.getLogger(__name__)
indigo_routes = Blueprint('indigo_routes', __name__)

# Initialize scheduler
scheduler = BackgroundScheduler(
    job_defaults={
        'coalesce': False,
        'max_instances': 3
    },
    timezone=pytz.UTC 
)
scheduler.start()

# Initialize file handler for indigo
current_dir = os.path.dirname(os.path.abspath(__file__))
download_dir = os.path.join(current_dir, "downloads")
os.makedirs(download_dir, exist_ok=True)

def initialize_indigo_scheduler(db_ops, socketio):
    """Initialize indigo scheduler with delayed scheduling for missed runs"""
    try:
        settings = db_ops.get_scheduler_settings()
        if not settings or not settings.get('auto_run'):
            logger.info("Auto-run disabled, skipping scheduler initialization")
            if scheduler.get_job('indigo_auto_scrape'):
                scheduler.remove_job('indigo_auto_scrape')
            if socketio:
                socketio.emit('indigo_scheduler_status', {
                    'status': 'disabled',
                    'message': 'Auto-run is disabled',
                    'next_run': None
                })
            return

        current_time = datetime.now(pytz.UTC)
        stored_next_run = settings.get('next_run')
        interval_minutes = settings.get('interval', 60)
        run_missed=False
        
        # Calculate next run time
        if stored_next_run:
            if isinstance(stored_next_run, str):
                stored_next_run = datetime.fromisoformat(stored_next_run.replace('Z', '+00:00'))
            
            if current_time > stored_next_run:
                next_run = current_time + timedelta(minutes=5)
                logger.info(f"Missed run detected. Scheduling for 5 minutes later: {next_run}")
                run_missed=True
            else:
                next_run = stored_next_run
        else:
            next_run = current_time + timedelta(minutes=interval_minutes)

        # Update scheduler settings with new next_run
        db_ops.update_scheduler_settings(
            auto_run=True,
            interval=interval_minutes,
            next_run=next_run
        )
        if scheduler.get_job('indigo_auto_scrape'):
            scheduler.remove_job('indigo_auto_scrape')

        # Schedule next run
        scheduler.add_job(
            run_automated_scrape,
            'interval',
            minutes=interval_minutes,
            next_run_time=next_run,
            args=[db_ops, socketio],
            id='indigo_auto_scrape',
            replace_existing=True
        )
        
        logger.info(f"Scheduler initialized: interval={interval_minutes}m, next_run={next_run}")
        
        # Emit initialization status
        if socketio:
            socketio.emit('indigo_scheduler_status', {
                'status': 'initialized',
                'message': f'Scheduler initialized with {interval_minutes}m interval',
                'next_run': next_run.isoformat(),
                'interval': interval_minutes,
                'auto_run': True
            })
            if run_missed:
                g.socketio.emit('indigo_settings_updated', {
                            'auto_run': True,
                            'interval': interval_minutes,
                            'next_run': next_run.isoformat(),
                            'message': 'Scheduler missed scheduling for next 5 minutes'
                        })

    except Exception as e:
        logger.error(f"Failed to initialize indigo scheduler: {e}")
        logger.error(traceback.format_exc())
        if socketio:
            socketio.emit('indigo_scheduler_error', {
                'message': str(e)
            })

def run_automated_scrape(db_ops, socketio):
    """Run automated scrape with enhanced scheduling and event emissions"""
    try:
        current_time = datetime.now(pytz.UTC)
        settings = db_ops.get_scheduler_settings()
        
        if not settings or not settings.get('auto_run'):
            initialize_indigo_scheduler(db_ops,socketio)
            if socketio:
                socketio.emit('indigo_auto_scrape_status', {
                    'status': 'skipped',
                    'message': 'Auto-run is disabled'
                })
            return

        # Get last state from scraper
        last_state = db_ops.get_last_scraper_state()
        if last_state:
            company_data = {
                'Ticket/PNR': last_state.get('pnr'),
                'SSR_Email': last_state.get('ssr_email'),
                'Port': 24000
            }
            
            if company_data.get('Ticket/PNR') and company_data.get('SSR_Email'):
                if socketio:
                    socketio.emit('indigo_auto_scrape_status', {
                        'status': 'starting',
                        'message': 'Starting automated scrape',
                        'pnr': company_data.get('Ticket/PNR')
                    })
                    
                result = run_scraper(company_data, db_ops, socketio)
                
                next_run = datetime.now(pytz.UTC) + timedelta(minutes=settings.get('interval', 60))
                db_ops.update_scheduler_settings(
                    auto_run=True,
                    interval=settings.get('interval', 60),
                    next_run=next_run
                )
                initialize_indigo_scheduler(db_ops, socketio)
                
                if socketio:
                    socketio.emit('indigo_settings_updated', {
                        'auto_run': True,
                        'interval': settings.get('interval', 60),
                        'next_run': next_run.isoformat(),
                        'message': 'Scheduler settings updated and activated'
                    })

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Scraping error: {error_msg}")
        logger.error(traceback.format_exc())
        
        if socketio:
            socketio.emit('indigo_auto_scrape_error', {
                'message': error_msg
            })
    finally:
        if socketio:
            socketio.emit('indigo_scrapper_run_completed')

@indigo_routes.route('/start_scraping', methods=['POST'])
def start_indigo_scraping():
    """Start indigo scraping with complete validation and error handling"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No data provided'
            }), 400

        required_fields = ['Ticket/PNR', 'SSR_Email']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return jsonify({
                'success': False,
                'message': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400

        # Store initial state with new field pattern
        g.db_ops.store_scraper_state(
            pnr=data['Ticket/PNR'],
            state='starting',
            message='Initiating scraping process',
            ssr_email=data['SSR_Email']
        )
        
        result = run_scraper(data, g.db_ops, g.socketio)
        
        if result.get('success'):
            g.db_ops.store_scraper_state(
                pnr=data['Ticket/PNR'],
                state='completed',
                message='Scraping completed successfully',
                data={
                    'files': result.get('data', {}).get('s3_link', []),
                    'timing': result.get('data', {}).get('processing_time'),
                    'airline': 'indigo'
                },
                ssr_email=data['SSR_Email']
            )
        else:
            g.db_ops.store_scraper_state(
                pnr=data['Ticket/PNR'],
                state='failed',
                message=result.get('message', 'Scraping failed'),
                data={'error': result.get('message')},
                ssr_email=data['SSR_Email']
            )
        
        return jsonify(result)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Scraping error: {error_msg}")
        logger.error(traceback.format_exc())
        
        try:
            if 'data' in locals() and 'Ticket/PNR' in data:
                g.db_ops.store_scraper_state(
                    pnr=data['Ticket/PNR'],
                    state='error',
                    message=error_msg,
                    ssr_email=data['SSR_Email']
                )
        except:
            pass
            
        return jsonify({
            'success': False,
            'message': error_msg,
            'data': None
        }), 500
    finally:
        g.socketio.emit('indigo_scrapper_run_completed')

@indigo_routes.route('/last_state')
def get_indigo_last_state():
    """Get last scraper state with complete error handling and safe defaults"""
    try:
        state = g.db_ops.get_last_scraper_state()
        if not state:
            return jsonify({
                'success': True,
                'data': {
                    'state': 'unknown',
                    'message': 'No previous state found',
                    'timestamp': datetime.now(pytz.UTC).isoformat()
                }
            })

        # Format timestamps safely
        try:
            if 'timestamp' in state:
                state['timestamp'] = state['timestamp'].isoformat() if isinstance(state['timestamp'], datetime) else state['timestamp']
            if 'next_run' in state:
                state['next_run'] = state['next_run'].isoformat() if isinstance(state['next_run'], datetime) else state['next_run']
        except Exception as e:
            logger.warning(f"Error formatting timestamps: {e}")
                
        return jsonify({
            'success': True,
            'data': state
        })

    except Exception as e:
        logger.error(f"Error getting last state: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': str(e),
            'data': {
                'state': 'error',
                'message': str(e),
                'timestamp': datetime.now(pytz.UTC).isoformat()
            }
        }), 500

@indigo_routes.route('/settings', methods=['GET', 'POST'])
def indigo_scheduler_settings():
    """Manage indigo scheduler settings with event emissions"""
    try:
        if request.method == 'GET':
            settings = g.db_ops.get_scheduler_settings()
            if not settings:
                settings = {
                    'auto_run': False,
                    'interval': 60,
                    'next_run': None
                }
            return jsonify({
                'success': True,
                'data': settings
            })
            
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No settings data provided'
            }), 400

        # Validate and set defaults
        auto_run = bool(data.get('auto_run', False))
        interval = int(data.get('interval', 60))
        next_run = data.get('next_run')
        
        # Validate interval
        if not isinstance(interval, int) or interval < 1 or interval > 1440:
            return jsonify({
                'success': False,
                'message': 'Interval must be between 1 and 1440 minutes'
            }), 400
            
        # Calculate next run if not provided
        current_time = datetime.now(pytz.UTC)
        if not next_run:
            next_run = current_time + timedelta(minutes=interval)
        else:
            try:
                if isinstance(next_run, str):
                    next_run = datetime.fromisoformat(next_run.replace('Z', '+00:00'))
                if next_run < current_time:
                    next_run = current_time + timedelta(minutes=5)  # Schedule 5 minutes later if past time
            except ValueError as e:
                return jsonify({
                    'success': False,
                    'message': f'Invalid next run time format: {str(e)}'
                }), 400
            
        # Update settings
        update_success = g.db_ops.update_scheduler_settings(
            auto_run=auto_run,
            interval=interval,
            next_run=next_run
        )
        
        if not update_success:
            return jsonify({
                'success': False,
                'message': 'Failed to update settings in database'
            }), 500

        try:
            if auto_run:
                initialize_indigo_scheduler(g.db_ops, g.socketio)
                if g.socketio:
                    g.socketio.emit('indigo_settings_updated', {
                        'auto_run': auto_run,
                        'interval': interval,
                        'next_run': next_run.isoformat(),
                        'message': 'Scheduler settings updated and activated'
                    })
            else:
                if g.socketio:
                    initialize_indigo_scheduler(g.db_ops, g.socketio)
                    g.socketio.emit('indigo_settings_updated', {
                        'auto_run': False,
                        'message': 'Scheduler paused'
                    })
                
        except Exception as e:
            logger.error(f"Scheduler state update failed: {e}")
            
        return jsonify({
            'success': True,
            'message': 'Settings updated successfully',
            'data': {
                'auto_run': auto_run,
                'interval': interval,
                'next_run': next_run.isoformat() if next_run else None,
                'updated_at': current_time.isoformat()
            }
        })
        
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': str(e),
            'data': None
        }), 500

def init_indigo_routes(app, db, socketio):
    """Initialize routes with complete error handling and cleanup"""
    try:
        # Create a middleware function to initialize db and socketio
        def initialize_context():
            if not hasattr(g, 'db_ops'):
                g.db_ops = IndigoFirestoreDB(db)
            if not hasattr(g, 'socketio'):
                g.socketio = socketio

        # Register middleware for all indigo routes
        @indigo_routes.before_request
        def before_indigo_request():
            try:
                initialize_context()
            except Exception as e:
                logger.error(f"Failed to initialize request context: {e}")
                return jsonify({
                    'success': False,
                    'message': 'Failed to initialize database connection',
                    'error': str(e)
                }), 500

        # Register blueprint with url_prefix to ensure middleware only runs for indigo routes
        app.register_blueprint(indigo_routes, url_prefix='/indigo')
    
        try:
            db_ops = IndigoFirestoreDB(db)
            initialize_indigo_scheduler(db_ops, socketio)
        except Exception as e:
            logger.error(f"Failed to initialize scheduler: {e}")
    
        def cleanup_old_files():
            """Clean up files older than 7 days"""
            try:
                cutoff = datetime.now() - timedelta(days=7)
                cleaned = 0
                failed = 0
                
                for file in os.listdir(download_dir):
                    file_path = os.path.join(download_dir, file)
                    try:
                        if os.path.getctime(file_path) < cutoff.timestamp():
                            os.remove(file_path)
                            cleaned += 1
                    except Exception as e:
                        logger.error(f"Failed to remove file {file}: {e}")
                        failed += 1
                
                logger.info(f"Cleanup completed: {cleaned} files removed, {failed} failed")
                
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
        try:
            if scheduler.get_job('indigo_cleanup'):
                scheduler.remove_job('indigo_cleanup')    
            scheduler.add_job(
                cleanup_old_files,
                'interval',
                hours=24,
                id='indigo_cleanup',
                replace_existing=True
            )
        except Exception as e:
            logger.error(f"Failed to schedule cleanup job: {e}")
        
        def shutdown_handlers():
            try:
                scheduler.shutdown()
                logger.info("indigo scheduler shutdown complete")
            except:
                pass
                
        atexit.register(shutdown_handlers)
        
        return app
        
    except Exception as e:
        logger.error(f"Failed to initialize indigo routes: {e}")
        logger.error(traceback.format_exc())
        return app

if __name__ == '__main__':
    from flask import Flask
    from flask_socketio import SocketIO
    import firebase_admin
    from firebase_admin import credentials, firestore
    import logging

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Initialize Flask app
    app = Flask(__name__)
    socketio = SocketIO(app, cors_allowed_origins="*")

    # Initialize Firebase
    try:
        # Try to get the credentials file from parent directory
        cred_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'firebase-adminsdk.json')
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Failed to initialize Firebase: {e}")
        print("Make sure firebase-adminsdk.json is present in the parent directory")
        exit(1)

    # Get Firestore client
    db = firestore.client()

    # Initialize routes
    app = init_indigo_routes(app, db, socketio)

    # Run the application
    print("Starting Indigo Routes Test Server...")
    print("Access the server at http://localhost:5000")
    socketio.run(app, debug=True, port=5000)