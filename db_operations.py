from datetime import datetime
import pytz
import base64
import logging
from collections import defaultdict
from statistics import mean
from google.cloud.firestore import Query  # Add this import
from firebase_logger import firebase_logger

class FirestoreDB:
    def __init__(self, db):
        self.db = db
        self.urls_ref = self.db.collection('monitored_urls')

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

    def _add_history_entry(self, doc_ref, timestamp, status, response_time):
        """Add a history entry for a URL"""
        try:
            timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S_%f')
            history_ref = doc_ref.collection('history').document(timestamp_str)
            history_ref.set({
                'timestamp': timestamp,
                'status': status,
                'response_time': float(response_time)
            })
        except Exception as e:
            logging.error(f"Error adding history entry: {e}")

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

    def get_url_history(self, url, limit=None):
        doc_id = self._encode_url(url)
        doc_ref = self.urls_ref.document(doc_id)
        history = []
        try:
            query = doc_ref.collection('history').order_by(
                'timestamp',
                direction=Query.ASCENDING
            )
            if limit:
                query = query.limit(limit)
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
                        .where('status', '==', 'Down')\
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
            doc = self.db.collection('notification _email_list_file_upload').document('email').get()
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
