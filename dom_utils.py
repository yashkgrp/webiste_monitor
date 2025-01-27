import difflib
from datetime import datetime
from bs4 import BeautifulSoup
import logging
import re

logger = logging.getLogger(__name__)

class DOMChangeTracker:
    def __init__(self, db_ops):
        self.db_ops = db_ops
        
    def clean_html(self, html_content):
        """Clean HTML content for comparison"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script, style, and dynamic content
            for element in soup(['script', 'style', 'meta', 'link', 'noscript', 'iframe']):
                element.decompose()
            
            # Only keep meaningful structural elements
            allowed_tags = {'div', 'form', 'input', 'button', 'a', 'nav', 'section', 'main', 'header', 'footer'}
            for tag in soup.find_all():
                if tag.name not in allowed_tags:
                    tag.unwrap()  # Keep content but remove tag
            
            # Remove all attributes except essential ones
            for tag in soup.find_all():
                allowed_attrs = {'id', 'class', 'name', 'type', 'method', 'action'}
                attrs = dict(tag.attrs)
                for attr in attrs:
                    if attr not in allowed_attrs:
                        del tag[attr]
            
            # Normalize whitespace and remove empty lines
            lines = [line.strip() for line in str(soup).splitlines() if line.strip()]
            return '\n'.join(lines)
            
        except Exception as e:
            logger.error(f"Error cleaning HTML: {e}")
            return html_content

    def compare_dom(self, old_content, new_content):
        """Compare two DOM contents and return differences"""
        try:
            if not old_content or not new_content:
                logger.warning("Missing content for comparison")
                return [], True
                
            # Parse old content and add test div for comparison
            old_soup = BeautifulSoup(old_content, 'html.parser')
            body_tag = old_soup.find('body')
            if body_tag:
                test_div = old_soup.new_tag('input')
                test_div['class'] = 'yash'
                test_div.string = "this div fails the scrappers"  # Add some content to make it visible
                body_tag.append(test_div)
            
            old_clean = self.clean_html(str(old_soup))
            new_clean = self.clean_html(new_content)
            
            # If content is identical after cleaning, no changes
            if old_clean == new_clean:
                return [], False
            
            # Compare structurally significant elements
            differ = difflib.Differ()
            diff = list(differ.compare(
                old_clean.splitlines(),
                new_clean.splitlines()
            ))
            
            # Filter meaningful changes only and preserve full element text
            significant_changes = []
            for line in diff:
                if line.startswith(('+ ', '- ')):
                    stripped = line[2:].strip()
                    if any(tag in stripped for tag in ['<div', '<form', '<input', '<button', '<nav']):
                        change_type = 'added' if line.startswith('+ ') else 'removed'
                        
                        # Parse the element to get proper location path
                        element_soup = BeautifulSoup(stripped, 'html.parser')
                        element = element_soup.find()
                        if element:
                            tag_name = element.name
                            classes = ' '.join(element.get('class', []))
                            attrs = ' '.join(f'{k}="{v}"' for k, v in element.attrs.items())
                            path = tag_name
                            if classes:
                                path += f".{'.'.join(element.get('class', []))}"
                            if element.get('id'):
                                path += f"#{element['id']}"
                            
                            description = f"{change_type.title()} element in document:\n"
                            description += f"Type: <{tag_name}>\n"
                            description += f"Classes: {classes}\n" if classes else ""
                            description += f"Attributes: {attrs}\n" if attrs else ""
                            description += f"Content: {element.string}" if element.string else ""
                            
                            significant_changes.append({
                                'type': change_type,
                                'element': stripped,
                                'path': f"body > {path}",  # Add parent path
                                'description': description.strip(),
                                'attributes': {
                                    'tag': tag_name,
                                    'class': classes,
                                    'id': element.get('id', ''),
                                    'other_attrs': element.attrs
                                }
                            })
            
            return significant_changes, bool(significant_changes)
            
        except Exception as e:
            logger.error(f"Error comparing DOM: {e}")
            return [], False

    def _get_element_path(self, element_str):
        """Extract path from element string"""
        try:
            # Parse element string into a soup object
            soup = BeautifulSoup(element_str, 'html.parser')
            element = soup.find()
            if not element:
                return "unknown"

            # Build detailed path information
            path_info = []
            
            # Add tag name
            path_info.append(element.name)
            
            # Add ID if present
            if element.get('id'):
                path_info.append(f"#{element['id']}")
                
            # Add classes if present
            if element.get('class'):
                path_info.extend([f".{cls}" for cls in element['class']])
                
            # Add other important attributes
            important_attrs = ['name', 'type', 'method', 'action']
            for attr in important_attrs:
                if element.get(attr):
                    path_info.append(f"[{attr}='{element[attr]}']")
            
            # Combine path components
            return ''.join(path_info)
            
        except Exception as e:
            logger.error(f"Error getting element path: {str(e)}")
            return element_str  # Return original element string if parsing fails

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

    def store_dom_changes(self, page_id, html_content, gstin=None, pnr=None):
        """Store DOM changes in Firebase"""
        try:
            # Get previous snapshot
            prev_snapshot = self.db_ops.get_dom_snapshot(page_id)
            prev_content = prev_snapshot.get('content') if prev_snapshot else None
            
            # Compare with previous snapshot
            changes, has_changes = self.compare_dom(prev_content, html_content)
            
            if has_changes and changes:  # Only store if there are actual changes
                # Store new snapshot and changes
                change_data = {
                    'page_id': page_id,
                    'timestamp': datetime.now().isoformat(),
                    'gstin': gstin,
                    'pnr': pnr,
                    'changes': changes,
                    'type': 'structural_change',
                    'old_content_size': len(prev_content) if prev_content else 0,
                    'new_content_size': len(html_content)
                }
                
                # Store both current content and changes
                self.db_ops.store_dom_data({
                    'snapshot': {
                        'content': html_content,
                        'timestamp': change_data['timestamp']
                    },
                    'changes': change_data
                }, page_id)
                
                logger.info(f"Stored meaningful DOM changes for {page_id}")
                return changes, True
                
            return [], False
            
        except Exception as e:
            logger.error(f"Error storing DOM changes: {e}")
            return [], False
    
    def get_recent_changes(self, limit=10):
        """Get recent DOM changes"""
        try:
            changes = self.db_ops.get_dom_changes(limit)
            if changes:
                # Format changes for display
                formatted_changes = []
                for change in changes:
                    formatted_changes.append({
                        'page_id': change.get('page_id', 'unknown'),
                        'timestamp': change.get('timestamp'),
                        'type': change.get('type', 'unknown'),
                        'changes': change.get('changes', []),
                        'gstin': change.get('gstin'),
                        'pnr': change.get('pnr')
                    })
                return formatted_changes
            return []
        except Exception as e:
            logger.error(f"Error getting DOM changes: {e}")
            return []
