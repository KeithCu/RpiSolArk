#!/usr/bin/env python3
"""
Configuration and logging management for the frequency monitor.
"""

import logging
import yaml
from pathlib import Path
from typing import Dict, Any
from logging.handlers import RotatingFileHandler


class Config:
    """Configuration management class."""
    
    def __init__(self, config_file: str = "config.yaml"):
        self.config_file = config_file
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        with open(self.config_file, 'r') as f:
            return yaml.safe_load(f)
    
    
    def get(self, key_path: str, default=None):
        """Get configuration value using dot notation (e.g., 'hardware.gpio_pin')."""
        keys = key_path.split('.')
        value = self.config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_float(self, key_path: str, default: float = 0.0) -> float:
        """Get configuration value as float."""
        value = self.get(key_path, default)
        return float(value)
    
    def get_int(self, key_path: str, default: int = 0) -> int:
        """Get configuration value as int."""
        value = self.get(key_path, default)
        return int(value)


class Logger:
    """Enhanced logging setup."""
    
    def __init__(self, config: Config):
        self.config = config
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = getattr(logging, self.config.get('logging.log_level').upper())
        log_file = self.config.get('logging.log_file')
        max_size = self.config.get('logging.max_log_size')
        backup_count = self.config.get('logging.backup_count')
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Setup file handler with rotation
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_size, backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        
        # Setup console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Configure root logger
        logging.basicConfig(
            level=log_level,
            handlers=[file_handler, console_handler]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Logging initialized")
