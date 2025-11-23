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
    """Configuration management class with validation and defaults."""
    
    def __init__(self, config_file: str = "config.yaml"):
        self.config_file = config_file
        self.config = self._load_config()
        self._validate_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)
                return config if config is not None else {}
        except FileNotFoundError:
            # Return empty config if file doesn't exist - tests can rely on defaults
            return {}
        except Exception as e:
            # Log warning but continue with empty config
            print(f"Warning: Failed to load config from {self.config_file}: {e}")
            return {}
    
    def _validate_config(self):
        """Validate configuration - requires complete config.yaml file."""
        if not self.config:
            raise ValueError(f"Configuration file '{self.config_file}' is empty or missing. Please provide a complete config.yaml file.")
        
        # Validate critical configuration values
        self._validate_critical_values()
        
        print(f"Configuration validated successfully")
    
    def _validate_critical_values(self):
        """Validate critical configuration values."""
        # Check that all required top-level sections exist
        required_sections = [
            'hardware', 'sampling', 'analysis', 'state_machine', 
            'logging', 'health', 'memory'
        ]
        
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Missing required configuration section: '{section}'. Please check your config.yaml file.")
        
        # Validate hardware section
        hardware = self.config['hardware']
        required_hardware_keys = [
            'gpio_pin', 'led_green', 'led_red', 'reset_button', 'button_pin',
            'lcd_address', 'lcd_port', 'lcd_cols', 'lcd_rows', 'display_timeout_seconds'
        ]
        
        for key in required_hardware_keys:
            if key not in hardware:
                raise ValueError(f"Missing required hardware configuration: '{key}'. Please check your config.yaml file.")
        
        # Validate optocoupler configuration
        if 'optocoupler' not in hardware:
            raise ValueError("Missing required 'optocoupler' configuration in hardware section.")
        
        optocoupler = hardware['optocoupler']
        if 'enabled' not in optocoupler:
            raise ValueError("Missing required 'enabled' setting in optocoupler configuration.")
        
        if optocoupler['enabled']:
            if 'primary' not in optocoupler:
                raise ValueError("Missing required 'primary' optocoupler configuration.")
            
            primary = optocoupler['primary']
            required_primary_keys = ['gpio_pin', 'name', 'pulses_per_cycle', 'measurement_duration']
            for key in required_primary_keys:
                if key not in primary:
                    raise ValueError(f"Missing required primary optocoupler configuration: '{key}'.")
        
        # Validate GPIO pins are integers
        gpio_pins = [
            'hardware.gpio_pin',
            'hardware.led_green', 
            'hardware.led_red',
            'hardware.reset_button',
            'hardware.button_pin',
            'hardware.lcd_address'
        ]
        
        for pin_path in gpio_pins:
            value = self.get(pin_path)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"Invalid GPIO pin value for {pin_path}: {value}. Must be non-negative integer.")
        
        # Validate timeouts are positive floats
        timeout_paths = [
            'state_machine.transition_timeout',
            'state_machine.zero_voltage_threshold',
            'sampling.sample_rate',
            'sampling.buffer_duration'
        ]
        
        for timeout_path in timeout_paths:
            value = self.get(timeout_path)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"Invalid timeout value for {timeout_path}: {value}. Must be positive number.")
        
        # Validate frequency ranges
        min_freq = self.get('sampling.min_freq')
        max_freq = self.get('sampling.max_freq')
        if min_freq >= max_freq:
            raise ValueError(f"Invalid frequency range: min_freq ({min_freq}) must be less than max_freq ({max_freq})")
        
        # Validate thresholds are positive
        thresholds = self.get('analysis.generator_thresholds')
        for threshold_name, threshold_value in thresholds.items():
            if not isinstance(threshold_value, (int, float)) or threshold_value <= 0:
                raise ValueError(f"Invalid threshold value for analysis.generator_thresholds.{threshold_name}: {threshold_value}. Must be positive number.")
        
        # Validate state machine configuration
        state_machine = self.config['state_machine']
        if 'persistent_state_enabled' in state_machine and state_machine['persistent_state_enabled']:
            if 'state_file' not in state_machine:
                raise ValueError("persistent_state_enabled is True but state_file is not configured.")
        
    
    def validate_config(self) -> bool:
        """Public method to validate configuration."""
        try:
            self._validate_critical_values()
            return True
        except Exception as e:
            print(f"Configuration validation failed: {e}")
            return False
    
    def get(self, key_path: str):
        """Get configuration value using dot notation (e.g., 'hardware.gpio_pin')."""
        keys = key_path.split('.')
        value = self.config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError) as e:
            raise KeyError(f"Configuration key '{key_path}' not found. Please check your config.yaml file. Error: {e}")
    
    def get_float(self, key_path: str) -> float:
        """Get configuration value as float."""
        value = self.get(key_path)
        return float(value)
    
    def get_int(self, key_path: str) -> int:
        """Get configuration value as int."""
        value = self.get(key_path)
        return int(value)
    
    def __getitem__(self, key):
        """Support subscripting for backward compatibility."""
        return self.config[key]
    
    def __setitem__(self, key, value):
        """Support item assignment."""
        self.config[key] = value


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
