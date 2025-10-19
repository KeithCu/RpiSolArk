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
        self.config = self._create_test_config()
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
        
    def _create_test_config(self) -> dict:
        """Create test configuration for GPIO 26."""
        return {
            'hardware': {
                'optocoupler': {
                    'enabled': True,
                    'gpio_pin': 26,  # GPIO 26 as requested
                    'pulses_per_cycle': 2,  # H11A1 gives 2 pulses per AC cycle
                    'measurement_duration': 1.0
                }
            }
        }
    
    def test_gpio_setup(self):
        """Test GPIO setup and basic functionality."""
        print("\n=== GPIO Setup Test ===")
        
        if not GPIO_AVAILABLE:
            print("❌ RPi.GPIO not available - cannot test hardware")
            return False
            
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return False
            
        print(f"✅ Optocoupler initialized on GPIO {self.optocoupler.optocoupler_pin}")
        print(f"✅ Pulses per cycle: {self.optocoupler.pulses_per_cycle}")
        print(f"✅ Measurement duration: {self.optocoupler.measurement_duration}s")
        return True
    
    def test_pulse_detection(self, duration: float = 10.0):
        """Test real-time pulse detection."""
        print(f"\n=== Pulse Detection Test ({duration}s) ===")
        print("Monitoring for pulses... Press Ctrl+C to stop early")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return
            
        start_time = time.time()
        last_count = 0
        
        try:
            while time.time() - start_time < duration:
                current_count = self.optocoupler.pulse_count
                if current_count != last_count:
                    elapsed = time.time() - start_time
                    print(f"Pulse #{current_count} detected at {elapsed:.2f}s")
                    last_count = current_count
                time.sleep(0.1)  # Check every 100ms
                
        except KeyboardInterrupt:
            print("\nTest interrupted by user")
            
        final_count = self.optocoupler.pulse_count
        elapsed_time = time.time() - start_time
        print(f"\nFinal pulse count: {final_count} in {elapsed_time:.2f}s")
        
        if final_count > 0:
            print("✅ Pulses detected successfully")
        else:
            print("⚠️  No pulses detected - check connections")
    
    def test_frequency_measurement(self, duration: float = 5.0):
        """Test frequency measurement."""
        print(f"\n=== Frequency Measurement Test ({duration}s) ===")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return None
            
        # Reset pulse counter
        with self.optocoupler.pulse_count_lock:
            self.optocoupler.pulse_count = 0
            
        print(f"Counting pulses for {duration} seconds...")
        start_time = time.time()
        
        # Count pulses over duration
        pulse_count = self.optocoupler.count_optocoupler_pulses(duration)
        
        # Calculate frequency
        frequency = self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
        
        print(f"Pulse count: {pulse_count}")
        print(f"Duration: {duration:.2f}s")
        
        if frequency is not None:
            print(f"Calculated frequency: {frequency:.2f} Hz")
            
            # Validate frequency range (typical AC is 50-60 Hz)
            if 45 <= frequency <= 65:
                print("✅ Frequency within expected range (45-65 Hz)")
            else:
                print(f"⚠️  Frequency outside typical range (45-65 Hz): {frequency:.2f} Hz")
        else:
            print("❌ Could not calculate frequency")
            
        return frequency
    
    def test_continuous_monitoring(self, duration: float = 30.0):
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
                # Reset and count pulses
                with self.optocoupler.pulse_count_lock:
                    self.optocoupler.pulse_count = 0
                
                time.sleep(measurement_interval)
                
                # Get pulse count and calculate frequency
                with self.optocoupler.pulse_count_lock:
                    pulse_count = self.optocoupler.pulse_count
                
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
        print("🔧 Optocoupler Test Suite")
        print("=" * 50)
        
        # Test 1: GPIO Setup
        if not self.test_gpio_setup():
            print("\n❌ GPIO setup failed - cannot continue with other tests")
            return
            
        # Test 2: Pulse Detection
        self.test_pulse_detection(10.0)
        
        # Test 3: Frequency Measurement
        frequency = self.test_frequency_measurement(5.0)
        
        # Test 4: Continuous Monitoring (optional)
        if frequency is not None and frequency > 0:
            print("\nWould you like to run continuous monitoring? (y/n): ", end="")
            try:
                response = input().lower().strip()
                if response in ['y', 'yes']:
                    self.test_continuous_monitoring(30.0)
            except KeyboardInterrupt:
                print("\nSkipping continuous monitoring")
        
        print("\n🏁 Test suite completed")
    
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
