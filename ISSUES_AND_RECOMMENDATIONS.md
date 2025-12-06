# Codebase Analysis: Issues and Recommendations

This document details the major issues identified during the codebase analysis of the RpiSolark frequency monitor. These issues impact system responsiveness, reliability, and maintainability.

## 1. Blocking Main Loop (Critical Architectural Issue)

**Severity**: High
**Affected Files**: `monitor.py`, `optocoupler.py`

### Description
The application's core loop in `monitor.py` is synchronous and blocks for the entire duration of the frequency measurement window (default: 2 seconds) on every iteration.

**Call Chain**:
1. `monitor.py`: `FrequencyMonitor.run()` calls `self.analyzer.count_zero_crossings(duration=measurement_duration)`
2. `monitor.py`: `FrequencyAnalyzer._count_optocoupler_pulses()` calls `self.hardware_manager.count_optocoupler_pulses()`
3. `hardware.py`: Delegates to `optocoupler.count_optocoupler_pulses()`
4. `optocoupler.py`: `SingleOptocoupler.count_optocoupler_pulses()` executes `time.sleep(duration)`

```python
# optocoupler.py
def count_optocoupler_pulses(self, duration: float = None, ...):
    # ...
    # Wait for the specified duration - libgpiod handles counting in background
    time.sleep(duration)  # <--- THIS BLOCKS THE MAIN THREAD
    # ...
```

### Impact
*   **Unresponsive UI**: The LCD display and LED status indicators are frozen during the 2-second sleep. They only update once per loop (every ~2.1 seconds).
*   **Missed Inputs**: Although `ButtonHandler` runs in a separate thread, any other inputs handled by the main loop (like the Reset Button check in `monitor.py`) are only checked once every ~2 seconds.
*   **Watchdog Jitter**: The systemd watchdog is "petted" only once per loop. If the system load delays the loop slightly beyond the watchdog timeout, it could trigger a false reboot.
*   **Health Check Delays**: System health monitoring logic in the main loop is paused.

### Recommendation
Refactor the frequency measurement to be **non-blocking** or **asynchronous**.
*   **Approach**: Since `gpio_event_counter.py` already runs a background thread to collect timestamps, the main loop does not need to sleep.
*   **Implementation**:
    1.  Start a measurement window (record start time, reset counters).
    2.  Let the main loop continue running (updating display, checking buttons, petting watchdog).
    3.  Check periodically if the measurement window has elapsed.
    4.  When elapsed, retrieve the count/timestamps and process the result.

## 2. State Persistence Configuration Conflict

**Severity**: High
**Affected Files**: `monitor.py`, `rpisolark_optimize_writes.py`

### Description
The application attempts to save persistent state (power state, previous state) to a file to survive restarts. However, the configuration places this file in `/tmp`, and the optimization script mounts `/tmp` as RAM (tmpfs).

**Code**:
*   `monitor.py`: `self.state_file = f"/tmp/{config.get('state_machine.state_file')}"`
*   `rpisolark_optimize_writes.py`: `apply_tmpfs_tmp()` adds `tmpfs /tmp ...` to `/etc/fstab`.

### Impact
Any state saved to `/tmp` is lost when the Raspberry Pi reboots. This defeats the purpose of the `persistent_state_enabled` feature. If the system reboots while "Off-Grid", it will forget this state and potentially start in "Grid" mode or "Transitioning", losing context of the ongoing power event.

### Recommendation
*   Move the state file location to a persistent directory, such as `/var/lib/rpisolark/` or `/home/pi/.rpisolark/`.
*   Update `config.yaml` and `monitor.py` to use this persistent path.

## 3. Busy-Wait in Fallback Counter

**Severity**: Medium
**Affected Files**: `monitor.py` (FrequencyAnalyzer)

### Description
If the optocoupler hardware (libgpiod) is not available, the system falls back to `_count_zero_crossings_original`. This method uses a busy-wait loop.

```python
# monitor.py
while time.time() - start_time < duration:
    state = self.hardware_manager.read_gpio()
    # ...
    time.sleep(0.00005)  # 50 microsecond sleep
```

### Impact
*   **High CPU Usage**: This loop consumes significant CPU resources compared to interrupt-based detection.
*   **Blocking**: Like the optocoupler method, this blocks the main thread completely.

### Recommendation
If fallback to polling is required, ensure it is done in a way that doesn't monopolize the CPU if possible, or accept the limitation but be aware of the CPU cost. Ideally, `libgpiod` should always be available on the target hardware.

## 4. Excessive Logging (Log Spam)

**Severity**: Low/Medium
**Affected Files**: `optocoupler.py`

### Description
The `optocoupler.py` module has a hardcoded flag enabled by default:
```python
ENABLE_REGRESSION_COMPARISON = True
```
This causes an `INFO` level log message to be written on *every* measurement cycle (every ~2 seconds):
`INFO: ... frequency comparison: First/Last=... Hz, Regression=... Hz ...`

### Impact
*   **Disk Wear/Fill**: Even with log rotation, writing to logs every 2 seconds generates 43,200 lines per day. If logging to SD card, this increases wear. If logging to RAM (via volatile journald), it fills the ring buffer, pushing out other important logs.

### Recommendation
*   Set `ENABLE_REGRESSION_COMPARISON = False` by default in production code.
*   Or move the log level to `DEBUG` so it only appears when verbose logging is enabled.

## 5. Ignored Debounce Parameter

**Severity**: Low
**Affected Files**: `optocoupler.py`

### Description
The `SingleOptocoupler.count_optocoupler_pulses` method accepts a `debounce_time` argument, but it is effectively ignored for the `libgpiod` path because the debounce setting is applied during initialization (`register_pin`) and not updated during the measurement call.

### Impact
Runtime changes to debounce timing (if passed) will not take effect. The system uses the default or configured debounce time set at startup.

### Recommendation
*   Remove the unused parameter to avoid confusion.
*   Or update `gpio_event_counter.py` to allow updating debounce settings dynamically (though this might be unnecessary complexity).

## 6. Sol-Ark Integration Fragility

**Severity**: Medium (Risk)
**Affected Files**: `solark_cloud.py`

### Description
The integration uses Playwright to scrape the Sol-Ark cloud website. It relies on specific DOM selectors (e.g., classes, text content).

### Impact
Any update to the Sol-Ark web portal's UI (HTML structure, class names) will break this integration instantly. This is an inherent risk of web scraping.

### Recommendation
*   Maintain comprehensive error handling (which seems to be in place).
*   Consider if an official API is available.
*   Add a specific "Integration Health" check that alerts if the DOM structure seems to have changed (e.g., cannot find login form or inverter table).

---

## Summary of Next Steps
1.  **Refactor `monitor.py`** to use a state-based, non-blocking approach for frequency measurement.
2.  **Change State File Path** in `config.yaml` / `monitor.py` to a persistent location.
3.  **Disable Debug Logging** flags in `optocoupler.py`.
