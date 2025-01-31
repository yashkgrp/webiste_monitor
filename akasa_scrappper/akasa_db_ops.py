from datetime import datetime
import pytz
import logging
from bs4 import BeautifulSoup
import difflib
from google.cloud.firestore import Query, ArrayUnion  # Add ArrayUnion import
import firebase_admin
from firebase_admin import firestore
from firebase_logger import firebase_logger
from email_utils import send_notification_email, generate_dom_change_email

logger = logging.getLogger(__name__)

class AkasaFirestoreDB:
    def __init__(self, db):
        self.db = db
        self.urls_ref = self.db.collection('monitored_urls')
        self.akasa_ref = self.urls_ref.document('akasa_air')
        
        # Initialize subcollections
        self.scraper_state_ref = self.akasa_ref.collection('scraper_states')
        self.scraper_history_ref = self.akasa_ref.collection('scraper_history')
        self.dom_changes_ref = self.akasa_ref.collection('dom_changes')
        self.error_ref = self.akasa_ref.collection('errors')  # Add error collection

    def store_dom_snapshot(self, page_id, content):
        """Store DOM snapshot with structural comparison"""
        try:
            doc_ref = self.dom_changes_ref.document(page_id)
            old_snapshot = doc_ref.get()
            
            def get_structure(html_content):
                soup = BeautifulSoup(html_content, 'html.parser')
                for tag in soup.find_all():
                    attrs = tag.attrs
                    keep_attrs = {'id', 'class', 'type', 'name', 'method', 'action'}
                    tag.attrs = {k: v for k, v in attrs.items() if k in keep_attrs}
                    if tag.string:
                        tag.string = ''
                return str(soup)

            new_structure = get_structure(content)
            
            if old_snapshot.exists:
                old_structure = get_structure(old_snapshot.to_dict().get('content', ''))
                diff = list(difflib.unified_diff(
                    old_structure.splitlines(),
                    new_structure.splitlines(),
                    fromfile='previous',
                    tofile='current',
                    lineterm=''
                ))
                has_changes = bool(diff)
                
                if has_changes:
                    self.dom_changes_ref.add({
                        'timestamp': datetime.now(pytz.UTC),
                        'page_id': page_id,
                        'changes': diff,
                        'type': 'structural'
                    })
            else:
                has_changes = True
                diff = ["Initial snapshot"]
            
            doc_ref.set({
                'content': content,
                'structure': new_structure,
                'timestamp': datetime.now(pytz.UTC),
                'has_changes': has_changes
            })
            
            return has_changes, diff
            
        except Exception as e:
            logger.error(f"Error storing DOM snapshot: {str(e)}")
            return False, []

    def handle_dom_changes(self, changes, pnr=None, lastName=None):
        """Handle DOM changes with Akasa specific fields"""
        if not changes:
            return

        try:
            notification_emails = self.get_notification_emails()
            if (notification_emails):
                html_content = generate_dom_change_email(
                    pnr=pnr,
                    changes=changes,
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    lastName=lastName,
                    airline='Akasa Air'
                )
                send_notification_email(
                    subject=f"Akasa Air DOM Changes - PNR: {pnr}",
                    html_content=html_content,
                    notification_emails=notification_emails
                )

            # Store changes in Firestore with Akasa specific fields
            self.dom_changes_ref.add({
                'timestamp': datetime.now(pytz.UTC),
                'pnr': pnr,
                'lastName': lastName,
                'changes': changes,
                'airline': 'akasa'
            })

        except Exception as e:
            logger.error(f"Error handling DOM changes: {str(e)}")

    def store_scraper_state(self, pnr, state='pending', message=None, next_run=None, lastName=None, traveller_name=None, preserve_last_run=False, preserve_next_run=False, auto_run=None):
        """Enhanced store scraper state with timestamp preservation"""
        try:
            doc_id = pnr
            current_time = datetime.now(pytz.UTC)
            
            # Get existing state to preserve values if needed
            existing_state = self.scraper_state_ref.document(doc_id).get()
            
            state_data = {
                'pnr': pnr,
                'state': state,
                'message': message,
                'updated_at': current_time,
                'lastName': lastName,
                'traveller_name': traveller_name,
                'airline': 'akasa'
            }
            
            # Handle last_run preservation
            if not preserve_last_run:
                state_data['last_run'] = current_time
            elif existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'last_run' in existing_data:
                    state_data['last_run'] = existing_data['last_run']
            
            # Handle next_run preservation
            if preserve_next_run and existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'next_run' in existing_data:
                    state_data['next_run'] = existing_data['next_run']
            elif next_run is not None:
                state_data['next_run'] = next_run
            
            # Handle auto_run
            if auto_run is not None:
                state_data['auto_run'] = auto_run
            elif existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'auto_run' in existing_data:
                    state_data['auto_run'] = existing_data['auto_run']
            
            self.scraper_state_ref.document(doc_id).set(state_data, merge=True)
            
            # Add to history
            history_data = {
                'timestamp': current_time,
                'pnr': pnr,
                'state': state,
                'message': message,
                'lastName': lastName,
                'traveller_name': traveller_name
            }
            
            self.scraper_history_ref.add(history_data)
            
        except Exception as e:
            logger.error(f"Error storing scraper state: {e}")
            raise

    def save_dom_comparison(self, page_id, has_changes, changes, html_content, pnr=None, lastName=None):
        """Save DOM comparison results and history"""
        try:
            timestamp = datetime.now(pytz.UTC)
            
            # Save current snapshot and comparison result
            self.dom_changes_ref.document(page_id).set({
                'has_changes': has_changes,
                'timestamp': timestamp,
                'content': html_content,
                'pnr': pnr,
                'lastName': lastName
            })

            # Always add to history, even if no changes
            history_entry = {
                'timestamp': timestamp,
                'page_id': page_id,
                'has_changes': has_changes,
                'changes': changes if changes else [],
                'pnr': pnr,
                'lastName': lastName
            }
            
            # Add to history collection
            self.dom_changes_ref.document(page_id).collection('history').add(history_entry)
            
            return True
        except Exception as e:
            logger.error(f"Error saving DOM comparison: {str(e)}")
            return False

    def get_scraper_state(self, pnr):
        """Enhanced state getter"""
        try:
            doc = self.scraper_state_ref.document(pnr).get()
            if doc.exists:
                data = doc.to_dict()
                # Add attempt tracking
                if 'attempted_lastNames' not in data:
                    data['attempted_lastNames'] = []
                return data
            return {
                'state': 'new',
                'attempted_lastNames': [],
                'last_run': None
            }
        except Exception as e:
            logger.error(f"Error getting scraper state: {e}")
            return None

    def get_notification_emails(self):
        """Get list of notification emails from Firestore"""
        try:
            doc = self.db.collection('notification_email_list_file_upload').document('email').get()
            if doc.exists:
                return doc.to_dict().get('emails', [])
            return []
        except Exception as e:
            logger.error(f"Error getting notification emails: {str(e)}")
            return []

    def get_scraper_analytics(self, pnr=None, lastName=None, last_timestamp=None):
        """Get analytics for scraper runs with Akasa specific fields"""
        try:
            query = self.scraper_history_ref.order_by('timestamp', direction=Query.DESCENDING)
            
            if pnr:
                query = query.where('pnr', '==', pnr)
            if lastName:
                query = query.where('lastName', '==', lastName)
            if last_timestamp:
                query = query.start_after({'timestamp': last_timestamp})
                
            query = query.limit(1000)
            docs = query.stream()
            
            analytics = {
                'total_runs': 0,
                'success_rate': 0,
                'recent_runs': [],
                'dom_changes': [],
                'name_attempts': {},  # Track success rate by lastName
                'last_successful_name': None
            }
            
            success_count = 0
            for doc in docs:
                data = doc.to_dict()
                analytics['total_runs'] += 1
                
                lastName = data.get('lastName')
                if lastName:
                    if lastName not in analytics['name_attempts']:
                        analytics['name_attempts'][lastName] = {'attempts': 0, 'successes': 0}
                    analytics['name_attempts'][lastName]['attempts'] += 1
                    
                if data.get('state') == 'completed':
                    success_count += 1
                    if lastName:
                        analytics['name_attempts'][lastName]['successes'] += 1
                        if not analytics['last_successful_name']:
                            analytics['last_successful_name'] = lastName
                    
                analytics['recent_runs'].append({
                    'timestamp': data.get('timestamp'),
                    'state': data.get('state'),
                    'pnr': data.get('pnr'),
                    'message': data.get('message'),
                    'lastName': data.get('lastName'),
                    'traveller_name': data.get('traveller_name')
                })
            
            if analytics['total_runs'] > 0:
                analytics['success_rate'] = (success_count / analytics['total_runs']) * 100
                
            return analytics
            
        except Exception as e:
            logger.error(f"Error getting scraper analytics: {str(e)}")
            return None

    def get_recent_dom_changes(self):
        """Get recent DOM changes"""
        try:
            changes = []
            docs = self.dom_changes_ref.order_by(
                'timestamp', 
                direction=Query.DESCENDING
            ).limit(50).stream()
            
            for doc in docs:
                data = doc.to_dict()
                if data and data.get('changes'):
                    changes.append({
                        'timestamp': data.get('timestamp'),
                        'pnr': data.get('pnr'),
                        'changes': data.get('changes')
                    })
            
            return changes
        except Exception as e:
            logger.error(f"Error getting recent DOM changes: {str(e)}")
            return []

    def get_scheduler_settings(self):
        """Get scheduler settings with millisecond timestamps"""
        try:
            doc = self.akasa_ref.collection('settings').document('scheduler').get()
            if doc.exists:
                data = doc.to_dict()
                # Convert next_run to millisecond timestamp
                if 'next_run' in data and data['next_run']:
                    data['next_run'] = int(data['next_run'].timestamp() * 1000)
                return data
            return {
                'auto_run': False,
                'interval': 60,
                'next_run': None
            }
        except Exception as e:
            logger.error(f"Error getting scheduler settings: {e}")
            return None

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
            self.akasa_ref.collection('settings').document('scheduler').set(
                settings,
                merge=True
            )
            
            # Update last state with new settings
            last_state = self.get_last_scraper_state()
            if last_state:
                self.store_scraper_state(
                    pnr=last_state.get('pnr'),
                    state=last_state.get('state', 'idle'),
                    lastName=last_state.get('lastName'),
                    traveller_name=last_state.get('traveller_name'),
                    next_run=next_run,
                    auto_run=auto_run,
                    preserve_last_run=True
                )
            
            return True
        except Exception as e:
            logger.error(f"Error updating scheduler settings: {e}")
            return False

    def update_next_run_time(self, next_run):
        """Update next run time"""
        try:
            self.akasa_ref.collection('settings').document('scheduler').update({
                'next_run': next_run
            })
            return True
        except Exception as e:
            logger.error(f"Error updating next run time: {str(e)}")
            return False

    def get_last_successful_name(self, pnr):
        """Get the last successful lastName for a PNR"""
        try:
            # Query the scraper history for the last successful run with this PNR
            docs = self.scraper_history_ref\
                .where('pnr', '==', pnr)\
                .where('state', '==', 'completed')\
                .order_by('timestamp', direction=Query.DESCENDING)\
                .limit(1)\
                .stream()
            
            for doc in docs:
                data = doc.to_dict()
                # Return the successful lastName
                if data.get('lastName'):
                    return data['lastName']
            
            # Return None if no successful run found
            return None
            
        except Exception as e:
            logger.error(f"Error getting last successful name for PNR {pnr}: {str(e)}")
            return None

    def log_error(self, error_type, error_message, context=None):
        """Add error logging"""
        try:
            self.error_ref.add({
                'timestamp': datetime.now(pytz.UTC),
                'type': error_type,
                'message': error_message,
                'context': context or {},
                'airline': 'akasa'
            })
        except Exception as e:
            logger.error(f"Error logging to Firestore: {e}")

    def clear_scraper_state(self, pnr):
        """Add state clearing"""
        try:
            self.scraper_state_ref.document(pnr).delete()
            return True
        except Exception as e:
            logger.error(f"Error clearing scraper state: {e}")
            return False

    def log_scraper_error(self, error_type, error_message, context=None):
        """Log Akasa Air specific scraper errors"""
        try:
            error_doc = {
                'timestamp': datetime.now(pytz.UTC),
                'type': error_type,
                'message': error_message,
                'context': context or {},
                'airline': 'akasa',
                'severity': 'error'
            }
            
            # Add to error collection
            self.error_ref.add(error_doc)
            
            # Update scraper state if PNR is provided
            if context and 'pnr' in context:
                self.store_scraper_state(
                    pnr=context['pnr'],
                    state='failed',
                    message=error_message,
                    lastName=context.get('lastName')
                )
                
            # Send notification if critical error
            if error_type in ['AUTH_ERROR', 'API_ERROR', 'CRITICAL']:
                self.send_error_notification(error_type, error_message, context)
                
        except Exception as e:
            logger.error(f"Error logging scraper error: {str(e)}")

    def send_error_notification(self, error_type, error_message, context):
        """Send error notifications for Akasa Air"""
        try:
            notification_emails = self.get_notification_emails()
            if notification_emails:
                html_content = f"""
                    <h2>Akasa Air Scraper Error</h2>
                    <p><strong>Error Type:</strong> {error_type}</p>
                    <p><strong>Message:</strong> {error_message}</p>
                    <p><strong>PNR:</strong> {context.get('pnr', 'N/A')}</p>
                    <p><strong>Last Name:</strong> {context.get('lastName', 'N/A')}</p>
                    <p><strong>Timestamp:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                """
                
                send_notification_email(
                    subject=f"Akasa Air Scraper Error - {error_type}",
                    html_content=html_content,
                    notification_emails=notification_emails
                )
        except Exception as e:
            logger.error(f"Error sending error notification: {str(e)}")

    def get_scraper_state_by_pnr(self, pnr):
        """Get scraper state by PNR only"""
        try:
            doc = self.scraper_state_ref.document(pnr).get()
            if doc.exists:
                data = doc.to_dict()
                # Convert timestamps to milliseconds for frontend
                for field in ['last_run', 'next_run', 'updated_at']:
                    if field in data and data[field]:
                        data[field] = int(data[field].timestamp() * 1000)
                return data
            return None
        except Exception as e:
            logger.error(f"Error getting scraper state by PNR: {e}")
            return None

    def store_api_response(self, pnr, response_data, status='success'):
        """Store API response data"""
        try:
            doc_id = f"api_response_{pnr}"
            self.akasa_ref.collection('api_responses').document(doc_id).set({
                'pnr': pnr,
                'response': response_data,
                'status': status,
                'timestamp': datetime.now(pytz.UTC)
            }, merge=True)
            return True
        except Exception as e:
            logger.error(f"Error storing API response: {e}")
            return False

    def update_scraper_progress(self, pnr, stage, status, message=None):
        """Update scraper progress for monitoring"""
        try:
            current_time = datetime.now(pytz.UTC)
            progress_data = {
                'stage': stage,
                'status': status,
                'message': message,
                'updated_at': current_time
            }
            
            # Update current state
            self.scraper_state_ref.document(pnr).set({
                'current_stage': progress_data
            }, merge=True)
            
            # Add to progress history
            self.scraper_state_ref.document(pnr)\
                .collection('progress_history').add({
                    **progress_data,
                    'timestamp': current_time
                })
            
            return True
        except Exception as e:
            logger.error(f"Error updating scraper progress: {e}")
            return False

    def get_last_scraper_state(self):
        """Get most recent scraper state with proper error handling"""
        try:
            states = self.scraper_state_ref\
                .order_by('updated_at', direction=Query.DESCENDING)\
                .limit(1)\
                .stream()
            
            for state in states:
                data = state.to_dict()
                # Convert timestamps to milliseconds for frontend
                for field in ['last_run', 'next_run', 'updated_at']:
                    if field in data and data[field]:
                        data[field] = int(data[field].timestamp() * 1000)
                return data
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting last scraper state: {e}")
            return None

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

    def get_last_dom_comparison_result(self, page_id):
        """Get latest DOM comparison result"""
        try:
            doc = self.dom_changes_ref.document(page_id).get()
            if doc.exists:
                data = doc.to_dict()
                return {
                    'has_changes': data.get('has_changes', False),
                    'last_check': data.get('timestamp'),
                    'changes_count': len(data.get('changes', [])),
                    'pnr': data.get('pnr'),
                    'traveller_name': data.get('traveller_name')
                }
            return {
                'has_changes': False,
                'last_check': None,
                'changes_count': 0
            }
        except Exception as e:
            logger.error(f"Error getting last DOM comparison: {e}")
            return None
