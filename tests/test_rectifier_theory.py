#!/usr/bin/env python3
"""
Test Rectifier Theory
Tests the theory that missing rectifier is causing half frequency.
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

def test_rectifier_theory():
    """Test the theory that missing rectifier is causing half frequency."""
    print("🔍 Testing Rectifier Theory")
    print("=" * 50)
    print("H11AA1 optocoupler needs rectifier for full AC detection")
    print("Without rectifier: Only positive AC cycles are detected")
    print("With rectifier: Both positive and negative cycles are detected")
    print("")
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    try:
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        pin = 26
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        print(f"Monitoring GPIO {pin} for 10 seconds...")
        print("Analyzing signal to confirm rectifier theory...")
        print("")
        
        # Collect signal data
        start_time = time.time()
        signal_data = []
        last_state = GPIO.input(pin)
        
        while time.time() - start_time < 10.0:
            current_state = GPIO.input(pin)
            current_time = time.time()
            
            if current_state != last_state:
                signal_data.append({
                    'time': current_time - start_time,
                    'state': current_state,
                    'edge': 'FALLING' if last_state == 1 and current_state == 0 else 'RISING'
                })
                last_state = current_state
            time.sleep(0.001)  # 1ms polling
        
        elapsed = time.time() - start_time
        
        if not signal_data:
            print("❌ NO SIGNAL DETECTED")
            print("💡 Optocoupler is not working at all")
            return
        
        # Analyze signal
        falling_edges = [d for d in signal_data if d['edge'] == 'FALLING']
        rising_edges = [d for d in signal_data if d['edge'] == 'RISING']
        
        print(f"📊 Signal Analysis:")
        print(f"Duration: {elapsed:.2f}s")
        print(f"Falling edges: {len(falling_edges)}")
        print(f"Rising edges: {len(rising_edges)}")
        
        # Calculate frequency
        frequency = len(falling_edges) / (elapsed * 2)  # 2 pulses per cycle
        print(f"Calculated frequency: {frequency:.2f} Hz")
        
        # Check for half frequency pattern
        expected_60hz = 60 * 2 * elapsed  # 2 pulses per cycle for 60 Hz
        expected_30hz = 30 * 2 * elapsed  # 2 pulses per cycle for 30 Hz
        
        print(f"\n🔍 Frequency Analysis:")
        print(f"Expected for 60 Hz: {expected_60hz:.0f} edges")
        print(f"Expected for 30 Hz: {expected_30hz:.0f} edges")
        print(f"Actual falling edges: {len(falling_edges)}")
        
        error_60hz = abs(len(falling_edges) - expected_60hz)
        error_30hz = abs(len(falling_edges) - expected_30hz)
        
        print(f"Error from 60 Hz: {error_60hz:.0f} edges")
        print(f"Error from 30 Hz: {error_30hz:.0f} edges")
        
        if error_30hz < error_60hz:
            print("✅ CONFIRMED: Getting ~30 Hz (half frequency)")
            print("💡 This confirms the rectifier theory!")
            print("💡 H11AA1 is only detecting positive AC cycles")
            print("💡 You need a full-wave rectifier")
        elif error_60hz < error_30hz:
            print("✅ Getting ~60 Hz (correct frequency)")
            print("💡 H11AA1 is working correctly")
            print("💡 You already have a rectifier or it's not needed")
        else:
            print("⚠️  Frequency doesn't match 30 Hz or 60 Hz")
            print("💡 There might be other issues")
        
        # Analyze signal pattern
        print(f"\n🔬 Signal Pattern Analysis:")
        print("-" * 30)
        
        if len(falling_edges) > 1:
            intervals = []
            for i in range(1, len(falling_edges)):
                interval = falling_edges[i]['time'] - falling_edges[i-1]['time']
                intervals.append(interval)
            
            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                min_interval = min(intervals)
                max_interval = max(intervals)
                
                print(f"Average interval: {avg_interval:.3f}s")
                print(f"Min interval: {min_interval:.3f}s")
                print(f"Max interval: {max_interval:.3f}s")
                
                # Check for expected timing
                expected_60hz_interval = 1.0 / (60 * 2)  # 2 pulses per cycle
                expected_30hz_interval = 1.0 / (30 * 2)  # 2 pulses per cycle
                
                print(f"Expected 60 Hz interval: {expected_60hz_interval:.3f}s")
                print(f"Expected 30 Hz interval: {expected_30hz_interval:.3f}s")
                
                if abs(avg_interval - expected_30hz_interval) < 0.01:
                    print("✅ Timing matches 30 Hz (half frequency)")
                    print("💡 This confirms the rectifier theory!")
                elif abs(avg_interval - expected_60hz_interval) < 0.01:
                    print("✅ Timing matches 60 Hz (correct frequency)")
                    print("💡 H11AA1 is working correctly")
                else:
                    print("❌ Timing doesn't match expected frequencies")
                    print("💡 There might be other issues")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        print("-" * 20)
        
        if error_30hz < error_60hz:
            print("🔧 ADD RECTIFIER:")
            print("1. Add a full-wave rectifier before H11AA1")
            print("2. Use 4 diodes in bridge configuration")
            print("3. This will convert AC to DC pulses")
            print("4. H11AA1 will detect both positive and negative cycles")
            print("5. You should get 60 Hz instead of 30 Hz")
            print("")
            print("📋 RECTIFIER CIRCUIT:")
            print("AC Line → Rectifier → H11AA1 → GPIO")
            print("")
            print("🔧 DIODE BRIDGE RECTIFIER:")
            print("Use 4 diodes (1N4007 or similar)")
            print("Connect in bridge configuration")
            print("This will give you full-wave rectification")
        else:
            print("✅ NO RECTIFIER NEEDED:")
            print("1. H11AA1 is working correctly")
            print("2. You're getting 60 Hz as expected")
            print("3. The issue is elsewhere in your system")
    
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
    test_rectifier_theory()
