from datetime import datetime
import pytz
import logging
from firebase_admin import firestore
import firebase_admin
import base64
import os

logger = logging.getLogger(__name__)

class PortalFirestoreDB:
    def __init__(self, db, portal_id):
        """Initialize database with portal-specific collections"""
        self.db = db
        self.portal_id = portal_id
        self.urls_ref = self.db.collection('monitored_urls')
        self.portal_ref = self.urls_ref.document('fcm')
        
        # Initialize subcollections
        self.scraper_state_ref = self.portal_ref.collection('scraper_states')
        self.scraper_history_ref = self.portal_ref.collection('scraper_history')
        self.error_ref = self.portal_ref.collection('errors')
        self.invoice_ref = self.portal_ref.collection('invoices')
        self.settings_ref = self.portal_ref.collection('settings')
        self.scheduler_settings_ref = self.settings_ref.document('scheduler')
        self.credentials_ref = self.portal_ref.collection('credentials')
        
        self._init_default_settings()

    def store_credentials(self, username, password):
        """Store credentials directly"""
        try:
            self.credentials_ref.document(username).set({
                'username': username,
                'password': password,
                'updated_at': datetime.now(pytz.UTC)
            }, merge=True)
            return True
        except Exception as e:
            logger.error(f"Error storing credentials: {e}")
            return False

    def get_credentials(self, username):
        """Retrieve credentials directly"""
        try:
            doc = self.credentials_ref.document(username).get()
            if not doc.exists:
                return None
                
            data = doc.to_dict()
            return {
                'username': username,
                'password': data.get('password')
            }
        except Exception as e:
            logger.error(f"Error retrieving credentials: {e}")
            return None

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
            
            # Ensure all collections exist
            self._ensure_collections_exist()
            
            settings_doc = self.scheduler_settings_ref.get()
            if not settings_doc.exists:
                self.scheduler_settings_ref.set(default_settings)
                logger.info(f"Initialized default {self.portal_id} scheduler settings")
                return default_settings
                
            return settings_doc.to_dict()
            
        except Exception as e:
            logger.error(f"Error initializing default settings: {e}")
            return None

    def _ensure_collections_exist(self):
        """Ensure all required collections exist with initial documents"""
        collections_data = {
            'scraper_states': {'initialized': True, 'type': 'state_collection'},
            'scraper_history': {'initialized': True, 'type': 'history_collection'},
            'errors': {'initialized': True, 'type': 'error_collection'},
            'invoices': {'initialized': True, 'type': 'invoice_collection'},
            'settings': {'initialized': True, 'type': 'settings_collection'},
            'members': {'initialized': True, 'type': 'members_collection'},
            'files': {'initialized': True, 'type': 'files_collection'}
        }
        
        for coll_name, init_data in collections_data.items():
            coll_ref = self.portal_ref.collection(coll_name)
            if not self._check_collection_exists(coll_ref):
                init_data.update({
                    'created_at': datetime.now(pytz.UTC),
                    'portal_id': self.portal_id
                })
                coll_ref.document('_init').set(init_data)
                logger.info(f"Initialized collection: {coll_name}")

    def store_scraper_state(self, username, state='pending', message=None, data=None, 
                           portal=None, auto_run=False, next_run=None, preserve_last_run=False,
                           password=None):
        """Store scraper state with member management state tracking"""
        try:
            current_time = datetime.now(pytz.UTC)
            
            state_data = {
                'username': username,
                'state': state,
                'message': message or f"State changed to {state}",
                'updated_at': current_time,
                'portal': portal or self.portal_id,
                'portal_id': self.portal_id,
                'auto_run': auto_run,
                'member_management_completed': False  # Track member management completion
            }
            
            # If member management was completed, update the flag
            if data and 'member_added' in data:
                state_data['member_management_completed'] = True
                state_data['last_member_added'] = data['member_added']
            
            # Store password if provided
            if password:
                stored = self.store_credentials(username, password)
                if not stored:
                    logger.warning(f"Failed to store credentials for {username}")

            # Get existing state if needed
            if preserve_last_run:
                existing_state = self.scraper_state_ref.document(username).get()
                if existing_state.exists:
                    existing_data = existing_state.to_dict()
                    if 'last_run' in existing_data:
                        state_data['last_run'] = existing_data['last_run']
            
            if state not in ['new', 'pending']:
                state_data['last_run'] = current_time

            if next_run:
                state_data['next_run'] = next_run
            
            if data:
                state_data['data'] = data
                
            if state == 'failed':
                state_data['last_error'] = {
                    'message': message,
                    'timestamp': current_time,
                    'data': data
                }
                
            # Store state
            self.scraper_state_ref.document(username).set(state_data, merge=True)
            
            # Add to history
            self.scraper_history_ref.add({
                'timestamp': current_time,
                'username': username,
                'state': state,
                'message': message,
                'data': data
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing scraper state: {e}")
            self.log_error('STATE_STORE_ERROR', str(e), {
                'username': username,
                'state': state
            })
            return False

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

    def get_scraper_state(self, username):
        """Get current scraper state with password"""
        try:
            state_doc = self.scraper_state_ref.document(username).get()
            credentials = self.get_credentials(username)
            
            state_data = {
                'state': 'new',
                'last_run': None
            }
            
            if state_doc.exists:
                state_data.update(state_doc.to_dict())
                
            if credentials:
                state_data['password'] = credentials['password']
                
            # Convert timestamps for frontend
            for field in ['last_run', 'next_run', 'updated_at']:
                if field in state_data and state_data[field]:
                    state_data[field] = int(state_data[field].timestamp() * 1000)
                    
            return state_data
            
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
            doc = self.scheduler_settings_ref.get()  # Changed from scheduler_doc to scheduler_settings_ref
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
                    if isinstance(data['next_run'], datetime):
                        settings['next_run'] = int(data['next_run'].timestamp() * 1000)
                    else:
                        settings['next_run'] = None
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
            if last_state and last_state.get('username'):  # Changed to use username instead of reference
                self.store_scraper_state(
                    username=last_state.get('username'),  # Changed from reference to username
                    state=last_state.get('state', 'idle'),
                    message="Settings updated",
                    portal=self.portal_id,
                    next_run=next_run,
                    preserve_last_run=True
                )
            
            return True
        except Exception as e:
            logger.error(f"Error updating scheduler settings: {e}")
            return False

    def get_last_scraper_state(self):
        """Get most recent scraper state with enhanced error handling"""
        try:
            states = self.scraper_state_ref\
                .where('state', '!=', 'new')\
                .order_by('state')\
                .order_by('updated_at', direction=firestore.Query.DESCENDING)\
                .limit(1)\
                .stream()
            
            state_data = None
            for state in states:
                state_data = state.to_dict()
                break
                
            if not state_data:
                # Return default state for first-time
                return {
                    'state': 'new',
                    'last_run': None,
                    'next_run': None,
                    'auto_run': False,
                    'updated_at': datetime.now(pytz.UTC)
                }
                
            # Convert timestamps for frontend
            for field in ['last_run', 'next_run', 'updated_at']:
                if field in state_data and state_data[field]:
                    state_data[field] = int(state_data[field].timestamp() * 1000)
                    
            # Get credentials if username exists
            if state_data.get('username'):
                credentials = self.get_credentials(state_data['username'])
                if credentials:
                    state_data['password'] = credentials['password']
                    
            return state_data
            
        except Exception as e:
            logger.error(f"Error getting last scraper state: {e}")
            return {
                'state': 'new',
                'error': str(e),
                'last_run': None,
                'next_run': None
            }

    def store_file_record(self, username, file_data):
        """Store processed file record"""
        try:
            current_time = datetime.now(pytz.UTC)
            
            file_record = {
                'username': username,
                'filename': file_data.get('filename'),
                'file_type': file_data.get('type'),
                'file_path': file_data.get('path'),
                'size': file_data.get('size'),
                'status': file_data.get('status', 'processed'),
                'process_time': file_data.get('process_time'),
                'created_at': current_time,
                'portal_id': self.portal_id
            }
            
            # Add to files collection
            self.portal_ref.collection('files').add(file_record)
            
            # Update last state with file info
            self.store_scraper_state(
                username=username,
                state='completed',
                data={'last_processed_file': file_record},
                preserve_last_run=True
            )
            
            return True
        except Exception as e:
            logger.error(f"Error storing file record: {e}")
            return False

    def get_file_records(self, username=None, file_type=None, start_date=None, end_date=None):
        """Get processed file records with optional filters"""
        try:
            query = self.portal_ref.collection('files')
            
            if username:
                query = query.where('username', '==', username)
            if file_type:
                query = query.where('file_type', '==', file_type)
            if start_date:
                query = query.where('created_at', '>=', start_date)
            if end_date:
                query = query.where('created_at', '<=', end_date)
                
            records = []
            for doc in query.stream():
                record = doc.to_dict()
                # Convert timestamps for frontend
                if 'created_at' in record:
                    record['created_at'] = int(record['created_at'].timestamp() * 1000)
                records.append(record)
                
            return records
        except Exception as e:
            logger.error(f"Error retrieving file records: {e}")
            return []

    def store_member_operation(self, username, member_data, status='completed'):
        """Store member management operation details"""
        try:
            current_time = datetime.now(pytz.UTC)
            
            member_op = {
                'username': username,
                'member_email': member_data.get('email'),
                'workspace': member_data.get('workspace'),
                'role': member_data.get('role'),
                'status': status,
                'timestamp': current_time,
                'portal_id': self.portal_id
            }
            
            # Store in members collection
            self.portal_ref.collection('members').add(member_op)
            
            # Update last state with member operation
            self.store_scraper_state(
                username=username,
                state='completed',
                message=f"Member {member_data.get('email')} added successfully",
                data={'last_member_operation': member_op},
                preserve_last_run=True
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing member operation: {e}")
            return False
            
    def get_notification_emails(self):
        """Get list of notification emails from Firestore"""
        try:
            print('notification_email_list_file_upload', 'get_emails')
            # Changed collection and document names to match file_upload implementation
            doc = self.db.collection('monitor_mails').document('email').get()
            if doc.exists:
                emails = doc.to_dict().get('emails', [])
                logging.info(f"Found notification emails: {emails}")
                return emails
            logging.warning("No notification emails document found")
            return []
        except Exception as e:
            print('get_notification_emails', str(e))
            logging.error(f"Error fetching notification emails: {e}")
            # Fallback to email document
            try:
                doc = self.db.collection('notification_email_list_file_upload').document('emails').get()
                if doc.exists:
                    return doc.to_dict().get('email', [])
                return []
            except Exception:
                return []


    def get_member_operations(self, username=None, start_date=None, end_date=None):
        """Get member management operation history"""
        try:
            query = self.portal_ref.collection('members')
            
            if username:
                query = query.where('username', '==', username)
            if start_date:
                query = query.where('timestamp', '>=', start_date)
            if end_date:
                query = query.where('timestamp', '<=', end_date)
                
            operations = []
            for doc in query.stream():
                operation = doc.to_dict()
                # Convert timestamps for frontend
                if 'timestamp' in operation:
                    operation['timestamp'] = int(operation['timestamp'].timestamp() * 1000)
                operations.append(operation)
                
            return operations
            
        except Exception as e:
            logger.error(f"Error retrieving member operations: {e}")
            return []

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
