#!/usr/bin/env python3
"""
Test script to verify thread priority optimizations for optocoupler.
This tests the high-priority threading and CPU affinity settings.
"""

import sys
import os
import time
import logging
import psutil

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from optocoupler import OptocouplerManager

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available.")

def test_thread_priority():
    """Test thread priority optimizations."""
    print("🧵 THREAD PRIORITY OPTIMIZATION TEST")
    print("=" * 50)
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Setup logger
    logger = logging.getLogger('thread_priority_test')
    logger.setLevel(logging.INFO)
    
    # Create test configuration
    config = {
        'hardware': {
            'optocoupler': {
                'enabled': True,
                'gpio_pin': 26,
                'pulses_per_cycle': 2,
                'measurement_duration': 1.0
            }
        }
    }
    
    # Initialize optocoupler manager
    optocoupler = OptocouplerManager(config, logger)
    
    print("\n📊 Testing thread priority optimizations:")
    
    # Test 1: Check process priority
    print("\n🔧 Process Priority Check:")
    try:
        current_process = psutil.Process()
        nice_value = current_process.nice()
        print(f"  Current nice value: {nice_value}")
        
        if nice_value < 0:
            print(f"  ✅ High priority set (nice = {nice_value})")
        elif nice_value == 0:
            print(f"  ⚠️  Normal priority (nice = {nice_value})")
        else:
            print(f"  ❌ Low priority (nice = {nice_value})")
    except Exception as e:
        print(f"  ❌ Could not check priority: {e}")
    
    # Test 2: Check CPU affinity
    print("\n🔧 CPU Affinity Check:")
    try:
        current_process = psutil.Process()
        cpu_affinity = current_process.cpu_affinity()
        print(f"  CPU affinity: {cpu_affinity}")
        
        if len(cpu_affinity) == 1:
            print(f"  ✅ Pinned to single core: {cpu_affinity[0]}")
        else:
            print(f"  ⚠️  Using multiple cores: {cpu_affinity}")
    except Exception as e:
        print(f"  ❌ Could not check CPU affinity: {e}")
    
    # Test 3: Test optocoupler performance
    print("\n📈 Optocoupler Performance Test:")
    if optocoupler.optocoupler_initialized:
        print("  Testing 5-second measurement with optimizations...")
        
        start_time = time.perf_counter()
        pulse_count = optocoupler.count_optocoupler_pulses(5.0, debounce_time=0.001)
        elapsed = time.perf_counter() - start_time
        
        frequency = optocoupler.calculate_frequency_from_pulses(pulse_count, 5.0)
        
        print(f"  Pulses counted: {pulse_count}")
        print(f"  Measurement time: {elapsed:.3f}s")
        print(f"  Frequency: {frequency:.3f} Hz" if frequency else "  Frequency: Could not calculate")
        
        if frequency:
            error = abs(frequency - 60.01)
            print(f"  Error from 60.01 Hz: {error:.3f} Hz")
            
            if error < 0.1:
                print(f"  🎯 Excellent accuracy!")
            elif error < 0.5:
                print(f"  ✅ Good accuracy")
            else:
                print(f"  ⚠️  Could be improved")
    else:
        print("  ❌ Optocoupler not initialized")
    
    # Test 4: System load during measurement
    print("\n📊 System Load Test:")
    print("  Monitoring system load during measurement...")
    
    # Get initial system stats
    initial_cpu = psutil.cpu_percent(interval=0.1)
    initial_memory = psutil.virtual_memory().percent
    
    print(f"  Initial CPU usage: {initial_cpu:.1f}%")
    print(f"  Initial memory usage: {initial_memory:.1f}%")
    
    # Run measurement with monitoring
    if optocoupler.optocoupler_initialized:
        start_time = time.perf_counter()
        pulse_count = optocoupler.count_optocoupler_pulses(3.0, debounce_time=0.001)
        elapsed = time.perf_counter() - start_time
        
        # Get final system stats
        final_cpu = psutil.cpu_percent(interval=0.1)
        final_memory = psutil.virtual_memory().percent
        
        print(f"  Final CPU usage: {final_cpu:.1f}%")
        print(f"  Final memory usage: {final_memory:.1f}%")
        print(f"  Measurement completed in: {elapsed:.3f}s")
        
        if final_cpu - initial_cpu < 10:
            print(f"  ✅ Low CPU impact")
        else:
            print(f"  ⚠️  High CPU usage during measurement")
    
    print(f"\n💡 Thread Priority Summary:")
    print(f"  • Process priority: {'High' if psutil.Process().nice() < 0 else 'Normal'}")
    print(f"  • CPU affinity: {psutil.Process().cpu_affinity()}")
    print(f"  • Optimizations: {'Active' if optocoupler.optocoupler_initialized else 'Inactive'}")
    
    # Cleanup
    optocoupler.cleanup()

def test_priority_comparison():
    """Compare performance with and without priority optimizations."""
    print("\n🔄 PRIORITY COMPARISON TEST")
    print("=" * 50)
    
    if not GPIO_AVAILABLE:
        print("❌ RPi.GPIO not available")
        return
    
    # Test without optimizations (simulate)
    print("\n📊 Testing without optimizations:")
    print("  (This would require modifying the optocoupler class)")
    print("  For now, we'll test the current optimized version")
    
    # Run the optimized test
    test_thread_priority()

if __name__ == "__main__":
    print("🧵 OPTCOUPLER THREAD PRIORITY TESTING")
    print("=" * 60)
    print("Testing high-priority threading optimizations")
    print("=" * 60)
    
    test_thread_priority()
    test_priority_comparison()
    
    print(f"\n🏁 Thread priority testing completed!")
    print(f"💡 Check the results above to verify optimizations are working")
