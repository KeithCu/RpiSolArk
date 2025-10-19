#!/usr/bin/env python3
"""
Fast frequency measurement optimized for 1-2 second accuracy.
Uses sudo for high thread priority and optimized polling.
"""

import sys
import os
import time
import logging
import statistics
import threading
import psutil

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

class FastFrequencyMeasurer:
    """High-performance frequency measurement with sudo optimizations."""
    
    def __init__(self, gpio_pin=26, pulses_per_cycle=2):
        self.gpio_pin = gpio_pin
        self.pulses_per_cycle = pulses_per_cycle
        self.gpio_available = GPIO_AVAILABLE
        
        # Setup high-priority threading
        self._setup_high_priority()
        
        if self.gpio_available:
            self._setup_gpio()
    
    def _setup_high_priority(self):
        """Setup maximum thread priority using sudo capabilities."""
        try:
            # Set process to real-time priority (requires sudo)
            current_process = psutil.Process()
            
            # Try to set to real-time priority
            if hasattr(psutil, 'REALTIME_PRIORITY_CLASS'):
                current_process.nice(psutil.REALTIME_PRIORITY_CLASS)
                print("✅ Set to REALTIME priority")
            else:
                # On Linux, use nice value -20 (highest priority)
                os.nice(-20)
                print("✅ Set nice value to -20 (highest priority)")
                
        except (PermissionError, OSError) as e:
            print(f"⚠️  Could not set high priority: {e}")
            print("💡 Run with 'sudo python fast_frequency_measurement.py' for best results")
        except Exception as e:
            print(f"⚠️  Priority setup failed: {e}")
    
    def _setup_gpio(self):
        """Setup GPIO for high-speed polling."""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print(f"✅ GPIO {self.gpio_pin} configured for high-speed polling")
        except Exception as e:
            print(f"❌ GPIO setup failed: {e}")
            self.gpio_available = False
    
    def _optimize_for_speed(self):
        """Optimize system for maximum polling speed."""
        try:
            # Set CPU affinity to single core for consistency
            current_process = psutil.Process()
            current_process.cpu_affinity([0])  # Pin to CPU 0
            
            # Set thread priority to maximum
            current_thread = threading.current_thread()
            if hasattr(current_thread, 'set_priority'):
                current_thread.set_priority(threading.HIGHEST_PRIORITY)
            
            print("✅ System optimized for high-speed polling")
            
        except Exception as e:
            print(f"⚠️  Speed optimization failed: {e}")
    
    def fast_measurement(self, duration=1.0, samples=3):
        """
        Fast frequency measurement optimized for 1-2 second accuracy.
        
        Args:
            duration: Measurement duration in seconds (1.0-2.0 recommended)
            samples: Number of samples to average (3-5 recommended)
            
        Returns:
            Average frequency in Hz, or None if measurement failed
        """
        if not self.gpio_available:
            print("❌ GPIO not available")
            return None
        
        print(f"🚀 Fast measurement: {duration}s duration, {samples} samples")
        
        # Optimize system for speed
        self._optimize_for_speed()
        
        frequencies = []
        
        for i in range(samples):
            print(f"  Sample {i+1}/{samples}: ", end="", flush=True)
            
            # High-speed polling
            start_time = time.perf_counter()
            pulse_count = 0
            last_state = GPIO.input(self.gpio_pin)
            
            # Ultra-fast polling loop (no sleep, no debouncing)
            while time.perf_counter() - start_time < duration:
                current_state = GPIO.input(self.gpio_pin)
                if last_state == 1 and current_state == 0:  # Falling edge
                    pulse_count += 1
                last_state = current_state
                # No sleep for maximum speed
            
            elapsed = time.perf_counter() - start_time
            frequency = pulse_count / (elapsed * self.pulses_per_cycle)
            frequencies.append(frequency)
            
            print(f"{frequency:.3f} Hz")
        
        # Calculate statistics
        avg_frequency = statistics.mean(frequencies)
        std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
        
        # Calculate accuracy
        target_freq = 60.01
        error = abs(avg_frequency - target_freq)
        accuracy = (1 - error / target_freq) * 100
        
        print(f"\n📊 Results:")
        print(f"  Average frequency: {avg_frequency:.3f} Hz")
        print(f"  Standard deviation: {std_dev:.3f} Hz")
        print(f"  Error from 60.01 Hz: {error:.3f} Hz")
        print(f"  Accuracy: {accuracy:.2f}%")
        
        # Performance assessment
        if error < 0.1:
            print(f"  🎯 Excellent accuracy!")
        elif error < 0.5:
            print(f"  ✅ Good accuracy")
        else:
            print(f"  ⚠️  Could be improved")
        
        return avg_frequency
    
    def ultra_fast_measurement(self, duration=1.0):
        """
        Ultra-fast single measurement for maximum speed.
        
        Args:
            duration: Measurement duration in seconds
            
        Returns:
            Frequency in Hz, or None if measurement failed
        """
        if not self.gpio_available:
            return None
        
        print(f"⚡ Ultra-fast measurement: {duration}s")
        
        # Optimize for maximum speed
        self._optimize_for_speed()
        
        # Single high-speed measurement
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = GPIO.input(self.gpio_pin)
        
        # Maximum speed polling
        while time.perf_counter() - start_time < duration:
            current_state = GPIO.input(self.gpio_pin)
            if last_state == 1 and current_state == 0:
                pulse_count += 1
            last_state = current_state
        
        elapsed = time.perf_counter() - start_time
        frequency = pulse_count / (elapsed * self.pulses_per_cycle)
        
        # Calculate accuracy
        target_freq = 60.01
        error = abs(frequency - target_freq)
        accuracy = (1 - error / target_freq) * 100
        
        print(f"  Frequency: {frequency:.3f} Hz")
        print(f"  Error: {error:.3f} Hz")
        print(f"  Accuracy: {accuracy:.2f}%")
        
        return frequency
    
    def cleanup(self):
        """Cleanup resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
                print("✅ GPIO cleanup completed")
            except Exception as e:
                print(f"⚠️  GPIO cleanup error: {e}")

def main():
    """Test fast frequency measurements."""
    print("🚀 FAST FREQUENCY MEASUREMENT TEST")
    print("=" * 50)
    print("Optimized for 1-2 second accuracy with sudo")
    print("=" * 50)
    
    # Initialize fast measurer
    measurer = FastFrequencyMeasurer()
    
    if not measurer.gpio_available:
        print("❌ Cannot proceed without GPIO")
        return
    
    print("\n📊 Test 1: Ultra-fast single measurement (1s)")
    freq1 = measurer.ultra_fast_measurement(1.0)
    
    print("\n📊 Test 2: Fast averaged measurement (1s, 3 samples)")
    freq2 = measurer.fast_measurement(1.0, 3)
    
    print("\n📊 Test 3: Fast averaged measurement (2s, 3 samples)")
    freq3 = measurer.fast_measurement(2.0, 3)
    
    print("\n📊 Test 4: High-precision fast measurement (2s, 5 samples)")
    freq4 = measurer.fast_measurement(2.0, 5)
    
    print(f"\n🏁 Fast measurement testing completed!")
    print(f"💡 For best results, run with: sudo python fast_frequency_measurement.py")
    
    # Cleanup
    measurer.cleanup()

if __name__ == "__main__":
    main()
