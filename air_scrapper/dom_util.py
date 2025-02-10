import difflib
import logging
from bs4 import BeautifulSoup
from datetime import datetime


class AirIndiaDOMTracker:
    def __init__(self, db_ops):
        self.db_ops = db_ops
        self.last_snapshots = {}  # Add cache for last snapshots

    def clean_html(self, content):
        """Clean HTML content for comparison"""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove script, style, and dynamic content
            for element in soup(['script', 'style', 'meta', 'link']):
                element.decompose()
            
            # Only keep meaningful structural elements
            allowed_tags = {'div', 'form', 'input', 'button', 'select', 'table'}
            for tag in soup.find_all():
                if tag.name not in allowed_tags:
                    tag.unwrap()
            
            # Remove all attributes except essential ones
            for tag in soup.find_all():
                allowed_attrs = {'id', 'class', 'name', 'type'}
                attrs = dict(tag.attrs)
                for attr in attrs:
                    if attr not in allowed_attrs:
                        del tag[attr]
            
            return str(soup)
            
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
        """Compare content with improved path format"""
        try:
            if not old_content or not new_content:
                return []

            # Parse and modify old content with test div
            old_soup = BeautifulSoup(old_content, 'html.parser')
            body_tag = old_soup.find('body')
            if body_tag:
                test_div = old_soup.new_tag('input')
                test_div['class'] = 'yash'
                test_div.string = "this div fails the scrappers"
                body_tag.append(test_div)
                
            # Clean and parse content
            old_clean = BeautifulSoup(self.clean_html(str(old_soup)), 'html.parser')
            new_clean = BeautifulSoup(self.clean_html(new_content), 'html.parser')

            # Log for debugging
            print(f"Old content length: {len(str(old_clean))}")
            print(f"New content length: {len(str(new_clean))}")

            changes = []
            
            # Compare raw content first
            if str(old_clean) != str(new_clean):
                logging.info("Content difference detected")
                changes.append({
                    'type': 'content_change',
                    'description': 'Content modified',
                    'size_diff': len(str(new_clean)) - len(str(old_clean))
                })

            # Continue with element comparison
            def get_elements_map(soup):
                elements = {}
                for tag in ['form', 'input', 'button', 'select', 'table', 'div']:
                    for elem in soup.find_all(tag):
                        key = f"{tag}_{elem.get('id', '')}_{' '.join(elem.get('class', []))}"
                        elements[key] = elem
                return elements

            # Use BeautifulSoup objects for comparison
            old_elements = get_elements_map(old_clean)
            new_elements = get_elements_map(new_clean)

            # Track added elements
            for key, elem in new_elements.items():
                if key not in old_elements:
                    path = self.get_element_path(elem)
                    changes.append({
                        'type': 'addition',
                        'element': str(elem),
                        'element_type': elem.name,
                        'path': path,
                        'description': f'New element at {path}'
                    })

            # Track removed elements
            for key, elem in old_elements.items():
                if key not in new_elements:
                    changes.append({
                        'type': 'removal',
                        'element': str(elem),
                        'element_type': elem.name,
                        'attributes': {
                            'id': elem.get('id', ''),
                            'class': ' '.join(elem.get('class', [])),
                            'name': elem.get('name', ''),
                            'type': elem.get('type', '')
                        },
                        'description': f'Existing {elem.name} element removed'
                    })

            # Compare structure using difflib
            if str(old_clean) != str(new_clean):
                diff = list(difflib.unified_diff(
                    str(old_clean).splitlines(),
                    str(new_clean).splitlines()
                ))
                if diff:
                    changes.append({
                        'type': 'structure_change',
                        'diff': '\n'.join(diff),
                        'description': 'Page structure modified'
                    })

            # Add path to changes
            for change in changes:
                if 'element' in change:
                    soup = BeautifulSoup(change['element'], 'html.parser')
                    element = soup.find()
                    if element:
                        change['path'] = self.get_element_path(element)

            logging.info(f"Detected changes: {changes}")
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

    def track_page_changes(self, page_id, html_content, pnr=None, origin=None, skip_snapshot=False):
        """Track changes with improved duplicate prevention"""
        try:
            # Get previous snapshot
            prev_snapshot = self.db_ops.get_dom_snapshot(page_id)
            prev_content = prev_snapshot.get('content') if prev_snapshot else None

            # Compare content and get changes
            changes = self.compare_content(prev_content, html_content)
            
            # Only store snapshot if not skipping and there are actual changes
            if not skip_snapshot and (not prev_content or changes):
                metadata = {
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'pnr': pnr,
                    'origin': origin,
                    'has_changes': bool(changes)
                }
                
                # Store both snapshot and changes
                self.db_ops.store_dom_data({
                    'snapshot': {
                        'content': html_content,
                        'metadata': metadata
                    },
                    'changes': {
                        'changes': changes,
                        'metadata': metadata
                    } if changes else None
                }, page_id)
            
            # Only store changes if there are any
            if changes:
                self.db_ops.store_dom_changes({
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'changes': changes,
                    'pnr': pnr,
                    'origin': origin
                })
            
            return changes
            
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

    def store_dom_changes(self, page_id, html_content, pnr=None, origin=None):
        """Store DOM changes with metadata"""
        try:
            # Get previous snapshot
            prev_snapshot = self.db_ops.get_dom_snapshot(page_id)
            prev_content = prev_snapshot.get('content') if prev_snapshot else None
            
            # Compare with previous snapshot
            changes = self.compare_content(prev_content, html_content)
            
            if changes:
                # Store new snapshot and changes
                change_data = {
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'pnr': pnr,
                    'origin': origin,
                    'changes': changes,
                    'type': 'structural_change',
                    'old_content_size': len(prev_content) if prev_content else 0,
                    'new_content_size': len(html_content),
                    'airline': 'Air India'
                }
                
                # Store both current content and changes
                self.db_ops.store_dom_data({
                    'snapshot': {
                        'content': html_content,
                        'timestamp': change_data['timestamp']
                    },
                    'changes': change_data
                }, page_id)
                
                logging.info(f"Stored meaningful DOM changes for {page_id}")
                return changes, True
                
            return [], False
            
        except Exception as e:
            logging.error(f"Error storing DOM changes: {e}")
            return [], False

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
