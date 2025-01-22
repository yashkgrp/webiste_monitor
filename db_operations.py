from datetime import datetime
import pytz
import base64
import logging
from collections import defaultdict
from statistics import mean
from google.cloud.firestore import Query  # Add this import

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

                # Add to history
                self._add_history_entry(doc_ref, current_time, status, response_time)
                
        except Exception as e:
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

    def get_url_history(self, url, limit=1000):
        """Get historical data for a URL"""
        doc_id = self._encode_url(url)
        doc_ref = self.urls_ref.document(doc_id)
        history = []
        
        try:
            # Use Query.DESCENDING instead of 'desc'
            for doc in doc_ref.collection('history').order_by(
                'timestamp', 
                direction=Query.DESCENDING
            ).limit(limit).stream():
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
        
        up_count = sum(1 for entry in history if 'Up' in entry['status'])
        avg_response = mean(entry['response_time'] for entry in history)
        
        return {
            'uptime': round((up_count / total) * 100, 2),
            'avg_response': round(avg_response, 2),
            'total_checks': total
        }
