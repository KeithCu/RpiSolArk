#!/usr/bin/env python3
"""
Test 60 Hz Configuration
Shows how to configure the system to display 60 Hz readings.
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

def test_60hz_config():
    """Test configuration to get 60 Hz readings."""
    print("🔧 Testing 60 Hz Configuration")
    print("=" * 50)
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    try:
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        pin = 26
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        print(f"Monitoring GPIO {pin} for 5 seconds...")
        print("Testing different configurations to get 60 Hz readings...")
        
        # Count pulses
        start_time = time.time()
        falling_edges = 0
        last_state = GPIO.input(pin)
        
        while time.time() - start_time < 5.0:
            current_state = GPIO.input(pin)
            if current_state != last_state:
                if last_state == 1 and current_state == 0:
                    falling_edges += 1
                last_state = current_state
            time.sleep(0.001)
        
        elapsed = time.time() - start_time
        
        print(f"\n📊 Results:")
        print(f"Falling edges: {falling_edges}")
        print(f"Duration: {elapsed:.2f}s")
        
        # Test different pulses_per_cycle values
        print(f"\n📈 Frequency Calculations:")
        print("-" * 30)
        
        for pulses_per_cycle in [1, 2, 3, 4]:
            frequency = falling_edges / (elapsed * pulses_per_cycle)
            print(f"{pulses_per_cycle} pulses/cycle: {frequency:.2f} Hz")
            
            if 55 <= frequency <= 65:
                print(f"  ✅ This gives 60 Hz readings!")
                print(f"  💡 RECOMMENDED: Use pulses_per_cycle: {pulses_per_cycle}")
        
        # Find the best configuration
        print(f"\n🎯 Best Configuration:")
        print("-" * 25)
        
        best_pulses = None
        best_frequency = 0
        
        for pulses_per_cycle in [1, 2, 3, 4]:
            frequency = falling_edges / (elapsed * pulses_per_cycle)
            if 55 <= frequency <= 65:
                best_pulses = pulses_per_cycle
                best_frequency = frequency
                break
        
        if best_pulses:
            print(f"✅ Use pulses_per_cycle: {best_pulses}")
            print(f"✅ This will give: {best_frequency:.2f} Hz")
            print(f"")
            print(f"📝 Update your config.yaml:")
            print(f"   Change line 22 from:")
            print(f"     pulses_per_cycle: 2")
            print(f"   To:")
            print(f"     pulses_per_cycle: {best_pulses}")
            print(f"")
            print(f"🔄 After updating config:")
            print(f"   1. Restart your monitor: python monitor.py")
            print(f"   2. Check if frequency readings are now ~60 Hz")
        else:
            print("❌ No configuration gives 60 Hz readings")
            print("💡 Your AC frequency is actually 39 Hz")
            print("💡 This is normal for some regions")
            print("💡 Consider accepting 39 Hz as correct")
        
        # Show what each configuration gives
        print(f"\n📋 All Configurations:")
        print("-" * 25)
        for pulses_per_cycle in [1, 2, 3, 4]:
            frequency = falling_edges / (elapsed * pulses_per_cycle)
            status = "✅ 60 Hz" if 55 <= frequency <= 65 else "❌ Not 60 Hz"
            print(f"  {pulses_per_cycle} pulses/cycle: {frequency:.2f} Hz ({status})")
    
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
    test_60hz_config()
