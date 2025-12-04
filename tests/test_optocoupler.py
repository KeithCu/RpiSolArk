#!/usr/bin/env python3
"""
Test module for optocoupler functionality.
Tests pulse detection and frequency measurement on GPIO 26.
"""

import sys
import os
import time
import logging
from typing import Optional

# Add parent directory to path to import optocoupler module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optocoupler import OptocouplerManager
from config import Config

# Hardware imports with graceful degradation
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. Running in simulation mode.")


class OptocouplerTester:
    """Test class for optocoupler functionality."""
    
    def __init__(self):
        self.logger = self._setup_logger()
        # Load actual config.yaml file - test should fail if config is invalid
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"config.yaml not found at {config_path}. Test requires a valid config.yaml file.")
        self.config = Config(config_path)
        self.optocoupler = OptocouplerManager(self.config, self.logger)
        
    def _setup_logger(self) -> logging.Logger:
        """Setup logging for the test."""
        logger = logging.getLogger('optocoupler_test')
        logger.setLevel(logging.DEBUG)
        
        # Create console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
        return logger
    
    def test_gpio_setup(self):
        """Test GPIO setup and basic functionality."""
        print("\n=== GPIO Setup Test ===")
        
        if not GPIO_AVAILABLE:
            print("❌ RPi.GPIO not available - cannot test hardware")
            return False
            
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return False
        
        # Access the primary optocoupler through the manager
        primary_optocoupler = self.optocoupler.optocouplers.get('primary')
        if not primary_optocoupler:
            print("❌ Primary optocoupler not found")
            return False
            
        print(f"✅ Optocoupler initialized on GPIO {primary_optocoupler.pin}")
        print(f"✅ Pulses per cycle: {primary_optocoupler.pulses_per_cycle}")
        print(f"✅ Measurement duration: {primary_optocoupler.measurement_duration}s")
        return True
    
    def test_pulse_detection(self, duration: float = 5.0):
        """Test real-time pulse detection using polling method."""
        print(f"\n=== Pulse Detection Test ({duration}s) ===")
        print("Monitoring for pulses using polling method...")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return
            
        # Use the same polling method as frequency measurement for consistency
        pulse_count = self.optocoupler.count_optocoupler_pulses(duration)
        
        print(f"\nFinal pulse count: {pulse_count} in {duration:.2f}s")
        
        if pulse_count > 0:
            print("✅ Pulses detected successfully")
        else:
            print("⚠️  No pulses detected - check connections")
    
    def test_frequency_measurement(self, duration: float = 5.0):
        """Test frequency measurement with improved precision."""
        print(f"\n=== Frequency Measurement Test ({duration}s) ===")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return None
            
        print(f"Counting pulses for {duration} seconds with high precision timing...")
        start_time = time.time()
        
        # Count pulses over duration with debouncing
        pulse_count = self.optocoupler.count_optocoupler_pulses(duration, debounce_time=0.001)
        
        # Calculate frequency
        frequency = self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
        
        print(f"Pulse count: {pulse_count}")
        print(f"Duration: {duration:.2f}s")
        
        if frequency is not None:
            print(f"Calculated frequency: {frequency:.3f} Hz")
            
            # Check how close to 60.01 Hz
            error = abs(frequency - 60.01)
            accuracy = (1 - error / 60.01) * 100
            
            print(f"Error from 60.01 Hz: {error:.3f} Hz")
            print(f"Accuracy: {accuracy:.2f}%")
            
            # Validate frequency range (typical AC is 50-60 Hz)
            if 45 <= frequency <= 65:
                print("✅ Frequency within expected range (45-65 Hz)")
                if error < 0.1:
                    print("🎯 Very close to target 60.01 Hz!")
                elif error < 0.5:
                    print("✅ Close to target 60.01 Hz")
                else:
                    print("⚠️  Somewhat off from target 60.01 Hz")
            else:
                print(f"⚠️  Frequency outside typical range (45-65 Hz): {frequency:.2f} Hz")
        else:
            print("❌ Could not calculate frequency")
            
        return frequency
    
    
    def test_continuous_monitoring(self, duration: float = 5.0):
        """Test continuous monitoring with frequency updates."""
        print(f"\n=== Continuous Monitoring Test ({duration}s) ===")
        print("Monitoring frequency every 2 seconds... Press Ctrl+C to stop")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return
            
        start_time = time.time()
        measurement_interval = 2.0  # Measure every 2 seconds
        
        try:
            while time.time() - start_time < duration:
                # Count pulses over the measurement interval
                pulse_count = self.optocoupler.count_optocoupler_pulses(
                    measurement_interval, debounce_time=0.001
                )
                
                # Calculate frequency from the pulse count
                frequency = self.optocoupler.calculate_frequency_from_pulses(
                    pulse_count, measurement_interval
                )
                
                elapsed = time.time() - start_time
                if frequency is not None:
                    print(f"[{elapsed:6.1f}s] {pulse_count:3d} pulses → {frequency:5.1f} Hz")
                else:
                    print(f"[{elapsed:6.1f}s] {pulse_count:3d} pulses → No signal")
                    
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
    
    def run_all_tests(self):
        """Run all optocoupler tests."""
        print("🔧 Enhanced Optocoupler Test Suite")
        print("=" * 50)
        
        # Test 1: GPIO Setup
        if not self.test_gpio_setup():
            print("\n❌ GPIO setup failed - cannot continue with other tests")
            return
            
        # Test 2: Pulse Detection (5 seconds)
        self.test_pulse_detection(5.0)
        
        # Test 3: Standard Frequency Measurement (5 seconds)
        frequency = self.test_frequency_measurement(5.0)
        
        print("\n🏁 Enhanced test suite completed")
        print(f"📊 Final Results:")
        if frequency is not None:
            print(f"  Frequency measurement: {frequency:.3f} Hz")
            error = abs(frequency - 60.01)
            print(f"  Error from 60.01 Hz: {error:.3f} Hz")
    
    def cleanup(self):
        """Cleanup resources."""
        if hasattr(self, 'optocoupler'):
            self.optocoupler.cleanup()
        print("🧹 Cleanup completed")


def main():
    """Main test function."""
    tester = OptocouplerTester()
    
    try:
        tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
    finally:
        tester.cleanup()


if __name__ == "__main__":
    main()
