import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

class SMTPLogger:
    def __init__(self):
        self.logger = logging.getLogger('smtp_logger')
        self.logger.setLevel(logging.INFO)
        
        # Create logs directory if it doesn't exist
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Create rotating file handler for SMTP logs
        log_file = os.path.join(log_dir, 'smtp_logs.log')
        handler = RotatingFileHandler(
            log_file,
            maxBytes=1024 * 1024,  # 1MB
            backupCount=5
        )
        
        # Create detailed formatter for SMTP logs
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - SMTP: %(message)s'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(handler)
    
    def log_connection(self, server, port):
        """Log SMTP connection attempt"""
        self.logger.info(f"Connecting to {server}:{port}")
    
    def log_login(self, user):
        """Log SMTP login attempt"""
        self.logger.info(f"Login attempt for user: {user}")
    
    def log_tls(self, success=True):
        """Log TLS operation"""
        if success:
            self.logger.info("TLS connection established successfully")
        else:
            self.logger.error("TLS connection failed")
    
    def log_error(self, operation, error):
        """Log SMTP errors"""
        self.logger.error(f"SMTP {operation} failed: {error}")

smtp_logger = SMTPLogger()
