#!/usr/bin/env python3
"""
Test script for dual optocoupler accuracy improvements.
Tests the new threaded simultaneous measurement implementation.
"""

import time
import logging
import sys
from config import Config

# Add current directory to path for imports
sys.path.append('.')

from optocoupler import OptocouplerManager

def setup_logging():
    """Setup logging for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger('dual_optocoupler_test')

def test_dual_optocoupler_accuracy():
    """Test dual optocoupler accuracy with threaded implementation."""
    logger = setup_logging()
    logger.info("Starting dual optocoupler accuracy test...")
    
    # Load configuration
    config = Config("config.yaml")
    
    # Initialize optocoupler manager
    optocoupler_manager = OptocouplerManager(config, logger)
    
    if not optocoupler_manager.optocoupler_initialized:
        logger.error("Optocoupler manager not initialized - check GPIO availability")
        return False
    
    # Check if dual mode is enabled
    if not optocoupler_manager.is_dual_mode():
        logger.warning("Dual mode not enabled - testing single optocoupler only")
        return test_single_optocoupler(optocoupler_manager, logger)
    
    logger.info("Dual optocoupler mode enabled - testing simultaneous measurement")
    
    # Test parameters
    test_duration = 2.0  # 2-second measurements
    num_tests = 5
    debounce_time = 0.0  # No debouncing for clean signals
    
    logger.info(f"Running {num_tests} dual measurements of {test_duration}s each...")
    
    results = []
    start_time = time.time()
    
    for i in range(num_tests):
        logger.info(f"Test {i+1}/{num_tests}")
        
        # Measure both optocouplers simultaneously
        primary_freq, secondary_freq = optocoupler_manager.get_dual_frequencies(
            duration=test_duration, 
            debounce_time=debounce_time
        )
        
        result = {
            'test': i + 1,
            'primary_freq': primary_freq,
            'secondary_freq': secondary_freq,
            'timestamp': time.time()
        }
        results.append(result)
        
        logger.info(f"  Primary: {primary_freq:.3f} Hz" if primary_freq else "  Primary: No signal")
        logger.info(f"  Secondary: {secondary_freq:.3f} Hz" if secondary_freq else "  Secondary: No signal")
        
        # Small delay between tests
        time.sleep(0.5)
    
    total_time = time.time() - start_time
    logger.info(f"Completed {num_tests} tests in {total_time:.2f} seconds")
    
    # Analyze results
    analyze_results(results, logger)
    
    return True

def test_single_optocoupler(optocoupler_manager, logger):
    """Test single optocoupler mode."""
    logger.info("Testing single optocoupler mode...")
    
    test_duration = 2.0
    num_tests = 3
    
    for i in range(num_tests):
        logger.info(f"Single test {i+1}/{num_tests}")
        
        pulse_count = optocoupler_manager.count_optocoupler_pulses(
            duration=test_duration, 
            debounce_time=0.0, 
            optocoupler_name='primary'
        )
        
        frequency = optocoupler_manager.calculate_frequency_from_pulses(
            pulse_count, 
            test_duration, 
            'primary'
        )
        
        logger.info(f"  Pulses: {pulse_count}, Frequency: {frequency:.3f} Hz" if frequency else "  No signal detected")
        time.sleep(0.5)
    
    return True

def analyze_results(results, logger):
    """Analyze test results for accuracy assessment."""
    logger.info("\n=== ACCURACY ANALYSIS ===")
    
    # Filter valid results
    valid_primary = [r for r in results if r['primary_freq'] is not None]
    valid_secondary = [r for r in results if r['secondary_freq'] is not None]
    
    logger.info(f"Valid primary readings: {len(valid_primary)}/{len(results)}")
    logger.info(f"Valid secondary readings: {len(valid_secondary)}/{len(results)}")
    
    if valid_primary:
        primary_freqs = [r['primary_freq'] for r in valid_primary]
        primary_avg = sum(primary_freqs) / len(primary_freqs)
        primary_std = (sum((f - primary_avg)**2 for f in primary_freqs) / len(primary_freqs))**0.5
        
        logger.info(f"Primary frequency - Average: {primary_avg:.3f} Hz, Std Dev: {primary_std:.3f} Hz")
        logger.info(f"Primary range: {min(primary_freqs):.3f} - {max(primary_freqs):.3f} Hz")
    
    if valid_secondary:
        secondary_freqs = [r['secondary_freq'] for r in valid_secondary]
        secondary_avg = sum(secondary_freqs) / len(secondary_freqs)
        secondary_std = (sum((f - secondary_avg)**2 for f in secondary_freqs) / len(secondary_freqs))**0.5
        
        logger.info(f"Secondary frequency - Average: {secondary_avg:.3f} Hz, Std Dev: {secondary_std:.3f} Hz")
        logger.info(f"Secondary range: {min(secondary_freqs):.3f} - {max(secondary_freqs):.3f} Hz")
    
    # Check for simultaneous measurement accuracy
    if valid_primary and valid_secondary:
        logger.info("\n=== SIMULTANEOUS MEASUREMENT ANALYSIS ===")
        
        # Calculate timing differences
        timing_diffs = []
        for r in results:
            if r['primary_freq'] and r['secondary_freq']:
                # Calculate frequency difference as accuracy metric
                freq_diff = abs(r['primary_freq'] - r['secondary_freq'])
                timing_diffs.append(freq_diff)
        
        if timing_diffs:
            avg_diff = sum(timing_diffs) / len(timing_diffs)
            max_diff = max(timing_diffs)
            logger.info(f"Average frequency difference between optocouplers: {avg_diff:.3f} Hz")
            logger.info(f"Maximum frequency difference: {max_diff:.3f} Hz")
            
            if avg_diff < 0.1:
                logger.info("✅ EXCELLENT: Simultaneous measurement accuracy is very high")
            elif avg_diff < 0.5:
                logger.info("✅ GOOD: Simultaneous measurement accuracy is acceptable")
            else:
                logger.info("⚠️  WARNING: Simultaneous measurement accuracy may need improvement")

def main():
    """Main test function."""
    print("Dual Optocoupler Accuracy Test")
    print("=" * 40)
    
    try:
        success = test_dual_optocoupler_accuracy()
        
        if success:
            print("\n✅ Test completed successfully")
            print("\nKey improvements in the new implementation:")
            print("• Threaded simultaneous measurement (both optocouplers at same time)")
            print("• CPU affinity optimization for RPi4")
            print("• High-priority process scheduling")
            print("• No sequential measurement delays")
        else:
            print("\n❌ Test failed")
            return 1
            
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
