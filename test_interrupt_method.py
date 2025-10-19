#!/usr/bin/env python3
"""
Test interrupt-based pulse detection to see if we can get more accurate results.
"""

import sys
import os
import time
import threading

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

class InterruptPulseCounter:
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
        """Callback for pulse detection."""
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

def test_interrupt_method():
    """Test interrupt-based pulse detection."""
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    print("🔍 Testing Interrupt-Based Pulse Detection")
    print("=" * 50)
    
    try:
        # Create interrupt-based counter
        counter = InterruptPulseCounter(26)
        
        # Test for 5 seconds
        duration = 5.0
        print(f"Counting pulses for {duration} seconds using interrupts...")
        
        start_time = time.time()
        counter.reset_count()
        
        while time.time() - start_time < duration:
            time.sleep(0.1)  # Check every 100ms
        
        elapsed = time.time() - start_time
        pulse_count = counter.get_count()
        
        # Calculate frequency with both assumptions
        freq_2_pulses = pulse_count / (elapsed * 2)
        freq_1_pulse = pulse_count / elapsed
        
        print(f"  Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"  Frequency (2 pulses/cycle): {freq_2_pulses:.3f} Hz")
        print(f"  Frequency (1 pulse/cycle): {freq_1_pulse:.3f} Hz")
        print(f"  Error from 60Hz (2 pulses): {abs(freq_2_pulses - 60):.3f} Hz")
        print(f"  Error from 60Hz (1 pulse): {abs(freq_1_pulse - 60):.3f} Hz")
        
        # Cleanup
        counter.cleanup()
        
    except Exception as e:
        print(f"❌ Interrupt method failed: {e}")
        print("Falling back to polling method...")
        
        # Fallback to polling
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        duration = 5.0
        start_time = time.time()
        pulse_count = 0
        last_state = GPIO.input(26)
        
        while time.time() - start_time < duration:
            current_state = GPIO.input(26)
            if last_state == 1 and current_state == 0:
                pulse_count += 1
            last_state = current_state
            # No sleep for maximum speed
        
        elapsed = time.time() - start_time
        freq_2_pulses = pulse_count / (elapsed * 2)
        
        print(f"  Fallback - Pulses: {pulse_count} in {elapsed:.3f}s")
        print(f"  Fallback - Frequency (2 pulses/cycle): {freq_2_pulses:.3f} Hz")

if __name__ == "__main__":
    test_interrupt_method()
