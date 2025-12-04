# Codebase Analysis & Improvement Plan

## 1. Immediate Issue: Frequency Noise Analysis
The recent "Precise Timestamp" fix confirmed that we are reading approximately **60.6 Hz** on a likely 60.0 Hz signal. This +0.6 Hz bias indicates we are counting extra edges (noise/ringing).

### Plan
1.  **Analyze Interval Distribution**:
    *   Modify `test_optocoupler.py` (or create `analyze_noise.py`) to log the *difference* between consecutive timestamps.
    *   **Hypothesis**: We will see many intervals near ~8.33ms (correct half-cycle for 60Hz * 2 edges) but also some very short intervals (e.g., < 0.1ms) representing noise/bounce.
2.  **Implement Software Filtering**:
    *   Update `optocoupler.py` to ignore intervals smaller than a threshold (e.g., 2ms).
    *   $Frequency_{max} = 1 / (2ms) = 500Hz$. Since valid signal is 120Hz (edges) or 240Hz (edges), 2ms is safe.
3.  **Verify Hardware Debounce**:
    *   Check if `gpiod` line settings in `gpio_event_counter.py` can enable kernel-level debouncing.

## 2. Integration Verification
Ensure the new `optocoupler.py` logic integrates correctly with the main application `monitor.py`.

### Plan
1.  **Dry Run**: Run `python monitor.py --simulator` (or real if safely possible) and check logs for "Precision Frequency" entries.
2.  **Performance Check**: Ensure the overhead of storing/retrieving large lists of timestamps (e.g., ~1200 integers per 5s) does not cause CPU spikes or memory issues.

## 3. Codebase Health & Refactoring
The codebase has grown with multiple "managers" and hardware abstractions.

### Plan
1.  **Deprecation Cleanup**:
    *   Remove old `RPi.GPIO` fallback code if `libgpiod` is now the stable standard.
    *   Remove unused test scripts in `tests/`.
2.  **Type Safety**:
    *   Add Python type hints to `monitor.py` and `hardware.py`.
    *   Run `mypy` to catch potential type-related bugs.
3.  **Documentation**:
    *   Update `README.md` and `FREQUENCY_ANALYSIS.md` to reflect the new "Timestamp Method".
