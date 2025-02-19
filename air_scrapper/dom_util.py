import difflib
import logging
from bs4 import BeautifulSoup
from datetime import datetime


class AirIndiaDOMTracker:
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
        
        # More aggressive ignored patterns
        self.ignored_patterns = {
            'id_patterns': [
                'bat',      # Batch tracking
                'beacon',   # Beacons
                'gtm',     # Google Tag Manager
                'ga-',     # Google Analytics
                'recaptcha',
                'smartech',
                'boomr',
                'hansel',
                'clarity',
                'analytics',
                'tracking',
                'random',
                'uuid',
                '_dc_',
                'tagging',
                'activity',
                # Add more patterns for dynamic IDs
                r'.*\d{5,}.*',  # Any ID with 5+ digits
                r'.*[a-f0-9]{8}.*',  # Hex-like IDs
                r'bat.*',  # Anything starting with bat
                r'.*beacon.*',  # Anything containing beacon
            ],
            'class_patterns': [
                'grecaptcha',
                'dynamic',
                'tracking',
                'analytics',
                'beacon',
                'temporary',
                'generated',
                'timestamp',
                'test-',  # Test elements
                'yash',   # Your test class
                'debug'
            ],
            'tag_blacklist': {
                'script', 'noscript', 'style', 'link', 'meta', 'iframe',
                'img[src*="tracking"]', 'img[src*="beacon"]', 'img[src*="analytics"]'
            },
            'attribute_blacklist': {
                'data-timestamp', 'data-random', 'data-uuid', 'data-gtm',
                'onclick', 'onload', 'onerror', 'data-analytics', 'data-tracking',
                'style', 'src', 'href', 'integrity', 'crossorigin'
            },
            # Add patterns for dynamic values
            'value_patterns': [
                r'\d{13,}',  # Long numbers (timestamps)
                r'[a-f0-9]{32}',  # MD5/UUID-like strings
                r'\d+\.\d+\.\d+\.\d+',  # IP addresses
                r'(?:[a-zA-Z0-9+/]{4}){2,}(?:[a-zA-Z0-9+/]{2}==|[a-zA-Z0-9+/]{3}=)?'  # Base64
            ]
        }

        # Add more specific beacon patterns
        self.beacon_patterns = {
            'id': [
                r'batBeacon\d+',  # Match any batBeacon followed by numbers
                r'bat.*\d+',      # Any bat-prefixed ID with numbers
                r'beacon\d+',     # Any beacon with numbers
                r'analytics\d+',   # Analytics IDs
                r'\d{8,}',        # Any 8+ digit number
            ],
            'attributes': [
                'msclkid',
                'uach',
                'evt',
                'rn',
                'cdb'
            ]
        }

        # Only track meaningful UI elements
        self.tracked_elements = {
            'content': [
                'div.gstdetail-td',  # GST invoice rows
                'div.invoice-list',  # Invoice list container
                'div.main-content',  # Main content area
                'table.invoice-table', # Invoice table
                'form.search-form'  # Search form
            ],
            'interactive': [
                'button.search-button', 
                'input#pnr',
                'input#Origin',
                'select.dropdown'
            ]
        }

    def clean_html(self, content):
        """Enhanced HTML cleaning with stricter filtering"""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # 1. First aggressive pass - remove all batBeacon elements
            for element in soup.find_all('div'):
                if element.get('id', '').lower().startswith('batbeacon'):
                    element.decompose()
                    continue
                # Also check style for hidden elements
                if element.get('style'):
                    style = element.get('style').lower()
                    if ('display: none' in style or 
                        'visibility: hidden' in style or 
                        'width: 0px' in style or 
                        'height: 0px' in style):
                        element.decompose()
                        continue

            # 2. Second pass - remove all tracking elements
            for element in soup.find_all():
                should_remove = False
                
                # Check ID for any tracking patterns
                element_id = element.get('id', '').lower()
                if (any(pattern in element_id for pattern in ['bat', 'beacon', 'tracking', 'analytics']) or
                    any(char.isdigit() for char in element_id)):
                    should_remove = True

                # Check class for tracking indicators
                element_classes = ' '.join(element.get('class', [])).lower()
                if any(word in element_classes for word in ['tracking', 'beacon', 'analytics', 'hidden']):
                    should_remove = True

                # Check for hidden elements
                if element.name in ['div', 'img', 'span']:
                    if element.get('style'):
                        style = element.get('style').lower()
                        if any(pattern in style for pattern in [
                            'display: none', 'visibility: hidden',
                            'width: 0', 'height: 0'
                        ]):
                            should_remove = True

                if should_remove:
                    element.decompose()
                    continue

            # 3. Final pass - only keep meaningful elements
            content_elements = []
            valid_elements = ['div', 'form', 'input', 'button', 'select', 'table']
            
            for elem in soup.find_all(valid_elements):
                # Skip if element has any tracking-related attributes
                if (not any('bat' in str(attr).lower() for attr in elem.attrs.values()) and
                    not any('beacon' in str(attr).lower() for attr in elem.attrs.values()) and
                    (elem.text.strip() or elem.name == 'input' or elem.get('type') == 'submit')):
                    content_elements.append(str(elem))

            return '\n'.join(content_elements)

        except Exception as e:
            logging.error(f"Error cleaning HTML: {e}")
            return content

    def get_element_path(self, element):
        """Generate unique path for DOM element like Star Air format"""
        try:
            path_parts = []
            current = element
            
            while current and current.name:
                # Build selector for current element with simplified format
                selector = current.name
                
                # Add classes (if any)
                if current.get('class'):
                    selector += f".{'.'.join(current.get('class'))}"
                
                # Add id (if any)  
                if current.get('id'):
                    selector += f"#{current['id']}"
                    
                path_parts.insert(0, selector)
                current = current.parent
                
            # Only prefix with 'body >' if we have path parts
            return 'body > ' + ' > '.join(path_parts) if path_parts else 'body'
                
        except Exception as e:
            logger.error(f"Error generating element path: {e}")
            return None

    def compare_content(self, old_content, new_content):
        """Compare content with proper test div handling"""
        try:
            if not old_content or not new_content:
                return []

            # Clean content first
            old_clean = BeautifulSoup(self.clean_html(old_content), 'html.parser')
            new_clean = BeautifulSoup(self.clean_html(new_content), 'html.parser')

            # Add test div to old content before comparison
            body_tag = old_clean.find('body')
            if (body_tag):
                test_div = old_clean.new_tag('div')
                # Use a regular, non-tracking like ID/class
                test_div['id'] = 'content-test-div'  
                test_div['class'] = 'content-monitor'
                test_div.string = "Content monitoring test element"
                body_tag.append(test_div)
                logging.info(f"Added test div: {str(test_div)}")

            changes = []

            # Compare DOM trees
            def get_meaningful_elements(soup):
                elements = {}
                for elem in soup.find_all(['div', 'form', 'input', 'button', 'select', 'table']):
                    # Don't have any special handling for test div
                    # Let it be processed like any other element
                    key = f"{elem.name}_{elem.get('id', '')}_{' '.join(elem.get('class', []))}"
                    elements[key] = elem
                return elements

            old_elements = get_meaningful_elements(old_clean)
            new_elements = get_meaningful_elements(new_clean)

            # Find added elements
            for key, elem in new_elements.items():
                element_id = elem.get('id', '').lower()
                if element_id.startswith('batbeacon'):
                    continue
                if key not in old_elements:
                    path = self.get_element_path(elem)
                    changes.append({
                        'type': 'addition',
                        'element': str(elem),
                        'element_type': elem.name,
                        'path': path,
                        'description': f'New element added at {path}'
                    })

            # Find removed elements (including test div)
            for key, elem in old_elements.items():
                if key not in new_elements:
                    path = self.get_element_path(elem)
                    element_id = elem.get('id', '').lower()
                    if element_id.startswith('batbeacon'):
                        continue
                    # Explicitly log test div removal
                    if elem.get('id') == 'test-monitor-div':
                        logging.info("Test div removal detected")
                        
                    changes.append({
                        'type': 'removal',
                        'element': str(elem),
                        'element_type': elem.name,
                        'path': path,
                        'description': f'Element removed from {path}'
                    })

            # Add explicit test div verification
            found_test_removal = any(
                change['type'] == 'removal' and 
                'content-test-div' in change.get('element', '')
                for change in changes
            )

            if not found_test_removal:
                logging.warning("Test div removal was not detected - filtering may be too aggressive")
            else:
                logging.info("Test div removal successfully detected - filtering is working correctly")

            return changes

        except Exception as e:
            logging.error(f"Error comparing content: {e}", exc_info=True)
            return []

    def store_snapshot(self, page_id, html_content, metadata=None):
        """Store a new DOM snapshot"""
        try:
            snapshot_data = {
                'page_id': page_id,
                'content': html_content,
                'timestamp': datetime.now().isoformat(),
                'metadata': metadata or {}
            }
            self.db_ops.store_dom_snapshot(page_id, snapshot_data)
            return True
        except Exception as e:
            logging.error(f"Error storing snapshot: {e}")
            return False

    def format_dom_changes_for_notification(self, changes, pnr=None, origin=None):
        """Format DOM changes specifically for Air India notifications"""
        try:
            # Group changes by type
            additions = []
            removals = []
            test_changes = []

            for change in changes:
                change_type = change.get('type')
                element = change.get('element', '')
                path = change.get('path', 'Unknown path')
                
                # Format element details
                element_details = {
                    'type': change.get('element_type', 'unknown'),
                    'path': path,
                    'content': element,  # Include full element content
                    'description': change.get('description', 'No description')
                }

                # Categorize changes
                if 'test' in path.lower() or 'content-test-div' in element.lower():
                    test_changes.append(element_details)
                elif change_type == 'addition':
                    additions.append(element_details)
                elif change_type == 'removal':
                    removals.append(element_details)

            # Format HTML content with detailed element info
            html_content = f"""
                <h2>Air India Express - DOM Changes Detected</h2>
                <div style="margin: 10px 0; padding: 10px; background-color: #f8f9fa; border-radius: 5px;">
                    <p><strong>PNR:</strong> {pnr or 'N/A'}</p>
                    <p><strong>Origin:</strong> {origin or 'N/A'}</p>
                    <p><strong>Total Changes:</strong> {len(changes)}</p>
                    <p><strong>Timestamp:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            """

            # Add sections for each change type with full details
            for section, items, color in [
                ('New Elements Added', additions, '#28a745'),
                ('Elements Removed', removals, '#dc3545'),
                ('Test Element Changes', test_changes, '#007bff')
            ]:
                if items:
                    html_content += f"""
                        <div style="margin-top: 20px;">
                            <h3 style="color: {color};">{'🟢' if color == '#28a745' else '🔴' if color == '#dc3545' else '🔵'} {section}</h3>
                    """
                    for item in items:
                        html_content += f"""
                            <div style="margin: 10px 0; padding: 10px; border-left: 4px solid {color}; background-color: #f8f9fa;">
                                <p><strong>Element Type:</strong> {item['type']}</p>
                                <p><strong>Path:</strong> {item['path']}</p>
                                <p><strong>Description:</strong> {item['description']}</p>
                                <div style="background: #fff; padding: 10px; border-radius: 4px; margin-top: 5px;">
                                    <strong>Element Content:</strong>
                                    <pre style="white-space: pre-wrap; word-wrap: break-word;">{item['content']}</pre>
                                </div>
                            </div>
                        """
                    html_content += "</div>"

            # Add monitoring status
            # html_content += f"""
            #     <div style="margin-top: 20px; padding: 10px; background-color: #e9ecef; border-radius: 5px;">
            #         <h4>Monitoring Status:</h4>
            #         <p>✓ Test Element Detection: {'Working' if test_changes else 'Warning: No test element detected'}</p>
            #         <p>✓ Change Detection: {'Active' if changes else 'No changes detected'}</p>
            #     </div>
            # """

            return {
                'subject': f"Air India Express DOM Changes - PNR: {pnr or 'N/A'}",
                'html_content': html_content,
                'summary': {
                    'additions': len(additions),
                    'removals': len(removals),
                    'test_changes': len(test_changes),
                    'total': len(changes)
                }
            }

        except Exception as e:
            logging.error(f"Error formatting DOM changes: {e}")
            return None

    def track_page_changes(self, page_id, html_content, pnr=None, origin=None, skip_snapshot=False):
        """Track changes with improved dynamic content handling and notifications"""
        try:
            # Get previous snapshot from DB with logging
            prev_snapshot = self.db_ops.get_dom_snapshot(page_id)
            prev_content = prev_snapshot.get('content') if prev_snapshot else None
            
            logging.info(f"Previous snapshot for {page_id}: {'exists' if prev_content else 'none'}")

            # First run or no previous data - store snapshot and skip comparison
            if not prev_content:
                if not skip_snapshot:
                    metadata = {
                        'page_id': page_id,
                        'timestamp': datetime.now().isoformat(),
                        'pnr': pnr,
                        'origin': origin,
                        'has_changes': False,
                        'first_run': True,
                        'content_hash': hash(self.clean_html(html_content))  # Add content hash
                    }
                    
                    # Store initial snapshot and verify
                    success = self.db_ops.store_dom_data({
                        'snapshot': {
                            'content': html_content,
                            'metadata': metadata
                        }
                    }, page_id)
                    
                    if not success:
                        logging.error(f"Failed to store initial snapshot for {page_id}")
                    else:
                        logging.info(f"Stored initial snapshot for {page_id}")
                return []

            # Compare contents with hash verification
            if hash(self.clean_html(prev_content)) == hash(self.clean_html(html_content)):
                logging.info(f"No content changes for {page_id} (hash match)")
                return []

            # Compare content and get changes
            changes = self.compare_content(prev_content, html_content)
            print(f"changes here{changes}")

            # If changes detected, format and send notification
            if changes and self.notification_handler:
                notification_data = self.format_dom_changes_for_notification(
                    changes=changes,
                    pnr=pnr,
                    origin=origin
                )
                
                if notification_data:
                    try:
                        self.notification_handler.send_dom_change_notification(
                            changes=changes,
                            gstin=origin,
                            pnr=pnr,
                            airline="Air India Express",
                            html_content=notification_data['html_content'],  # Pass formatted HTML
                            subject=notification_data['subject']  # Pass custom subject
                        )
                        logging.info(f"Sent notification for {notification_data['summary']['total']} changes")
                    except Exception as notify_error:
                        logging.error(f"Failed to send notification: {notify_error}")

            # Only store if there are actual changes and not skipping
            if changes and not skip_snapshot:
                metadata = {
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'pnr': pnr,
                    'origin': origin,
                    'has_changes': True,
                    'content_hash': hash(self.clean_html(html_content))  # Add content hash
                }

                # Store new snapshot and verify it was saved
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
                    return []  # Return empty if storage failed
                
                # Verify snapshot was updated
                new_snapshot = self.db_ops.get_dom_snapshot(page_id)
                if not new_snapshot or hash(self.clean_html(new_snapshot.get('content', ''))) != hash(self.clean_html(html_content)):
                    logging.error(f"Snapshot verification failed for {page_id}")
                    return []
                    
                logging.info(f"Stored and verified {len(changes)} changes for {page_id}")
            

            return changes if changes else []

        except Exception as e:
            logging.error(f"Error tracking changes: {e}", exc_info=True)
            return []

    def _extract_attributes(self, element_str):
        """Extract all attributes from an element string"""
        try:
            soup = BeautifulSoup(element_str, 'html.parser')
            element = soup.find()
            if not element:
                return {}
            
            return {
                'tag': element.name,
                'id': element.get('id', ''),
                'class': ' '.join(element.get('class', [])),
                'attributes': {
                    k: v for k, v in element.attrs.items()
                    if k not in ['id', 'class']
                }
            }
        except:
            return {}

    def get_recent_changes(self, limit=1000):
        """Get recent DOM changes"""
        try:
            changes = self.db_ops.get_dom_changes(limit)
            if changes:
                formatted_changes = []
                for change in changes:
                    formatted_changes.append({
                        'page_id': change.get('page_id', 'unknown'),
                        'timestamp': change.get('timestamp'),
                        'type': change.get('type', 'unknown'),
                        'changes': change.get('changes', []),
                        'pnr': change.get('pnr'),
                        'origin': change.get('origin')
                    })
                return formatted_changes
            return []
        except Exception as e:
            logging.error(f"Error getting DOM changes: {e}")
            return []

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Initialize Firebase
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        # Use your service account key
        cred = credentials.Certificate("../firebase-adminsdk.json")
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        
        # Create db_ops instance
        from db_ops import AirIndiaFirestoreDB
        db_ops = AirIndiaFirestoreDB(db)
        
        # Create tracker instance
        tracker = AirIndiaDOMTracker(db_ops)
        
        # Test HTML content
        original_content = """
        <html><body>
            <div id="test">Original content</div>
            <form id="form1">
                <input type="text" name="field1">
            </form>
        </body></html>
        """
        
        modified_content = """
        <html><body>
            <div id="test">Modified content</div>
            <form id="form1">
                <input type="text" name="field1">
                <input type="text" name="field2" class="new-field">
            </form>
        </body></html>
        """
        
        # Test tracking changes
        print("\n=== Testing DOM Change Tracking ===")
        
        # First store original content
        print("\n1. Storing original content...")
        tracker.track_page_changes(
            page_id='test_page',
            html_content=original_content,
            pnr='TEST123',
            origin='TEST'
        )
        
        # Then track changes with modified content
        print("\n2. Tracking changes with modified content...")
        changes = tracker.track_page_changes(
            page_id='test_page',
            html_content=modified_content,
            pnr='TEST123',
            origin='TEST'
        )
        
        # Print results
        print("\n=== Results ===")
        if changes:
            print(f"\nDetected {len(changes)} changes:")
            for i, change in enumerate(changes, 1):
                print(f"\nChange {i}:")
                print(f"Type: {change.get('type')}")
                print(f"Description: {change.get('description')}")
                if 'element' in change:
                    print(f"Element: {change.get('element')}")
        else:
            print("No changes detected")
            
        # Get recent changes from DB
        print("\n3. Retrieving recent changes from DB...")
        recent_changes = tracker.get_recent_changes(limit=5)
        if recent_changes:
            print(f"\nFound {len(recent_changes)} recent changes in DB:")
            for change in recent_changes:
                print(f"\nPage ID: {change.get('page_id')}")
                print(f"Timestamp: {change.get('timestamp')}")
                print(f"Type: {change.get('type')}")
        else:
            print("No recent changes found in DB")
            
    except Exception as e:
        print(f"\nError during testing: {e}")
        logging.error(f"Test error: {e}", exc_info=True)
