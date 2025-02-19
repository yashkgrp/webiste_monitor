from datetime import datetime
import pytz
import logging
from firebase_admin import firestore
import firebase_admin

logger = logging.getLogger(__name__)

class PortalFirestoreDB:
    def __init__(self, db, portal_id):
        """Initialize database with portal-specific collections"""
        self.db = db
        self.portal_id = portal_id
        self.urls_ref = self.db.collection('monitored_urls')
        self.portal_ref = self.urls_ref.document(portal_id)
        
        # Initialize subcollections
        self.scraper_state_ref = self.portal_ref.collection('scraper_states')
        self.scraper_history_ref = self.portal_ref.collection('scraper_history')
        self.error_ref = self.portal_ref.collection('errors')
        self.invoice_ref = self.portal_ref.collection('invoices')
        self.settings_ref = self.portal_ref.collection('settings')
        self.scheduler_settings_ref = self.settings_ref.document('scheduler')
        
        # Add scheduler settings collection for compatibility
        self.scheduler_collection = self.portal_ref.collection('settings')
        self.scheduler_doc = self.scheduler_collection.document('scheduler')
        
        self._init_default_settings()

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
            
            settings_doc = self.scheduler_settings_ref.get()
            if not settings_doc.exists:
                self.scheduler_settings_ref.set(default_settings)
                logger.info(f"Initialized default {self.portal_id} scheduler settings")
                return default_settings
                
            return settings_doc.to_dict()
            
        except Exception as e:
            logger.error(f"Error initializing database structure: {e}")
            return None

    def store_scraper_state(self, username, state='pending', message=None, data=None, 
                           portal=None, auto_run=False, next_run=None, preserve_last_run=False):
        """Store scraper state using username instead of reference"""
        try:
            doc_id = username  # Use username as document ID
            current_time = datetime.now(pytz.UTC)
            
            state_data = {
                'username': username,
                'state': state,
                'message': message,
                'updated_at': current_time,
                'portal': portal,
                'portal_id': self.portal_id,
                'auto_run': auto_run
            }
            
            # Get existing state if needed
            existing_state = self.scraper_state_ref.document(doc_id).get() if preserve_last_run else None
            
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
            
            if data:
                state_data['data'] = data
                
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
                'reference': username,
                'state': state,
                'message': message,
                'data': data
            }
            
            self.scraper_history_ref.add(history_data)
            
        except Exception as e:
            logger.error(f"Error storing scraper state: {e}")
            raise

    def store_invoice_data(self, username, invoice_data, invoice_files=None):
        """Store processed invoice data with username"""
        try:
            current_time = datetime.now(pytz.UTC)
            doc_data = {
                'username': username,  # Changed from reference
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

    def get_scraper_state(self, reference):
        """Get current scraper state"""
        try:
            doc = self.scraper_state_ref.document(reference).get()
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
        """Log errors with context"""
        try:
            error_doc = {
                'timestamp': datetime.now(pytz.UTC),
                'type': error_type,
                'message': error_message,
                'context': context or {},
                'portal_id': self.portal_id,
                'severity': 'error',
                'vendor': context.get('vendor') if context else None
            }
            
            # Store error
            self.error_ref.add(error_doc)
            
            # Update scraper state if reference provided
            if context and 'reference' in context:
                self.store_scraper_state(
                    reference=context['reference'],
                    state='failed',
                    message=error_message,
                    data={'error': error_message}
                )
                
        except Exception as e:
            logger.error(f"Error logging error: {str(e)}")

    def update_scraper_progress(self, username, stage, step, status, message, data=None):
        """Update scraper progress using username"""
        try:
            progress_data = {
                'username': username,  # Ensure username is stored
                'stage': stage,
                'step': step,
                'status': status,
                'message': message,
                'updated_at': datetime.now(pytz.UTC),
                'portal': self.portal_id
            }
            if data:
                progress_data['data'] = data
                
            self.scraper_state_ref.document(username).set(
                progress_data, 
                merge=True
            )
        except Exception as e:
            logger.error(f"Error updating scraper progress: {e}")
            raise

    def get_notification_emails(self):
        """Get notification email list"""
        try:
            doc = self.db.collection('monitor_mails').document('email').get()
            if doc.exists:
                return doc.to_dict().get('emails', [])
            return []
        except Exception as e:
            logger.error(f"Error getting notification emails: {str(e)}")
            return []

    def get_scheduler_settings(self):
        """Get scheduler settings with full compatibility"""
        try:
            doc = self.scheduler_doc.get()
            if not doc.exists:
                default_settings = self._init_default_settings()
                if not default_settings:
                    raise Exception("Failed to initialize default settings")
                return default_settings

            data = doc.to_dict()
            if not data:
                raise Exception("Empty settings document")

            settings = {
                'auto_run': data.get('auto_run', False),
                'interval': data.get('interval', 60),
                'updated_at': data.get('updated_at', datetime.now(pytz.UTC))
            }

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
            return {
                'auto_run': False,
                'interval': 60,
                'next_run': None,
                'updated_at': datetime.now(pytz.UTC)
            }

    def update_scheduler_settings(self, auto_run, interval, next_run=None):
        """Update scheduler settings with full compatibility"""
        try:
            settings = {
                'auto_run': auto_run,
                'interval': interval,
                'updated_at': datetime.now(pytz.UTC)
            }
            if next_run:
                settings['next_run'] = next_run
                
            self.scheduler_settings_ref.set(settings, merge=True)
            
            # Update last state with new settings
            last_state = self.get_last_scraper_state()
            if last_state:
                self.store_scraper_state(
                    reference=last_state.get('reference'),
                    state=last_state.get('state', 'idle'),
                    vendor=last_state.get('vendor'),
                    next_run=next_run,
                    preserve_last_run=True
                )
            
            return True
        except Exception as e:
            logger.error(f"Error updating scheduler settings: {e}")
            return False

    def get_last_scraper_state(self):
        """Get most recent scraper state with compatibility"""
        try:
            states = self.scraper_state_ref\
                .order_by('updated_at', direction=firestore.Query.DESCENDING)\
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

def test_db_ops():
    """Test database operations"""
    try:
        # Initialize Firebase if not already initialized
        try:
            app = firebase_admin.get_app()
        except ValueError:
            cred = firebase_admin.credentials.Certificate('../firebase-adminsdk.json')
            app = firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        portal_db = PortalFirestoreDB(db, 'test_portal')
        
        # Updated test data
        test_username = "test_user"
        test_portal = "TestPortal"
        
        print("\nTesting database operations...")
        print("-" * 50)
        
        # Test state storage
        print("\n1. Testing state storage...")
        portal_db.store_scraper_state(
            username=test_username,
            state='starting',
            message='Test execution',
            portal=test_portal
        )
        print("State stored successfully")
        
        # Test state retrieval
        print("\n2. Testing state retrieval...")
        state = portal_db.get_scraper_state(test_username)
        print(f"Retrieved state: {state}")
        
        # Test progress update
        print("\n3. Testing progress update...")
        portal_db.update_scraper_progress(
            username=test_username,
            stage='processing',
            step='download',
            status='in_progress',
            message='Downloading files'
        )
        print("Progress updated successfully")
        
        # Test error logging
        print("\n4. Testing error logging...")
        portal_db.log_error(
            'TEST_ERROR',
            'Test error message',
            {'reference': test_username}
        )
        print("Error logged successfully")
        
        # Test invoice storage
        print("\n5. Testing invoice storage...")
        test_invoice = {
            'test_data': 'sample invoice data'
        }
        test_files = [{
            'name': 'test.pdf',
            'type': 'invoice',
            'size': 1024,
            'path': '/test/path'
        }]
        portal_db.store_invoice_data(
            test_username,
            test_invoice,
            test_files
        )
        print("Invoice data stored successfully")
        
        print("\nAll tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"\nTest failed: {str(e)}")
        return False

if __name__ == '__main__':
    # Run tests
    test_db_ops()
