#!/usr/bin/env python3
"""
State Machine Tests for RpiSolark Frequency Monitor
Tests the power state machine transitions and functionality.
"""

import sys
import os
import logging
from pathlib import Path

# Add parent directory to path so we can import monitor module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitor import PowerState, PowerStateMachine
from config import Config


def test_state_machine():
    """Test the state machine with simulated conditions."""
    # Setup basic logging for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    # Create config and state machine
    config = Config("config.yaml")
    state_machine = PowerStateMachine(config, logger)

    print("Testing State Machine Transitions")
    print("=" * 50)

    # Test scenarios
    test_cases = [
        # (frequency, power_source, zero_voltage_duration, expected_state, description)
        (None, "Unknown", 6.0, PowerState.OFF_GRID, "No signal for 6 seconds"),
        (None, "Unknown", 2.0, PowerState.TRANSITIONING, "No signal for 2 seconds"),
        (59.8, "Utility Grid", 0.0, PowerState.GRID, "Stable utility power"),
        (60.2, "Utility Grid", 0.0, PowerState.GRID, "Stable utility power"),
        (58.5, "Generac Generator", 0.0, PowerState.GENERATOR, "Generator power detected"),
        (61.5, "Generac Generator", 0.0, PowerState.GENERATOR, "Generator power detected"),
        (60.0, "Unknown", 0.0, PowerState.TRANSITIONING, "Uncertain classification"),
        (None, "Unknown", 8.0, PowerState.OFF_GRID, "Extended no signal"),
    ]

    all_passed = True
    for freq, power_source, zero_duration, expected, description in test_cases:
        state = state_machine.update_state(freq, power_source, zero_duration)
        status = "PASS" if state == expected else "FAIL"
        if state != expected:
            all_passed = False
        print(f"{status}: {description}")
        print(f"    State: {state.value} (expected: {expected.value})")
        if freq is not None:
            print(f"    Frequency: {freq:.1f} Hz, Source: {power_source}, ZeroDuration: {zero_duration:.1f}s")
        else:
            print(f"    No signal, ZeroDuration: {zero_duration:.1f}s")
        print()

    # Summary
    print("=" * 50)
    if all_passed:
        print("ALL TESTS PASSED!")
        return True
    else:
        print("SOME TESTS FAILED!")
        return False


def test_state_transitions():
    """Test specific state transition sequences."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    config = Config("config.yaml")
    state_machine = PowerStateMachine(config, logger)

    print("\nTesting State Transition Sequences")
    print("=" * 50)

    # Test: Off-grid -> Grid (power restoration)
    print("Test 1: Power restoration sequence")
    state_machine.update_state(None, "Unknown", 6.0)  # OFF_GRID
    assert state_machine.current_state == PowerState.OFF_GRID
    print("  OFF_GRID: OK")

    state_machine.update_state(60.0, "Utility Grid", 0.0)  # GRID
    assert state_machine.current_state == PowerState.GRID
    print("  -> GRID: OK")

    # Test: Grid -> Generator (generator starts)
    print("\nTest 2: Generator startup sequence")
    state_machine.update_state(58.5, "Generac Generator", 0.0)  # GENERATOR
    assert state_machine.current_state == PowerState.GENERATOR
    print("  -> GENERATOR: OK")

    # Test: Generator -> Off-grid (power failure)
    print("\nTest 3: Complete power failure")
    state_machine.update_state(None, "Unknown", 6.0)  # OFF_GRID
    assert state_machine.current_state == PowerState.OFF_GRID
    print("  -> OFF_GRID: OK")

    print("\nALL TRANSITION TESTS PASSED!")
    return True


def test_state_timeout():
    """Test transition timeout functionality."""
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')  # Reduce log noise
    logger = logging.getLogger(__name__)

    config = Config("config.yaml")
    state_machine = PowerStateMachine(config, logger)

    print("\nTesting Transition Timeout")
    print("=" * 50)

    # Put in transitioning state
    state_machine.update_state(None, "Unknown", 2.0)  # TRANSITIONING
    assert state_machine.current_state == PowerState.TRANSITIONING
    print("Initial state: TRANSITIONING: OK")

    # Simulate timeout by manually setting state_entry_time
    import time
    state_machine.state_entry_time = time.time() - 35  # 35 seconds ago (past timeout)

    # This should trigger timeout and force OFF_GRID
    state_machine.update_state(None, "Unknown", 2.0)  # Should timeout
    assert state_machine.current_state == PowerState.OFF_GRID
    print("Timeout triggered: OFF_GRID: OK")

    print("\nTIMEOUT TEST PASSED!")
    return True


def test_reset_button():
    """Test reset button functionality (mock test)."""
    print("\nTesting Reset Button Configuration")
    print("=" * 50)

    # Test that reset button is configured in config
    try:
        from config import Config
        config = Config("config.yaml")
        reset_pin = config.get('hardware.reset_button', None)

        if reset_pin == 22:
            print("PASS: Reset button pin configured correctly (GPIO 22)")
            return True
        else:
            print(f"FAIL: Reset button pin not configured correctly. Expected 22, got {reset_pin}")
            return False
    except Exception as e:
        print(f"ERROR: Failed to test reset button configuration: {e}")
        return False


def run_all_tests():
    """Run all state machine tests."""
    print("TEST: Running State Machine Tests")
    print("=" * 60)

    tests = [
        ("Basic State Transitions", test_state_machine),
        ("State Transition Sequences", test_state_transitions),
        ("Transition Timeout", test_state_timeout),
        ("Reset Button Configuration", test_reset_button),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\nTEST: {test_name}")
        try:
            result = test_func()
            results.append((test_name, result))
            status = "PASSED" if result else "FAILED"
            print(f"{test_name}: {status}")
        except Exception as e:
            print(f"{test_name}: ERROR - {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = 0
    total = len(results)
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{status}: {test_name}")
        if result:
            passed += 1

    print(f"\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("SUCCESS: ALL TESTS PASSED! State machine is working correctly.")
        return True
    else:
        print("WARNING: SOME TESTS FAILED! Check the output above.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
