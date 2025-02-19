from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
from .alliance_scrapper import run_scraper
from .db_util import AllianceFirestoreDB
import logging
import os
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
import traceback
import atexit

logger = logging.getLogger(__name__)
alliance_routes = Blueprint('alliance_routes', __name__)

# Initialize scheduler
scheduler = BackgroundScheduler(
    job_defaults={
        'coalesce': False,
        'max_instances': 3
    }
)
scheduler.start()

# Initialize file handler for alliance
current_dir = os.path.dirname(os.path.abspath(__file__))
download_dir = os.path.join(current_dir, "downloads")
os.makedirs(download_dir, exist_ok=True)

def initialize_alliance_scheduler(db_ops, socketio):
    """Initialize alliance scheduler with delayed scheduling for missed runs"""
    try:
        settings = db_ops.get_scheduler_settings()
        if not settings or not settings.get('auto_run'):
            logger.info("Auto-run disabled, skipping scheduler initialization")
            if scheduler.get_job('alliance_auto_scrape'):
                scheduler.remove_job('alliance_auto_scrape')
            if socketio:
                socketio.emit('alliance_scheduler_status', {
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
                # Missed run - schedule for 5 minutes from now
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
        if scheduler.get_job('alliance_auto_scrape'):
            scheduler.remove_job('alliance_auto_scrape')

        # Schedule next run
        scheduler.add_job(
            run_automated_scrape,
            'interval',
            minutes=interval_minutes,
            next_run_time=next_run,
            args=[db_ops, socketio],
            id='alliance_auto_scrape',
            replace_existing=True
        )
        
        logger.info(f"Scheduler initialized: interval={interval_minutes}m, next_run={next_run}")
        
        # Emit initialization status
        if socketio:
            socketio.emit('alliance_scheduler_status', {
                'status': 'initialized',
                'message': f'Scheduler initialized with {interval_minutes}m interval',
                'next_run': next_run.isoformat(),
                'interval': interval_minutes,
                'auto_run': True
            })
            if run_missed:
                g.socketio.emit('alliance_settings_updated', {
                            'auto_run': True,
                            'interval': interval_minutes,
                            'next_run': next_run.isoformat(),
                            'message': 'Scheduler missed scheduling for next 5 minutes'
                        })

    except Exception as e:
        logger.error(f"Failed to initialize alliance scheduler: {e}")
        logger.error(traceback.format_exc())
        if socketio:
            socketio.emit('alliance_scheduler_error', {
                'message': str(e)
            })

def run_automated_scrape(db_ops, socketio):
    """Run automated scrape with enhanced scheduling and event emissions"""
    try:
        current_time = datetime.now(pytz.UTC)
        settings = db_ops.get_scheduler_settings()
        
        if not settings or not settings.get('auto_run'):
            initialize_alliance_scheduler(db_ops,socketio)
            if socketio:
                socketio.emit('alliance_auto_scrape_status', {
                    'status': 'skipped',
                    'message': 'Auto-run is disabled'
                })
            return

        # Get company details from latest state
        last_state = db_ops.get_last_scraper_state()
        if last_state:
            
            company_data={
                'Ticket/PNR':last_state.get('pnr','no pnr avlr'),
                'Transaction_Date':last_state.get('transaction_date','no date avl'),
                'Vendor':last_state.get('vendor','ALLIANCE AIR ')
            }
            data=company_data
            if company_data:
                if socketio:
                    socketio.emit('alliance_auto_scrape_status', {
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
                initialize_alliance_scheduler(db_ops,socketio)
                socketio.emit('alliance_settings_updated', {
                        'auto_run': True,
                        'interval': settings.get('interval', 60),
                        'next_run': next_run.isoformat(),
                        'message': 'Scheduler settings updated and activated'
                    })
                
                if result.get('success'):
                    g.db_ops.store_scraper_state(
                        pnr=data['Ticket/PNR'],
                        state='completed',
                        message='Scraping completed successfully',
                        data={
                            'files': result.get('data', {}).get('files', []),
                            'timing': result.get('data', {}).get('timing_data', {}),
                            'screenshot': result.get('data', {}).get('screenshot_path'),
                            'airline': 'alliance_air'
                        },
                        
                    )
                else:
                    g.db_ops.store_scraper_state(
                        pnr=data['Ticket/PNR'],
                        state='failed',
                        message=result.get('message', 'Scraping failed'),
                        data={'error': result.get('message')},
                        
                    )

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
                    transaction_date=data['Transaction_Date'],
                )
        except:
            pass
    finally:
        socketio.emit('alliance_scrapper_run_completed')

@alliance_routes.route('/alliance/start_scraping', methods=['POST'])
def start_alliance_scraping():
    """Start alliance scraping with complete validation and error handling"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': 'No data provided'
            }), 400

        required_fields = ['Ticket/PNR', 'Transaction_Date']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return jsonify({
                'success': False,
                'message': f'Missing required fields: {", ".join(missing_fields)}'
            }), 400

        # Validate date format
        try:
            datetime.strptime(data['Transaction_Date'], '%d-%m-%Y')
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid date format. Required format: DD-MM-YYYY'
            }), 400

        # Store initial state
        g.db_ops.store_scraper_state(
            pnr=data['Ticket/PNR'],
            state='starting',
            message='Initiating scraping process',
            transaction_date=data['Transaction_Date'],
            vendor='ALLIANCE AIR'
        )
        
        result = run_scraper(data, g.db_ops, g.socketio)
        
        if result.get('success'):
            g.db_ops.store_scraper_state(
                pnr=data['Ticket/PNR'],
                state='completed',
                message='Scraping completed successfully',
                data={
                    'files': result.get('data', {}).get('files', []),
                    'timing': result.get('data', {}).get('timing_data', {}),
                    'screenshot': result.get('data', {}).get('screenshot_path'),
                    'airline': 'alliance_air'
                },
                transaction_date=data['Transaction_Date'],
            )
        else:
            g.db_ops.store_scraper_state(
                pnr=data['Ticket/PNR'],
                state='failed',
                message=result.get('message', 'Scraping failed'),
                data={'error': result.get('message')},
                transaction_date=data['Transaction_Date'],
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
                    transaction_date=data['Transaction_Date'],
                )
        except:
            pass
            
        return jsonify({
            'success': False,
            'message': error_msg,
            'data': None
        }), 500
    finally:
        g.socketio.emit('alliance_scrapper_run_completed')

@alliance_routes.route('/alliance/last_state')
def get_alliance_last_state():
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

@alliance_routes.route('/alliance/settings', methods=['GET', 'POST'])
def alliance_scheduler_settings():
    """Manage alliance scheduler settings with event emissions"""
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

        # Update scheduler state
        try:
            if auto_run:
                
                initialize_alliance_scheduler(g.db_ops, g.socketio)
                
                # Emit settings update event
                if g.socketio:
                    g.socketio.emit('alliance_settings_updated', {
                        'auto_run': auto_run,
                        'interval': interval,
                        'next_run': next_run.isoformat(),
                        'message': 'Scheduler settings updated and activated'
                    })
            else:
                
                # Emit disabled status
                if g.socketio:
                    initialize_alliance_scheduler(g.db_ops, g.socketio)
                    g.socketio.emit('alliance_settings_updated', {
                        'auto_run': False,
                        'message': 'Scheduler paused'
                    })
                
        except Exception as e:
            logger.error(f"Scheduler state update failed: {e}")
            # Don't fail the request if scheduler update fails
        
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

@alliance_routes.route('/alliance/changes', methods=['GET'])
def get_alliance_changes():
    """Get alliance DOM changes with complete validation and error handling"""
    try:
        # Validate and sanitize input parameters
        try:
            limit = min(int(request.args.get('limit', 1000)), 5000)  # Cap at 5000
        except ValueError:
            limit = 1000  # Default if invalid

        page_id = request.args.get('page_id')
        if page_id and not isinstance(page_id, str):
            
            page_id='alliance_gst_portal'
        
        changes = g.db_ops.get_dom_changes(
            page_id=page_id,
            limit=limit
        )
        
        # Ensure we always return a list, even if empty
        if changes is None:
            changes = []
            
        # Format timestamps in changes
        for change in changes:
            if 'timestamp' in change:
                try:
                    change['timestamp'] = change['timestamp'].isoformat() if isinstance(change['timestamp'], datetime) else change['timestamp']
                except:
                    change['timestamp'] = str(change['timestamp'])
        
        return jsonify({
            'success': True,
            'data': {
                'changes': changes,
                'count': len(changes),
                'limit': limit,
                'page_id': page_id
            }
        })
    except Exception as e:
        logger.error(f"Error getting DOM changes: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': str(e),
            'data': {
                'changes': [],
                'count': 0,
                'error': str(e)
            }
        }), 500

def init_alliance_routes(app, db, socketio):
    """Initialize routes with complete error handling and cleanup"""
    try:
        # Register blueprint
        app.register_blueprint(alliance_routes)
        
        # Initialize DB connection before each request
        @app.before_request
        def before_request():
            try:
                g.db_ops = AllianceFirestoreDB(db)
                g.socketio = socketio
            except Exception as e:
                logger.error(f"Failed to initialize request context: {e}")
                # Still set the attributes to avoid attribute errors
                g.db_ops = None
                g.socketio = None
    
        # Initialize scheduler with error handling
        try:
            db_ops = AllianceFirestoreDB(db)
            initialize_alliance_scheduler(db_ops, socketio)
        except Exception as e:
            logger.error(f"Failed to initialize scheduler: {e}")
    
        # Schedule daily cleanup with error handling
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
            if scheduler.get_job('alliance_cleanup'):
                scheduler.remove_job('alliance_cleanup')    
            scheduler.add_job(
                cleanup_old_files,
                'interval',
                hours=24,
                id='alliance_cleanup',
                replace_existing=True
            )
        except Exception as e:
            logger.error(f"Failed to schedule cleanup job: {e}")
        
        # Register shutdown handlers
        def shutdown_handlers():
            try:
                scheduler.shutdown()
                logger.info("Alliance scheduler shutdown complete")
            except:
                pass
                
        atexit.register(shutdown_handlers)
        
        return app
        
    except Exception as e:
        logger.error(f"Failed to initialize alliance routes: {e}")
        logger.error(traceback.format_exc())
        # Still return app to prevent application startup failure
        return app