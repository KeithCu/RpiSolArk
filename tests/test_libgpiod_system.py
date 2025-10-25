#!/usr/bin/env python3
"""
Test libgpiod System
Tests the libgpiod system to see if it works and can be fixed for all edges.
"""

import sys
import os
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_libgpiod_system():
    """Test the libgpiod system."""
    print("🔧 Testing libgpiod System")
    print("=" * 50)
    print("Testing if libgpiod system works and can be fixed")
    print("")
    
    try:
        # Import the libgpiod system
        from gpio_event_counter import create_counter
        from config import Config, Logger
        
        # Create config and logger
        config = Config()
        logger = Logger(config).logger
        
        print("✅ libgpiod system imported successfully")
        
        # Create counter
        counter = create_counter(logger)
        print("✅ Counter created successfully")
        
        # Test with GPIO pin 26
        pin = 26
        print(f"Testing with GPIO pin {pin}...")
        
        # Register pin
        if counter.register_pin(pin):
            print(f"✅ Pin {pin} registered successfully")
        else:
            print(f"❌ Failed to register pin {pin}")
            return
        
        # Test counting for 5 seconds
        print("Counting pulses for 5 seconds...")
        start_time = time.time()
        
        while time.time() - start_time < 5.0:
            time.sleep(0.1)  # Check every 100ms
        
        elapsed = time.time() - start_time
        pulse_count = counter.get_count(pin)
        
        print(f"Pulse count: {pulse_count}")
        print(f"Duration: {elapsed:.2f}s")
        
        if pulse_count > 0:
            # Calculate frequency
            frequency = pulse_count / (elapsed * 2)  # 2 pulses per cycle
            print(f"Frequency: {frequency:.2f} Hz")
            
            if 55 <= frequency <= 65:
                print("✅ Frequency is correct (55-65 Hz)")
                print("✅ libgpiod system is working correctly")
            elif 35 <= frequency <= 45:
                print("⚠️  Frequency is too low (35-45 Hz)")
                print("💡 This suggests the system is only counting falling edges")
                print("💡 We need to fix it to count all edges")
            else:
                print(f"❌ Frequency is wrong: {frequency:.2f} Hz")
                print("💡 There's an issue with the libgpiod system")
        else:
            print("❌ No pulses detected")
            print("💡 libgpiod system is not working")
        
        # Cleanup
        counter.cleanup()
        print("✅ Cleanup completed")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 You need to install libgpiod:")
        print("   sudo apt install python3-gpiod")
        print("   or")
        print("   pip install gpiod")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_libgpiod_system()
