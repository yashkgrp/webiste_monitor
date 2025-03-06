from datetime import datetime, timedelta
import logging
import pytz
from google.cloud.firestore import Query, ArrayUnion

logger = logging.getLogger(__name__)

class IndigoFirestoreDB:
    def __init__(self, db):
        self.db = db
        self.urls_ref = self.db.collection('monitored_urls')
        self.indigo_ref = self.urls_ref.document('indigo_air')
        
        # Initialize collections
        self.scraper_state_ref = self.indigo_ref.collection('scraper_states_indigo')
        self.scraper_history_ref = self.indigo_ref.collection('scraper_history')
        self.error_ref = self.indigo_ref.collection('errors')
        self.invoice_ref = self.indigo_ref.collection('invoices')
        
        # Initialize DOM collections
        self.dom_snapshots_ref = self.indigo_ref.collection('dom_snapshots')
        self.dom_changes_ref = self.indigo_ref.collection('dom_changes')
        
        # Settings collection
        self.settings_ref = self.indigo_ref.collection('settings')
        self.scheduler_settings_ref = self.settings_ref.document('scheduler')
        
        self._init_default_settings()

    def _init_default_settings(self):
        """Initialize default settings"""
        try:
            settings_doc = self.scheduler_settings_ref.get()
            if not settings_doc.exists:
                self.scheduler_settings_ref.set({
                    'auto_run': False,
                    'interval': 60,  # Default 60 minutes
                    'next_run': None,
                    'notification_emails': []
                })
        except Exception as e:
            logger.error(f"Failed to initialize settings: {e}")

    def store_scraper_state(self, pnr, state='pending', message=None, data=None, 
                           next_run=None, ssr_email=None, 
                           preserve_last_run=False, vendor="INDIGO AIR"):
        """Store scraper state for Indigo Air"""
        try:
            timestamp = datetime.now(pytz.UTC)
            doc_ref = self.scraper_state_ref.document(pnr)
            
            state_data = {
                'pnr': pnr,
                'state': state,
                'message': message,
                'timestamp': timestamp,
                'vendor': vendor,
                'ssr_email': ssr_email
            }
            
            if data:
                state_data['data'] = self.format_for_json(data)
            if next_run:
                state_data['next_run'] = next_run
                
            # Preserve last successful run if needed
            if preserve_last_run:
                existing = doc_ref.get()
                if existing.exists and existing.to_dict().get('last_success'):
                    state_data['last_success'] = existing.to_dict()['last_success']
                    
            doc_ref.set(state_data, merge=True)
            
            # Add to history
            self.scraper_history_ref.add({
                'pnr': pnr,
                'state': state,
                'message': message,
                'timestamp': timestamp,
                'vendor': vendor,
                'ssr_email': ssr_email
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to store scraper state: {e}")
            return False

    def format_for_json(self, data):
        """Helper method to format data for JSON serialization"""
        if isinstance(data, dict):
            return {k: self.format_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.format_for_json(item) for item in data]
        elif isinstance(data, datetime):
            return data.isoformat()
        return data

    def log_error(self, error_type, message, context=None):
        """Log error with context"""
        try:
            error_data = {
                'type': error_type,
                'message': message,
                'timestamp': datetime.now()
            }
            if context:
                error_data['context'] = self.format_for_json(context)
            self.error_ref.add(error_data)
            return True
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
            return False

    def store_dom_snapshot(self, page_id, content, metadata=None):
        """Store DOM snapshot"""
        try:
            snapshot_data = {
                'page_id': page_id,
                'content': content,
                'timestamp': datetime.now()
            }
            if metadata:
                snapshot_data['metadata'] = self.format_for_json(metadata)
            self.dom_snapshots_ref.add(snapshot_data)
            return True
        except Exception as e:
            logger.error(f"Failed to store DOM snapshot: {e}")
            return False

    def store_dom_data(self, data, page_id):
        """Store DOM changes and snapshots"""
        try:
            data['timestamp'] = datetime.now()
            data['page_id'] = page_id
            self.dom_changes_ref.add(self.format_for_json(data))
            return True
        except Exception as e:
            logger.error(f"Failed to store DOM data: {e}")
            return False

    def get_notification_emails(self):
        """Get notification email list"""
        try:
            doc = self.db.collection('monitor_mails').document('email').get()
            if doc.exists:
                emails = doc.to_dict().get('emails', [])
                logging.info(f"Found notification emails: {emails}")
                return emails
            logging.warning("No notification emails document found")
            return []
        except Exception as e:
            logger.error(f"Failed to get notification emails: {e}")
            return []

    def get_scheduler_settings(self):
        """Get scheduler settings"""
        try:
            settings = self.scheduler_settings_ref.get()
            if settings.exists:
                return settings.to_dict()
            return None
        except Exception as e:
            logger.error(f"Failed to get scheduler settings: {e}")
            return None

    def update_scheduler_settings(self, auto_run, interval, next_run=None):
        """Update scheduler settings"""
        try:
            update_data = {
                'auto_run': auto_run,
                'interval': interval
            }
            if next_run:
                update_data['next_run'] = next_run
            self.scheduler_settings_ref.set(update_data, merge=True)
            return True
        except Exception as e:
            logger.error(f"Failed to update scheduler settings: {e}")
            return False

    def store_invoice_data(self, pnr, invoice_data, invoice_files=None):
        """Store downloaded invoice data"""
        try:
            invoice_doc = {
                'pnr': pnr,
                'data': self.format_for_json(invoice_data),
                'timestamp': datetime.now()
            }
            if invoice_files:
                invoice_doc['files'] = invoice_files
            self.invoice_ref.add(invoice_doc)
            return True
        except Exception as e:
            logger.error(f"Failed to store invoice data: {e}")
            return False

    def get_state(self, pnr):
        """Get current scraper state"""
        try:
            doc = self.scraper_state_ref.document(pnr).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get state: {e}")
            return None

    def update_state(self, pnr, state_data):
        """Update scraper state"""
        try:
            self.scraper_state_ref.document(pnr).set(
                self.format_for_json(state_data), merge=True)
            return True
        except Exception as e:
            logger.error(f"Failed to update state: {e}")
            return False

    def get_performance_stats(self):
        """Get performance statistics"""
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(days=7)
            
            stats = {
                'total_runs': 0,
                'successful': 0,
                'failed': 0,
                'states': {},
                'recent_runs': []
            }
            
            # Query last 7 days of history
            query = (self.scraper_history_ref
                    .where('timestamp', '>=', start_time)
                    .order_by('timestamp', direction=Query.DESCENDING)
                    .limit(100))
            
            for doc in query.stream():
                data = doc.to_dict()
                stats['total_runs'] += 1
                
                if data.get('state') == 'completed':
                    stats['successful'] += 1
                elif data.get('state') == 'failed':
                    stats['failed'] += 1
                    
                stats['states'][data.get('state', 'unknown')] = (
                    stats['states'].get(data.get('state', 'unknown'), 0) + 1
                )
                
                stats['recent_runs'].append({
                    'pnr': data.get('pnr'),
                    'state': data.get('state'),
                    'timestamp': data.get('timestamp'),
                    'message': data.get('message')
                })
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get performance stats: {e}")
            return None

    def get_last_scraper_state(self):
        """Get most recent scraper state"""
        try:
            query = (self.scraper_state_ref
                    .order_by('timestamp', direction=Query.DESCENDING)
                    .limit(1))
            
            docs = list(query.stream())
            scheduler_settings = self.get_scheduler_settings()

            # Add next_run and auto_run to the returned state for first doc
            state_dict = {}
            for doc in docs:
                state_dict = doc.to_dict()
                state_dict['next_run'] = scheduler_settings.get('next_run')
                state_dict['auto_run'] = scheduler_settings.get('auto_run')
                return state_dict
            return None
            
            
        except Exception as e:
            logger.error(f"Failed to get last scraper state: {e}")
            return None

    def get_dom_changes(self, page_id=None, limit=100):
        """Get recent DOM changes"""
        try:
            query = self.dom_changes_ref.order_by(
                'timestamp', direction=Query.DESCENDING)
            if page_id:
                query = query.where('page_id', '==', page_id)
            query = query.limit(limit)
            
            return [doc.to_dict() for doc in query.stream()]
            
        except Exception as e:
            logger.error(f"Failed to get DOM changes: {e}")
            return []

    def mark_captcha(self, captcha_id, success):
        """Store CAPTCHA result"""
        try:
            self.scraper_history_ref.add({
                'type': 'captcha',
                'captcha_id': captcha_id,
                'success': success,
                'timestamp': datetime.now()
            })
            return True
        except Exception as e:
            logger.error(f"Failed to mark captcha: {e}")
            return False

    def get_dom_snapshot(self, page_id):
        """Get the most recent DOM snapshot for a page"""
        try:
            query = (self.dom_snapshots_ref
                    .where('page_id', '==', page_id)
                    .order_by('timestamp', direction=Query.DESCENDING)
                    .limit(1))
            
            docs = list(query.stream())
            if docs:
                return docs[0].to_dict()
            return None
            
        except Exception as e:
            logger.error(f"Failed to get DOM snapshot: {e}")
            return None

    def update_scraper_progress(self, pnr, stage, step, status, message, data=None):
        """Update scraper progress state"""
        try:
            progress_data = {
                'pnr': pnr,
                'stage': stage,
                'step': step,
                'status': status,
                'message': message,
                'timestamp': datetime.now()
            }
            if data:
                progress_data['data'] = self.format_for_json(data)
                
            # self.scraper_state_ref.document(pnr).set({
            #     'current_progress': progress_data
            # }, merge=True)
            
            self.scraper_history_ref.add(progress_data)
            return True
            
        except Exception as e:
            logger.error(f"Failed to update scraper progress: {e}")
            return False

class MockFirestoreDB:
    """Mock DB implementation for testing"""
    def __init__(self):
        self.data = {
            'snapshots': {},
            'changes': [],
            'states': {},
            'errors': []
        }

    def collection(self, _):
        return self

    def document(self, doc_id):
        self.current_doc_id = doc_id
        return self

    def set(self, data, merge=False):
        if hasattr(self, 'current_doc_id'):
            if merge and self.current_doc_id in self.data['snapshots']:
                self.data['snapshots'][self.current_doc_id].update(data)
            else:
                self.data['snapshots'][self.current_doc_id] = data
        return True

    def get(self):
        class MockDoc:
            def __init__(self, exists, data=None):
                self.exists = exists
                self._data = data

            def to_dict(self):
                return self._data

        if hasattr(self, 'current_doc_id'):
            data = self.data['snapshots'].get(self.current_doc_id)
            return MockDoc(exists=bool(data), data=data)
        return MockDoc(exists=False)

    def add(self, data):
        self.data['changes'].append(data)
        return None

    def where(self, field, op, value):
        return self  # For testing, just return self

    def stream(self):
        # Return mock documents
        return []

# Update test execution in db_util.py
if __name__ == '__main__':
    import firebase_admin
    from firebase_admin import credentials, firestore
    import json
    import time
    from datetime import datetime, timedelta
    import pytz
    
    print("\n=== Indigo DB Tests with Real Firebase ===")
    
    # Initialize Firebase with service account
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate("../firebase-adminsdk.json")
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Successfully connected to Firestore")
    except Exception as e:
        print(f"❌ Failed to initialize Firebase: {e}")
        print("Please ensure firebase-adminsdk.json is present in the parent directory")
        exit(1)

    indigo_db = IndigoFirestoreDB(db)
    test_pnr = "TEST123"
    test_ssr_email = "test@example.com"
    
    def run_tests():
        tests = [
            test_store_scraper_state,
            test_get_state,
            test_log_error,
            test_store_dom_snapshot,
            test_store_dom_data,
            test_get_notification_emails,
            test_scheduler_settings,
            test_store_invoice_data,
            test_performance_stats,
            test_dom_changes
        ]
        
        results = {
            'passed': 0,
            'failed': 0,
            'errors': []
        }
        
        print("\n🚀 Starting Indigo DB Tests")
        print("=" * 60)
        
        for test in tests:
            try:
                print(f"\n📋 Running: {test.__name__}")
                print("-" * 40)
                test()
                results['passed'] += 1
                print(f"✅ {test.__name__} passed")
            except Exception as e:
                results['failed'] += 1
                error = f"❌ {test.__name__} failed: {str(e)}"
                results['errors'].append(error)
                print(error)
                print(f"Error details: {e}")
            print("-" * 40)
        
        return results

    def test_store_scraper_state():
        """Test scraper state storage"""
        print("Testing scraper state storage...")
        
        # Test data with ssr_email instead of transaction_date
        initial_state = {
            'pnr': test_pnr,
            'state': "testing",
            'message': "Test state",
            'ssr_email': test_ssr_email
        }
        
        print("\n📥 Storing initial state:")
        print(json.dumps(initial_state, indent=2))
        
        # Test basic state storage
        result = indigo_db.store_scraper_state(**initial_state)
        assert result == True, "Failed to store scraper state"
        
        # Verify stored state
        stored_state = indigo_db.get_state(test_pnr)
        print("\n📤 Retrieved state:")
        formatted_state = indigo_db.format_for_json(stored_state)
        print(json.dumps(formatted_state, indent=2))
        
        # Test state update with preservation
        updated_state = {
            'pnr': test_pnr,
            'state': "updated",
            'message': "Updated state",
            'ssr_email': test_ssr_email,
            'preserve_last_run': True
        }
        
        print("\n📥 Updating state with preservation:")
        print(json.dumps(updated_state, indent=2))
        
        result = indigo_db.store_scraper_state(**updated_state)
        assert result == True, "Failed to preserve last run time"
        
        # Verify updated state
        final_state = indigo_db.get_state(test_pnr)
        print("\n📤 Final state:")
        formatted_final = indigo_db.format_for_json(final_state)
        print(json.dumps(formatted_final, indent=2))
        
        assert final_state['state'] == "updated", "State not updated correctly"
        assert final_state['ssr_email'] == test_ssr_email, "SSR email not preserved"

    def test_get_state():
        """Test state retrieval for Indigo"""
        print("Testing state retrieval...")
        
        state = indigo_db.get_last_scraper_state()
        print("\n📤 Retrieved state:")
        formatted_state = indigo_db.format_for_json(state)
        print(json.dumps(formatted_state, indent=2))
        
        assert state is not None, "Failed to get state"
        
        assert 'pnr' in state, "PNR missing in state"
        assert 'ssr_email' in state, "SSR email missing in state"

    def test_log_error():
        """Test error logging for Indigo"""
        print("Testing error logging...")
        
        context = {
            'pnr': test_pnr,
            'ssr_email': test_ssr_email,
            'stage': 'testing'
        }
        
        error_data = {
            'error_type': 'TEST_ERROR',
            'message': 'Test error message for Indigo',
            'context': context
        }
        
        print("\n📥 Logging error:")
        print(json.dumps(error_data, indent=2))
        
        result = indigo_db.log_error(**error_data)
        assert result == True, "Failed to log error"
        
        # Verify error affected state
        error_state = indigo_db.get_state(test_pnr)
        print("\n📤 State after error:")
        formatted_state = indigo_db.format_for_json(error_state)
        print(json.dumps(formatted_state, indent=2))

    def test_store_dom_snapshot():
        """Test DOM snapshot storage for Indigo portal"""
        print("Testing DOM snapshot storage...")
        
        test_data = {
            'page_id': 'indigo_gst_portal',
            'content': '<html><body>Test content for Indigo portal</body></html>',
            'metadata': {
                'pnr': test_pnr,
                'ssr_email': test_ssr_email,
                'timestamp': datetime.now(pytz.UTC).isoformat()
            }
        }
        
        print("\n📥 Storing DOM snapshot:")
        print(json.dumps(test_data, indent=2))
        
        result = indigo_db.store_dom_snapshot(**test_data)
        assert result == True, "Failed to store DOM snapshot"

    def test_store_dom_data():
        """Test DOM data storage for Indigo"""
        print("Testing DOM data storage...")
        
        test_data = {
            'snapshot': {
                'content': '<html><body>Updated Indigo portal content</body></html>',
                'metadata': {
                    'update_type': 'test',
                    'pnr': test_pnr,
                    'ssr_email': test_ssr_email
                }
            },
            'changes': {
                'changes': [
                    {'type': 'addition', 'path': 'body/div[1]'}
                ],
                'count': 1
            }
        }
        
        print("\n📥 Storing DOM data:")
        print(json.dumps(test_data, indent=2))
        
        result = indigo_db.store_dom_data(test_data, 'indigo_gst_portal')
        assert result == True, "Failed to store DOM data"

    def test_get_notification_emails():
        """Test notification email retrieval"""
        print("Testing notification email retrieval...")
        
        emails = indigo_db.get_notification_emails()
        print("\n📤 Retrieved emails:")
        print(json.dumps(emails, indent=2))
        
        assert isinstance(emails, list), "Invalid email list format"

    def test_scheduler_settings():
        """Test scheduler settings for Indigo"""
        print("Testing scheduler settings...")
        
        # Test update
        new_settings = {
            'auto_run': True,
            'interval': 120,
            'next_run': datetime.now(pytz.UTC) + timedelta(minutes=60)
        }
        
        print("\n📥 Updating scheduler settings:")
        print(json.dumps({
            k: str(v) if isinstance(v, datetime) else v 
            for k, v in new_settings.items()
        }, indent=2))
        
        result = indigo_db.update_scheduler_settings(**new_settings)
        assert result == True, "Failed to update scheduler settings"

    def test_store_invoice_data():
        """Test invoice data storage for Indigo"""
        print("Testing invoice data storage...")
        
        invoice_data = {
            'pnr': test_pnr,
            'invoice_data': {
                'ssr_email': test_ssr_email,
                'invoice_id': 'INV123',
                'timestamp': datetime.now().isoformat()
            },
            'invoice_files': [{
                'name': f'{test_pnr}_INV123_invoice.pdf',
                'path': '/test/path',
                'type': 'pdf',
                'size': 1024
            }]
        }
        
        print("\n📥 Storing invoice data:")
        print(json.dumps(invoice_data, indent=2))
        
        result = indigo_db.store_invoice_data(**invoice_data)
        assert result == True, "Failed to store invoice data"

    def test_performance_stats():
        """Test performance statistics"""
        print("Testing performance statistics...")
        
        stats = indigo_db.get_performance_stats()
        print("\n📤 Retrieved performance stats:")
        print(json.dumps(indigo_db.format_for_json(stats), indent=2))
        
        assert stats is not None, "Failed to get performance stats"
        assert 'total_runs' in stats, "Missing total runs count"

    def test_dom_changes():
        """Test DOM changes retrieval"""
        print("Testing DOM changes retrieval...")
        
        changes = indigo_db.get_dom_changes('indigo_gst_portal', 10)
        print("\n📤 Retrieved DOM changes:")
        print(json.dumps([
            indigo_db.format_for_json(change) for change in changes
        ], indent=2))
        
        assert isinstance(changes, list), "Invalid DOM changes format"

    # Run all tests
    print("\nStarting Indigo DB Tests with Real Firebase...")
    print("=" * 60)
    print("Test PNR:", test_pnr)
    print("Test Email:", test_ssr_email)
    print("=" * 60)
    
    try:
        results = run_tests()
        
        # Print summary
        print("\n" + "="*50)
        print("Test Summary:")
        print(f"Total Tests: {results['passed'] + results['failed']}")
        print(f"✅ Passed: {results['passed']}")
        print(f"❌ Failed: {results['failed']}")
        
        if results['errors']:
            print("\nErrors:")
            for error in results['errors']:
                print(error)
    except Exception as e:
        print(f"\n❌ Test execution failed: {str(e)}")
    finally:
        print("="*50)