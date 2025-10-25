#!/usr/bin/env python3
"""
Quick GPIO Test for Frequency Reading Issues
Simple test to quickly check if GPIO pin 26 is receiving any signal.
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

def quick_gpio_test():
    """Quick test of GPIO pin 26 for signal activity."""
    print("🔍 Quick GPIO Test - Pin 26")
    print("=" * 40)
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    try:
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        pin = 26  # From your config
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        print(f"Testing GPIO pin {pin}...")
        print("Monitoring for 5 seconds...")
        print("Press Ctrl+C to stop early")
        
        # Monitor for state changes
        start_time = time.time()
        state_changes = 0
        last_state = GPIO.input(pin)
        initial_state = last_state
        
        print(f"Initial state: {initial_state}")
        print("Looking for state changes...")
        
        try:
            while time.time() - start_time < 5.0:
                current_state = GPIO.input(pin)
                if current_state != last_state:
                    state_changes += 1
                    elapsed = time.time() - start_time
                    edge_type = "FALLING" if last_state == 1 and current_state == 0 else "RISING"
                    print(f"[{elapsed:5.2f}s] {edge_type} edge: {last_state} → {current_state}")
                    last_state = current_state
                time.sleep(0.001)  # 1ms polling
                
        except KeyboardInterrupt:
            print("\nStopped by user")
        
        elapsed = time.time() - start_time
        final_state = GPIO.input(pin)
        
        print(f"\n📊 Results:")
        print(f"Duration: {elapsed:.2f}s")
        print(f"Initial state: {initial_state}")
        print(f"Final state: {final_state}")
        print(f"State changes: {state_changes}")
        
        if state_changes == 0:
            print("\n❌ NO SIGNAL DETECTED")
            print("This means:")
            print("- H11AA1 optocoupler is likely damaged")
            print("- No AC signal reaching optocoupler")
            print("- Connection problem")
            print("- Wrong GPIO pin")
            print("\n🔧 Check:")
            print("1. AC voltage on transformer output")
            print("2. Optocoupler connections")
            print("3. Try different H11AA1 optocoupler")
            print("4. Verify GPIO pin in config.yaml")
            
        elif state_changes < 10:
            print(f"\n⚠️  WEAK SIGNAL ({state_changes} changes)")
            print("This means:")
            print("- Optocoupler may be partially damaged")
            print("- Weak AC signal")
            print("- Intermittent connection")
            
        else:
            print(f"\n✅ SIGNAL DETECTED ({state_changes} changes)")
            print("This means:")
            print("- Optocoupler is working")
            print("- Signal is reaching GPIO")
            print("- Check frequency calculation")
            
            # Estimate frequency
            if state_changes > 0:
                # H11AA1 gives 2 pulses per AC cycle
                estimated_freq = state_changes / (elapsed * 2)
                print(f"Estimated frequency: {estimated_freq:.2f} Hz")
                
                if 50 <= estimated_freq <= 70:
                    print("✅ Frequency in expected range")
                else:
                    print("⚠️  Frequency outside expected range")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        try:
            GPIO.cleanup()
            print("\n✅ GPIO cleanup completed")
        except:
            pass

if __name__ == "__main__":
    quick_gpio_test()
