#!/usr/bin/env python3
"""
Comprehensive Optocoupler Test
Combines all optimizations and benefits from the troubleshooting guide.
Tests the consolidated optocoupler implementation with real measurements.
"""

import sys
import os
import time
import statistics
from typing import Dict, List, Optional

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import existing system components
from config import Config, Logger
from optocoupler import OptocouplerManager

class ComprehensiveOptocouplerTest:
    """Comprehensive test of the optimized optocoupler implementation."""
    
    def __init__(self):
        self.config = Config()
        self.logger = Logger(self.config).logger
        self.optocoupler = OptocouplerManager(self.config, self.logger)
        self.target_freq = 60.0
        
    def test_single_measurement(self) -> Dict:
        """Test single 2-second measurement (no averaging)."""
        print("🎯 Test 1: Single 2-Second Measurement (No Averaging)")
        print("-" * 55)
        
        start_time = time.perf_counter()
        pulse_count = self.optocoupler.count_optocoupler_pulses(duration=2.0, debounce_time=0.0)
        elapsed = time.perf_counter() - start_time
        
        frequency = self.optocoupler.calculate_frequency_from_pulses(pulse_count, elapsed)
        
        if frequency is None:
            return {'success': False, 'error': 'No frequency calculated'}
        
        error = abs(frequency - self.target_freq)
        accuracy = max(0, 100 - (error / self.target_freq * 100))
        
        result = {
            'success': True,
            'frequency': frequency,
            'accuracy': accuracy,
            'error': error,
            'duration': elapsed,
            'pulses': pulse_count
        }
        
        print(f"Frequency: {frequency:.3f} Hz")
        print(f"Accuracy: {accuracy:.2f}%")
        print(f"Error: {error:.3f} Hz")
        print(f"Duration: {elapsed:.3f}s")
        print(f"Pulses: {pulse_count}")
        
        if error < 0.1:
            print("🎯 Excellent accuracy!")
        elif error < 0.5:
            print("✅ Good accuracy")
        else:
            print("⚠️  Could be improved")
        
        return result
    
    def test_multiple_measurements(self, count: int = 5) -> Dict:
        """Test multiple measurements to show frequency changes."""
        print(f"\n📊 Test 2: Multiple Measurements (Shows Real Changes)")
        print("-" * 55)
        
        measurements = []
        frequencies = []
        
        for i in range(count):
            print(f"   Measurement {i+1}/{count}...", end=" ")
            
            start_time = time.perf_counter()
            pulse_count = self.optocoupler.count_optocoupler_pulses(duration=2.0, debounce_time=0.0)
            elapsed = time.perf_counter() - start_time
            
            frequency = self.optocoupler.calculate_frequency_from_pulses(pulse_count, elapsed)
            
            if frequency is not None:
                measurements.append({
                    'frequency': frequency,
                    'pulses': pulse_count,
                    'duration': elapsed
                })
                frequencies.append(frequency)
                print(f"{frequency:.3f} Hz")
            else:
                print("Failed")
        
        if not measurements:
            return {'success': False, 'error': 'No successful measurements'}
        
        # Calculate statistics
        mean_freq = statistics.mean(frequencies)
        std_dev = statistics.stdev(frequencies) if len(frequencies) > 1 else 0.0
        min_freq = min(frequencies)
        max_freq = max(frequencies)
        range_freq = max_freq - min_freq
        
        result = {
            'success': True,
            'measurements': measurements,
            'frequencies': frequencies,
            'mean_frequency': mean_freq,
            'std_deviation': std_dev,
            'min_frequency': min_freq,
            'max_frequency': max_freq,
            'frequency_range': range_freq
        }
        
        print(f"\n📈 Statistics:")
        print(f"Mean: {mean_freq:.3f} Hz")
        print(f"Std Dev: {std_dev:.3f} Hz")
        print(f"Range: {range_freq:.3f} Hz ({min_freq:.3f} - {max_freq:.3f})")
        
        # Show frequency changes
        if len(frequencies) > 1:
            changes = []
            for i in range(1, len(frequencies)):
                change = abs(frequencies[i] - frequencies[i-1])
                changes.append(change)
            
            avg_change = statistics.mean(changes)
            max_change = max(changes)
            
            print(f"Average Change: {avg_change:.3f} Hz")
            print(f"Maximum Change: {max_change:.3f} Hz")
            
            if max_change > 0.5:
                print("📊 Significant frequency changes detected!")
            elif max_change > 0.1:
                print("📊 Moderate frequency changes detected")
            else:
                print("📊 Stable frequency (minimal changes)")
        
        return result
    
    def test_different_durations(self) -> Dict:
        """Test different measurement durations."""
        print(f"\n⏱️  Test 3: Different Measurement Durations")
        print("-" * 55)
        
        durations = [1.0, 2.0, 5.0]
        results = {}
        
        for duration in durations:
            print(f"   Testing {duration}s measurement...", end=" ")
            
            start_time = time.perf_counter()
            pulse_count = self.optocoupler.count_optocoupler_pulses(duration=duration, debounce_time=0.0)
            elapsed = time.perf_counter() - start_time
            
            frequency = self.optocoupler.calculate_frequency_from_pulses(pulse_count, elapsed)
            
            if frequency is not None:
                error = abs(frequency - self.target_freq)
                accuracy = max(0, 100 - (error / self.target_freq * 100))
                
                results[duration] = {
                    'frequency': frequency,
                    'accuracy': accuracy,
                    'error': error,
                    'pulses': pulse_count,
                    'duration': elapsed
                }
                
                print(f"{frequency:.3f} Hz ({accuracy:.1f}% accuracy)")
            else:
                print("Failed")
                results[duration] = None
        
        # Show comparison
        print(f"\n📊 Duration Comparison:")
        for duration, result in results.items():
            if result:
                print(f"{duration:4.1f}s: {result['frequency']:6.3f} Hz, {result['accuracy']:5.1f}% accuracy, {result['error']:5.3f} Hz error")
            else:
                print(f"{duration:4.1f}s: Failed")
        
        return results
    
    def test_debouncing_impact(self) -> Dict:
        """Test impact of debouncing on clean signals."""
        print(f"\n🔧 Test 4: Debouncing Impact (Clean Signals)")
        print("-" * 55)
        
        # Test without debouncing
        print("   Testing without debouncing...", end=" ")
        start_time = time.perf_counter()
        pulse_count_no_debounce = self.optocoupler.count_optocoupler_pulses(duration=2.0, debounce_time=0.0)
        elapsed_no_debounce = time.perf_counter() - start_time
        freq_no_debounce = self.optocoupler.calculate_frequency_from_pulses(pulse_count_no_debounce, elapsed_no_debounce)
        
        if freq_no_debounce:
            error_no_debounce = abs(freq_no_debounce - self.target_freq)
            print(f"{freq_no_debounce:.3f} Hz (error: {error_no_debounce:.3f} Hz)")
        else:
            print("Failed")
            return {'success': False}
        
        # Test with debouncing
        print("   Testing with 1ms debouncing...", end=" ")
        start_time = time.perf_counter()
        pulse_count_with_debounce = self.optocoupler.count_optocoupler_pulses(duration=2.0, debounce_time=0.001)
        elapsed_with_debounce = time.perf_counter() - start_time
        freq_with_debounce = self.optocoupler.calculate_frequency_from_pulses(pulse_count_with_debounce, elapsed_with_debounce)
        
        if freq_with_debounce:
            error_with_debounce = abs(freq_with_debounce - self.target_freq)
            print(f"{freq_with_debounce:.3f} Hz (error: {error_with_debounce:.3f} Hz)")
        else:
            print("Failed")
            return {'success': False}
        
        # Compare results
        print(f"\n📊 Debouncing Comparison:")
        print(f"No debouncing:  {freq_no_debounce:.3f} Hz (error: {error_no_debounce:.3f} Hz)")
        print(f"With debouncing: {freq_with_debounce:.3f} Hz (error: {error_with_debounce:.3f} Hz)")
        
        if error_no_debounce < error_with_debounce:
            print("✅ No debouncing is better for clean signals")
        elif error_with_debounce < error_no_debounce:
            print("✅ Debouncing helps with noisy signals")
        else:
            print("📊 Similar performance")
        
        return {
            'success': True,
            'no_debounce': {
                'frequency': freq_no_debounce,
                'error': error_no_debounce,
                'pulses': pulse_count_no_debounce
            },
            'with_debounce': {
                'frequency': freq_with_debounce,
                'error': error_with_debounce,
                'pulses': pulse_count_with_debounce
            }
        }
    
    def run_comprehensive_test(self):
        """Run all tests and provide summary."""
        print("🚀 COMPREHENSIVE OPTOCUPLER TEST")
        print("=" * 60)
        print("Testing optimized 2-second measurement with no averaging")
        print("Target frequency: 60.0 Hz")
        print("=" * 60)
        
        try:
            # Test 1: Single measurement
            result1 = self.test_single_measurement()
            
            # Test 2: Multiple measurements
            result2 = self.test_multiple_measurements(5)
            
            # Test 3: Different durations
            result3 = self.test_different_durations()
            
            # Test 4: Debouncing impact
            result4 = self.test_debouncing_impact()
            
            # Summary
            print(f"\n📈 COMPREHENSIVE TEST SUMMARY")
            print("=" * 40)
            
            if result1['success']:
                print(f"✅ Single 2s measurement: {result1['frequency']:.3f} Hz ({result1['accuracy']:.1f}% accuracy)")
            
            if result2['success']:
                print(f"✅ Multiple measurements: {result2['mean_frequency']:.3f} Hz ± {result2['std_deviation']:.3f} Hz")
                print(f"   Range: {result2['frequency_range']:.3f} Hz (shows real changes)")
            
            if result3:
                best_duration = None
                best_accuracy = 0
                for duration, result in result3.items():
                    if result and result['accuracy'] > best_accuracy:
                        best_accuracy = result['accuracy']
                        best_duration = duration
                
                if best_duration:
                    print(f"✅ Best duration: {best_duration}s ({best_accuracy:.1f}% accuracy)")
            
            if result4['success']:
                no_debounce_error = result4['no_debounce']['error']
                with_debounce_error = result4['with_debounce']['error']
                if no_debounce_error < with_debounce_error:
                    print(f"✅ No debouncing recommended for clean signals")
                else:
                    print(f"✅ Debouncing helps with signal noise")
            
            print(f"\n💡 RECOMMENDATIONS")
            print("-" * 20)
            print("✅ Use 2-second measurements for optimal accuracy")
            print("✅ No averaging - detects real frequency changes")
            print("✅ No debouncing for clean signals")
            print("✅ Single measurements show actual system behavior")
            print("⚠️  Moving average masks real changes - not suitable for change detection")
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.optocoupler.cleanup()
            print(f"\n✅ Cleanup completed")

def main():
    """Run the comprehensive optocoupler test."""
    test = ComprehensiveOptocouplerTest()
    test.run_comprehensive_test()

if __name__ == "__main__":
    main()
