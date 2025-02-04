import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import sys

class CustomFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    COLORS = {
        logging.DEBUG: '\033[0;36m',     # Cyan
        logging.INFO: '\033[0;32m',      # Green
        logging.WARNING: '\033[0;33m',   # Yellow
        logging.ERROR: '\033[0;31m',     # Red
        logging.CRITICAL: '\033[0;37;41m'  # White on Red
    }
    RESET = '\033[0m'

    def __init__(self, include_timestamp=True):
        fmt = '%(levelname)s: %(message)s'
        if include_timestamp:
            fmt = '%(asctime)s - ' + fmt
        super().__init__(fmt)

    def format(self, record):
        if not record.exc_info:
            level = record.levelno
            if level in self.COLORS:
                record.msg = f"{self.COLORS[level]}{record.msg}{self.RESET}"
        return super().format(record)

class LoggerFactory:
    """Factory class to create and configure loggers"""
    
    @staticmethod
    def create_logger(name, log_dir='logs', log_to_console=True, log_level=logging.INFO):
        """
        Create a logger with both file and console handlers
        
        Args:
            name (str): Name of the logger/module
            log_dir (str): Directory to store log files
            log_to_console (bool): Whether to output logs to console
            log_level (int): Logging level (default: logging.INFO)
            
        Returns:
            logging.Logger: Configured logger instance
        """
        # Create logger
        logger = logging.getLogger(name)
        logger.setLevel(log_level)
        
        # Clear any existing handlers
        logger.handlers = []
        
        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        # Daily rotating file handler
        log_file = os.path.join(log_dir, f'{name}.log')
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=7,
            encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        file_handler.setLevel(log_level)
        logger.addHandler(file_handler)
        
        # Size-based rotating handler for detailed logs
        detailed_log = os.path.join(log_dir, f'{name}_detailed.log')
        detailed_handler = RotatingFileHandler(
            detailed_log,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        detailed_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s\n'
            'Path: %(pathname)s:%(lineno)d\n'
            'Function: %(funcName)s\n'
        ))
        detailed_handler.setLevel(logging.DEBUG)
        logger.addHandler(detailed_handler)
        
        # Console handler with colors
        if log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(CustomFormatter())
            console_handler.setLevel(log_level)
            logger.addHandler(console_handler)
        
        return logger

# Example usage
if __name__ == "__main__":
    # Create a test logger
    test_logger = LoggerFactory.create_logger("test_module")
    
    # Test different log levels
    test_logger.debug("This is a debug message")
    test_logger.info("This is an info message")
    test_logger.warning("This is a warning message")
    test_logger.error("This is an error message")
    test_logger.critical("This is a critical message")
    
    # Test exception logging
    try:
        raise ValueError("This is a test exception")
    except Exception as e:
        test_logger.exception("An error occurred")
