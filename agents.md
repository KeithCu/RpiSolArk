# RpiSolArk Codebase Guide for New Developers

## Overview

This document provides comprehensive guidance for new developers joining the RpiSolArk project. The system is a sophisticated frequency monitoring solution for Raspberry Pi that detects power source (Utility Grid vs Generator) by analyzing AC line frequency stability.

## System Architecture

### High-Level Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Optocoupler   │──▶│  Frequency      │──▶│  Power State    │
│   (Hardware)    │    │  Analysis       │    │  Machine        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │  Data Logger    │    │  Display &      │
                       │  & Health       │    │  LED Control    │
                       │  Monitoring     │    │                 │
                       └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │  Sol-Ark Cloud  │    │  System Updates │
                       │  Integration    │    │  & OS Tuning    │
                       └─────────────────┘    └─────────────────┘
```

### Data Flow

1. **Input**: AC line frequency via optocoupler (H11AA1) using `libgpiod` interrupts.
2. **Processing**: Real-time frequency analysis using standard deviation and Allan variance (simplified OR logic).
3. **Classification**: Power source detection (Utility Grid vs Generac Generator).
4. **State Management**: Power state machine with simple debouncing (5-second consistency requirement) and persistence.
5. **Output**: LCD display, LED indicators, logging, and **Sol-Ark Cloud automation** (Time of Use toggling).

## Core Components

### 1. monitor.py - Main Application Orchestrator

**Purpose**: Central coordinator that orchestrates all system components with comprehensive reliability features.

**Key Classes**:
- `FrequencyMonitor`: Main application controller with resource tracking.
- `FrequencyAnalyzer`: Simplified frequency analysis using std_dev + Allan variance (OR logic).
- `PowerStateMachine`: Persistent state management with simple debouncing (5-second consistency requirement).

**Key Features**:
- **Upgrade Lock**: Prevents automatic system upgrades (`unattended-upgrades`) during Off-Grid or Generator states to ensure system availability.
- **Drift Correction**: Main loop calculates sleep time to maintain precise sample rates.
- **Reliability**: Persistent state storage (JSON), buffer corruption detection, and atomic file operations.
- **Simplified Detection**: Uses only std_dev + Allan variance (removed kurtosis and confidence complexity for maintainability).

**Dependencies**: All other components.

### 2. hardware.py - Hardware Abstraction Layer

**Purpose**: Provides unified interface to all hardware components with graceful degradation.

**Key Classes**:
- `HardwareManager`: Main hardware coordinator.

**Key Features**:
- Delegates to specialized component managers (`gpio`, `optocoupler`, `display`).
- Graceful degradation when hardware (GPIO, LCD) is unavailable.
- **Thread Priority**: Sets high process priority and CPU affinity (Core 3) for stable timing.

### 3. display.py - Display and LED Management

**Purpose**: Manages LCD display, LED indicators, and display logic.

**Key Classes**:
- `DisplayManager`: LCD and LED control.

**Key Features**:
- **Smart Timeout**: Turns off display after inactivity unless in emergency state (Off-Grid/Generator).
- **Driver Support**: Supports both original `LCD1602` and `RPLCD` libraries.
- **Emergency State Handling**: Forces display ON during power events.

### 4. optocoupler.py - Frequency Measurement

**Purpose**: High-accuracy frequency measurement using `libgpiod` interrupts (GIL-safe).

**Key Classes**:
- `OptocouplerManager`: Manages the optocoupler hardware.
- `SingleOptocoupler`: Individual optocoupler management with recovery mechanisms.

**Key Features**:
- **GIL-free Counting**: Uses `gpio_event_counter` C extension (via `libgpiod`) for accurate interrupt counting.
- **Health Monitoring**: Tracks consecutive errors and attempts automatic recovery (re-initialization).
- **Frequency Calculation**: Configurable pulse counting logic.

### 5. solark_cloud.py & solark_integration.py - Cloud Automation

**Purpose**: Automates Sol-Ark inverter settings via the cloud portal using **Playwright**.

**Key Classes**:
- `SolArkCloud`: Low-level browser automation (Login, Navigation, TOU Toggling).
- `SolArkIntegration`: High-level logic mapping power states to inverter settings.

**Key Features**:
- **Browser Automation**: Uses Playwright (Chromium) to interact with the Sol-Ark web portal.
- **Session Persistence**: Saves/loads cookies and local storage to avoid repeated logins.
- **Time of Use (TOU) Toggling**: Automatically enables TOU on Grid and disables on Generator/Off-Grid.
- **Multi-Inverter Support**: Can control multiple inverters mapped to specific optocouplers.
- **Resilience**: Handles redirects, login expirations, and network timeouts.

### 6. rpisolark_optimize_writes.py - SD Card Preservation

**Purpose**: System tuning script to reduce MicroSD card wear for 24/7 operation.

**Key Features**:
- **Journald in RAM**: Sets `Storage=volatile` for system logs.
- **Disable Periodic Tasks**: Disables APT daily update timers.
- **Mount Options**: Applies `noatime` to filesystems.
- **Tmpfs**: Mounts `/tmp` in RAM.
- **Idempotent**: Can be run multiple times safely (`apply`, `revert`, `status` modes).

### 7. config.py - Configuration Management

**Purpose**: YAML configuration loading with strict validation.

**Key Features**:
- **Fail-fast Validation**: Prevents startup if critical config is missing.
- **Type Checking**: Ensures numeric values are within valid ranges.

### 8. health.py - System Monitoring

**Purpose**: Monitors system health (CPU, RAM) and integrates with systemd watchdog.

**Key Classes**:
- `HealthMonitor`: Resource tracking and systemd watchdog notifications.
- `MemoryMonitor`: Tracks process memory and triggers GC if needed.

**Key Features**:
- **Systemd Watchdog Integration**: Sends watchdog notifications to systemd for automatic service restart.
- **Resource Monitoring**: Tracks CPU, memory, threads, and file handles.
- **Atomic CSV Logging**: Uses `fcntl` locking for safe log writes.

### 9. setup_zero_code_updates.sh - Auto-Update System

**Purpose**: User-friendly script to set up automatic code updates.

**Options**:
- Systemd Timer (Recommended)
- Cron Job
- GitHub Actions
- Watchman / Inotify

---

## Key Concepts

### Frequency Analysis & Power Source Detection

The system uses **two complementary analysis methods** (simplified for reliability and maintainability):

1. **Standard Deviation**: Measures overall frequency spread (100% detection rate - catches all generator instability patterns).
2. **Allan Variance**: Detects short-term frequency instability and temporal hunting patterns (75% detection rate - catches temporal patterns std dev might miss).

**Generator Detection**: Generators exhibit "hunting" patterns (oscillations around 60Hz). Utility grid is typically very stable. 

**Simplified OR Logic**: The system uses simple OR logic: if EITHER metric exceeds threshold → generator detected. This maintains 100% accuracy while keeping the code simple and maintainable.

**Note**: Kurtosis was removed (only 25% effective) and confidence scoring was simplified to simple debouncing. See [SIMPLIFICATION_PROPOSAL.md](SIMPLIFICATION_PROPOSAL.md) for details.

### Power State Machine

**States**: `OFF_GRID`, `GRID`, `GENERATOR`, `TRANSITIONING`.

**Features**:
- **Persistence**: Saves state to JSON to survive restarts.
- **Simple Debouncing**: Requires state to be consistent for 5 seconds before transitioning (prevents rapid state changes).
- **Upgrade Lock**: Creates `/var/run/unattended-upgrades.lock` during Off-Grid/Generator states to prevent system updates from causing downtime when power is critical.

### Sol-Ark Cloud Automation

- **Goal**: Optimize battery usage based on power source.
- **Logic**:
    - **Grid**: Enable Time of Use (TOU) to use battery for peak shaving/arbitrage.
    - **Generator/Off-Grid**: Disable TOU to prioritize battery charging/preservation.
- **Implementation**: Headless browser automation fills gaps in the official API.

---

## Configuration

### config.yaml Structure (Updated)

```yaml
# Hardware Configuration
hardware:
  gpio_pin: 17
  led_green: 19
  led_red: 27
  reset_button: 22
  button_pin: 18
  lcd_address: 0x27
  display_timeout_seconds: 300
  optocoupler:
    enabled: true
    primary:
      gpio_pin: 26
      name: "Mechanical"
      pulses_per_cycle: 2
      measurement_duration: 2.0
      # List of inverters controlled by this source
      inverters:
        - id: "2207079903"
          name: "Main Inverter"
          enabled: true

# Sol-Ark Cloud Integration
solark_cloud:
  enabled: true
  username: "your_email@example.com"
  password: "your_password"
  base_url: "https://www.solarkcloud.com"
  cache_dir: "solark_cache"
  headless: true
  timeout: 30
  retry_attempts: 3
  session_persistence: true
  session_file: "solark_session.json"
  session_timeout: 3600
  cache_pages: false
  sync_interval: 300
  parameter_changes:
    enabled: true
    time_of_use_enabled: true

# Analysis, State Machine, Logging, Health... (same as before)
```

## Development Workflow

### Getting Started

1. **Clone & Install**:
   ```bash
   git clone <repo>
   uv sync
   playwright install chromium  # Required for Sol-Ark integration
   ```

2. **Optimize OS (Recommended)**:
   ```bash
   sudo python3 rpisolark_optimize_writes.py apply
   ```

3. **Configure**:
   Copy `config.yaml.example` to `config.yaml` and edit.

4. **Run**:
   ```bash
   # Activate virtual environment first
   source .venv/bin/activate  # or: . .venv/bin/activate
   
   # Simulator
   python monitor.py --simulator
   
   # Real Hardware
   python monitor.py --real
   ```

### Testing

- **Unit Tests**: `pytest tests/`
- **Sol-Ark Integration**: `python solark_cloud.py` (Runs a test login/TOU toggle check)
- **Hardware**: `python tests/test_optocoupler.py`

## Raspberry Pi Specifics

### Platform Requirements

- **Platform**: Raspberry Pi (tested on RPi 4B)
- **OS**: Latest Debian (Raspberry Pi OS)
- **Python**: 3.8+
- **GPIO Library**: `libgpiod` via `gpio_event_counter` (C extension)

### Performance Optimizations

1.  **CPU Affinity**: The `HardwareManager` attempts to pin the process to **Core 3** (via `psutil`). This isolates the monitoring loop from system processes typically running on Core 0/1, ensuring consistent timing for frequency analysis.
2.  **Process Priority**: Sets "high" process priority (`nice -5`) to reduce scheduling latency.
3.  **MicroSD Wear**: The `rpisolark_optimize_writes.py` script reduces write amplification by moving logs to RAM and disabling unnecessary background updates.

### LCD Options

- **LCD1602 (Default)**: Uses direct I2C communication. Fast and simple.
- **RPLCD (Alternative)**: Enable by setting `USE_RPLCD = True` in `display.py`. Provides a more robust driver if the default one has compatibility issues.

---

## Common Tasks

### Add New GPIO Device

To add control for a new hardware component (e.g., a relay or buzzer):

1.  **Update Configuration**:
    Add the pin number to `config.yaml`:
    ```yaml
    hardware:
      new_device_pin: 23
    ```

2.  **Update `gpio_manager.py`**:
    Initialize the pin in `_setup_gpio()`:
    ```python
    def _setup_gpio(self):
        # ... existing setup ...
        if 'new_device_pin' in self.config['hardware']:
            pin = self.config['hardware']['new_device_pin']
            self.gpio.setup(pin, self.gpio.OUT)
            self.gpio.output(pin, self.gpio.LOW)
    ```

3.  **Add Control Method**:
    Add a method to `GPIOManager`:
    ```python
    def set_new_device(self, state: bool):
        pin = self.config['hardware'].get('new_device_pin')
        if pin:
            self.gpio.output(pin, state)
    ```

### Adjust Detection Thresholds

If the system falsely detects Generator power (False Positive) or misses it (False Negative):

1.  **Collect Data**:
    Run in tuning mode to capture raw frequency data during the event:
    ```bash
    python monitor.py --tuning --tuning-duration 1800
    ```

2.  **Update `config.yaml`**:
    *   **False Generator**: Increase thresholds (make it less sensitive).
    *   **Missed Generator**: Decrease thresholds (make it more sensitive).

    ```yaml
    analysis:
      generator_thresholds:
        allan_variance: 0.0001  # Typical range: 0.00005 - 0.0005
        std_dev: 0.6            # Typical range: 0.3 - 1.0
        # Note: Kurtosis removed - simplified to std_dev + allan_variance only
    ```

### Add New Sol-Ark Parameter

To automate a new setting (e.g., "Battery Charge Current"):

1.  **Update `solark_cloud.py`**:
    Add a method to navigate to and toggle the specific setting using Playwright selectors. Use `self.page.click()` and `self.page.fill()`.

2.  **Update `solark_integration.py`**:
    Map the power state (`grid`/`generator`) to the desired parameter value in `on_power_source_change`.

---

## Troubleshooting

### Sol-Ark Integration Issues

**Symptoms**: Logs show "Element not found" or "Login failed".

**Solutions**:
1.  **Check Dependencies**: Run `playwright install chromium`.
2.  **Headless Mode**: Try running with `headless: false` in `config.yaml` to watch the browser automation and see where it fails.
3.  **Cache**: Clear the `solark_session.json` file to force a fresh login.
4.  **Selectors**: Sol-Ark may have updated their UI. Check `solark_cloud.py` selectors against the actual website HTML.

### No Frequency Reading

**Symptoms**: "No pulses detected" or 0Hz reading.

**Solutions**:
1.  **Optocoupler Wiring**: Verify H11AA1 pinout. Input side needs AC, output side needs pull-up resistor.
2.  **GPIO Permissions**: Ensure user has access: `sudo usermod -a -G gpio pi`.
3.  **Simulator**: Test with `python monitor.py --simulator` to verify software logic.

### High CPU Usage

**Symptoms**: System becomes sluggish.

**Solutions**:
1.  **Sample Rate**: Reduce `sampling.sample_rate` in `config.yaml`.
2.  **Logging**: Disable `detailed_logging` if enabled.
3.  **Browser**: Ensure Playwright isn't spawning "zombie" processes. The `SolArkCloud` class should clean these up, but check `htop` for stuck `chrome` or `node` processes.

### Memory Issues

**Symptoms**: Application crashes with Out of Memory.

**Solutions**:
1.  **Memory Monitor**: Check `memory_usage.csv`.
2.  **Buffer Size**: Reduce `analysis.analysis_window_seconds` (default: 30 seconds).
3.  **Browser Leaks**: Browser automation is heavy. Ensure `solark_cloud` is only instantiating the browser when needed or properly closing contexts.
