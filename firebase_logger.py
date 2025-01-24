import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

class FirebaseLogger:
    def __init__(self):
        self.logger = logging.getLogger('firebase_logger')
        self.logger.setLevel(logging.INFO)
        
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        log_file = os.path.join(log_dir, 'firebase_logs.log')
        handler = RotatingFileHandler(
            log_file,
            maxBytes=1024 * 1024,  # 1MB
            backupCount=5
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - FIREBASE: %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_query(self, collection, operation, params=None):
        """Log Firebase query execution"""
        self.logger.info(f"Query | Collection: {collection} | Operation: {operation} | Params: {params or 'None'}")
    
    def log_write(self, collection, document, operation):
        """Log Firebase write operations"""
        self.logger.info(f"Write | Collection: {collection} | Document: {document} | Operation: {operation}")
    
    def log_error(self, operation, error, details=None):
        """Log Firebase errors"""
        self.logger.error(f"Error | Operation: {operation} | Error: {error} | Details: {details or 'None'}")
    
    def log_transaction(self, operation, status):
        """Log Firebase transactions"""
        self.logger.info(f"Transaction | Operation: {operation} | Status: {status}")

firebase_logger = FirebaseLogger()
