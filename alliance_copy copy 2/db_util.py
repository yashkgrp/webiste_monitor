from datetime import datetime, timedelta
import logging
import pytz
from google.cloud.firestore import Query, ArrayUnion

logger = logging.getLogger(__name__)

class AllianceFirestoreDB:
    def __init__(self, db):
        self.db = db
        self.urls_ref = self.db.collection('monitored_urls')
        self.alliance_ref = self.urls_ref.document('alliance_air')
        
        # Initialize collections
        self.scraper_state_ref = self.alliance_ref.collection('scraper_states')
        self.scraper_history_ref = self.alliance_ref.collection('scraper_history')
        self.error_ref = self.alliance_ref.collection('errors')
        self.invoice_ref = self.alliance_ref.collection('invoices')
        
        # Initialize DOM collections
        self.dom_snapshots_ref = self.alliance_ref.collection('dom_snapshots')
        self.dom_changes_ref = self.alliance_ref.collection('dom_changes')
        
        # Settings collection
        self.settings_ref = self.alliance_ref.collection('settings')
        self.scheduler_settings_ref = self.settings_ref.document('scheduler')
        
        self._init_default_settings()

    def _init_default_settings(self):
        """Initialize default settings"""
        try:
            default_settings = {
                'auto_run': False,
                'interval': 60,
                'next_run': None,
                'created_at': datetime.now(pytz.UTC),
                'updated_at': datetime.now(pytz.UTC)
            }
            
            doc = self.scheduler_settings_ref.get()
            if not doc.exists:
                self.scheduler_settings_ref.set(default_settings)
                
        except Exception as e:
            logger.error(f"Error initializing settings: {e}")

    def store_scraper_state(self, pnr, state='pending', message=None, data=None, 
                           next_run=None, transaction_date=None, 
                           preserve_last_run=False, vendor="ALLIANCE AIR"):
        """Store scraper state for Alliance Air"""
        try:
            doc_id = pnr
            current_time = datetime.now(pytz.UTC)
            
            existing_state = None
            if preserve_last_run:
                existing_state = self.scraper_state_ref.document(doc_id).get()
            
            state_data = {
                'pnr': pnr,
                'state': state,
                'message': message,
                'updated_at': current_time,
                'vendor': vendor,
                'airline': 'alliance_air'
            }

            # Use existing transaction date if not provided and exists in current state
            if transaction_date:
                state_data['transaction_date'] = transaction_date
            elif existing_state and existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'transaction_date' in existing_data:
                    state_data['transaction_date'] = existing_data['transaction_date']
            
            if data:
                state_data['data'] = data
                
            if preserve_last_run and existing_state and existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'last_run' in existing_data:
                    state_data['last_run'] = existing_data['last_run']
            else:
                state_data['last_run'] = current_time
                
            if next_run:
                state_data['next_run'] = next_run
                
            if state == 'failed':
                state_data['last_error'] = {
                    'message': message,
                    'timestamp': current_time
                }
                
            self.scraper_state_ref.document(doc_id).set(state_data, merge=True)
            
            # Store in history
            history_data = {
                'timestamp': current_time,
                'pnr': pnr,
                'state': state,
                'message': message,
                'transaction_date': transaction_date,
                'vendor': vendor,
                'data': data
            }
            
            self.scraper_history_ref.add(history_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing state: {e}")
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
        """
        Log error with context
        Args:
            error_type (str): Type of error
            message (str): Error message
            context (dict, optional): Additional context data. Defaults to None.
        Returns: bool
        """
        try:
            error_doc = {
                'timestamp': datetime.now(pytz.UTC),
                'error_type': error_type,
                'message': message,
                'context': context or {},
                'airline': 'alliance_air'
            }
            
            self.error_ref.add(error_doc)
            
            # Update scraper state if PNR provided in context
            if context and 'pnr' in context:
                self.store_scraper_state(
                    pnr=context['pnr'],
                    state='failed',
                    message=message,
                    transaction_date=context.get('transaction_date'),
                    data={'error': message}
                )
                
            return True
                
        except Exception as e:
            logger.error(f"Error logging error: {e}")
            return False

    def store_dom_snapshot(self, page_id, content, metadata=None):
        """Store DOM snapshot"""
        try:
            doc_data = {
                'content': content,
                'timestamp': datetime.now(pytz.UTC),
                'page_id': page_id,
                'metadata': metadata or {}
            }
            
            self.dom_snapshots_ref.document(page_id).set(doc_data)
            return True
            
        except Exception as e:
            logger.error(f"Error storing DOM snapshot: {e}")
            return False

    def store_dom_data(self, data, page_id):
        """
        Store DOM changes and snapshots
        Returns: bool
        """
        try:
            current_time = datetime.now(pytz.UTC)
            
            # Store snapshot if provided
            if data.get('snapshot'):
                snapshot_data = data['snapshot']
                snapshot_data['timestamp'] = current_time
                snapshot_data['page_id'] = page_id
                snapshot_data['airline'] = 'alliance_air'  # Add airline identifier
                self.dom_snapshots_ref.document(page_id).set(snapshot_data)
            
            # Store changes if provided
            if data.get('changes'):
                changes_data = data['changes']
                changes_data['timestamp'] = current_time
                changes_data['page_id'] = page_id
                changes_data['airline'] = 'alliance_air'
                self.dom_changes_ref.add(changes_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error storing DOM data: {e}")
            return False

    def get_notification_emails(self):
        """Get notification email list"""
        try:
            doc = self.db.collection('monitor_mails').document('email').get()
            if doc.exists:
                return doc.to_dict().get('emails', [])
            return []
        except Exception as e:
            logger.error(f"Error getting notification emails: {e}")
            return []

    def get_scheduler_settings(self):
        """Get scheduler settings"""
        try:
            doc = self.scheduler_settings_ref.get()
            if doc.exists:
                return doc.to_dict()
            return {
                'auto_run': False,
                'interval': 60,
                'next_run': None
            }
        except Exception as e:
            logger.error(f"Error getting scheduler settings: {e}")
            return {
                'auto_run': False,
                'interval': 60,
                'next_run': None
            }

    def update_scheduler_settings(self, auto_run, interval, next_run=None):
        """Update scheduler settings"""
        try:
            settings = {
                'auto_run': auto_run,
                'interval': interval,
                'updated_at': datetime.now(pytz.UTC)
            }
            if next_run:
                settings['next_run'] = next_run
                
            self.scheduler_settings_ref.set(settings, merge=True)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating scheduler settings: {e}")
            return False

    def store_invoice_data(self, pnr, invoice_data, invoice_files=None):
        """Store downloaded invoice data"""
        try:
            current_time = datetime.now(pytz.UTC)
            doc_data = {
                'pnr': pnr,
                'invoice_data': invoice_data,
                'timestamp': current_time,
                'status': 'processed'
            }
            
            if invoice_files:
                doc_data['files'] = invoice_files
                
            self.invoice_ref.add(doc_data)
            return True
            
        except Exception as e:
            logger.error(f"Error storing invoice: {e}")
            return False

    def get_state(self, pnr):
        """Get current scraper state"""
        try:
            doc = self.scraper_state_ref.document(pnr).get()
            if doc.exists:
                return doc.to_dict()
            return {
                'state': 'not_started',
                'message': None,
                'pnr': pnr
            }
        except Exception as e:
            logger.error(f"Error getting state: {e}")
            return None

    def update_state(self, pnr, state_data):
        """Update scraper state"""
        try:
            state_data['updated_at'] = datetime.now(pytz.UTC)
            self.scraper_state_ref.document(pnr).set(state_data, merge=True)
            return True
        except Exception as e:
            logger.error(f"Error updating state: {e}")
            return False

    def get_performance_stats(self):
        """Get performance statistics"""
        try:
            docs = self.scraper_history_ref.order_by(
                'timestamp', direction=Query.DESCENDING
            ).limit(100).stream()
            
            stats = {
                'total_runs': 0,
                'successful': 0,
                'failed': 0,
                'avg_time': 0,
                'error_types': {}
            }
            
            total_time = 0
            
            for doc in docs:
                data = doc.to_dict()
                stats['total_runs'] += 1
                
                if data.get('state') == 'completed':
                    stats['successful'] += 1
                    if 'processing_time' in data:
                        total_time += data['processing_time']
                else:
                    stats['failed'] += 1
                    error_type = data.get('error', {}).get('type', 'unknown')
                    stats['error_types'][error_type] = stats['error_types'].get(error_type, 0) + 1
                    
            if stats['successful'] > 0:
                stats['avg_time'] = total_time / stats['successful']
                
            return stats
            
        except Exception as e:
            logger.error(f"Error getting performance stats: {e}")
            return None

    def get_last_scraper_state(self):
        """Get most recent scraper state"""
        try:
            docs = self.scraper_state_ref.order_by(
                'updated_at', direction=Query.DESCENDING
            ).limit(1).stream()
            # Get scheduler settings
            scheduler_settings = self.get_scheduler_settings()

            # Add next_run and auto_run to the returned state for first doc
            state_dict = {}
            for doc in docs:
                state_dict = doc.to_dict()
                state_dict['next_run'] = scheduler_settings.get('next_run')
                state_dict['auto_run'] = scheduler_settings.get('auto_run')
                return state_dict
            return None
            for doc in docs:
                return doc.to_dict()
            return None
        
            
        except Exception as e:
            logger.error(f"Error getting last state: {e}")
            return None

    def get_dom_changes(self, page_id=None, limit=100):
        """Get recent DOM changes for Alliance Air"""
        try:
            query = self.dom_changes_ref.order_by('timestamp', direction=Query.DESCENDING)
            
            if page_id:
                query = query.where('page_id', '==', page_id)
            
            # Add airline filter
            query = query.where('airline', '==', 'alliance_air')
            
            docs = query.limit(limit).stream()
            print(docs)

            changes = []
            
            for doc in docs:
                data = doc.to_dict()
                print(data)
                # Format timestamps and other non-JSON serializable data
                changes.append(self.format_for_json(data))
                
            return changes
            
        except Exception as e:
            if "The query requires an index" in str(e):
                logger.error(e)
            else:
                logger.error(f"Error getting DOM changes: {e}")
            return []

    def mark_captcha(self, captcha_id, success):
        """Store CAPTCHA result"""
        try:
            doc_data = {
                'captcha_id': captcha_id,
                'success': success,
                'timestamp': datetime.now(pytz.UTC)
            }
            
            self.alliance_ref.collection('captcha_results').add(doc_data)
            return True
            
        except Exception as e:
            logger.error(f"Error marking CAPTCHA: {e}")
            return False

    def get_dom_snapshot(self, page_id):
        """Get the most recent DOM snapshot for a page"""
        try:
            doc = self.dom_snapshots_ref.document(page_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting DOM snapshot: {e}")
            return None

    def update_scraper_progress(self, pnr, stage, step, status, message, data=None):
        """
        Update scraper progress state
        Returns: bool
        """
        try:
            current_time = datetime.now(pytz.UTC)
            doc_data = {
                'pnr': pnr,
                'stage': stage,
                'step': step,
                'status': status,
                'message': message,
                'timestamp': current_time,
                'airline': 'alliance_air'
            }
            
            if data:
                doc_data['data'] = data
                
            self.scraper_state_ref.document(pnr).set(doc_data, merge=True)
            return True
            
        except Exception as e:
            logger.error(f"Error updating progress: {e}")
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
    
    print("\n=== Alliance DB Tests ===")
    
    # Try real Firebase first, fallback to mock
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate("../firebase-adminsdk.json")
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Using real Firebase instance")
    except Exception as e:
        print(f"⚠️ Firebase initialization failed: {e}")
        print("↪️ Using mock DB for testing")
        db = MockFirestoreDB()

    alliance_db = AllianceFirestoreDB(db)
    test_pnr = "TEST123"
    
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
            test_dom_changes,
            test_captcha_handling
        ]
        
        results = {
            'passed': 0,
            'failed': 0,
            'errors': []
        }
        
        print("\n🚀 Starting Alliance DB Tests")
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
            print("-" * 40)
        
        return results

    def test_store_scraper_state():
        """Test scraper state storage"""
        print("Testing scraper state storage...")
        
        # Test data
        initial_state = {
            'pnr': test_pnr,
            'state': "testing",
            'message': "Test state",
            'transaction_date': "2024-02-13"
        }
        
        print("\n📥 Storing initial state:")
        print(json.dumps(initial_state, indent=2))
        
        # Test basic state storage
        result = alliance_db.store_scraper_state(**initial_state)
        assert result == True, "Failed to store scraper state"
        
        # Verify stored state
        stored_state = alliance_db.get_state(test_pnr)
        print("\n📤 Retrieved state:")
        formatted_state = alliance_db.format_for_json(stored_state)
        print(json.dumps(formatted_state, indent=2))
        
        # Test state update with preservation
        updated_state = {
            'pnr': test_pnr,
            'state': "updated",
            'message': "Updated state",
            'preserve_last_run': True
        }
        
        print("\n📥 Updating state with preservation:")
        print(json.dumps(updated_state, indent=2))
        
        result = alliance_db.store_scraper_state(**updated_state)
        assert result == True, "Failed to preserve last run time"
        
        # Verify updated state
        final_state = alliance_db.get_state(test_pnr)
        print("\n📤 Final state:")
        formatted_final = alliance_db.format_for_json(final_state)
        print(json.dumps(formatted_final, indent=2))
        
        assert final_state['state'] == "updated", "State not updated correctly"

    def test_get_state():
        """Test state retrieval"""
        print("Testing state retrieval...")
        
        state = alliance_db.get_state(test_pnr)
        print("\n📤 Retrieved state:")
        formatted_state = alliance_db.format_for_json(state)
        print(json.dumps(formatted_state, indent=2))
        
        assert state is not None, "Failed to get state"
        assert 'state' in state, "State missing required field"
        assert 'pnr' in state, "PNR missing in state"

    def test_log_error():
        """Test error logging"""
        print("Testing error logging...")
        
        context = {
            'pnr': test_pnr,
            'transaction_date': '2024-02-13',
            'stage': 'testing'
        }
        
        error_data = {
            'error_type': 'TEST_ERROR',  # Changed from 'type' to 'error_type'
            'message': 'Test error message',
            'context': context
        }
        
        print("\n📥 Logging error:")
        print(json.dumps(error_data, indent=2))
        
        alliance_db.log_error(**error_data)
        
        # Verify error affected state
        error_state = alliance_db.get_state(test_pnr)
        print("\n📤 State after error:")
        formatted_state = alliance_db.format_for_json(error_state)
        print(json.dumps(formatted_state, indent=2))
        
        assert error_state['state'] == 'failed', "Error state not updated"

    def test_store_dom_snapshot():
        """Test DOM snapshot storage"""
        print("Testing DOM snapshot storage...")
        
        test_data = {
            'page_id': 'test_page',
            'content': '<html><body>Test content</body></html>',
            'metadata': {
                'test_meta': 'test_value',
                'timestamp': datetime.now(pytz.UTC).isoformat()
            }
        }
        
        print("\n📥 Storing DOM snapshot:")
        print(json.dumps(test_data, indent=2))
        
        result = alliance_db.store_dom_snapshot(**test_data)
        assert result == True, "Failed to store DOM snapshot"
        
        # Verify stored snapshot
        stored = alliance_db.dom_snapshots_ref.document(test_data['page_id']).get()
        stored_data = stored.to_dict()
        print("\n📤 Retrieved snapshot:")
        print(json.dumps({
            k: str(v) if isinstance(v, datetime) else v 
            for k, v in stored_data.items()
        }, indent=2))

    def test_store_dom_data():
        """Test DOM data storage"""
        print("Testing DOM data storage...")
        
        test_data = {
            'snapshot': {
                'content': '<html><body>Updated content</body></html>',
                'metadata': {'update_type': 'test'}
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
        
        result = alliance_db.store_dom_data(test_data, 'test_page')
        assert result == True, "Failed to store DOM data"
        
        # Verify stored changes
        changes = alliance_db.get_dom_changes('test_page', 1)
        print("\n📤 Retrieved changes:")
        print(json.dumps([
            {k: str(v) if isinstance(v, datetime) else v for k, v in change.items()}
            for change in changes
        ], indent=2))

    def test_get_notification_emails():
        """Test notification email retrieval"""
        print("Testing notification email retrieval...")
        
        emails = alliance_db.get_notification_emails()
        print("\n📤 Retrieved emails:")
        print(json.dumps(emails, indent=2))
        
        assert isinstance(emails, list), "Invalid email list format"

    def test_scheduler_settings():
        """Test scheduler settings operations"""
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
        
        result = alliance_db.update_scheduler_settings(**new_settings)
        assert result == True, "Failed to update scheduler settings"
        
        # Test retrieval
        settings = alliance_db.get_scheduler_settings()
        print("\n📤 Retrieved settings:")
        print(json.dumps({
            k: str(v) if isinstance(v, datetime) else v 
            for k, v in settings.items()
        }, indent=2))
        
        assert settings['auto_run'] == True, "Scheduler settings not updated correctly"
        assert settings['interval'] == 120, "Interval not updated correctly"

    def test_store_invoice_data():
        """Test invoice data storage"""
        print("Testing invoice data storage...")
        
        invoice_data = {
            'pnr': test_pnr,
            'invoice_data': {
                'amount': 1000,
                'currency': 'INR',
                'date': '2024-02-13'
            },
            'invoice_files': [{
                'name': 'test_invoice.pdf',
                'path': '/test/path',
                'type': 'pdf',
                'size': 1024
            }]
        }
        
        print("\n📥 Storing invoice data:")
        print(json.dumps(invoice_data, indent=2))
        
        result = alliance_db.store_invoice_data(**invoice_data)
        assert result == True, "Failed to store invoice data"

    def test_performance_stats():
        """Test performance statistics"""
        print("Testing performance statistics...")
        
        stats = alliance_db.get_performance_stats()
        print("\n📤 Retrieved performance stats:")
        print(json.dumps(stats, indent=2))
        
        assert stats is not None, "Failed to get performance stats"
        assert 'total_runs' in stats, "Missing total runs count"

    def test_dom_changes():
        """Test DOM changes retrieval"""
        print("Testing DOM changes retrieval...")
        
        changes = alliance_db.get_dom_changes(limit=10)
        print("\n📤 Retrieved DOM changes:")
        print(json.dumps([
            {k: str(v) if isinstance(v, datetime) else v for k, v in change.items()}
            for change in changes
        ], indent=2))
        
        assert isinstance(changes, list), "Invalid DOM changes format"

    def test_captcha_handling():
        """Test CAPTCHA result storage"""
        print("Testing CAPTCHA handling...")
        
        captcha_data = {
            'captcha_id': 'test_captcha_123',
            'success': True
        }
        
        print("\n📥 Storing CAPTCHA result:")
        print(json.dumps(captcha_data, indent=2))
        
        result = alliance_db.mark_captcha(**captcha_data)
        assert result == True, "Failed to mark CAPTCHA result"

    # Run all tests
    print("\nStarting Alliance DB Tests...")
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
    print("="*50)