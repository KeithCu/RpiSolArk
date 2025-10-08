# Raspberry Pi Frequency Monitor

A sophisticated frequency monitoring system for Raspberry Pi that detects power source (Utility Grid vs Generator) by analyzing AC line frequency stability.

## Features

- **Real-time frequency monitoring** using optocoupler input
- **Power source classification** (Utility Grid vs Generac Generator)
- **Allan variance analysis** for frequency stability assessment
- **LCD display** with real-time status
- **LED indicators** for power source
- **Health monitoring** with system resource tracking
- **Graceful degradation** when hardware is unavailable
- **Comprehensive logging** with hourly status reports
- **Configurable parameters** via YAML configuration
- **Unit tests** for reliability
- **Sol-Ark cloud integration** with automatic parameter updates
- **Web automation** using Playwright for cloud platform interaction

## Hardware Requirements

- Raspberry Pi (any model)
- H11AA1 optocoupler for AC line isolation
- 16x2 I2C LCD display (address 0x27)
- Green and Red LEDs for status indication
- Resistors and basic wiring components

## Installation

1. **Clone or download** the project files
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers** (for Sol-Ark cloud integration):
   ```bash
   playwright install chromium
   ```

4. **Configure hardware** (optional - see config.yaml):
   - Connect optocoupler to GPIO pin 17
   - Connect green LED to GPIO pin 18
   - Connect red LED to GPIO pin 27
   - Connect I2C LCD to address 0x27

5. **Configure Sol-Ark cloud** (optional):
   - Edit `config.yaml` and add your Sol-Ark cloud credentials
   - Set `solark_cloud.enabled: true` to enable integration

## Usage

### Basic Usage

```bash
# Run in simulator mode (default)
python monitor.py

# Run with real hardware
python monitor.py --real


# Enable verbose logging
python monitor.py --verbose

# Test Sol-Ark cloud integration
python test_solark_cloud.py

# Download Sol-Ark pages for analysis
python test_solark_cloud.py --download-only
```

### Command Line Options

- `--simulator, -s`: Force simulator mode
- `--real, -r`: Force real hardware mode
- `--verbose, -v`: Enable verbose logging

### Configuration

The system uses a hard-coded configuration file `config.yaml`. Edit this file to customize:

- **Hardware settings**: GPIO pins, LCD address, etc.
- **Sampling parameters**: Sample rate, buffer duration
- **Analysis thresholds**: Generator detection criteria
- **Logging options**: Log files, rotation settings
- **Health monitoring**: Watchdog timeout, resource thresholds
- **Sol-Ark cloud settings**: Credentials, sync intervals, parameter mappings

## Output Files

- `hourly_status.csv`: Hourly status reports
- `monitor.log`: Detailed application logs (with rotation)
- `solark_cache/`: Cached Sol-Ark cloud pages for analysis

## Testing

Run the unit tests:

```bash
python test_monitor.py
```

Test Sol-Ark cloud integration:

```bash
python test_solark_cloud.py
```

## Architecture

The system is built with a modular architecture:

- **Config**: Configuration management
- **Logger**: Enhanced logging setup
- **HardwareManager**: Hardware abstraction with graceful degradation
- **FrequencyAnalyzer**: Frequency analysis and classification
- **HealthMonitor**: System health and performance monitoring
- **DataLogger**: Data logging operations
- **FrequencyMonitor**: Main application class
- **SolArkCloud**: Sol-Ark cloud integration with Playwright
- **SolArkIntegration**: Integration layer for automatic parameter updates

## Graceful Degradation

The system automatically detects hardware availability:

- **No RPi.GPIO**: Runs in simulator mode
- **No LCD**: Logs display updates to console
- **Hardware errors**: Continues operation with error logging
- **No Sol-Ark credentials**: Disables cloud integration gracefully
- **Network issues**: Continues local operation without cloud sync

## Monitoring

The system provides comprehensive monitoring:

- **Real-time frequency display** on LCD
- **LED indicators** for power source
- **System health monitoring** (CPU, memory, watchdog)
- **Hourly status logging** to CSV
- **Detailed application logging** with rotation
- **Sol-Ark cloud synchronization** with automatic parameter updates
- **Power source-based parameter changes** (utility vs generator modes)

## Troubleshooting

1. **Check logs**: Review `monitor.log` for errors
2. **Verify hardware**: Ensure proper GPIO connections
3. **Test in simulator**: Use `--simulator` flag to test without hardware
4. **Check permissions**: Ensure GPIO access permissions
5. **Review configuration**: Verify `config.yaml` settings
6. **Test Sol-Ark integration**: Run `python test_solark_cloud.py` to verify cloud connectivity
7. **Check cached pages**: Review `solark_cache/` directory for downloaded pages
8. **Verify credentials**: Ensure Sol-Ark username/password are correctly configured

## License

This project is provided as-is for educational and monitoring purposes.
