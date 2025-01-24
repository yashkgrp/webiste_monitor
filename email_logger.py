import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

class EmailLogger:
    def __init__(self):
        self.logger = logging.getLogger('email_logger')
        self.logger.setLevel(logging.INFO)
        
        # Create logs directory if it doesn't exist
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Create rotating file handler
        log_file = os.path.join(log_dir, 'email_logs.log')
        handler = RotatingFileHandler(
            log_file,
            maxBytes=1024 * 1024,  # 1MB
            backupCount=5
        )
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(handler)
    
    def log_email_sent(self, to_email, subject, status_type):
        """Log successful email send"""
        self.logger.info(
            f"Email sent successfully | To: {to_email} | Subject: {subject} | Type: {status_type}"
        )
    
    def log_email_error(self, to_email, subject, error):
        """Log email send failure"""
        self.logger.error(
            f"Failed to send email | To: {to_email} | Subject: {subject} | Error: {error}"
        )

email_logger = EmailLogger()
