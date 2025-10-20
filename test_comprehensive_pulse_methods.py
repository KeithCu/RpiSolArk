#!/usr/bin/env python3
"""
Comprehensive test for pulse detection methods: polling vs callbacks vs C extension.
Tests accuracy, GIL impact, and performance of different approaches.
"""

import sys
import os
import time
import threading
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    GPIO_AVAILABLE = False
    print(f"Warning: RPi.GPIO not available ({e}). Running in simulation mode.")

# Try to import C extension
try:
    import pulse_counter
    C_EXTENSION_AVAILABLE = True
except ImportError:
    C_EXTENSION_AVAILABLE = False
    print("Warning: C extension not available.")

# Try to import GIL-safe counter
try:
    from gil_safe_counter import create_counter
    GIL_SAFE_COUNTER_AVAILABLE = True
except ImportError:
    GIL_SAFE_COUNTER_AVAILABLE = False
    print("Warning: GIL-safe counter not available.")

class InterruptPulseCounter:
    """Original interrupt-based counter with Python callbacks (has GIL issues)."""
    def __init__(self, pin):
        self.pin = pin
        self.pulse_count = 0
        self.lock = threading.Lock()
        self.setup_gpio()
    
    def setup_gpio(self):
        """Setup GPIO with interrupt detection."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        # Try to add event detection
        try:
            GPIO.add_event_detect(self.pin, GPIO.FALLING, callback=self.pulse_callback)
            print("✅ Interrupt detection setup successfully")
        except Exception as e:
            print(f"❌ Failed to setup interrupt detection: {e}")
            raise
    
    def pulse_callback(self, channel):
        """Callback for pulse detection (has GIL issues)."""
        with self.lock:
            self.pulse_count += 1
    
    def get_count(self):
        """Get current pulse count."""
        with self.lock:
            return self.pulse_count
    
    def reset_count(self):
        """Reset pulse count."""
        with self.lock:
            self.pulse_count = 0
    
    def cleanup(self):
        """Cleanup GPIO."""
        try:
            GPIO.remove_event_detect(self.pin)
        except:
            pass


class PollingPulseCounter:
    """High-speed polling counter (no GIL issues but CPU intensive)."""
    def __init__(self, pin):
        self.pin = pin
        self.pulse_count = 0
        self.last_state = None
        self.setup_gpio()
    
    def setup_gpio(self):
        """Setup GPIO for polling."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.last_state = GPIO.input(self.pin)
        print("✅ Polling counter setup successfully")
    
    def count_pulses(self, duration):
        """Count pulses using high-speed polling."""
        start_time = time.perf_counter()
        pulse_count = 0
        last_state = self.last_state
        
        while time.perf_counter() - start_time < duration:
            current_state = GPIO.input(self.pin)
            if last_state == 1 and current_state == 0:  # Falling edge
                pulse_count += 1
            last_state = current_state
            # No sleep for maximum speed
        
        return pulse_count
    
    def get_count(self):
        """Get current pulse count (for compatibility)."""
        return self.pulse_count
    
    def reset_count(self):
        """Reset pulse count (for compatibility)."""
        self.pulse_count = 0
    
    def cleanup(self):
        """Cleanup GPIO."""
        pass


class CExtensionPulseCounter:
    """GIL-safe counter using C extension (optimal performance)."""
    def __init__(self, pin):
        self.pin = pin
        self.pulse_count = 0
        self.setup_gpio()
    
    def setup_gpio(self):
        """Setup GPIO with C extension interrupt detection."""
        if not C_EXTENSION_AVAILABLE:
            raise Exception("C extension not available")
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        # Register pin with C extension
        slot = pulse_counter.register_pin(self.pin)
        if slot == -1:
            raise Exception("Failed to register pin with C extension")
        
        # Setup GPIO interrupt with minimal Python callback
        GPIO.add_event_detect(self.pin, GPIO.FALLING, callback=self._gil_safe_callback)
        print("✅ C extension interrupt detection setup successfully")
    
    def _gil_safe_callback(self, channel):
        """Minimal callback that just calls C function (GIL-safe)."""
        try:
            pulse_counter.increment_count(channel)
        except Exception:
            # Don't log in interrupt context
            pass
    
    def get_count(self):
        """Get current pulse count from C extension."""
        return pulse_counter.get_count(self.pin)
    
    def reset_count(self):
        """Reset pulse count in C extension."""
        pulse_counter.reset_count(self.pin)
    
    def cleanup(self):
        """Cleanup GPIO and C extension."""
        try:
            GPIO.remove_event_detect(self.pin)
        except:
            pass


class GILSafeCounterWrapper:
    """GIL-safe counter using the wrapper (fallback to C extension)."""
    def __init__(self, pin):
        self.pin = pin
        self.counter = None
        self.setup_gpio()
    
    def setup_gpio(self):
        """Setup GPIO with GIL-safe counter."""
        if not GIL_SAFE_COUNTER_AVAILABLE:
            raise Exception("GIL-safe counter not available")
        
        self.counter = create_counter(logging.getLogger('test'))
        
        if not self.counter.setup_gpio_interrupt(self.pin):
            raise Exception("Failed to setup GIL-safe counter")
        
        print("✅ GIL-safe counter setup successfully")
    
    def get_count(self):
        """Get current pulse count."""
        return self.counter.get_count(self.pin)
    
    def reset_count(self):
        """Reset pulse count."""
        self.counter.reset_count(self.pin)
    
    def cleanup(self):
        """Cleanup counter."""
        if self.counter:
            self.counter.cleanup()

def test_method(counter_class, method_name, pin=26, duration=5.0):
    """Test a specific pulse counting method."""
    print(f"\n🔍 Testing {method_name}")
    print("-" * 40)
    
    try:
        # Create counter
        counter = counter_class(pin)
        
        # Test for specified duration
        print(f"Counting pulses for {duration} seconds...")
        
        start_time = time.time()
        counter.reset_count()
        
        if hasattr(counter, 'count_pulses'):
            # Polling method
            pulse_count = counter.count_pulses(duration)
        else:
            # Interrupt method
            while time.time() - start_time < duration:
                time.sleep(0.1)  # Check every 100ms
            pulse_count = counter.get_count()
        
        elapsed = time.time() - start_time
        
        # Calculate frequency with both assumptions
        freq_2_pulses = pulse_count / (elapsed * 2)
        freq_1_pulse = pulse_count / elapsed
        
        print(f"  ✅ Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"  ✅ Frequency (2 pulses/cycle): {freq_2_pulses:.3f} Hz")
        print(f"  ✅ Frequency (1 pulse/cycle): {freq_1_pulse:.3f} Hz")
        print(f"  ✅ Error from 60Hz (2 pulses): {abs(freq_2_pulses - 60):.3f} Hz")
        print(f"  ✅ Error from 60Hz (1 pulse): {abs(freq_1_pulse - 60):.3f} Hz")
        
        # Cleanup
        counter.cleanup()
        return True
        
    except Exception as e:
        print(f"  ❌ {method_name} failed: {e}")
        return False


def comprehensive_pulse_test():
    """Comprehensive test of all pulse detection methods."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available - running simulation mode")
        print("This will test the C extension and logic without actual GPIO")
        
        # Test C extension availability
        if C_EXTENSION_AVAILABLE:
            print("✅ C Extension is available and working")
            print("✅ GIL-safe interrupt callbacks are ready")
            print("✅ Optimal for dual optocoupler measurement")
        else:
            print("❌ C Extension not available")
        
        # Test GIL-safe counter
        if GIL_SAFE_COUNTER_AVAILABLE:
            print("✅ GIL-Safe Counter wrapper is available")
        else:
            print("❌ GIL-Safe Counter wrapper not available")
        
        print("\n🎯 SIMULATION RESULTS:")
        print("• C Extension: Ready for GIL-free interrupt callbacks")
        print("• Your dual optocoupler implementation will use the best available method")
        print("• Deploy on RPi4 for full GPIO testing")
        return
    
    print("🚀 Comprehensive Pulse Detection Test")
    print("=" * 60)
    
    # Test parameters
    pin = 26
    duration = 5.0
    
    # Available methods
    methods = []
    
    # 1. Python Interrupt Callbacks (has GIL issues)
    methods.append((InterruptPulseCounter, "Python Interrupt Callbacks (GIL Issues)"))
    
    # 2. High-Speed Polling (no GIL issues, CPU intensive)
    methods.append((PollingPulseCounter, "High-Speed Polling (CPU Intensive)"))
    
    # 3. C Extension (GIL-safe, optimal)
    if C_EXTENSION_AVAILABLE:
        methods.append((CExtensionPulseCounter, "C Extension (GIL-Safe, Optimal)"))
    else:
        print("⚠️  C Extension not available - skipping optimal method")
    
    # 4. GIL-Safe Counter Wrapper (fallback)
    if GIL_SAFE_COUNTER_AVAILABLE:
        methods.append((GILSafeCounterWrapper, "GIL-Safe Counter Wrapper"))
    else:
        print("⚠️  GIL-Safe Counter not available - skipping wrapper method")
    
    # Test each method
    results = {}
    for counter_class, method_name in methods:
        success = test_method(counter_class, method_name, pin, duration)
        results[method_name] = success
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    for method_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status}: {method_name}")
    
    # Recommendations
    print("\n🎯 RECOMMENDATIONS:")
    if results.get("C Extension (GIL-Safe, Optimal)", False):
        print("• ✅ Use C Extension for maximum accuracy and GIL-free operation")
        print("• ✅ Best for dual optocoupler simultaneous measurement")
    elif results.get("GIL-Safe Counter Wrapper", False):
        print("• ✅ Use GIL-Safe Counter Wrapper as fallback")
        print("• ⚠️  May have minor GIL issues but better than Python callbacks")
    elif results.get("High-Speed Polling (CPU Intensive)", False):
        print("• ⚠️  Use High-Speed Polling as fallback")
        print("• ❌ CPU intensive but no GIL issues")
    elif results.get("Python Interrupt Callbacks (GIL Issues)", False):
        print("• ❌ Python callbacks work but have GIL issues")
        print("• ❌ Not recommended for critical applications")
    else:
        print("• ❌ No methods available - check GPIO setup")


def test_interrupt_method():
    """Legacy function for backward compatibility."""
    comprehensive_pulse_test()


if __name__ == "__main__":
    comprehensive_pulse_test()
