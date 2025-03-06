from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
import pytz
import logging
from .portal_scrapper import run_scraper
from .db_util import PortalFirestoreDB
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
portal_routes = Blueprint('portal_routes', __name__)

# Initialize scheduler
scheduler = BackgroundScheduler(
    job_defaults={
        'coalesce': False,
        'max_instances': 3
    },
    timezone=pytz.UTC 
)

__all__ = ['portal_routes', 'init_portal_routes', 'initialize_portal_scheduler']

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
                elif isinstance(stored_next_run, str):
                    stored_next_run = datetime.fromisoformat(stored_next_run.replace('Z', '+00:00'))
            except Exception as e:
                logger.error(f"Error parsing next_run time: {e}")
                stored_next_run = current_time

            if stored_next_run <= current_time:
                next_run = current_time + timedelta(minutes=5)
                next_run_ts = int(next_run.timestamp() * 1000)
                
                scheduler.add_job(
                    run_automated_scrape,
                    'date',
                    run_date=next_run,
                    id='portal_auto_scraper',
                    replace_existing=True,
                    args=[db_ops, socketio],
                    misfire_grace_time=None
                )
                
                db_ops.update_scheduler_settings(True, settings.get('interval', 60), next_run)
                
                last_state = db_ops.get_last_scraper_state()
                if last_state:
                    db_ops.store_scraper_state(
                        username=last_state.get('username'),
                        state='scheduled',
                        message="Scheduled to run in 5 minutes",
                        portal=last_state.get('portal'),
                        next_run=next_run,
                        auto_run=True
                    )

                if socketio:
                    socketio.emit('portal_settings_updated', {
                        "next_run": next_run_ts,
                        "auto_run": True,
                        "interval": settings.get('interval', 60)
                    })

    except Exception as e:
        logger.error(f"Error initializing portal scheduler: {e}")

def run_automated_scrape(db_ops, socketio):
    """Run automated scrape with company details handling"""
    try:
        last_state = db_ops.get_last_scraper_state()
        settings = db_ops.get_scheduler_settings()
        
        if not last_state or not settings.get('auto_run'):
            return

        data = {
            'username': last_state.get('username'),
            'password': last_state.get('password'),
            'portal': last_state.get('portal')
        }

        # Run scraper
        result = run_scraper(data, db_ops, socketio)
        
        if socketio:
            # Add back completion emission
            socketio.emit('portal_scraper_completed', {
                'success': result['success'],
                'message': result.get('message'),
                'data': {
                    'files': result.get('data', {}).get('files', []),
                    'company_details': result.get('data', {}).get('company_details'),
                    'processing_time': result.get('data', {}).get('processing_time')
                }
            })
        
        # Store result with company details
        if settings.get('auto_run'):
            current_time = datetime.now(pytz.UTC)
            interval_minutes = settings.get('interval', 60)
            next_run = current_time + timedelta(minutes=interval_minutes)
            
            state_data = {
                'username': data['username'],
                'state': 'completed' if result['success'] else 'failed',
                'message': result.get('message'),
                'portal': data['portal'],
                'next_run': next_run,
                'auto_run': True
            }
            
            # Include company details if available
            if result.get('data', {}).get('company_details'):
                state_data['company_details'] = result['data']['company_details']
            
            db_ops.store_scraper_state(**state_data)
            
            # Schedule next run
            scheduler.add_job(
                run_automated_scrape,
                'date',
                run_date=next_run,
                id='portal_auto_scraper',
                replace_existing=True,
                args=[db_ops, socketio]
            )

        return result

    except Exception as e:
        logger.error(f"Automated portal scrape failed: {e}")
        if socketio:
            socketio.emit('portal_scraper_error', {
                'message': str(e)
            })
            # Add completion emission for error case
            socketio.emit('portal_scraper_completed', {
                'success': False,
                'message': str(e),
                'data': {}
            })

@portal_routes.route('/portal/start_scraping', methods=['POST'])
def start_portal_scraping():
    """Start portal scraping with company details support"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        portal = data.get('portal')
        socketio = request.socketio  # Get socketio from request context
        
        if not all([username, password, portal]):
            return jsonify({
                "success": False,
                "message": "Missing required fields"
            }), 400

        db_ops = PortalFirestoreDB(request.db, portal)
        
        # Initial state with empty company details
        db_ops.store_scraper_state(
            username=username,
            state='starting',
            message='Starting scraper',
            portal=portal,
            company_details=None
        )

        # Run scraper
        result = run_scraper(data, db_ops, socketio)  # Pass socketio here
        
        # Update final state including company details
        state_data = {
            'username': username,
            'state': 'completed' if result['success'] else 'failed',
            'message': result.get('message'),
            'portal': portal,
            'data': result.get('data')
        }
        
        # Add company details if generated during scraping
        if result.get('data', {}).get('company_details'):
            state_data['company_details'] = result.get('data')['company_details']
            
        db_ops.store_scraper_state(**state_data)
        
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Portal scraping error: {error_msg}")
        
        if 'db_ops' in locals() and 'username' in locals():
            db_ops.store_scraper_state(
                username=username,
                state='failed',
                message=error_msg,
                portal=portal
            )
        
        return jsonify({
            "success": False,
            "message": error_msg
        }), 500
    finally:
        print("og entered the chat")
        portal = request.args.get('portal', 'qatar')
        db_ops = PortalFirestoreDB(request.db, portal)
        
        state = db_ops.get_last_scraper_state()
        settings = db_ops.get_scheduler_settings() or {}
        
        if not state:
            default_state = {
                "state": "new",
                "last_run": None,
                "next_run": None,
                "username": None,
                "password": None,
                "portal": portal,
                "auto_run": settings.get('auto_run', False),
                "message": None,
                "error": None,
                "company_details": None
            }
            socketio.emit('update_last_run_qatar', default_state)
        else:  # Use socketio from earlier

            response_data = {
                "state": state.get('state', 'new'),
                "last_run": state.get('last_run'),
                "next_run": settings.get('next_run'),
                "username": state.get('username'),
                "password": state.get('password'),
                "portal": state.get('portal', portal),
                "auto_run": settings.get('auto_run', False),
                "message": state.get('message'),
                "error": state.get('error') if state.get('state') == 'failed' else None,
                "company_details": state.get('company_details')
            }
            socketio.emit('update_last_run_qatar', response_data)
        

        
        
    

@portal_routes.route('/portal/last_state')
def get_portal_last_state():
    """Get last state with company details"""
    try:
        # Default to qatar portal if none provided
        portal = request.args.get('portal', 'qatar')
        db_ops = PortalFirestoreDB(request.db, portal)
        
        state = db_ops.get_last_scraper_state()
        settings = db_ops.get_scheduler_settings() or {}  # Default to empty dict if None
        
        # Return default state if no state exists
        if not state:
            default_state = {
                "state": "new",
                "last_run": None,
                "next_run": None,
                "username": None,
                "password": None,  # Added password field
                "portal": portal,
                "auto_run": settings.get('auto_run', False),
                "message": None,
                "error": None,
                "company_details": None
            }
            return jsonify({
                "success": True,
                "data": default_state
            })

        # Build response with safe gets
        response_data = {
            "state": state.get('state', 'new'),
            "last_run": state.get('last_run'),
            "next_run": settings.get('next_run'),
            "username": state.get('username'),
            "password": state.get('password'),  # Added password field
            "portal": state.get('portal', portal),
            "auto_run": settings.get('auto_run', False),
            "message": state.get('message'),
            "error": state.get('error') if state.get('state') == 'failed' else None,
            "company_details": state.get('company_details')
        }

        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except Exception as e:
        logger.error(f"Error getting last portal state: {e}")
        return jsonify({
            "success": False,
            "message": str(e),
            "data": {
                "state": "error",
                "message": str(e)
            }
        }), 500

@portal_routes.route('/portal/settings', methods=['GET', 'POST'])
def portal_scheduler_settings():
    """Handle portal scheduler settings"""
    try:
        portal = request.args.get('portal', 'default_portal')
        db_ops = PortalFirestoreDB(request.db, portal)
        
        if request.method == 'GET':
            settings = db_ops.get_scheduler_settings()
            return jsonify({
                "success": True,
                "settings": settings
            })

        settings = request.json
        auto_run = settings.get('auto_run', False)
        interval = settings.get('interval', 60)
        
        next_run = datetime.now(pytz.UTC) + timedelta(minutes=interval) if auto_run else None
        
        db_ops.update_scheduler_settings(auto_run, interval, next_run)
        
        # Update last state with new settings
        last_state = db_ops.get_last_scraper_state()
        if last_state:
            db_ops.store_scraper_state(
                username=last_state.get('username'),
                state=last_state.get('state', 'idle'),
                portal=last_state.get('portal'),
                next_run=next_run,
                auto_run=auto_run,
                preserve_last_run=True
            )

        # Update scheduler job
        job_id = 'portal_auto_scraper'
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            
        if auto_run and next_run:
            scheduler.add_job(
                run_automated_scrape,
                'date',
                run_date=next_run,
                id=job_id,
                replace_existing=True,
                args=[db_ops, request.socketio]
            )
            
        next_run_ts = int(next_run.timestamp() * 1000) if next_run else None
        
        if request.socketio:
            request.socketio.emit('portal_settings_updated', {
                "next_run": next_run_ts,
                "auto_run": auto_run,
                "interval": interval
            })
        
        return jsonify({
            "success": True,
            "message": "Settings updated",
            "next_run": next_run_ts,
            "auto_run": auto_run,
            "interval": interval
        })
        
    except Exception as e:
        logger.error(f"Error updating portal scheduler settings: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

def init_portal_routes(app, db, socketio):
    """Initialize routes with dependencies"""
    app.register_blueprint(portal_routes)
    
    # Add db and socketio to request context
    @app.before_request
    def before_request():
        request.db = db
        request.socketio = socketio
    
    return app
