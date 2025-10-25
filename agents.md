# RpiSolArk Codebase Guide for New Developers

## Overview

This document provides comprehensive guidance for new developers joining the RpiSolArk project. The system is a sophisticated frequency monitoring solution for Raspberry Pi that detects power source (Utility Grid vs Generator) by analyzing AC line frequency stability.

## System Architecture

### High-Level Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Optocoupler   │───▶│  Frequency      │───▶│  Power State    │
│   (Hardware)    │    │  Analysis       │    │  Machine        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │  Data Logger    │    │  Display &      │
                       │  & Health       │    │  LED Control    │
                       │  Monitoring     │    │                 │
                       └─────────────────┘    └─────────────────┘
```

### Data Flow

1. **Input**: AC line frequency via optocoupler (H11AA1)
2. **Processing**: Real-time frequency analysis using Allan variance, standard deviation, and kurtosis
3. **Classification**: Power source detection (Utility Grid vs Generac Generator)
4. **State Management**: Power state machine with confidence-based transitions
5. **Output**: LCD display, LED indicators, logging, and optional Sol-Ark integration

## Core Components

### 1. monitor.py - Main Application Orchestrator

**Purpose**: Central coordinator that orchestrates all system components.

**Key Classes**:
- `FrequencyMonitor`: Main application controller
- `FrequencyAnalyzer`: Frequency analysis and classification
- `PowerStateMachine`: State management for power system

**Key Methods**:
- `run()`: Main monitoring loop
- `_signal_handler()`: Graceful shutdown handling
- `cleanup()`: Resource cleanup

**Dependencies**: All other components

### 2. hardware.py - Hardware Abstraction Layer

**Purpose**: Provides unified interface to all hardware components with graceful degradation.

**Key Classes**:
- `HardwareManager`: Main hardware coordinator

**Key Features**:
- Delegates to specialized component managers
- Graceful degradation when hardware unavailable
- Backward compatibility for existing code

**Dependencies**: `display.py`, `gpio_manager.py`, `optocoupler.py`

### 3. display.py - Display and LED Management

**Purpose**: Manages LCD display, LED indicators, and display logic.

**Key Classes**:
- `DisplayManager`: LCD and LED control

**Key Features**:
- Smart backlight timeout management
- Dual optocoupler cycling display
- LCD driver selection (original LCD1602 vs RPLCD)
- Emergency state handling (keeps display on during power events)

**Configuration**: Set `USE_RPLCD = True` in display.py to use RPLCD library

### 4. optocoupler.py - Frequency Measurement

**Purpose**: High-accuracy frequency measurement using libgpiod interrupts.

**Key Classes**:
- `OptocouplerManager`: Manages one or more optocouplers
- `SingleOptocoupler`: Individual optocoupler management

**Key Features**:
- GIL-free interrupt counting via libgpiod
- Dual optocoupler support
- CPU affinity optimization for consistent timing
- High-priority threading for accuracy

**AC-into-DC-Optocoupler Configuration**:
- **Hardware Setup**: H11AA1 DC optocoupler receiving AC input WITHOUT rectifier
- **Signal Behavior**: 
  - Positive AC half-cycle: optocoupler conducts → produces pulse
  - Negative AC half-cycle: reverse-biased → no output
  - Result: 1 pulse per AC cycle (not 2 like with rectifier)
- **Frequency Calculation**: `frequency = pulse_count / (duration * 2)`
  - libgpiod counts both edges: 2 edges per pulse
  - H11AA1 produces 1 pulse per AC cycle
  - Total: 2 edges per AC cycle
- **Noise Considerations**: AC signal may produce edge noise; outlier filtering applied

**Dependencies**: `gpio_event_counter.py` (C extension)

### 5. gpio_manager.py - GPIO Operations

**Purpose**: Low-level GPIO control for LEDs and buttons.

**Key Features**:
- LED control (green/red for power source indication)
- Reset button handling (active LOW with pull-up)
- Graceful degradation when GPIO unavailable

### 6. button_handler.py - Display Button Control

**Purpose**: Handles tactile push button for manual display activation.

**Key Features**:
- Manual display activation (5-minute timeout)
- Debounced button detection
- Polling-based detection (more reliable than edge detection)

### 7. config.py - Configuration Management

**Purpose**: YAML configuration loading and access helpers.

**Key Features**:
- Hierarchical configuration access
- Type conversion helpers
- Default value handling

### 8. health.py - System Monitoring

**Purpose**: Monitors system health and memory usage.

**Key Classes**:
- `HealthMonitor`: System health tracking
- `MemoryMonitor`: Memory usage monitoring

**Key Features**:
- CPU and memory threshold monitoring
- Watchdog timeout detection
- Memory cleanup automation
- CSV logging of memory usage

### 9. data_logger.py - Data Persistence

**Purpose**: Handles all data logging operations.

**Key Features**:
- Hourly status logging
- Detailed frequency logging (configurable)
- CSV output with comprehensive metadata
- Confidence scoring for classifications

### 10. tuning_collector.py - Data Collection for Tuning

**Purpose**: High-frequency data collection for threshold optimization.

**Key Features**:
- 10Hz sampling rate
- Comprehensive analysis data export
- Automatic collection duration
- Multiple export formats (CSV, JSON)

### 11. offline_analyzer.py - Post-Processing Analysis

**Purpose**: Analyzes collected data to recommend optimal thresholds.

**Key Features**:
- Statistical analysis of frequency data
- Threshold recommendations
- Pattern recognition
- Performance metrics

### 12. restart_manager.py - Application Restart Logic

**Purpose**: Handles application restart with safety checks.

**Key Features**:
- Cooldown periods between restarts
- Safety checks before restart
- Rate limiting (max restarts per hour)

## Supporting Components

### dashboard.py - Web Health Monitoring

**Purpose**: Separate Flask-based web dashboard for system monitoring.

**Features**:
- System status API
- Monitor process tracking
- Log viewing
- Temperature monitoring

**Usage**: `python dashboard.py` (runs on port 5000)

**Note**: This is a separate application, not integrated with the main monitor loop.

### solark_integration.py - Sol-Ark Cloud Integration

**Purpose**: Integrates with Sol-Ark cloud platform for parameter updates.

**Status**: Available but needs integration work. Not currently connected to main monitor loop.

**Features**:
- Automatic parameter changes based on power source
- Cloud synchronization
- Session persistence

### solark_cloud.py - Sol-Ark Cloud API Client

**Purpose**: Low-level Sol-Ark cloud API client using Playwright.

**Features**:
- Web automation for cloud platform
- Parameter change application
- Data synchronization

## Key Concepts

### Frequency Analysis & Power Source Detection

The system uses three complementary analysis methods:

1. **Allan Variance**: Detects short-term frequency instability and hunting patterns
2. **Standard Deviation**: Measures overall frequency spread
3. **Kurtosis**: Analyzes distribution shape to identify hunting vs random noise

**Generator Detection**: Generators exhibit characteristic "hunting" patterns where frequency oscillates around 60Hz due to mechanical governor response.

### Power State Machine

**States**:
- `OFF_GRID`: No voltage detected for extended period
- `GRID`: Stable utility power detected
- `GENERATOR`: Backup generator power detected  
- `TRANSITIONING`: Unclear state, waiting for classification

**Features**:
- Confidence-based transitions
- Emergency state handling (prevents system upgrades, forces display on)
- Timeout protection against stuck states

### Graceful Degradation

The system is designed to continue operating even when hardware components fail:

- **LCD Failure**: Falls back to console display
- **GPIO Failure**: Continues with simulated LEDs
- **Optocoupler Failure**: Uses simulator mode
- **Network Failure**: Continues local operation

### Dual Optocoupler Support

- Simultaneous frequency measurement from two sources
- Cycling display between readings (2-second intervals)
- Configurable via GPIO pins in config.yaml
- Useful for comparing different measurement points

## Configuration

### config.yaml Structure

```yaml
# Hardware Configuration
hardware:
  gpio_pin: 17          # Main GPIO input pin
  led_green: 19         # Green LED for Utility
  led_red: 27           # Red LED for Generator
  reset_button: 22      # Reset button input
  button_pin: 18        # Display control button
  lcd_address: 0x27     # I2C address for LCD
  optocoupler:
    enabled: true
    primary:
      gpio_pin: 26
      name: "Mechanical"
    secondary:
      gpio_pin: -1      # -1 for single mode
      name: "Lights"

# Sampling Configuration
sampling:
  sample_rate: 2.0      # Hz - Optimal for generator detection
  buffer_duration: 300  # seconds - Captures hunting cycles
  min_freq: 30.0        # Hz - Accounts for generator drops
  max_freq: 80.0        # Hz - Accounts for overspeed

# Analysis Configuration
analysis:
  allan_variance_tau: 10.0  # seconds for Allan variance
  generator_thresholds:
    allan_variance: 0.0001  # Hunting detection threshold
    std_dev: 0.6           # Frequency spread threshold
    kurtosis: 1.5           # Distribution shape threshold

# State Machine Configuration
state_machine:
  transition_timeout: 30.0       # Max time in transitioning
  zero_voltage_threshold: 1.0    # Time before off-grid
  unsteady_voltage_threshold: 0.1 # Hz variation threshold

# Logging Configuration
logging:
  detailed_logging_enabled: false
  detailed_log_interval: 1.0
  detailed_log_file: "detailed_frequency_data.csv"

# Health Monitoring
health:
  watchdog_timeout: 30.0
  memory_warning_threshold: 0.8
  cpu_warning_threshold: 0.8
  auto_reboot: true

# Sol-Ark Cloud (Work in Progress)
solark_cloud:
  enabled: true
  username: ""
  password: ""
  sync_interval: 300
```

## Development Workflow

### Getting Started

1. **Clone Repository**:
   ```bash
   git clone <repository-url>
   cd RpiSolArk
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Hardware**:
   - Edit `config.yaml` with your GPIO pin assignments
   - Enable I2C: `sudo raspi-config` → Interfacing Options → I2C
   - Check I2C address: `i2cdetect -y 1`

4. **Test in Simulator Mode**:
   ```bash
   python monitor.py --simulator
   ```

5. **Run with Hardware**:
   ```bash
   python monitor.py --real
   ```

### Testing

**Unit Tests**:
```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_monitor.py -v

# Run with coverage
python -m pytest tests/ --cov=.
```

**Hardware Tests**:
```bash
# Test GPIO components
python tests/quick_gpio_test.py

# Test LCD display
python tests/test_lcd_compatibility.py

# Test optocoupler
python tests/test_optocoupler.py
```

### Debugging

**Verbose Logging**:
```bash
python monitor.py --verbose
```

**Remote Debugging**:
```bash
python monitor.py --debug --debug-port 5678
# Connect with VS Code or PyCharm debugger
```

**Detailed Frequency Logging**:
```bash
python monitor.py --detailed-logging --log-interval 0.5
```

**Check Logs**:
```bash
tail -f monitor.log
cat hourly_status.csv
```

### Tuning Thresholds

1. **Collect Data**:
   ```bash
   python monitor.py --tuning --tuning-duration 3600
   ```

2. **Analyze Data**:
   ```bash
   python monitor.py --analyze-offline --input-file tuning_data.csv
   ```

3. **Update Thresholds**:
   - Edit `config.yaml` with recommended values
   - Test with `--verbose` logging

4. **Validate Changes**:
   ```bash
   python monitor.py --real --verbose
   ```

## Raspberry Pi Specifics

### Platform Requirements

- **Platform**: Raspberry Pi (tested on RPi 4B)
- **OS**: Latest Debian (Raspberry Pi OS)
- **Python**: 3.8+
- **GPIO Library**: libgpiod via gpio_event_counter (C extension)

### GPIO Library Details

**libgpiod Integration**:
- GIL-free interrupt counting for maximum accuracy
- High-priority threading with CPU affinity
- Optimized for consistent timing on RPi 4B

**Performance Optimizations**:
- CPU affinity to core 3 (avoids system process interference)
- High-priority process scheduling
- Thread priority optimization

### LCD Options

**Original LCD1602.py** (Default):
- Tested and reliable
- Direct I2C communication
- Custom character support

**RPLCD Library** (Alternative):
- Set `USE_RPLCD = True` in display.py
- More features but less tested
- Better error handling

### System Integration

**Systemd Service**:
```bash
# Enable service
sudo systemctl enable rpisolkark-monitor

# Start service
sudo systemctl start rpisolkark-monitor

# Check status
sudo systemctl status rpisolkark-monitor
```

**Auto-Updates**:
```bash
# Setup system-level auto-updates
./setup_zero_code_updates.sh
```

**Scheduled Reboots**:
- Configured in config.yaml
- Prevents memory leaks and system degradation
- Graceful shutdown with cleanup

## File Organization

```
/home/keith/RpiSolArk/
├── monitor.py              # Main application
├── config.yaml             # Configuration
├── hardware.py               # Hardware abstraction
├── display.py                # Display management
├── optocoupler.py            # Frequency measurement
├── gpio_manager.py           # GPIO operations
├── button_handler.py         # Button handling
├── config.py                 # Config loading
├── health.py                 # Health monitoring
├── data_logger.py            # Data logging
├── tuning_collector.py       # Tuning data collection
├── offline_analyzer.py       # Offline analysis
├── restart_manager.py        # Restart management
├── LCD1602.py                # LCD driver (original)
├── lcd_rplcd.py              # LCD driver (RPLCD)
├── dashboard.py              # Web dashboard (separate)
├── solark_cloud.py           # Sol-Ark API (WIP)
├── solark_integration.py     # Sol-Ark integration (WIP)
├── requirements.txt          # Python dependencies
├── setup_*.sh                # Setup scripts
└── tests/                    # Test files
    ├── test_*.py            # Unit tests
    ├── test_backlight_control.py
    ├── test_power_state_backlight.py
    ├── test_simple_backlight.py
    └── *.csv                # Test data files
```

## Common Tasks

### Add New GPIO Device

1. **Update Configuration**:
   ```yaml
   hardware:
     new_device_pin: 23
   ```

2. **Add Setup in gpio_manager.py**:
   ```python
   def setup_new_device(self):
       GPIO.setup(self.new_device_pin, GPIO.OUT)
   ```

3. **Add Control Methods in HardwareManager**:
   ```python
   def control_new_device(self, state):
       self.gpio.set_new_device(state)
   ```

4. **Test with Hardware**:
   ```bash
   python tests/quick_gpio_test.py
   ```

### Adjust Detection Thresholds

1. **Collect Baseline Data**:
   ```bash
   python monitor.py --tuning --tuning-duration 1800
   ```

2. **Analyze Patterns**:
   ```bash
   python monitor.py --analyze-offline
   ```

3. **Update Thresholds**:
   ```yaml
   analysis:
     generator_thresholds:
       allan_variance: 0.0001  # Based on analysis
       std_dev: 0.6           # Based on analysis
       kurtosis: 1.5          # Based on analysis
   ```

4. **Validate Changes**:
   ```bash
   python monitor.py --real --verbose
   ```

### Add New Display Mode

1. **Update DisplayManager**:
   ```python
   def update_display_and_leds(self, freq, ug_indicator, state_machine, zero_voltage_duration, secondary_freq=None):
       # Add new display logic
       if self.new_display_mode:
           line1, line2 = self._format_new_display(freq, ug_indicator)
           self.update_display(line1, line2)
   ```

2. **Add Display Logic**:
   ```python
   def _format_new_display(self, freq, ug_indicator):
       # Custom formatting logic
       return line1, line2
   ```

3. **Test on LCD Hardware**:
   ```bash
   python tests/test_lcd_compatibility.py
   ```

## Troubleshooting

### No Frequency Reading

**Symptoms**: No frequency data, "No pulses detected" messages

**Solutions**:
1. Check optocoupler wiring (H11AA1 pinout)
2. Verify GPIO pin in config.yaml
3. Check libgpiod permissions: `sudo usermod -a -G gpio pi`
4. Test with simulator mode: `python monitor.py --simulator`
5. Check optocoupler with multimeter

### LCD Not Working

**Symptoms**: Blank LCD display, "LCD not available" messages

**Solutions**:
1. Check I2C address: `i2cdetect -y 1`
2. Verify LCD configuration in config.yaml
3. Enable I2C: `sudo raspi-config` → Interfacing Options → I2C
4. Check wiring (SDA/SCL connections)
5. Try RPLCD library: Set `USE_RPLCD = True` in display.py
6. Fall back to simulator display

### High CPU Usage

**Symptoms**: High CPU usage, system slowdown

**Solutions**:
1. Check sample_rate in config.yaml (lower = less CPU)
2. Verify CPU affinity settings
3. Check for tight loops in logs
4. Monitor with: `htop` or `top`
5. Adjust buffer_duration if too short

### Memory Issues

**Symptoms**: Memory warnings, system instability

**Solutions**:
1. Check memory_usage.csv logs
2. Adjust cleanup_interval in config.yaml
3. Review buffer_duration settings
4. Monitor with: `free -h`
5. Enable automatic cleanup

### False Generator Detection

**Symptoms**: Utility power classified as generator

**Solutions**:
1. Increase thresholds in config.yaml:
   ```yaml
   analysis:
     generator_thresholds:
       allan_variance: 0.001  # Increase sensitivity
       std_dev: 0.8          # Increase tolerance
       kurtosis: 2.0         # Increase threshold
   ```
2. Use tuning mode to collect utility data
3. Analyze with offline analyzer
4. Adjust based on recommendations

### Missed Generator Detection

**Symptoms**: Generator power classified as utility

**Solutions**:
1. Decrease thresholds in config.yaml:
   ```yaml
   analysis:
     generator_thresholds:
       allan_variance: 0.0001  # Decrease sensitivity
       std_dev: 0.4           # Decrease tolerance
       kurtosis: 1.0         # Decrease threshold
   ```
2. Use tuning mode to collect generator data
3. Analyze with offline analyzer
4. Adjust based on recommendations

### Sol-Ark Integration Issues

**Symptoms**: Sol-Ark cloud sync failures, parameter changes not applied

**Solutions**:
1. Check credentials in config.yaml
2. Verify network connectivity
3. Test with: `python test_solark_cloud.py`
4. Check browser dependencies: `playwright install chromium`
5. Review solark_cache/ directory for cached pages

### Dashboard Not Working

**Symptoms**: Web dashboard not accessible, Flask errors

**Solutions**:
1. Install Flask: `pip install flask`
2. Check port 5000 availability
3. Run dashboard: `python dashboard.py`
4. Check firewall settings
5. Verify monitor process is running

## Performance Optimization

### Raspberry Pi 4B Optimizations

1. **CPU Affinity**: Process pinned to core 3
2. **Thread Priority**: High priority for optocoupler measurements
3. **Memory Management**: Automatic cleanup every hour
4. **Buffer Sizing**: Optimized for 5-minute analysis windows

### Memory Management

1. **Automatic Cleanup**: Garbage collection every hour
2. **Buffer Limits**: Fixed-size buffers prevent memory growth
3. **Log Rotation**: Automatic log file rotation
4. **Process Monitoring**: Memory usage tracking and alerts

### Network Optimization

1. **Sol-Ark Caching**: Local cache of cloud pages
2. **Session Persistence**: Avoid repeated logins
3. **Timeout Handling**: Graceful network failure handling
4. **Retry Logic**: Exponential backoff for failed requests

## Security Considerations

### System Security

1. **GPIO Permissions**: Proper GPIO group membership
2. **File Permissions**: Secure log file access
3. **Network Security**: HTTPS for Sol-Ark communication
4. **Process Isolation**: Limited system access

### Data Security

1. **Credential Storage**: Secure configuration file handling
2. **Log Sanitization**: No sensitive data in logs
3. **Session Security**: Secure session management
4. **Data Encryption**: Optional data encryption for sensitive logs

## Contributing

### Code Style

- Follow PEP 8 Python style guidelines
- Use type hints where appropriate
- Document all public methods
- Add unit tests for new features

### Testing Requirements

- All new code must have unit tests
- Hardware-specific tests require actual GPIO
- Integration tests for new components
- Performance tests for critical paths

### Documentation

- Update this agents.md for architectural changes
- Document new configuration options
- Add troubleshooting entries for new issues
- Update README.md for user-facing changes

## Support and Resources

### Documentation

- This agents.md file
- README.md for user documentation
- Inline code documentation
- Configuration file comments

### Testing

- Unit tests in tests/ directory
- Hardware tests for GPIO components
- Integration tests for full system
- Performance tests for optimization

### Debugging Tools

- Verbose logging with --verbose flag
- Remote debugging with --debug flag
- Detailed frequency logging
- Memory usage monitoring
- System health monitoring

### Community

- GitHub issues for bug reports
- Pull requests for contributions
- Discussion forums for questions
- Documentation updates welcome

---

This guide should provide new developers with everything they need to understand, modify, and extend the RpiSolArk system. For additional help, refer to the inline code documentation and test files.
