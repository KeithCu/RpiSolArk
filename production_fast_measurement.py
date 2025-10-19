#!/usr/bin/env python3
"""
Production-ready fast frequency measurement.
Optimized for 1-2 second accuracy with sudo support.
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

class ProductionFastMeasurer:
    """Production-ready fast frequency measurement with sudo optimization."""
    
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
            # Try to set highest priority (requires sudo)
            os.nice(-20)
            self.sudo_available = True
        except (PermissionError, OSError):
            try:
                # Try medium priority
                os.nice(-5)
            except (PermissionError, OSError):
                pass  # Continue with normal priority
        
        # Set CPU affinity for consistency
        try:
            current_process = psutil.Process()
            current_process.cpu_affinity([0])
        except Exception:
            pass  # Continue if affinity fails
    
    def _setup_gpio(self):
        """Setup GPIO for high-speed polling."""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except Exception as e:
            raise RuntimeError(f"GPIO setup failed: {e}")
    
    def measure_frequency(self, duration=1.5, samples=3):
        """
        Fast frequency measurement optimized for production use.
        
        Args:
            duration: Measurement duration in seconds (1.0-2.0 recommended)
            samples: Number of samples to average (3-5 recommended)
            
        Returns:
            dict: {
                'frequency': float,  # Average frequency in Hz
                'accuracy': float,   # Accuracy percentage
                'error': float,      # Error from 60.01 Hz
                'std_dev': float,    # Standard deviation
                'samples': int,      # Number of samples taken
                'duration': float,   # Total measurement time
                'sudo_used': bool    # Whether sudo optimizations were used
            }
        """
        if not self.gpio_available:
            raise RuntimeError("GPIO not available")
        
        start_time = time.perf_counter()
        frequencies = []
        
        # Take multiple samples
        for i in range(samples):
            sample_start = time.perf_counter()
            pulse_count = 0
            last_state = GPIO.input(self.gpio_pin)
            
            # High-speed polling (no sleep, no debouncing)
            while time.perf_counter() - sample_start < duration:
                current_state = GPIO.input(self.gpio_pin)
                if last_state == 1 and current_state == 0:  # Falling edge
                    pulse_count += 1
                last_state = current_state
            
            sample_elapsed = time.perf_counter() - sample_start
            frequency = pulse_count / (sample_elapsed * self.pulses_per_cycle)
            frequencies.append(frequency)
        
        total_elapsed = time.perf_counter() - start_time
        
        # Calculate statistics
        avg_frequency = statistics.mean(frequencies)
        std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0
        
        # Calculate accuracy
        target_freq = 60.01
        error = abs(avg_frequency - target_freq)
        accuracy = (1 - error / target_freq) * 100
        
        return {
            'frequency': avg_frequency,
            'accuracy': accuracy,
            'error': error,
            'std_dev': std_dev,
            'samples': samples,
            'duration': total_elapsed,
            'sudo_used': self.sudo_available
        }
    
    def quick_measure(self, duration=1.0):
        """
        Single fast measurement for maximum speed.
        
        Args:
            duration: Measurement duration in seconds
            
        Returns:
            dict: Same format as measure_frequency but with single sample
        """
        if not self.gpio_available:
            raise RuntimeError("GPIO not available")
        
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = GPIO.input(self.gpio_pin)
        
        # Single high-speed measurement
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
        
        return {
            'frequency': frequency,
            'accuracy': accuracy,
            'error': error,
            'std_dev': 0.0,
            'samples': 1,
            'duration': elapsed,
            'sudo_used': self.sudo_available
        }
    
    def cleanup(self):
        """Cleanup resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
            except Exception:
                pass

def main():
    """Test production fast measurements."""
    print("🏭 PRODUCTION FAST FREQUENCY MEASUREMENT")
    print("=" * 50)
    
    try:
        measurer = ProductionFastMeasurer()
        
        print(f"GPIO Pin: {measurer.gpio_pin}")
        print(f"Sudo optimizations: {'Yes' if measurer.sudo_available else 'No'}")
        print(f"Target frequency: 60.01 Hz")
        
        # Test different configurations
        configs = [
            (1.0, 1, "Quick single (1s)"),
            (1.5, 3, "Balanced (1.5s, 3 samples)"),
            (2.0, 3, "High precision (2s, 3 samples)")
        ]
        
        results = []
        
        for duration, samples, description in configs:
            print(f"\n🔧 {description}:")
            
            try:
                if samples == 1:
                    result = measurer.quick_measure(duration)
                else:
                    result = measurer.measure_frequency(duration, samples)
                
                print(f"  Frequency: {result['frequency']:.3f} Hz")
                print(f"  Error: {result['error']:.3f} Hz")
                print(f"  Accuracy: {result['accuracy']:.2f}%")
                print(f"  Std Dev: {result['std_dev']:.3f} Hz")
                print(f"  Duration: {result['duration']:.2f}s")
                print(f"  Sudo used: {'Yes' if result['sudo_used'] else 'No'}")
                
                # Performance rating
                if result['error'] < 0.1:
                    rating = "🎯 Excellent"
                elif result['error'] < 0.5:
                    rating = "✅ Very Good"
                elif result['error'] < 1.0:
                    rating = "✅ Good"
                else:
                    rating = "⚠️  Needs Improvement"
                
                print(f"  Rating: {rating}")
                
                results.append((description, result))
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
        
        # Summary
        if results:
            print(f"\n📈 PERFORMANCE SUMMARY:")
            print(f"{'Configuration':<30} {'Frequency':<10} {'Error':<8} {'Accuracy':<10} {'Time':<6}")
            print("-" * 70)
            
            for desc, result in results:
                print(f"{desc:<30} {result['frequency']:<10.3f} {result['error']:<8.3f} {result['accuracy']:<10.2f}% {result['duration']:<6.2f}s")
            
            # Best result
            best = min(results, key=lambda x: x[1]['error'])
            print(f"\n🏆 BEST CONFIGURATION: {best[0]}")
            print(f"   Frequency: {best[1]['frequency']:.3f} Hz")
            print(f"   Error: {best[1]['error']:.3f} Hz")
            print(f"   Accuracy: {best[1]['accuracy']:.2f}%")
            print(f"   Duration: {best[1]['duration']:.2f}s")
        
        print(f"\n💡 For maximum performance, run with: sudo python production_fast_measurement.py")
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
    
    finally:
        if 'measurer' in locals():
            measurer.cleanup()

if __name__ == "__main__":
    main()
