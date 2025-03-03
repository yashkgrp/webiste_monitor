
from datetime import datetime, timedelta
import pytz
import base64
import logging
from collections import defaultdict
import difflib
from statistics import mean
from google.cloud.firestore import Query  # Add this import
from firebase_logger import firebase_logger
from bs4 import BeautifulSoup

class FirestoreDB:
    def __init__(self, db):
        self.db = db
        self.urls_ref = self.db.collection('monitored_urls')
        # Create reference to star_air document
        self.star_air_ref = self.urls_ref.document('star_air')
        
        # Initialize subcollections under star_air
        self.scraper_state_ref = self.star_air_ref.collection('scraper_states')
        self.scraper_history_ref = self.star_air_ref.collection('scraper_history')
        self.dom_changes_ref = self.star_air_ref.collection('dom_changes')

    def _encode_url(self, url):
        """Convert URL to safe document ID"""
        return base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')

    def _convert_timestamp(self, value):
        """Convert Firebase timestamp to Unix timestamp if needed"""
        if hasattr(value, 'timestamp'):
            return value.timestamp()
        return value

    def _process_document_data(self, data):
        """Process document data to ensure correct types"""
        if not data:
            return None
            
        processed = data.copy()
        # Convert numeric fields
        for field in ['last_response_time', 'avg_response_time', 'interval']:
            if field in processed:
                try:
                    processed[field] = float(processed[field])
                except (ValueError, TypeError):
                    processed[field] = 0.0
                    
        # Convert timestamp fields
        for field in ['last_check', 'created_at']:
            if field in processed:
                processed[field] = self._convert_timestamp(processed[field])
                
        return processed

    def add_url(self, url, interval):
        doc_id = self._encode_url(url)
        doc_ref = self.urls_ref.document(doc_id)
        doc_ref.set({
            'url': url,
            'interval': interval,
            'status': '',
            'last_response_time': 0,
            'avg_response_time': 0,
            'paused': False,
            'created_at': datetime.now(pytz.UTC),
            'last_check': 0
        })

    def update_url_status(self, url, status, response_time):
        doc_id = self._encode_url(url)
        doc_ref = self.urls_ref.document(doc_id)
        current_time = datetime.now(pytz.UTC)
        
        try:
            firebase_logger.log_transaction('update_status', 'started')
            # Get current document
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                avg_time = float(data.get('avg_response_time', 0))
                
                # Calculate new average
                if avg_time == 0:
                    new_avg = float(response_time)
                else:
                    new_avg = round((avg_time + float(response_time)) / 2, 2)

                # Update document
                update_data = {
                    'status': status,
                    'last_response_time': float(response_time),
                    'avg_response_time': new_avg,
                    'last_check': current_time,
                }
                doc_ref.update(update_data)
                firebase_logger.log_write('monitored_urls', doc_id, 'update_status')
                firebase_logger.log_transaction('update_status', 'completed')

                # Add to history
                self._add_history_entry(doc_ref, current_time, status, response_time)
                
        except Exception as e:
            firebase_logger.log_error('update_status', str(e), {'url': url})
            logging.error(f"Error updating URL status: {e}")
            raise

    def _add_history_entry(self, doc_ref, timestamp, status, response_time, changes=None):
        """
        Create a record in the 'history' sub-collection.
        Include an empty or "No Changes" record for consistent logging.
        """
        if changes is None:
            changes = []
        doc_ref.collection("history").add({
            "timestamp": timestamp,
            "status": status,
            "response_time": response_time,
            "changes": changes if changes else ["No Changes"]
        })

    def delete_url(self, url):
        doc_id = self._encode_url(url)
        # Delete history subcollection first
        doc_ref = self.urls_ref.document(doc_id)
        self._delete_collection(doc_ref.collection('history'))
        # Delete the main document
        doc_ref.delete()

    def _delete_collection(self, coll_ref, batch_size=100):
        """Helper method to delete a collection"""
        docs = coll_ref.limit(batch_size).stream()
        deleted = 0

        for doc in docs:
            doc.reference.delete()
            deleted += 1

        if deleted >= batch_size:
            return self._delete_collection(coll_ref, batch_size)

    def toggle_pause(self, url):
        doc_id = self._encode_url(url)
        doc_ref = self.urls_ref.document(doc_id)
        doc = doc_ref.get()
        if doc.exists:
            current_state = doc.to_dict().get('paused', False)
            doc_ref.update({'paused': not current_state})

    def get_url_data(self, url):
        """Get single URL data from Firestore"""
        try:
            doc_id = self._encode_url(url)
            doc = self.urls_ref.document(doc_id).get()
            if doc.exists:
                return self._process_document_data(doc.to_dict())
            return None
        except Exception as e:
            logging.error(f"Error getting URL data: {e}")
            return None

    def get_all_urls(self):
        urls = {}
        for doc in self.urls_ref.stream():
            try:
                data = self._process_document_data(doc.to_dict())
                if data and 'url' in data:
                    urls[data['url']] = data
            except Exception as e:
                logging.error(f"Error processing document {doc.id}: {e}")
                continue
        return urls

    def sync_urls(self):
        """Sync all URLs from Firestore"""
        try:
            urls = {}
            for doc in self.urls_ref.stream():
                try:
                    data = self._process_document_data(doc.to_dict())
                    # Ensure all numeric fields are properly converted
                    if data and 'url' in data:  # Only add if URL field exists
                        urls[data['url']] = data
                except Exception as e:
                    logging.error(f"Error processing document {doc.id}: {e}")
                    continue
            return urls
        except Exception as e:
            logging.error(f"Error syncing URLs: {e}")
            return {}

    def get_url_history(self, url, offset=0, limit=5000):
        doc_id = self._encode_url(url)
        doc_ref = self.urls_ref.document(doc_id)
        history = []
        try:
            query = doc_ref.collection('history')\
                .order_by('timestamp', direction=Query.DESCENDING)\
                .offset(offset)\
                .limit(limit)
                
            for doc in query.stream():
                data = doc.to_dict()
                data['timestamp'] = self._convert_timestamp(data['timestamp'])
                history.append(data)
            return history
        except Exception as e:
            logging.error(f"Error getting URL history: {e}")
            return []

    def analyze_best_times(self, url):
        """Analyze best times for scraping based on response times"""
        history = self.get_url_history(url)
        hourly_data = defaultdict(list)
        
        for entry in history:
            hour = datetime.fromtimestamp(entry['timestamp']).hour
            hourly_data[hour].append(entry['response_time'])
        
        best_times = []
        for hour, times in hourly_data.items():
            avg_time = mean(times) if times else 0
            best_times.append({
                'hour': hour,
                'avg_response_time': round(avg_time, 2),
                'sample_size': len(times)
            })
        
        return sorted(best_times, key=lambda x: x['avg_response_time'])

    def get_hourly_averages(self, url):
        """Get average response times by hour"""
        history = self.get_url_history(url)
        hourly_data = defaultdict(list)
        
        for entry in history:
            hour = datetime.fromtimestamp(entry['timestamp']).hour
            hourly_data[hour].append(entry['response_time'])
        
        return [{
            'hour': hour,
            'avg_response_time': round(mean(times), 2) if times else 0,
            'count': len(times)
        } for hour, times in sorted(hourly_data.items())]

    def get_reliability_stats(self, url):
        """Get reliability statistics"""
        history = self.get_url_history(url)
        total = len(history)
        if not total:
            return {'uptime': 0, 'avg_response': 0, 'total_checks': 0}
        
        # Count both 'Up' and 'Slow' as uptime
        up_count = sum(1 for entry in history if entry['status'] in ['Up', 'Slow'])
        avg_response = mean(entry['response_time'] for entry in history)
        
        # Get last down and slow times using direct queries
        last_down = self.get_last_status_time(url, 'down')
        last_slow = self.get_last_status_time(url, 'slow')
        
        return {
            'uptime': round((up_count / total) * 100, 2),
            'avg_response': round(avg_response, 2),
            'total_checks': total,
            'last_down_period': last_down,
            'last_slow_period': last_slow
        }

    def _find_last_status_period(self, history, status_check):
        """Find the most recent period for a given status"""
        if not history:
            return "Never"

        period_end = None
        period_start = None
        
        # Look through history in reverse to find most recent period
        for entry in reversed(history):
            is_status = status_check(entry['status'])
            
            if period_end is None and is_status:
                # Found the end of the most recent period
                period_end = entry['timestamp']
            elif period_end is not None and not is_status:
                # Found the start of the period
                period_start = entry['timestamp']
                break
            
        if period_end is None:
            return "Never"
            
        if period_start is None:
            # Status continues from the beginning of our data
            period_start = history[0]['timestamp']

        duration_seconds = period_end - period_start
        duration_str = self._format_duration(duration_seconds)
        
        end_time = datetime.fromtimestamp(period_end).strftime('%Y-%m-%d %H:%M:%S')
        start_time = datetime.fromtimestamp(period_start).strftime('%Y-%m-%d %H:%M:%S')
        
        return f"Was down for {duration_str} ({start_time} to {end_time})"

    def _format_duration(self, seconds):
        """Format duration in seconds to human readable string"""
        if seconds < 60:
            return f"{int(seconds)} seconds"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)} minutes"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)} hours"
        days = hours / 24
        return f"{int(days)} days"

    def get_last_status_time(self, url, status_type):
        """Get the last time a specific status occurred using direct Firebase query"""
        try:
            doc_id = self._encode_url(url)
            doc_ref = self.urls_ref.document(doc_id)
            
            firebase_logger.log_query(
                'history',
                f'get_last_{status_type}_status',
                {'url': url}
            )
            
            try:
                # Query directly with timestamp ordering
                if status_type == 'down':
                    query = doc_ref.collection('history')\
                                            .where('status', '>=', 'Down')\
                                            .where('status', '<', 'Down' + '\uf8ff')\
                                            .order_by('status')\
                                            .order_by('timestamp', direction=Query.DESCENDING)\
                                            .limit(1)
                else:  # For slow status
                    query = doc_ref.collection('history')\
                        .where('status', '==', 'Slow')\
                        .order_by('timestamp', direction=Query.DESCENDING)\
                        .limit(1)

                docs = list(query.stream())
                
                firebase_logger.log_query(
                    'history',
                    'query_results',
                    {'count': len(docs), 'url': url, 'status_type': status_type}
                )
                
                if docs:
                    last_entry = docs[0].to_dict()
                    if not last_entry or 'timestamp' not in last_entry:
                        firebase_logger.log_error(
                            'get_last_status_time', 
                            'Invalid document format', 
                            {'url': url, 'doc_data': str(last_entry)}
                        )
                        return "Error fetching status"
                        
                    timestamp = self._convert_timestamp(last_entry['timestamp'])
                    now = datetime.now(pytz.UTC).timestamp()
                    duration = now - timestamp
                    
                    end_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    status_msg = f"Last {status_type} at {end_time} ({self._format_duration(duration)} ago)"
                    
                    firebase_logger.log_query(
                        'history',
                        'found_status',
                        {'status': status_msg, 'timestamp': end_time}
                    )
                    
                    return status_msg
                else:
                    firebase_logger.log_query(
                        'history',
                        'no_status_found',
                        {'url': url, 'status_type': status_type}
                    )
                    return "Never"
                
            except Exception as query_error:
                firebase_logger.log_error(
                    'get_last_status_time_query', 
                    str(query_error), 
                    {'url': url, 'status_type': status_type}
                )
                return "Error fetching status"
                
        except Exception as e:
            firebase_logger.log_error('get_last_status_time', str(e), {'url': url, 'status_type': status_type})
            logging.error(f"Error getting last status time: {e}")
            return "Error fetching status"

    def _format_time_ago(self, seconds):
        """Format seconds into a human-readable time ago string"""
        if seconds is None:
            return "Never"
        
        minutes = seconds / 60
        hours = minutes / 60
        days = hours / 24
        
        if days > 1:
            return f"{int(days)} days ago"
        if hours > 1:
            return f"{int(hours)} hours ago"
        if minutes > 1:
            return f"{int(minutes)} minutes ago"
        return "Just now"

    def get_notification_emails(self):
        """Get list of notification emails from Firestore"""
        try:
            firebase_logger.log_query('notification_email_list_file_upload', 'get_emails')
            # Changed collection and document names to match file_upload implementation
            doc = self.db.collection('monitor_mails').document('email').get()
            if doc.exists:
                emails = doc.to_dict().get('emails', [])
                logging.info(f"Found notification emails: {emails}")
                return emails
            logging.warning("No notification emails document found")
            return []
        except Exception as e:
            firebase_logger.log_error('get_notification_emails', str(e))
            logging.error(f"Error fetching notification emails: {e}")
            # Fallback to email document
            try:
                doc = self.db.collection('notification_email_list_file_upload').document('emails').get()
                if doc.exists:
                    return doc.to_dict().get('email', [])
                return []
            except Exception:
                return []

    def handle_dom_changes(self, changes, gstin=None, pnr=None):
        """Handle DOM changes and send notifications"""
        if changes and len(changes) > 0:
            notification_emails = self.get_notification_emails()
            if notification_emails:
                from email_utils import generate_dom_change_email, send_notification_email
                html_content = generate_dom_change_email(
                    pnr=pnr,
                    gstin=gstin,
                    changes=changes,
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
                send_notification_email(
                    subject=f"DOM Changes Detected - PNR: {pnr}",
                    html_content=html_content,
                    notification_emails=notification_emails
                )

    def store_dom_snapshot(self, page_id, content):
        """Store DOM snapshot with structural comparison"""
        try:
            doc_ref = self.dom_changes_ref.document(page_id)
            old_snapshot = doc_ref.get()
            
            # Extract structural elements only
            def get_structure(html_content):
                soup = BeautifulSoup(html_content, 'html.parser')
                # Remove all text nodes and data attributes
                for tag in soup.find_all():
                    # Keep only tag name and essential attributes
                    attrs = tag.attrs
                    keep_attrs = {'id', 'class', 'type', 'name', 'method', 'action'}
                    tag.attrs = {k: v for k, v in attrs.items() if k in keep_attrs}
                    # Remove text content
                    if tag.string:
                        tag.string = ''
                return str(soup)

            new_structure = get_structure(content)
            
            if old_snapshot.exists:
                old_structure = get_structure(old_snapshot.to_dict().get('content', ''))
                
                # Generate structural diff
                diff = list(difflib.unified_diff(
                    old_structure.splitlines(),
                    new_structure.splitlines(),
                    fromfile='previous_structure',
                    tofile='current_structure',
                    lineterm=''
                ))
                
                has_changes = bool(diff)
                
                if has_changes:
                    # Log structural changes to Firebase
                    change_doc = {
                        'timestamp': datetime.now(pytz.UTC),
                        'page_id': page_id,
                        'changes': diff,
                        'type': 'structural',
                        'page_url': f"https://yourwebsite.com/{page_id}",
                        'detected_by': 'ScraperModule',
                        'change_summary': 'Structural changes detected in the DOM.'
                    }
                    self.dom_changes_ref.add(change_doc)
                    
                    # Call handle_dom_changes as an instance method
                    self.handle_dom_changes(diff, gstin=None, pnr=None)
            else:
                has_changes = True
                diff = ["Initial structure snapshot"]
            
            # Store new snapshot
            doc_ref.set({
                'content': content,
                'structure': new_structure,
                'timestamp': datetime.now(pytz.UTC),
                'has_changes': has_changes
            })
            
            return has_changes, diff
            
        except Exception as e:
            logging.error(f"Error storing DOM snapshot: {e}")
            return False, []

    def update_scraper_status(self, status, message=None):
        """Update scraper status in Firestore"""
        try:
            self.db.collection('scraper_status').document('latest').set({
                'status': status,
                'message': message,
                'timestamp': datetime.now(pytz.UTC)
            }, merge=True)
        except Exception as e:
            logging.error(f"Error updating scraper status: {e}")

    def store_scraper_state(self, gstin, pnr, state='pending', message=None, next_run=None, auto_run=None, preserve_last_run=False, preserve_next_run=False,last_run="0"):
        """Store scraper state in Firebase"""
        try:
            doc_id = f"{gstin}_{pnr}"
            current_time = datetime.now(pytz.UTC)
            
            # Get existing state to preserve values if needed
            existing_state = self.scraper_state_ref.document(doc_id).get()
            
            state_data = {
                'gstin': gstin,
                'pnr': pnr,
                'state': state,
                'message': message,
                'error': message if state == 'failed' else None,
                'updated_at': current_time
            }
            
            # Handle last_run preservation
            if not preserve_last_run:
                state_data['last_run'] = current_time
            elif existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'last_run' in existing_data:
                    state_data['last_run'] = existing_data['last_run']
            
            # Handle next_run timing
            if preserve_next_run and existing_state.exists:
                # If preserving next_run, keep existing value if present
                existing_data = existing_state.to_dict()
                if 'next_run' in existing_data:
                    state_data['next_run'] = existing_data['next_run']
            elif next_run is not None:
                # New scheduled run
                state_data['next_run'] = next_run
            
            # Update auto_run only if explicitly provided
            if auto_run is not None:
                state_data['auto_run'] = auto_run
            elif existing_state.exists:
                existing_data = existing_state.to_dict()
                if 'auto_run' in existing_data:
                    state_data['auto_run'] = existing_data['auto_run']
            
            # Store with merge to preserve any other existing fields
            self.scraper_state_ref.document(doc_id).set(state_data, merge=True)
            
            logging.debug(f"Stored scraper state: {state_data}")
            
        except Exception as e:
            print(f"Error storing scraper state: {e}")
            raise

    def get_last_scraper_state(self):
        """Get most recent scraper state"""
        try:
            # Query from scraper_states subcollection
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
            logging.error(f"Error getting last scraper state: {e}")
            raise

    def get_all_scraper_states(self):
        """Get all scraper states"""
        try:
            states = {}
            for doc in self.scraper_state_ref.stream():
                data = doc.to_dict()
                states[doc.id] = self._process_document_data(data)
            return states
        except Exception as e:
            logging.error(f"Error getting scraper states: {e}")
            return {}

    def get_scraper_analytics(self, gstin=None, pnr=None, last_timestamp=None):
        """Get analytics for scraper runs with pagination support"""
        try:
            query = self.scraper_history_ref
            if gstin and pnr:
                query = query.where('gstin', '==', gstin).where('pnr', '==', pnr)
            
            query = query.order_by('timestamp', direction=Query.DESCENDING).limit(1000)
            
            if last_timestamp:
                # Create a cursor to start after the last fetched timestamp
                last_doc = self.scraper_history_ref.where('timestamp', '<', last_timestamp)\
                    .order_by('timestamp', direction=Query.DESCENDING).limit(1).stream()
                last_doc = list(last_doc)
                if last_doc:
                    query = query.start_after({'timestamp': last_timestamp})
            
            docs = query.stream()
            
            analytics = {
                'total_runs': 0,
                'success_rate': 0,
                'last_run': None,
                'dom_changes': [],
                'hourly_success': defaultdict(lambda: {'total': 0, 'success': 0}),
                'recent_runs': []
            }
            
            # Process history data
            for doc in docs:
                data = doc.to_dict()
                analytics['total_runs'] += 1
                
                if data.get('success'):
                    hour = data['timestamp'].hour
                    analytics['hourly_success'][hour]['total'] += 1
                    analytics['hourly_success'][hour]['success'] += 1
                
                analytics['recent_runs'].append({
                    'timestamp': data.get('timestamp'),
                    'success': data.get('success'),
                    'gstin': data.get('gstin'),
                    'pnr': data.get('pnr')
                })
            
            # Calculate success rate
            if analytics['total_runs'] > 0:
                analytics['success_rate'] = (
                    len([r for r in analytics['recent_runs'] if r['success']]) / 
                    analytics['total_runs']
                ) * 100
            
            # Get recent DOM changes from dom_changes subcollection
            dom_changes = self.dom_changes_ref.order_by(
                'timestamp', 
                direction=Query.DESCENDING
            ).limit(1000).stream()
            
            analytics['dom_changes'] = [{
                'timestamp': doc.get('timestamp'),
                'page_id': doc.get('page_id'),
                'changes': doc.get('changes')
            } for doc in dom_changes]
            
            return analytics
                
        except Exception as e:
            logging.error(f"Error getting scraper analytics: {e}")
            return None

    def get_recent_dom_changes(self):
        """Get recent DOM changes from Firestore"""
        try:
            changes = []
            docs = self.dom_changes_ref.order_by(
                'timestamp', 
                direction=Query.DESCENDING
            ).limit(50).stream()
            
            for doc in docs:
                data = doc.to_dict()
                if data and data.get('changes'):  # Only include if there are actual changes
                    changes.append({
                        'timestamp': data.get('timestamp'),
                        'page_id': data.get('page_id'),
                        'changes': [
                            change for change in data.get('changes', [])
                            if any(tag in change for tag in ['<div', '<form', '<input', '<button', '<nav'])
                        ],
                        'type': data.get('type'),
                        'gstin': data.get('gstin'),
                        'pnr': data.get('pnr')
                    })
            
            # Only return entries that have meaningful changes
            return [change for change in changes if change['changes']]
        except Exception as e:
            logging.error(f"Error getting DOM changes: {e}")
            return []

    def get_dom_snapshot(self, page_id):
        """Get the latest DOM snapshot for a page"""
        try:
            doc = self.db.collection('dom_snapshots').document(page_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logging.error(f"Error getting DOM snapshot: {e}")
            return None
            
    def store_dom_data(self, data, page_id):
        """Store DOM snapshot and changes"""
        try:
            # Store snapshot
            self.db.collection('dom_snapshots').document(page_id).set(data['snapshot'])
            
            # Store changes in a subcollection
            changes_ref = self.db.collection('dom_changes').document()
            changes_ref.set(data['changes'])
            
            return True
        except Exception as e:
            print(f"Error storing DOM data: {e}")
            return False
            
    def get_dom_changes(self, limit=1000):
        """Get recent DOM changes"""
        try:
            changes = self.db.collection('dom_changes')\
                .order_by('timestamp', direction='DESCENDING')\
                .limit(limit)\
                .stream()
            return [change.to_dict() for change in changes]
        except Exception as e:
            print(f"Error getting DOM changes: {e}")
            return []

    def get_last_dom_comparison_result(self, page_id):
        """Get the latest DOM comparison result"""
        try:
            doc = self.dom_changes_ref.document(page_id).get()
            if doc.exists:
                data = doc.to_dict()
                return {
                    'has_changes': data.get('has_changes', False),
                    'last_check': data.get('timestamp'),
                    'changes_count': len(data.get('changes', []))
                }
            return {
                'has_changes': False,
                'last_check': None,
                'changes_count': 0
            }
        except Exception as e:
            print(f"Error getting last DOM comparison: {e}")
            return None

    def save_dom_comparison(self, page_id, has_changes, changes, html_content, gstin=None, pnr=None):
        """Save DOM comparison results and history"""
        try:
            timestamp = datetime.now(pytz.UTC)
            
            # Save current snapshot and comparison result
            self.dom_changes_ref.document(page_id).set({
                'has_changes': has_changes,
                'timestamp': timestamp,
                'content': html_content
            })

            # Always add to history, even if no changes
            history_entry = {
                'timestamp': timestamp,
                'page_id': page_id,
                'has_changes': has_changes,
                'changes': changes if changes else [],
                'gstin': gstin,
                'pnr': pnr
            }
            
            # Add to history collection
            self.dom_changes_ref.document(page_id).collection('history').add(history_entry)
            
            return True
        except Exception as e:
            print(f"Error saving DOM comparison: {e}")
            return False

    def get_scheduler_settings(self):
        """Get scheduler settings from Firestore"""
        try:
            doc = self.star_air_ref.collection('settings').document('scheduler').get()
            if doc.exists:
                data = doc.to_dict()
                # Convert next_run to timestamp in milliseconds
                if 'next_run' in data and data['next_run']:
                    data['next_run'] = int(data['next_run'].timestamp() * 1000)
                return data
            return {
                'auto_run': False,
                'interval': 60,
                'next_run': None
            }
        except Exception as e:
            print(f"Error getting scheduler settings: {e}")
            return None

    def update_scheduler_settings(self, auto_run, interval, next_run=None):
        """Update scheduler settings in Firestore"""
        try:
            settings = {
                'auto_run': auto_run,
                'interval': interval,
                'updated_at': datetime.now(pytz.UTC)
            }
            if next_run:
                # Store exact datetime object
                settings['next_run'] = next_run
                
            self.star_air_ref.collection('settings').document('scheduler').set(
                settings,
                merge=True
            )
            return True
        except Exception as e:
            print(f"Error updating scheduler settings: {e}")
            return False

    def update_next_run_time(self, next_run):
        """Update next run time in scheduler settings"""
        try:
            self.star_air_ref.collection('settings').document('scheduler').update({
                'next_run': next_run  # Store exact datetime object
            })
            return True
        except Exception as e:
            print(f"Error updating next run time: {e}")
            return False
