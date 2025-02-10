from datetime import datetime
import pytz
import logging
from bs4 import BeautifulSoup
import difflib
from google.cloud.firestore import Query, ArrayUnion
import firebase_admin
from firebase_admin import firestore
# from firebase_logger import firebase_logger
# from email_utils import send_notification_email, generate_dom_change_email

logger = logging.getLogger(__name__)

class AirIndiaFirestoreDB:
    def __init__(self, db):
        self.db = db
        self.urls_ref = self.db.collection('monitored_urls')
        self.air_india_ref = self.urls_ref.document('air_india_express')
        
        # Initialize subcollections
        self.scraper_state_ref = self.air_india_ref.collection('scraper_states')
        self.scraper_history_ref = self.air_india_ref.collection('scraper_history')
        self.error_ref = self.air_india_ref.collection('errors')
        self.invoice_ref = self.air_india_ref.collection('invoices')  # New collection for invoices
        
        # Add settings collection reference
        self.settings_ref = self.air_india_ref.collection('settings')
        self.scheduler_settings_ref = self.settings_ref.document('scheduler')
        
        # Add settings subcollection
        self.settings_collection = self.air_india_ref.collection('settings')
        self.scheduler_doc = self.settings_collection.document('scheduler')
        
        # Add DOM changes collection reference
        self.dom_changes_ref = self.air_india_ref.collection('dom_changes')
        self.dom_snapshots_ref = self.air_india_ref.collection('dom_snapshots')
        
        # Add explicit DOM collections
        self.dom_snapshots_collection = self.air_india_ref.collection('dom_snapshots')
        self.dom_changes_collection = self.air_india_ref.collection('dom_changes')
        self.dom_history_collection = self.air_india_ref.collection('dom_history')
        
        self._init_default_settings()
        
        # Initialize DOM-specific collections
        self.dom_collections = ['dom_changes', 'dom_snapshots']
        self._init_dom_collections()

    def _check_collection_exists(self, collection_ref):
        """Helper method to check if collection exists"""
        try:
            docs = list(collection_ref.limit(1).stream())
            return len(docs) > 0
        except Exception as e:
            logger.error(f"Error checking collection: {e}")
            return False

    def _init_default_settings(self):
        """Initialize default settings if they don't exist"""
        try:
            default_settings = {
                'auto_run': False,
                'interval': 60,
                'next_run': None,
                'created_at': datetime.now(pytz.UTC),
                'updated_at': datetime.now(pytz.UTC)
            }
            
            # Check collections using the new helper method
            collections = [
                self.scraper_state_ref,
                self.scraper_history_ref,
                self.error_ref,
                self.invoice_ref,
                self.settings_ref
            ]
            
            for collection in collections:
                if not self._check_collection_exists(collection):
                    collection.document('_init').set({
                        'initialized': True,
                        'created_at': datetime.now(pytz.UTC)
                    })
            
            # Initialize scheduler settings
            settings_doc = self.scheduler_settings_ref.get()
            if not settings_doc.exists:
                self.scheduler_settings_ref.set(default_settings)
                logger.info("Initialized default Air India Express scheduler settings")
                return default_settings
                
            return settings_doc.to_dict()
            
        except Exception as e:
            logger.error(f"Error initializing database structure: {e}")
            return None

    def _init_dom_collections(self):
        """Initialize DOM collections if they don't exist"""
        try:
            # Create collections if they don't exist
            collections = [
                self.dom_snapshots_collection,
                self.dom_changes_collection,
                self.dom_history_collection
            ]
            
            for collection in collections:
                if not self._check_collection_exists(collection):
                    collection.document('_init').set({
                        'initialized': True,
                        'timestamp': datetime.now(pytz.UTC)
                    })
            
            # Initialize last comparison document
            last_comp_doc = self.dom_changes_collection.document('last_comparison').get()
            if not last_comp_doc.exists:
                self.dom_changes_collection.document('last_comparison').set({
                    'has_changes': False,
                    'timestamp': datetime.now(pytz.UTC),
                    'changes_count': 0
                })
                
        except Exception as e:
            logger.error(f"Error initializing DOM collections: {e}")

    def store_scraper_state(self, pnr, state='pending', message=None, data=None, next_run=None, 
                           origin=None, vendor=None, preserve_last_run=False, auto_run=False):
        """Store scraper state with Air India specific fields"""
        try:
            doc_id = pnr
            current_time = datetime.now(pytz.UTC)
            
            # Get existing state if needed
            existing_state = self.scraper_state_ref.document(doc_id).get() if preserve_last_run else None
            
            state_data = {
                'pnr': pnr,
                'state': state,
                'message': message,
                'updated_at': current_time,
                'origin': origin,
                'vendor': vendor,  # Add vendor field
                'airline': 'air_india_express',
                'auto_run': auto_run  # Add auto_run field with default False
            }
            
            # Handle data field
            if data:
                state_data['data'] = data
                
            # Handle timestamp preservation
            if preserve_last_run and existing_state and existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'last_run' in existing_data:
                    state_data['last_run'] = existing_data['last_run']
            else:
                state_data['last_run'] = current_time
                
            # Handle next run
            if next_run:
                state_data['next_run'] = next_run
                
            # Add error preservation
            if state == 'failed':
                state_data['last_error'] = {
                    'message': message,
                    'timestamp': current_time,
                    'stage': data.get('stage') if data else None
                }
                
            self.scraper_state_ref.document(doc_id).set(state_data, merge=True)
            
            # Add to history
            history_data = {
                'timestamp': current_time,
                'pnr': pnr,
                'state': state,
                'message': message,
                'origin': origin,
                'data': data
            }
            
            self.scraper_history_ref.add(history_data)
            
        except Exception as e:
            logger.error(f"Error storing scraper state: {e}")
            raise

    def store_invoice_data(self, pnr, invoice_data, invoice_files=None):
        """Store invoice related data"""
        try:
            current_time = datetime.now(pytz.UTC)
            doc_data = {
                'pnr': pnr,
                'invoice_data': invoice_data,
                'timestamp': current_time,
                'status': 'processed'
            }
            
            if invoice_files:
                doc_data['files'] = [{
                    'name': f['name'],
                    'type': f['type'],
                    'size': f['size'],
                    'path': f['path']
                } for f in invoice_files]
                
            self.invoice_ref.add(doc_data)
            return True
        except Exception as e:
            logger.error(f"Error storing invoice data: {e}")
            return False

    def get_scraper_state(self, pnr):
        """Get current scraper state with empty state handling"""
        try:
            if not self.scraper_state_ref.get().exists:
                self._init_default_settings()
                return {
                    'state': 'new',
                    'last_run': None,
                    'next_run': None,
                    'auto_run': False
                }
                
            doc = self.scraper_state_ref.document(pnr).get()
            if doc.exists:
                data = doc.to_dict()
                # Convert timestamps for frontend
                for field in ['last_run', 'next_run', 'updated_at']:
                    if field in data and data[field]:
                        data[field] = int(data[field].timestamp() * 1000)
                return data
            return {
                'state': 'new',
                'last_run': None
            }
        except Exception as e:
            logger.error(f"Error getting scraper state: {e}")
            return None

    def log_error(self, error_type, error_message, context=None):
        """Log Air India specific errors"""
        try:
            error_doc = {
                'timestamp': datetime.now(pytz.UTC),
                'type': error_type,
                'message': error_message,
                'context': context or {},
                'airline': 'air_india_express',
                'severity': 'error',
                'vendor': context.get('vendor') if context else None  # Add vendor to error logs
            }
            
            # Store error
            self.error_ref.add(error_doc)
            
            # Update scraper state if PNR provided
            if context and 'pnr' in context:
                self.store_scraper_state(
                    pnr=context['pnr'],
                    state='failed',
                    message=error_message,
                    data={'error': error_message}
                )
                
            # Send notification for critical errors
            if error_type in ['AUTH_ERROR', 'API_ERROR', 'CRITICAL']:
                self.send_error_notification(error_type, error_message, context)
                
        except Exception as e:
            logger.error(f"Error logging error: {str(e)}")

    def send_error_notification(self, error_type, error_message, context):
        """Send error notifications"""
        try:
            notification_emails = self.get_notification_emails()
            if notification_emails:
                html_content = f"""
                    <h2>Air India Express Scraper Error</h2>
                    <p><strong>Error Type:</strong> {error_type}</p>
                    <p><strong>Message:</strong> {error_message}</p>
                    <p><strong>PNR:</strong> {context.get('pnr', 'N/A')}</p>
                    <p><strong>Origin:</strong> {context.get('origin', 'N/A')}</p>
                    <p><strong>Vendor:</strong> {context.get('vendor', 'N/A')}</p>  
                    <p><strong>Timestamp:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                """
                
                send_notification_email(
                    subject=f"Air India Express Scraper Error - {error_type}",
                    html_content=html_content,
                    notification_emails=notification_emails
                )
        except Exception as e:
            logger.error(f"Error sending error notification: {str(e)}")

    def get_notification_emails(self):
        """Get notification email list"""
        try:
            doc = self.db.collection('notification_email_list_file_upload').document('email').get()
            if doc.exists:
                return doc.to_dict().get('emails', [])
            return []
        except Exception as e:
            logger.error(f"Error getting notification emails: {str(e)}")
            return []

    def get_scraper_analytics(self, pnr=None, last_timestamp=None):
        """Get analytics for scraper runs"""
        try:
            query = self.scraper_history_ref.order_by('timestamp', direction=Query.DESCENDING)
            
            if pnr:
                query = query.where('pnr', '==', pnr)
            if last_timestamp:
                query = query.start_after({'timestamp': last_timestamp})
                
            query = query.limit(1000)
            docs = query.stream()
            
            analytics = {
                'total_runs': 0,
                'success_rate': 0,
                'recent_runs': [],
                'invoices_generated': 0
            }
            
            success_count = 0
            for doc in docs:
                data = doc.to_dict()
                analytics['total_runs'] += 1
                
                if data.get('state') == 'completed':
                    success_count += 1
                    if data.get('data', {}).get('files'):
                        analytics['invoices_generated'] += len(data['data']['files'])
                    
                analytics['recent_runs'].append({
                    'timestamp': data.get('timestamp'),
                    'state': data.get('state'),
                    'pnr': data.get('pnr'),
                    'message': data.get('message'),
                    'origin': data.get('origin')
                })
            
            if analytics['total_runs'] > 0:
                analytics['success_rate'] = (success_count / analytics['total_runs']) * 100
                
            return analytics
            
        except Exception as e:
            logger.error(f"Error getting scraper analytics: {str(e)}")
            return None

    def get_last_successful_invoice(self, pnr):
        """Get most recent successful invoice data"""
        try:
            docs = self.invoice_ref\
                .where('pnr', '==', pnr)\
                .where('status', '==', 'processed')\
                .order_by('timestamp', direction=Query.DESCENDING)\
                .limit(1)\
                .stream()
            
            for doc in docs:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting last invoice: {str(e)}")
            return None

    def clear_scraper_state(self, pnr):
        """Clear scraper state"""
        try:
            self.scraper_state_ref.document(pnr).delete()
            return True
        except Exception as e:
            logger.error(f"Error clearing scraper state: {e}")
            return False

    def get_scheduler_settings(self):
        """Get scheduler settings with default values for empty/missing data"""
        try:
            doc = self.scheduler_doc.get()
            if not doc.exists:
                # Initialize with default settings if none exist
                default_settings = self._init_default_settings()
                if not default_settings:
                    raise Exception("Failed to initialize default settings")
                return default_settings

            data = doc.to_dict()
            if not data:
                raise Exception("Empty settings document")

            # Ensure all required fields exist with defaults
            settings = {
                'auto_run': data.get('auto_run', False),
                'interval': data.get('interval', 60),
                'updated_at': data.get('updated_at', datetime.now(pytz.UTC))
            }

            # Handle next_run conversion safely
            if 'next_run' in data and data['next_run']:
                try:
                    settings['next_run'] = int(data['next_run'].timestamp() * 1000)
                except (AttributeError, TypeError):
                    settings['next_run'] = None
            else:
                settings['next_run'] = None

            return settings

        except Exception as e:
            logger.error(f"Error getting scheduler settings: {e}")
            # Return default settings on error
            return {
                'auto_run': False,
                'interval': 60,
                'next_run': None,
                'updated_at': datetime.now(pytz.UTC)
            }

    def update_scheduler_settings(self, auto_run, interval, next_run=None):
        """Update scheduler settings preserving timestamps"""
        try:
            settings = {
                'auto_run': auto_run,
                'interval': interval,
                'updated_at': datetime.now(pytz.UTC)
            }
            if next_run:
                settings['next_run'] = next_run
                
            # Always use merge to preserve other fields
            self.scheduler_settings_ref.set(
                settings,
                merge=True
            )
            
            # Update last state with new settings
            last_state = self.get_last_scraper_state()
            if last_state:
                self.store_scraper_state(
                    pnr=last_state.get('pnr'),
                    state=last_state.get('state', 'idle'),
                    origin=last_state.get('origin'),
                    vendor=last_state.get('vendor'),
                    next_run=next_run,
                    preserve_last_run=True
                )
            
            return True
        except Exception as e:
            logger.error(f"Error updating scheduler settings: {e}")
            return False

    def update_next_run_time(self, next_run):
        """Update next run time"""
        try:
            self.scheduler_settings_ref.update({
                'next_run': next_run
            })
            return True
        except Exception as e:
            logger.error(f"Error updating next run time: {str(e)}")
            return False

    def get_all_scraper_states(self):
        """Get all scraper states for scheduler"""
        try:
            states = {}
            docs = self.scraper_state_ref.stream()
            for doc in docs:
                data = doc.to_dict()
                # Convert timestamps for frontend
                for field in ['last_run', 'next_run', 'updated_at']:
                    if field in data and data[field]:
                        data[field] = int(data[field].timestamp() * 1000)
                states[doc.id] = data
            return states
        except Exception as e:
            logger.error(f"Error getting all scraper states: {e}")
            return {}

    def get_last_scraper_state(self):
        """Get most recent scraper state"""
        try:
            states = self.scraper_state_ref\
                .order_by('updated_at', direction=Query.DESCENDING)\
                .limit(1)\
                .stream()
            
            for state in states:
                data = state.to_dict()
                # Convert timestamps for frontend
                for field in ['last_run', 'next_run', 'updated_at']:
                    if field in data and data[field]:
                        data[field] = int(data[field].timestamp() * 1000)
                return data
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting last scraper state: {e}")
            return None

    def get_scraper_progress(self, pnr):
        """Get detailed progress for a specific PNR"""
        try:
            doc = self.scraper_state_ref.document(pnr).get()
            if doc.exists:
                data = doc.to_dict()
                # Add progress calculation logic
                return {
                    'stage': data.get('stage', 'unknown'),
                    'status': data.get('status', 'unknown'),
                    'message': data.get('message', ''),
                    'progress': data.get('progress', 0),
                    'timing': data.get('timing', {})
                }
            return None
        except Exception as e:
            logger.error(f"Error getting scraper progress: {e}")
            return None

    def update_scraper_progress(self, pnr, stage, step, status, message, data=None):
        """Update scraper progress details"""
        try:
            progress_data = {
                'stage': stage,
                'step': step,
                'status': status,
                'message': message,
                'updated_at': datetime.now(pytz.UTC)
            }
            if data:
                progress_data['data'] = data
                
            self.scraper_state_ref.document(pnr).set(
                progress_data, 
                merge=True
            )
        except Exception as e:
            logger.error(f"Error updating scraper progress: {e}")
            raise

    def store_dom_snapshot(self, page_id, content, metadata=None):
        """Store a DOM snapshot with metadata"""
        try:
            doc_data = {
                'content': content,
                'timestamp': datetime.now(pytz.UTC),
                'page_id': page_id
            }
            if metadata:
                doc_data.update(metadata)
                
            self.dom_snapshots_collection.document(page_id).set(doc_data)
            return True
        except Exception as e:
            logger.error(f"Error storing DOM snapshot: {e}")
            return False

    def get_dom_snapshot(self, page_id):
        """Get the latest DOM snapshot for a page"""
        try:
            doc = self.dom_snapshots_collection.document(page_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error getting DOM snapshot: {e}")
            return None

    def store_dom_changes(self, changes_data):
        """Store DOM changes with path information"""
        try:
            # Ensure each change has a path field (even if null)
            if changes_data.get('changes'):
                for change in changes_data['changes']:
                    if 'path' not in change:
                        change['path'] = None
                        
            # Add timestamp if not present
            if 'timestamp' not in changes_data:
                changes_data['timestamp'] = datetime.now(pytz.UTC)
            
            # Store changes in history
            self.dom_history_collection.add(changes_data)
            
            # Update last comparison state
            self.dom_changes_collection.document('last_comparison').set({
                'has_changes': bool(changes_data.get('changes')),
                'timestamp': changes_data['timestamp'],
                'changes_count': len(changes_data.get('changes', [])),
                'page_id': changes_data.get('page_id')
            })
            
            return True
        except Exception as e:
            logger.error(f"Error storing DOM changes: {e}")
            return False

    def get_recent_dom_changes(self, limit=50):
        """Get recent DOM changes with enhanced formatting"""
        try:
            changes = []
            docs = self.dom_history_collection\
                .order_by('timestamp', direction=Query.DESCENDING)\
                .limit(limit)\
                .stream()

            # Add debug logging
            print("Fetching DOM changes from collection...")
                
            for doc in docs:
                data = doc.to_dict()
                if data:
                    # Ensure proper data structure
                    formatted_change = {
                        'page_id': data.get('page_id', 'unknown'),
                        'timestamp': data.get('timestamp'),
                        'type': data.get('type', 'unknown'),
                        'changes': data.get('changes', []),
                        'pnr': data.get('pnr'),
                        'origin': data.get('origin'),
                        'metadata': data.get('metadata', {}),
                        # Add any other fields needed by frontend
                    }
                    changes.append(formatted_change)
                    print(f"Found change for page: {formatted_change['page_id']}")
                    
            print(f"Total changes found: {len(changes)}")
            return changes
                    
        except Exception as e:
            logger.error(f"Error getting DOM changes: {e}", exc_info=True)
            return []

    def get_last_dom_comparison(self):
        """Get latest DOM comparison result"""
        try:
            doc = self.dom_changes_collection.document('last_comparison').get()
            if doc.exists:
                data = doc.to_dict()
                print("Last comparison data:", data)  # Debug log
                return data
            return None
        except Exception as e:
            logger.error(f"Error getting last DOM comparison: {e}")
            return None

    def handle_dom_changes(self, change_data):
        """Handle DOM changes and send notifications"""
        try:
            if not change_data.get('changes'):
                return

            # Format notification email
            notification_emails = self.get_notification_emails()
            if not notification_emails:
                return

            # Generate HTML content
            changes_list = ""
            for change in change_data['changes']:
                change_type = change.get('type', 'unknown')
                description = change.get('description', 'No description')
                element = change.get('element', 'No element data')
                
                changes_list += f"""
                    <div style="margin: 10px 0; padding: 10px; border-left: 4px solid 
                        {'#28a745' if change_type == 'addition' else '#dc3545'}">
                        <strong>{change_type.upper()}</strong>
                        <p>{description}</p>
                        <pre style="background: #f8f9fa; padding: 10px; border-radius: 4px;">
                            {element}
                        </pre>
                    </div>
                """

            html_content = f"""
                <h2>Air India Express DOM Changes Detected</h2>
                <p><strong>Page:</strong> {change_data['page_type']}</p>
                <p><strong>PNR:</strong> {change_data.get('pnr', 'N/A')}</p>
                <p><strong>Origin:</strong> {change_data.get('origin', 'N/A')}</p>
                <p><strong>Changes Detected:</strong> {len(change_data['changes'])}</p>
                <div style="margin-top: 20px;">
                    <h3>Change Details:</h3>
                    {changes_list}
                </div>
            """

            # Send notification email
            send_notification_email(
                subject=f"Air India Express DOM Changes - {change_data['page_type']}",
                html_content=html_content,
                notification_emails=notification_emails
            )

        except Exception as e:
            logger.error(f"Error handling DOM changes notification: {e}")

    def store_dom_data(self, data, page_id):
        """Store both snapshot and changes data"""
        try:
            # Store snapshot
            if data.get('snapshot'):
                self.store_dom_snapshot(page_id, data['snapshot'])
            
            # Store changes if they exist
            if data.get('changes'):
                self.store_dom_changes(data['changes'])
                
            # Update last comparison
            if data.get('changes') and data['changes'].get('changes'):
                self.dom_changes_collection.document('last_comparison').set({
                    'has_changes': True,
                    'timestamp': datetime.now(pytz.UTC),
                    'changes_count': len(data['changes']['changes']),
                    'page_id': page_id
                })
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing DOM data: {e}")
            return False
            
    def get_dom_changes(self, limit=1000):
        """Get DOM changes with path handling"""
        try:
            changes = []
            docs = self.dom_changes_collection.order_by(
                'timestamp', 
                direction=Query.DESCENDING
            ).limit(limit).stream()
            
            for doc in docs:
                change_data = doc.to_dict()
                if change_data and change_data.get('changes'):
                    # Ensure each change has a path field
                    for change in change_data['changes']:
                        if 'path' not in change:
                            change['path'] = None
                    changes.append(change_data)
                    
            return changes
            
        except Exception as e:
            logger.error(f"Error getting DOM changes: {e}")
            return []

    def store_dom_snapshot(self, page_id, snapshot_data):
        """Store a DOM snapshot"""
        try:
            # Ensure timestamp exists
            if 'timestamp' not in snapshot_data:
                snapshot_data['timestamp'] = datetime.now(pytz.UTC)
                
            # Store in snapshots collection
            self.dom_snapshots_collection.document(page_id).set(snapshot_data)
            
            # Store in history
            history_data = snapshot_data.copy()
            history_data['page_id'] = page_id
            self.dom_history_collection.add(history_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing DOM snapshot: {e}")
            return False
