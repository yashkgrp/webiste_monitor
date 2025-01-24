import logging
from datetime import datetime

class SocketLogger:
    def __init__(self):
        self.logger = logging.getLogger('socket_logger')
        self.logger.setLevel(logging.INFO)
        
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - SOCKET: %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_stage(self, stage, status, message, timing=None, error=None):
        log_msg = f"Stage: {stage} | Status: {status} | Message: {message}"
        if timing:
            log_msg += f" | Timing: {timing}s"
        if error:
            log_msg += f" | Error: {error}"
        self.logger.info(log_msg)
    
    def log_error(self, stage, error):
        self.logger.error(f"Stage: {stage} | Error: {error}")
