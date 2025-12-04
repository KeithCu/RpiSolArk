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
from collections import Counter

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
        pulse_count, actual_elapsed = self.optocoupler.count_optocoupler_pulses(duration)
        
        print(f"\nFinal pulse count: {pulse_count} in {actual_elapsed:.3f}s (requested: {duration:.2f}s)")
        
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
        
        # Count pulses over duration with debouncing
        pulse_count, actual_elapsed = self.optocoupler.count_optocoupler_pulses(duration, debounce_time=0.001)
        
        # Calculate frequency using actual elapsed time for accuracy
        frequency = self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration, actual_duration=actual_elapsed)
        
        print(f"Pulse count: {pulse_count}")
        print(f"Requested duration: {duration:.2f}s")
        print(f"Actual elapsed: {actual_elapsed:.3f}s")
        
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
    
    
    def test_timing_accuracy(self, num_samples: int = 20, duration: float = 2.0):
        """Test timing accuracy - compare requested duration vs actual elapsed time."""
        print(f"\n=== Timing Accuracy Test ({num_samples} samples of {duration}s each) ===")
        print("This test measures the actual elapsed time and compares frequency calculations")
        print("using requested duration vs actual elapsed time.\n")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return
        
        print(f"{'Sample':<8} {'Pulses':<8} {'Requested':<12} {'Actual':<12} {'Diff (ms)':<12} {'Freq (req)':<12} {'Freq (act)':<12} {'Error (Hz)':<12}")
        print("-" * 100)
        
        timing_errors = []
        frequency_errors = []
        
        for i in range(num_samples):
            # Count pulses - now returns both pulse_count and actual_elapsed
            pulse_count, actual_elapsed = self.optocoupler.count_optocoupler_pulses(duration, debounce_time=0.0)
            
            # Calculate frequency with requested duration (old method - for comparison)
            freq_requested = self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration)
            
            # Calculate frequency with actual elapsed time (new accurate method)
            freq_actual = self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration, actual_duration=actual_elapsed)
            
            # Calculate differences
            time_diff_ms = (actual_elapsed - duration) * 1000
            freq_error = freq_requested - freq_actual if (freq_requested and freq_actual) else 0
            
            timing_errors.append(time_diff_ms)
            frequency_errors.append(freq_error)
            
            print(f"{i+1:<8} {pulse_count:<8} {duration:<12.6f} {actual_elapsed:<12.6f} "
                  f"{time_diff_ms:<12.3f} {freq_requested:<12.3f} {freq_actual:<12.3f} {freq_error:<12.3f}")
        
        # Statistics
        print("\n" + "=" * 100)
        print("Statistics:")
        print(f"  Timing error (actual - requested):")
        if timing_errors:
            mean_timing = sum(timing_errors) / len(timing_errors)
            variance = sum((x - mean_timing)**2 for x in timing_errors) / len(timing_errors)
            std_timing = variance ** 0.5
            print(f"    Mean: {mean_timing:.3f} ms")
            print(f"    Min:  {min(timing_errors):.3f} ms")
            print(f"    Max:  {max(timing_errors):.3f} ms")
            print(f"    Std:  {std_timing:.3f} ms")
        
        print(f"\n  Frequency error (using requested vs actual duration):")
        if frequency_errors:
            mean_freq = sum(frequency_errors) / len(frequency_errors)
            variance = sum((x - mean_freq)**2 for x in frequency_errors) / len(frequency_errors)
            std_freq = variance ** 0.5
            print(f"    Mean: {mean_freq:.3f} Hz")
            print(f"    Min:  {min(frequency_errors):.3f} Hz")
            print(f"    Max:  {max(frequency_errors):.3f} Hz")
            print(f"    Std:  {std_freq:.3f} Hz")
        
        # Analysis
        if frequency_errors:
            avg_freq_error = sum(frequency_errors) / len(frequency_errors)
            max_freq_error = max(abs(x) for x in frequency_errors)
            print(f"\n  Analysis:")
            if abs(avg_freq_error) > 0.01 or max_freq_error > 0.05:
                print(f"    ⚠️  Significant frequency error detected!")
                print(f"    💡 Average error: {avg_freq_error:.3f} Hz")
                print(f"    💡 Max error: {max_freq_error:.3f} Hz")
                print(f"    💡 Using actual elapsed time would improve accuracy")
                print(f"    💡 For 60 Hz, this could explain readings of 60.00-60.50 Hz")
            else:
                print(f"    ✅ Timing error is small, frequency calculation is accurate")
                print(f"    💡 Timing discrepancy is not the main cause of frequency variation")
    
    def test_pulse_count_analysis(self, num_samples: int = 50, duration: float = 2.0):
        """Analyze pulse count patterns to understand frequency variation."""
        print(f"\n=== Pulse Count Analysis ({num_samples} samples of {duration}s each) ===")
        print("This test analyzes pulse count patterns to understand if variation is due to")
        print("actual frequency changes or other factors.\n")
        
        if not self.optocoupler.optocoupler_initialized:
            print("❌ Optocoupler not initialized")
            return
        
        pulse_counts = []
        actual_times = []
        frequencies_actual = []
        
        for i in range(num_samples):
            # Count pulses - now returns both pulse_count and actual_elapsed
            pulse_count, actual_elapsed = self.optocoupler.count_optocoupler_pulses(duration, debounce_time=0.0)
            
            pulse_counts.append(pulse_count)
            actual_times.append(actual_elapsed)
            
            # Calculate frequency using actual elapsed time
            freq = self.optocoupler.calculate_frequency_from_pulses(pulse_count, duration, actual_duration=actual_elapsed)
            frequencies_actual.append(freq)
        
        # Analyze pulse count distribution
        count_distribution = Counter(pulse_counts)
        
        print("Pulse Count Distribution:")
        print(f"{'Count':<8} {'Frequency':<12} {'Percentage':<12} {'Freq (Hz)':<12}")
        print("-" * 50)
        for count in sorted(count_distribution.keys()):
            freq_val = count / (duration * 4)  # Approximate frequency
            percentage = (count_distribution[count] / num_samples) * 100
            print(f"{count:<8} {count_distribution[count]:<12} {percentage:<12.1f} {freq_val:<12.3f}")
        
        # Statistics
        print(f"\nStatistics (using actual elapsed time):")
        if frequencies_actual:
            valid_freqs = [f for f in frequencies_actual if f is not None]
            if valid_freqs:
                mean_freq = sum(valid_freqs) / len(valid_freqs)
                min_freq = min(valid_freqs)
                max_freq = max(valid_freqs)
                variance = sum((x - mean_freq)**2 for x in valid_freqs) / len(valid_freqs)
                std_freq = variance ** 0.5
                
                print(f"  Frequency range: {min_freq:.3f} - {max_freq:.3f} Hz")
                print(f"  Mean frequency: {mean_freq:.3f} Hz")
                print(f"  Std deviation: {std_freq:.3f} Hz")
                print(f"  Range: {max_freq - min_freq:.3f} Hz")
                
                # Expected for stable 60.00 Hz utility
                expected_freq = 60.00
                mean_error = abs(mean_freq - expected_freq)
                print(f"\n  Comparison to expected 60.00 Hz:")
                print(f"    Mean error: {mean_error:.3f} Hz")
                print(f"    Max deviation: {max(abs(f - expected_freq) for f in valid_freqs):.3f} Hz")
                
                if std_freq > 0.05:
                    print(f"\n  ⚠️  High frequency variation detected (std: {std_freq:.3f} Hz)")
                    print(f"  💡 This suggests either:")
                    print(f"     - Actual utility frequency is varying")
                    print(f"     - Pulse counting has some inconsistency")
                    print(f"     - There may be noise or edge detection issues")
                else:
                    print(f"\n  ✅ Frequency is relatively stable (std: {std_freq:.3f} Hz)")
        
        # Pulse count statistics
        print(f"\nPulse Count Statistics:")
        mean_pulses = sum(pulse_counts) / len(pulse_counts)
        min_pulses = min(pulse_counts)
        max_pulses = max(pulse_counts)
        variance = sum((x - mean_pulses)**2 for x in pulse_counts) / len(pulse_counts)
        std_pulses = variance ** 0.5
        
        print(f"  Range: {min_pulses} - {max_pulses} pulses")
        print(f"  Mean: {mean_pulses:.2f} pulses")
        print(f"  Std deviation: {std_pulses:.2f} pulses")
        print(f"  Expected for 60.00 Hz: {60.0 * duration * 4:.0f} pulses")
        
        # Check if pulse count variation is quantized (should be integer steps)
        unique_counts = sorted(set(pulse_counts))
        print(f"\n  Unique pulse counts: {unique_counts}")
        if len(unique_counts) > 5:
            print(f"  ⚠️  Many different pulse counts - suggests real frequency variation or counting issues")
        else:
            print(f"  ✅ Pulse counts are clustered around a few values")
    
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
                pulse_count, actual_elapsed = self.optocoupler.count_optocoupler_pulses(
                    measurement_interval, debounce_time=0.001
                )
                
                # Calculate frequency from the pulse count using actual elapsed time
                frequency = self.optocoupler.calculate_frequency_from_pulses(
                    pulse_count, measurement_interval, actual_duration=actual_elapsed
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
        
        # Test 4: Timing Accuracy Test (NEW - critical for frequency accuracy)
        self.test_timing_accuracy(num_samples=3, duration=2.0)
        
        # Test 5: Pulse Count Analysis (NEW - understand variation sources)
        self.test_pulse_count_analysis(num_samples=5, duration=2.0)
        
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
