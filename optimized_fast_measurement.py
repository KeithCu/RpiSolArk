#!/usr/bin/env python3
"""
Optimized fast frequency measurement for 1-2 second accuracy.
Best performance with sudo, good performance without.
"""

import sys
import os
import time
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

class OptimizedFastMeasurer:
    """Optimized for 1-2 second frequency measurements with maximum accuracy."""
    
    def __init__(self, gpio_pin=26, pulses_per_cycle=2):
        self.gpio_pin = gpio_pin
        self.pulses_per_cycle = pulses_per_cycle
        self.gpio_available = GPIO_AVAILABLE
        self.sudo_available = False
        
        # Setup optimizations
        self._setup_optimizations()
        
        if self.gpio_available:
            self._setup_gpio()
    
    def _setup_optimizations(self):
        """Setup all available optimizations."""
        try:
            # Try to set highest priority
            os.nice(-20)
            self.sudo_available = True
            print("✅ High priority enabled (sudo)")
        except (PermissionError, OSError):
            try:
                # Try medium priority
                os.nice(-5)
                print("✅ Medium priority enabled")
            except (PermissionError, OSError):
                print("⚠️  Normal priority (run with sudo for best results)")
        
        # Set CPU affinity
        try:
            current_process = psutil.Process()
            current_process.cpu_affinity([0])
            print("✅ CPU affinity set to core 0")
        except Exception as e:
            print(f"⚠️  CPU affinity failed: {e}")
    
    def _setup_gpio(self):
        """Setup GPIO for maximum speed."""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except Exception as e:
            print(f"❌ GPIO setup failed: {e}")
            self.gpio_available = False
    
    def fast_measure(self, duration=1.5, samples=3):
        """
        Optimized fast frequency measurement.
        
        Args:
            duration: Measurement duration (1.0-2.0 seconds)
            samples: Number of samples to average (3-5 recommended)
            
        Returns:
            (frequency, accuracy, error) tuple
        """
        if not self.gpio_available:
            return None, 0, 0
        
        frequencies = []
        
        for i in range(samples):
            # High-speed measurement
            start_time = time.perf_counter()
            pulse_count = 0
            last_state = GPIO.input(self.gpio_pin)
            
            # Ultra-fast polling (no sleep, no debouncing)
            while time.perf_counter() - start_time < duration:
                current_state = GPIO.input(self.gpio_pin)
                if last_state == 1 and current_state == 0:
                    pulse_count += 1
                last_state = current_state
            
            elapsed = time.perf_counter() - start_time
            frequency = pulse_count / (elapsed * self.pulses_per_cycle)
            frequencies.append(frequency)
        
        # Calculate results
        avg_frequency = statistics.mean(frequencies)
        std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
        
        target_freq = 60.01
        error = abs(avg_frequency - target_freq)
        accuracy = (1 - error / target_freq) * 100
        
        return avg_frequency, accuracy, error
    
    def single_fast_measure(self, duration=1.0):
        """
        Single fast measurement for maximum speed.
        
        Args:
            duration: Measurement duration in seconds
            
        Returns:
            (frequency, accuracy, error) tuple
        """
        if not self.gpio_available:
            return None, 0, 0
        
        # Single high-speed measurement
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = GPIO.input(self.gpio_pin)
        
        while time.perf_counter() - start_time < duration:
            current_state = GPIO.input(self.gpio_pin)
            if last_state == 1 and current_state == 0:
                pulse_count += 1
            last_state = current_state
        
        elapsed = time.perf_counter() - start_time
        frequency = pulse_count / (elapsed * self.pulses_per_cycle)
        
        target_freq = 60.01
        error = abs(frequency - target_freq)
        accuracy = (1 - error / target_freq) * 100
        
        return frequency, accuracy, error
    
    def cleanup(self):
        """Cleanup resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
            except Exception:
                pass

def main():
    """Test optimized fast measurements."""
    print("⚡ OPTIMIZED FAST FREQUENCY MEASUREMENT")
    print("=" * 50)
    
    measurer = OptimizedFastMeasurer()
    
    if not measurer.gpio_available:
        print("❌ GPIO not available")
        return
    
    print(f"\n📊 Testing different configurations:")
    print(f"Target: 60.01 Hz")
    print(f"Sudo available: {'Yes' if measurer.sudo_available else 'No'}")
    
    # Test configurations
    configs = [
        (1.0, 1, "Ultra-fast single (1s)"),
        (1.0, 3, "Fast averaged (1s, 3 samples)"),
        (1.5, 3, "Balanced (1.5s, 3 samples)"),
        (2.0, 3, "High precision (2s, 3 samples)"),
        (2.0, 5, "Maximum accuracy (2s, 5 samples)")
    ]
    
    results = []
    
    for duration, samples, description in configs:
        print(f"\n🔧 {description}:")
        
        if samples == 1:
            freq, accuracy, error = measurer.single_fast_measure(duration)
        else:
            freq, accuracy, error = measurer.fast_measure(duration, samples)
        
        if freq is not None:
            print(f"  Frequency: {freq:.3f} Hz")
            print(f"  Error: {error:.3f} Hz")
            print(f"  Accuracy: {accuracy:.2f}%")
            
            # Performance rating
            if error < 0.1:
                rating = "🎯 Excellent"
            elif error < 0.5:
                rating = "✅ Very Good"
            elif error < 1.0:
                rating = "✅ Good"
            else:
                rating = "⚠️  Needs Improvement"
            
            print(f"  Rating: {rating}")
            
            results.append((description, freq, error, accuracy, duration))
        else:
            print("  ❌ Measurement failed")
    
    # Summary
    print(f"\n📈 PERFORMANCE SUMMARY:")
    print(f"{'Configuration':<30} {'Frequency':<10} {'Error':<8} {'Accuracy':<10} {'Time':<6}")
    print("-" * 70)
    
    for desc, freq, error, accuracy, duration in results:
        print(f"{desc:<30} {freq:<10.3f} {error:<8.3f} {accuracy:<10.2f}% {duration:<6.1f}s")
    
    # Best recommendation
    if results:
        best = min(results, key=lambda x: x[2])  # Lowest error
        print(f"\n🏆 BEST CONFIGURATION: {best[0]}")
        print(f"   Frequency: {best[1]:.3f} Hz")
        print(f"   Error: {best[2]:.3f} Hz")
        print(f"   Accuracy: {best[3]:.2f}%")
        print(f"   Duration: {best[4]:.1f}s")
    
    print(f"\n💡 For maximum performance, run with: sudo python optimized_fast_measurement.py")
    
    measurer.cleanup()

if __name__ == "__main__":
    main()
