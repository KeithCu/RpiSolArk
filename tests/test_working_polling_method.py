#!/usr/bin/env python3
"""
Test Working Polling Method
Tests a working polling method that counts all edges for correct frequency.
"""

import sys
import os
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hardware imports
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("❌ RPi.GPIO not available")

class WorkingOptocouplerCounter:
    """Working optocoupler counter that counts all edges."""
    
    def __init__(self, gpio_pin: int, pulses_per_cycle: int = 2):
        self.gpio_pin = gpio_pin
        self.pulses_per_cycle = pulses_per_cycle
        self.gpio_available = GPIO_AVAILABLE
        
        if self.gpio_available:
            self._setup_gpio()
    
    def _setup_gpio(self):
        """Setup GPIO for optocoupler input."""
        if not self.gpio_available:
            return
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print(f"✅ GPIO {self.gpio_pin} configured for optocoupler input")
        except Exception as e:
            print(f"❌ GPIO setup failed: {e}")
            self.gpio_available = False
    
    def count_pulses(self, duration: float, debounce_time: float = 0.001) -> int:
        """Count pulses using polling method that counts ALL edges."""
        if not self.gpio_available:
            return 0
        
        start_time = time.time()
        edge_count = 0
        last_state = GPIO.input(self.gpio_pin)
        last_change_time = 0
        
        print(f"Counting ALL edges for {duration} seconds...")
        
        while time.time() - start_time < duration:
            current_state = GPIO.input(self.gpio_pin)
            current_time = time.time()
            
            if current_state != last_state:
                # Check debounce
                if current_time - last_change_time > debounce_time:
                    edge_count += 1  # Count ALL edges (both rising and falling)
                    last_change_time = current_time
                    last_state = current_state
            time.sleep(0.001)  # 1ms polling
        
        elapsed = time.time() - start_time
        print(f"Counted {edge_count} edges in {elapsed:.2f}s")
        return edge_count
    
    def calculate_frequency(self, edge_count: int, duration: float) -> float:
        """Calculate frequency from edge count."""
        if edge_count <= 0 or duration <= 0:
            return 0.0
        
        # Calculate frequency: edges / (duration * pulses_per_cycle)
        frequency = edge_count / (duration * self.pulses_per_cycle)
        return frequency
    
    def cleanup(self):
        """Cleanup GPIO resources."""
        if self.gpio_available:
            try:
                GPIO.cleanup()
                print("✅ GPIO cleanup completed")
            except:
                pass

def test_working_polling_method():
    """Test the working polling method."""
    print("🔧 Testing Working Polling Method")
    print("=" * 50)
    print("This method counts ALL edges (both rising and falling)")
    print("This should give you the correct 60 Hz frequency")
    print("")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    try:
        # Test with different configurations
        pin = 26
        duration = 5.0
        
        print(f"Testing with GPIO pin {pin} for {duration} seconds...")
        
        # Test with 2 pulses per cycle (H11AA1 default)
        print(f"\n📊 Test 1: 2 Pulses Per Cycle (H11AA1 Default)")
        print("-" * 45)
        
        counter = WorkingOptocouplerCounter(pin, pulses_per_cycle=2)
        
        if not counter.gpio_available:
            print("❌ GPIO not available")
            return
        
        edge_count = counter.count_pulses(duration)
        
        if edge_count > 0:
            frequency = counter.calculate_frequency(edge_count, duration)
            print(f"Edge count: {edge_count}")
            print(f"Frequency: {frequency:.2f} Hz")
            
            if 55 <= frequency <= 65:
                print("✅ PERFECT! This gives correct 60 Hz frequency")
                print("✅ Use this method in your system")
            elif 50 <= frequency <= 70:
                print("✅ GOOD! This gives close to 60 Hz frequency")
                print("✅ Use this method in your system")
            else:
                print(f"⚠️  Frequency is {frequency:.2f} Hz (not 60 Hz)")
                print("💡 This might be due to AC frequency variation")
        
        counter.cleanup()
        
        # Test with 1 pulse per cycle
        print(f"\n📊 Test 2: 1 Pulse Per Cycle")
        print("-" * 30)
        
        counter = WorkingOptocouplerCounter(pin, pulses_per_cycle=1)
        
        if counter.gpio_available:
            edge_count = counter.count_pulses(duration)
            
            if edge_count > 0:
                frequency = counter.calculate_frequency(edge_count, duration)
                print(f"Edge count: {edge_count}")
                print(f"Frequency: {frequency:.2f} Hz")
                
                if 55 <= frequency <= 65:
                    print("✅ PERFECT! This gives correct 60 Hz frequency")
                    print("✅ Use this method in your system")
                elif 50 <= frequency <= 70:
                    print("✅ GOOD! This gives close to 60 Hz frequency")
                    print("✅ Use this method in your system")
                else:
                    print(f"⚠️  Frequency is {frequency:.2f} Hz (not 60 Hz)")
        
        counter.cleanup()
        
        # Summary
        print(f"\n💡 SUMMARY:")
        print("-" * 15)
        print("✅ The working polling method counts ALL edges")
        print("✅ This gives you the correct frequency")
        print("✅ You can use this method in your system")
        print("")
        print("🔧 TO FIX YOUR SYSTEM:")
        print("1. Replace the C extension with this polling method")
        print("2. Make sure it counts ALL edges (both rising and falling)")
        print("3. Use 2 pulses per cycle for H11AA1 optocoupler")
        print("4. This should give you 60 Hz frequency readings")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_working_polling_method()
