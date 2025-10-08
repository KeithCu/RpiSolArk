#!/usr/bin/env python3
"""
Production-ready frequency monitor with enhanced reliability
"""

import signal
import sys
import time
import logging
from pathlib import Path
from monitor import FrequencyMonitor

class ProductionMonitor:
    """Production wrapper with enhanced reliability features."""
    
    def __init__(self):
        self.monitor = None
        self.restart_count = 0
        self.max_restarts = 10
        self.restart_window = 3600  # 1 hour
        self.last_restart_time = 0
        self.setup_logging()
        
    def setup_logging(self):
        """Setup production logging."""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Rotating file handler
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(
            log_dir / "monitor.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=10
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler, logging.StreamHandler()]
        )
        
        self.logger = logging.getLogger(__name__)
        
    def should_restart(self) -> bool:
        """Check if we should allow another restart."""
        current_time = time.time()
        
        # Reset counter if outside restart window
        if current_time - self.last_restart_time > self.restart_window:
            self.restart_count = 0
            
        if self.restart_count >= self.max_restarts:
            self.logger.critical(f"Too many restarts ({self.restart_count}) in {self.restart_window}s. Stopping.")
            return False
            
        return True
        
    def run_with_restart(self):
        """Run monitor with automatic restart on failure."""
        while True:
            try:
                self.logger.info("Starting frequency monitor...")
                self.monitor = FrequencyMonitor()
                self.monitor.run(simulator_mode=False)  # Real hardware
                
            except KeyboardInterrupt:
                self.logger.info("Shutdown requested by user")
                break
                
            except Exception as e:
                self.logger.error(f"Monitor crashed: {e}", exc_info=True)
                
                if not self.should_restart():
                    self.logger.critical("Maximum restart attempts reached. Exiting.")
                    sys.exit(1)
                    
                self.restart_count += 1
                self.last_restart_time = time.time()
                
                self.logger.warning(f"Restarting in 10 seconds... (attempt {self.restart_count}/{self.max_restarts})")
                time.sleep(10)
                
            finally:
                if self.monitor:
                    self.monitor.cleanup()

def main():
    """Main entry point."""
    # Setup signal handlers
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down...")
        sys.exit(0)
        
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run production monitor
    prod_monitor = ProductionMonitor()
    prod_monitor.run_with_restart()

if __name__ == "__main__":
    main()
