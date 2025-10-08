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
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logging.warning(f"Config file {self.config_file} not found. Using defaults.")
            return self._get_default_config()
        except yaml.YAMLError as e:
            logging.error(f"Error parsing config file: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            'hardware': {
                'gpio_pin': 17, 'led_green': 18, 'led_red': 27,
                'lcd_address': 0x27, 'lcd_port': 1, 'lcd_cols': 16, 'lcd_rows': 2
            },
            'sampling': {
                'sample_rate': 2.0, 'buffer_duration': 300, 'min_freq': 40.0, 'max_freq': 80.0
            },
            'analysis': {
                'allan_variance_tau': 10.0,
                'generator_thresholds': {'allan_variance': 1e-9, 'std_dev': 0.05, 'kurtosis': 0.5}
            },
            'logging': {
                'hourly_log_file': 'hourly_status.csv', 'log_level': 'INFO',
                'log_file': 'monitor.log', 'max_log_size': 10485760, 'backup_count': 5
            },
            'health': {
                'watchdog_timeout': 30.0, 'memory_warning_threshold': 0.8, 'cpu_warning_threshold': 0.8
            },
            'app': {
                'simulator_mode': True, 'display_update_interval': 1.0, 'cleanup_on_exit': True
            }
        }
    
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
        """Get configuration value as float with validation."""
        value = self.get(key_path, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            logging.warning(f"Invalid float value for {key_path}: {value}. Using default: {default}")
            return float(default)
    
    def get_int(self, key_path: str, default: int = 0) -> int:
        """Get configuration value as int with validation."""
        value = self.get(key_path, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            logging.warning(f"Invalid int value for {key_path}: {value}. Using default: {default}")
            return int(default)


class Logger:
    """Enhanced logging setup."""
    
    def __init__(self, config: Config):
        self.config = config
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = getattr(logging, self.config.get('logging.log_level', 'INFO').upper())
        log_file = self.config.get('logging.log_file', 'monitor.log')
        max_size = self.config.get('logging.max_log_size', 10485760)
        backup_count = self.config.get('logging.backup_count', 5)
        
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
