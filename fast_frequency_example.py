#!/usr/bin/env python3
"""
Example integration of fast frequency measurement.
Shows how to use the production fast measurer in your application.
"""

import sys
import os
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from production_fast_measurement import ProductionFastMeasurer

def main():
    """Example usage of fast frequency measurement."""
    print("🚀 FAST FREQUENCY MEASUREMENT EXAMPLE")
    print("=" * 40)
    
    # Initialize the fast measurer
    measurer = ProductionFastMeasurer(gpio_pin=26, pulses_per_cycle=2)
    
    try:
        print("📊 Taking quick measurement (1 second)...")
        result = measurer.quick_measure(1.0)
        
        print(f"Frequency: {result['frequency']:.3f} Hz")
        print(f"Accuracy: {result['accuracy']:.2f}%")
        print(f"Error: {result['error']:.3f} Hz")
        print(f"Duration: {result['duration']:.2f}s")
        print(f"Sudo optimizations: {'Yes' if result['sudo_used'] else 'No'}")
        
        # Performance assessment
        if result['error'] < 0.1:
            print("🎯 Excellent accuracy!")
        elif result['error'] < 0.5:
            print("✅ Good accuracy")
        else:
            print("⚠️  Could be improved")
        
        print("\n📊 Taking balanced measurement (1.5s, 3 samples)...")
        result2 = measurer.measure_frequency(1.5, 3)
        
        print(f"Frequency: {result2['frequency']:.3f} Hz")
        print(f"Accuracy: {result2['accuracy']:.2f}%")
        print(f"Error: {result2['error']:.3f} Hz")
        print(f"Std Dev: {result2['std_dev']:.3f} Hz")
        print(f"Duration: {result2['duration']:.2f}s")
        
        # Compare results
        print(f"\n📈 COMPARISON:")
        print(f"Quick (1s):     {result['frequency']:.3f} Hz, {result['accuracy']:.2f}% accuracy")
        print(f"Balanced (1.5s): {result2['frequency']:.3f} Hz, {result2['accuracy']:.2f}% accuracy")
        
        if result2['error'] < result['error']:
            print("✅ Balanced measurement is more accurate")
        else:
            print("✅ Quick measurement is sufficient")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    finally:
        measurer.cleanup()
        print("\n✅ Cleanup completed")

if __name__ == "__main__":
    main()
