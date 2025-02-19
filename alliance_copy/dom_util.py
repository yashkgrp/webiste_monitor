import logging
import difflib
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import sys
import os
import traceback
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class AllianceDOMTracker:
    def __init__(self, db_ops):
        self.db_ops = db_ops
        self.last_snapshots = {}
        
        # Import NotificationHandler with correct path
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            from notification_handler import NotificationHandler
            self.notification_handler = NotificationHandler(db_ops)
        except ImportError as e:
            print(f"Warning: Could not import NotificationHandler: {e}")
            self.notification_handler = None
            
        # Track only essential form and invoice elements
        self.tracked_elements = {
            'content': [
                'div.gstdetail-td',      
                'div.main-content',      
                'table#taxInvoicedetails', 
                'form#gstForm'           
            ],
            'interactive': [
                'input#txtPNR',
                'input#txtDOJ',
                'input#txtVerificationCodeNew',
                'button#btnSearch',
                'a#lnkdownload'
            ]
        }

    def clean_html(self, content):
        """Clean HTML content focusing on form and invoice elements"""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            content_elements = []
            
            # Only keep essential elements
            valid_elements = ['div', 'form', 'input', 'button', 'select', 'table', 'a']
            for elem in soup.find_all(valid_elements):
                # Keep element if it's part of form or invoice 
                if (elem.get('id') in ['gstForm', 'taxInvoicedetails', 'lnkdownload'] or
                    'gstdetail' in str(elem.get('class', [])) or
                    elem.name in ['input', 'button']):
                    content_elements.append(str(elem))
                    
            return '\n'.join(content_elements)
            
        except Exception as e:
            logging.error(f"Error cleaning HTML: {e}")
            return content

    def get_element_path(self, element):
        """Generate unique path for DOM element"""
        try:
            path_parts = []
            current = element
            
            while current and current.name:
                selector = current.name
                
                if current.get('class'):
                    selector += f".{'.'.join(current.get('class'))}"
                    
                if current.get('id'):
                    selector += f"#{current['id']}"
                    
                path_parts.insert(0, selector)
                current = current.parent
                
            return 'body > ' + ' > '.join(path_parts) if path_parts else 'body'
                
        except Exception as e:
            logging.error(f"Error generating element path: {e}")
            return None

    def compare_content(self, old_content, new_content):
        """Compare content focusing on invoice download changes"""
        try:
            if not old_content or not new_content:
                return []

            # Clean and parse content
            old_clean = BeautifulSoup(self.clean_html(old_content), 'html.parser')
            new_clean = BeautifulSoup(self.clean_html(new_content), 'html.parser')

            changes = []
            
            # Track invoice link changes specifically
            def check_invoice_link(soup):
                link = soup.find('a', id='lnkdownload')
                if link:
                    return {
                        'exists': True,
                        'href': link.get('href', ''),
                        'text': link.text.strip()
                    }
                return {'exists': False}
                
            old_invoice = check_invoice_link(old_clean)
            new_invoice = check_invoice_link(new_clean)
            
            if new_invoice['exists'] and not old_invoice['exists']:
                changes.append({
                    'type': 'addition',
                    'element': 'Invoice download link available',
                    'element_type': 'link',
                    'path': 'a#lnkdownload',
                    'description': 'Invoice download link appeared'
                })
                
            elif old_invoice['exists'] and not new_invoice['exists']:
                changes.append({
                    'type': 'removal',
                    'element': 'Invoice download link removed',
                    'element_type': 'link',
                    'path': 'a#lnkdownload',
                    'description': 'Invoice download link disappeared'
                })

            # Compare error messages
            def get_error_message(soup):
                error_elem = soup.find(class_='error-message')
                return error_elem.text.strip() if error_elem else None
                
            old_error = get_error_message(old_clean)
            new_error = get_error_message(new_clean)
            
            if new_error != old_error:
                if new_error:
                    changes.append({
                        'type': 'addition',
                        'element': f'Error message: {new_error}',
                        'element_type': 'error',
                        'path': '.error-message',
                        'description': 'New error message appeared'
                    })

            return changes

        except Exception as e:
            logging.error(f"Error comparing content: {e}")
            return []

    def format_dom_changes_for_notification(self, changes, pnr=None, transaction_date=None):
        """Format changes for notification with Alliance Air specifics"""
        try:
            additions = []
            removals = []

            for change in changes:
                element_details = {
                    'type': change.get('element_type', 'unknown'),
                    'path': change.get('path', 'Unknown path'),
                    'content': change.get('element', ''),
                    'description': change.get('description', 'No description')
                }

                if change.get('type') == 'addition':
                    additions.append(element_details)
                elif change.get('type') == 'removal':
                    removals.append(element_details)

            html_content = f"""
                <h2>Alliance Air - DOM Changes Detected</h2>
                <div style="margin: 10px 0; padding: 10px; background-color: #f8f9fa;">
                    <p><strong>PNR:</strong> {pnr or 'N/A'}</p>
                    <p><strong>Transaction Date:</strong> {transaction_date or 'N/A'}</p>
                    <p><strong>Total Changes:</strong> {len(changes)}</p>
                    <p><strong>Timestamp:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            """

            for section, items, color in [
                ('New Elements', additions, '#28a745'),
                ('Removed Elements', removals, '#dc3545')
            ]:
                if items:
                    html_content += f"""
                        <div style="margin-top: 20px;">
                            <h3 style="color: {color};">{section}</h3>
                            {''.join(f'''
                                <div style="margin: 10px 0; padding: 10px; border-left: 4px solid {color};">
                                    <p><strong>Type:</strong> {item['type']}</p>
                                    <p><strong>Path:</strong> {item['path']}</p>
                                    <p><strong>Description:</strong> {item['description']}</p>
                                    <div style="background: #fff; padding: 10px;">
                                        <pre>{item['content']}</pre>
                                    </div>
                                </div>
                            ''' for item in items)}
                        </div>
                    """

            return {
                'subject': f"Alliance Air DOM Changes - PNR: {pnr or 'N/A'}",
                'html_content': html_content,
                'summary': {
                    'additions': len(additions),
                    'removals': len(removals),
                    'total': len(changes)
                }
            }

        except Exception as e:
            logging.error(f"Error formatting DOM changes: {e}")
            return None

    def track_page_changes(self, page_id, html_content, pnr=None, transaction_date=None):
        """Track page changes and identify invoice availability"""
        try:
            logging.warning("into the main function track_page_changes")
            # Get previous snapshot
            prev_snapshot = self.db_ops.get_dom_snapshot(page_id)
            prev_content = prev_snapshot.get('content') if prev_snapshot else None
            
            logging.info(f"Previous snapshot for {page_id}: {'exists' if prev_content else 'none'}")

            # First run - store snapshot
            if not prev_content:
                metadata = {
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'pnr': pnr,
                    'transaction_date': transaction_date,
                    'has_changes': False,
                    'first_run': True
                }
                
                success = self.db_ops.store_dom_data({
                    'snapshot': {
                        'content': html_content,
                        'metadata': metadata
                    }
                }, page_id)
                
                if not success:
                    logging.error(f"Failed to store initial snapshot for {page_id}")
                return []

            # Compare for changes
            changes = self.compare_content(prev_content, html_content)

            # Send notification if there are changes
            if changes and self.notification_handler:
                notification_data = self.format_dom_changes_for_notification(
                    changes=changes,
                    pnr=pnr,
                    transaction_date=transaction_date
                )
                
                if notification_data:
                    try:
                        self.notification_handler.send_dom_change_notification(
                            changes=changes,
                            gstin=transaction_date,
                            pnr=pnr,
                            airline="Alliance Air",
                            html_content=notification_data['html_content'],
                            subject=notification_data['subject']
                        )
                        logging.info(f"Sent notification for {len(changes)} changes")
                    except Exception as notify_error:
                        logging.error(f"Failed to send notification: {notify_error}")

            # Store new snapshot if there are changes
            if changes:
                metadata = {
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'pnr': pnr,
                    'transaction_date': transaction_date,
                    'has_changes': True
                }

                success = self.db_ops.store_dom_data({
                    'snapshot': {
                        'content': html_content,
                        'metadata': metadata
                    },
                    'changes': {
                        'changes': changes,
                        'metadata': metadata
                    }
                }, page_id)

                if not success:
                    logging.error(f"Failed to store updated snapshot for {page_id}")
                    
                logging.info(f"Stored {len(changes)} changes for {page_id}")

            return changes

        except Exception as e:
            logging.error(f"Error tracking changes: {e}")
            return []

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('dom_tracker_test.log')
        ]
    )
    
    # Initialize Firebase
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        print("\n=== Alliance Air DOM Tracker Test ===")
        
        # Try loading Firebase credentials
        try:
            cred = credentials.Certificate("../firebase-adminsdk.json")
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("✅ Firebase initialized successfully")
            
        except Exception as firebase_error:
            print(f"⚠️ Firebase initialization failed: {firebase_error}")
            print("Running in mock DB mode...")
            
            # Mock DB for testing
            class MockDB:
                def collection(self, _): return self
                def document(self, _): return self
                def set(self, _, merge=False): return True
                def get(self): return None
                def add(self, _): return None
            
            db = MockDB()
        
        # Create db_ops instance - works with both real and mock DB
        from db_util import AllianceFirestoreDB
        db_ops = AllianceFirestoreDB(db)
        
        # Create tracker instance
        tracker = AllianceDOMTracker(db_ops)

        # Test constants for Alliance Air
        TEST_PAGE_ID = 'alliance_gst_portal_test'
        TEST_PNR = 'TEST123'
        TEST_DATE = '2024-02-13'
        
        print("\nTest Configuration:")
        print(f"- Page ID: {TEST_PAGE_ID}")
        print(f"- PNR: {TEST_PNR}")
        print(f"- Date: {TEST_DATE}")
        print("-" * 50)
        
        # Test HTML content 
        form_content = """
        <html><body>
            <form id="gstForm">
                <input type="text" id="txtPNR" name="pnr" value="">
                <input type="text" id="txtDOJ" name="date" value="">
                <input type="text" id="txtVerificationCodeNew" value="">
                <button type="button" id="btnSearch">Search</button>
            </form>
            <div class="error-message" style="display:none"></div>
        </body></html>
        """
        
        form_with_invoice = """
        <html><body>
            <form id="gstForm">
                <input type="text" id="txtPNR" name="pnr" value="TEST123">
                <input type="text" id="txtDOJ" name="date" value="13-02-2024">
                <input type="text" id="txtVerificationCodeNew" value="ABCD12">
                <button type="button" id="btnSearch">Search</button>
            </form>
            <div class="gstdetail-td">
                <table id="taxInvoicedetails">
                    <tr><td>Invoice Details</td></tr>
                </table>
                <a href="#" id="lnkdownload">Download Invoice</a>
                <span id="lbl">TEST123_invoice</span>
            </div>
        </body></html>
        """

        class MockDB:
            def __init__(self):
                self.snapshots = {}
                self.changes = []
                self.current_doc = None

            def collection(self, _): 
                return self

            def document(self, doc_id): 
                self.current_doc = doc_id
                return self

            def set(self, data, merge=False): 
                if self.current_doc:
                    if merge and self.current_doc in self.snapshots:
                        self.snapshots[self.current_doc].update(data)
                    else:
                        self.snapshots[self.current_doc] = data
                return True

            def get(self): 
                class MockDoc:
                    def __init__(self, exists, data=None):
                        self.exists = exists
                        self._data = data
                    def to_dict(self):
                        return self._data or {}
                return MockDoc(exists=self.current_doc in self.snapshots, 
                             data=self.snapshots.get(self.current_doc))

            def add(self, data): 
                self.changes.append(data)
                return None

            def where(self, field, op, value):
                return self

            def stream(self):
                return []

            def delete(self):
                if self.current_doc in self.snapshots:
                    del self.snapshots[self.current_doc]
                return True
        
        def run_dom_test():
            success_count = 0
            total_tests = 0
            
            try:
                print("\n1️⃣ Testing Initial Form Content Storage")
                total_tests += 1
                initial_result = tracker.track_page_changes(
                    page_id=TEST_PAGE_ID,
                    html_content=form_content,
                    pnr=TEST_PNR,
                    transaction_date=TEST_DATE
                )
                print("✅ Initial snapshot stored")
                success_count += 1
                
                print("\n2️⃣ Testing Change Detection (Adding Invoice)")
                total_tests += 1
                changes = tracker.track_page_changes(
                    page_id=TEST_PAGE_ID,
                    html_content=form_with_invoice,
                    pnr=TEST_PNR,
                    transaction_date=TEST_DATE
                )
                
                if changes:
                    print(f"✅ Detected {len(changes)} changes:")
                    for i, change in enumerate(changes, 1):
                        print(f"\nChange {i}:")
                        print(f"  Type: {change.get('type')}")
                        print(f"  Path: {change.get('path')}")
                        print(f"  Description: {change.get('description')}")
                    success_count += 1
                else:
                    print("⚠️ No changes detected")
                
                return success_count, total_tests
                
            except Exception as e:
                print(f"\n❌ Test Error: {str(e)}")
                traceback.print_exc()
                return success_count, total_tests
            
        def cleanup_test_data():
            """Clean up test data after running tests"""
            try:
                if isinstance(db, MockDB):
                    print("\n✅ Mock mode - no cleanup needed")
                    return
                    
                # Delete test snapshot
                db_ops.dom_snapshots_ref.document(TEST_PAGE_ID).delete()
                
                # Delete related test changes
                test_changes = db_ops.dom_changes_ref.where('page_id', '==', TEST_PAGE_ID).stream()
                for doc in test_changes:
                    doc.reference.delete()
                    
                print("\n✅ Test data cleaned up successfully")
            except Exception as e:
                print(f"\n⚠️ Cleanup warning: {e}")
        
        # Run tests and print results
        success_count, total_tests = run_dom_test()
        
        print("\n=== Test Summary ===")
        print(f"Total Tests: {total_tests}")
        print(f"Successful: {success_count}")
        print(f"Failed: {total_tests - success_count}")
        
        # Cleanup
        if input("\nClean up test data? (y/n): ").lower() == 'y':
            cleanup_test_data()
            
    except Exception as e:
        print(f"\n❌ Setup Error: {e}")
        traceback.print_exc()