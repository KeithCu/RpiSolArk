#!/usr/bin/env python3
"""
Test script to compare headless vs non-headless mode for Sol-Ark integration.
Tests TOU state reading for a single inverter in both modes.
"""

import sys
import time
import logging
from config import Config, Logger

# Setup logging
config = Config("config.yaml")
logger_setup = Logger(config)
logger = logging.getLogger(__name__)

def test_tou_reading(headless_mode: bool, inverter_id: str, plant_id: str):
    """Test TOU state reading in specified headless mode."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing TOU reading in {'HEADLESS' if headless_mode else 'NON-HEADLESS'} mode")
    logger.info(f"Inverter ID: {inverter_id}, Plant ID: {plant_id}")
    logger.info(f"{'='*60}\n")
    
    # Temporarily modify config
    original_headless = config['solark_cloud']['headless']
    config['solark_cloud']['headless'] = headless_mode
    
    try:
        from solark_cloud import SolArkCloud
        
        # Create SolArkCloud instance
        solark_cloud = SolArkCloud()
        
        # Test TOU state reading
        start_time = time.time()
        logger.info(f"Starting TOU state read at {time.strftime('%H:%M:%S')}...")
        
        result = solark_cloud.get_time_of_use_state(inverter_id, plant_id)
        
        elapsed_time = time.time() - start_time
        logger.info(f"TOU state read completed in {elapsed_time:.2f} seconds")
        logger.info(f"Result: {result}")
        
        # Cleanup
        solark_cloud.cleanup()
        
        return result, elapsed_time
        
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
        return None, None
    finally:
        # Restore original config
        config['solark_cloud']['headless'] = original_headless

def main():
    """Run comparison test."""
    if len(sys.argv) < 3:
        print("Usage: python test_headless_comparison.py <inverter_id> <plant_id>")
        print("Example: python test_headless_comparison.py 2209062020 122227")
        sys.exit(1)
    
    inverter_id = sys.argv[1]
    plant_id = sys.argv[2]
    
    logger.info("="*60)
    logger.info("Sol-Ark Headless vs Non-Headless Comparison Test")
    logger.info("="*60)
    
    # Test 1: Headless mode
    logger.info("\n>>> TEST 1: HEADLESS MODE <<<")
    headless_result, headless_time = test_tou_reading(True, inverter_id, plant_id)
    
    # Wait a bit between tests
    logger.info("\nWaiting 5 seconds before next test...")
    time.sleep(5)
    
    # Test 2: Non-headless mode
    logger.info("\n>>> TEST 2: NON-HEADLESS MODE <<<")
    non_headless_result, non_headless_time = test_tou_reading(False, inverter_id, plant_id)
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("COMPARISON SUMMARY")
    logger.info("="*60)
    logger.info(f"Headless Mode:")
    logger.info(f"  Result: {headless_result}")
    logger.info(f"  Time: {headless_time:.2f} seconds" if headless_time else "  Time: FAILED")
    logger.info(f"\nNon-Headless Mode:")
    logger.info(f"  Result: {non_headless_result}")
    logger.info(f"  Time: {non_headless_time:.2f} seconds" if non_headless_time else "  Time: FAILED")
    
    if headless_result is not None and non_headless_result is not None:
        if headless_result == non_headless_result:
            logger.info(f"\n✓ Results MATCH: Both modes returned {headless_result}")
        else:
            logger.warning(f"\n✗ Results DIFFER: Headless={headless_result}, Non-Headless={non_headless_result}")
    
    if headless_time and non_headless_time:
        time_diff = abs(headless_time - non_headless_time)
        faster_mode = "HEADLESS" if headless_time < non_headless_time else "NON-HEADLESS"
        logger.info(f"\nTime difference: {time_diff:.2f} seconds ({faster_mode} was faster)")
    
    logger.info("="*60)

if __name__ == "__main__":
    main()
