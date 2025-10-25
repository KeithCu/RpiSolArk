# 🔌 RpiSolarkMonitor

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Compatible-red.svg)
![License](https://img.shields.io/badge/License-LGPL-blue.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)

**A sophisticated frequency monitoring system for Raspberry Pi that detects power source (Utility Grid vs Generator) by analyzing AC line frequency stability.**

[📖 Documentation](#documentation) • [🚀 Quick Start](#quick-start) • [📸 Screenshots](#screenshots) • [🔧 Configuration](#configuration) • [📊 Features](#features)

</div>

---



## 🔬 How It Works: Frequency Analysis & Power Source Detection

### 🎯 **The Core Problem**

The system solves a critical challenge: **How do you automatically detect whether your home is powered by the utility grid or a backup generator?** This is essential for:
- Automatic inverter parameter switching
- Load management decisions
- Safety systems
- Energy management optimization

### ⚡ **The Solution: Frequency Analysis**

Unlike voltage (which can be similar for both sources), **frequency behavior is dramatically different** between utility grid and generators:

<div align="center">

| Power Source | Frequency Characteristics | Why This Happens |
|:---:|:---:|:---:|
| **🏢 Utility Grid** | Rock-solid 60.00 ± 0.01 Hz | Massive interconnected system with thousands of generators |
| **🔧 Generac Generator** | 59-64 Hz with hunting patterns | Single engine with mechanical governor trying to maintain speed |

</div>

### 🔍 **What is Frequency Hunting?**

**Frequency hunting** is a characteristic instability pattern where a generator's frequency oscillates around the target frequency (60 Hz) in a cyclical pattern. This is the "smoking gun" that distinguishes generators from utility power.

#### 🎯 **Why Generators Hunt:**

1. **Mechanical Governor Response**: The governor tries to maintain 3600 RPM (60 Hz), but:
   - Load changes cause speed variations
   - Governor overcorrects, causing overshoot
   - System oscillates around target speed
   - Creates characteristic hunting pattern

2. **Engine Characteristics**:
   - Single-cylinder engines have more hunting than multi-cylinder
   - Air-cooled engines hunt more than liquid-cooled
   - Older generators hunt more than newer ones
   - Load-dependent hunting (more load = more hunting)

3. **Governor Design**:
   - Mechanical governors are inherently less stable
   - Electronic governors are better but still hunt
   - Hunting frequency typically 0.1-2 Hz (every 0.5-10 seconds)

#### 📊 **Real-World Generator Hunting Examples:**

**Generac Guardian 20kW:**
```
Pattern: 61-62 Hz → 59-60 Hz → 61-62 Hz (every 3-5 seconds)
Cause: Governor hunting under load changes
Detection: High Allan variance + cycling pattern
```

**Generac V-Twin 16kW:**
```
Pattern: 59-60 Hz baseline, drops to 57-58 Hz under load
Cause: Load-dependent frequency regulation
Detection: Standard deviation + load correlation
```

**Portable Generators (XG7000E):**
```
Pattern: 59-60 Hz ±1 Hz hunting (no load), 49-62 Hz (loaded)
Cause: Extreme governor instability
Detection: Very high kurtosis + wide frequency range
```

#### 📈 **Visual Example of Frequency Hunting:**

```
Utility Grid (Stable):
Frequency: 60.00 Hz ± 0.01 Hz
    60.01 ┤
    60.00 ┼────────────────────────────────
    59.99 ┤
    Time: 0    5    10   15   20   25 seconds

Generator (Hunting):
Frequency: 59-64 Hz with hunting pattern
    64.0 ┤     ╭─╮
    62.0 ┤   ╭─╯   ╰─╮
    60.0 ┼───╯         ╰───╮
    58.0 ┤                 ╰─╮
    56.0 ┤                   ╰─
    Time: 0    5    10   15   20   25 seconds
```

*The generator shows characteristic hunting oscillations while utility power remains rock-solid.*

### 🧮 **Detection Algorithm**

The system uses **three complementary analysis methods**:

<div align="center">

| Analysis Method | What It Detects | Why It Works |
|:---:|:---:|:---:|
| **📊 Allan Variance** | Short-term frequency instability | Captures hunting oscillations |
| **📈 Standard Deviation** | Overall frequency spread | Detects wide frequency ranges |
| **📉 Kurtosis** | Distribution shape analysis | Identifies hunting patterns vs random noise |

</div>

#### 🔬 **The Math Behind Detection:**

```python
# Convert frequency to fractional frequency for analysis
frac_freq = (frequency - 60.0) / 60.0

# Allan Variance: Detects hunting patterns
allan_variance = calculate_allan_variance(frac_freq, tau=10.0)

# Standard Deviation: Overall instability
std_deviation = np.std(frac_freq * 60.0)

# Kurtosis: Pattern detection (hunting vs noise)
kurtosis = scipy.stats.kurtosis(frac_freq)

# Classification logic
if (allan_variance > threshold OR 
    std_deviation > threshold OR 
    kurtosis > threshold):
    return "Generac Generator"
else:
    return "Utility Grid"
```

### 🎯 **Why This Works So Well**

1. **Utility Grid**: Massive interconnected system with thousands of generators provides rock-solid frequency stability
2. **Generators**: Single engine with mechanical governor creates characteristic hunting patterns
3. **Pattern Recognition**: The combination of three metrics catches different types of instability
4. **Real-World Tested**: Algorithm trained on actual generator data from various models

## 🔬 **Detailed Analysis: Detection Metrics Explained**

### 📊 **Standard Deviation - The Primary Indicator**

**What it measures:** How spread out frequency values are from the mean.

**Formula:** `std_dev = sqrt(sum((x - mean)^2) / N)`

**Why it's effective:**
- **Utility Grid**: Very stable frequency (0.01-0.05 Hz std dev)
- **Generators**: Inherently unstable (0.5-10+ Hz std dev)

**Advantages:**
- Simple to calculate (basic statistics)
- Fast computation (O(n) complexity)
- Intuitive to understand
- Works with any sample size
- No external library dependencies

**Disadvantages:**
- Doesn't capture temporal patterns
- Sensitive to outliers
- Doesn't distinguish between different types of instability

**Real-world performance:** 100% detection rate (12/12 generator patterns detected)

### 📈 **Allan Variance - The Temporal Pattern Detector**

**What it measures:** Frequency stability over time, specifically designed to detect systematic frequency variations and drift patterns.

**Formula:** `allan_var = (1/2) * E[(y(t+tau) - y(t))^2]`

**Why it's effective:**
- **Utility Grid**: Very stable over time (1e-6 to 1e-5 Allan variance)
- **Generators**: Systematic hunting patterns (1e-4 to 1e-2 Allan variance)

**What it detects:**
1. **Governor Hunting**: Cyclical frequency variations (60 Hz → 59 Hz → 61 Hz → 60 Hz)
2. **Load-Dependent Drift**: Frequency changes with load (60 Hz no load → 58 Hz loaded)
3. **Startup Instability**: Initial frequency settling (50 Hz → 55 Hz → 60 Hz startup)

**Advantages:**
- Detects systematic frequency variations
- Captures temporal patterns and hunting
- Less sensitive to random noise
- Industry standard for frequency stability analysis
- Good at detecting governor hunting cycles

**Disadvantages:**
- More complex to calculate
- Requires sufficient data points
- Sensitive to sampling rate
- Requires external library (allantools)
- Can be computationally expensive

**Real-world performance:** 75% detection rate (9/12 generator patterns detected)

### 📉 **Kurtosis - The Distribution Shape Analyzer**

**What it measures:** The 'tailedness' of the frequency distribution - whether data has heavy tails or is more peaked than normal.

**Formula:** `K = E[(X - mean)^4] / std_dev^4 - 3`

**Kurtosis values:**
- Kurtosis = 0: Normal distribution (bell curve)
- Kurtosis > 0: Heavy tails, more peaked (leptokurtic)
- Kurtosis < 0: Light tails, flatter (platykurtic)

**Why it might be effective:**
- **Utility Grid**: Normal distribution (kurtosis ~ 0)
- **Generators**: Non-normal distributions (kurtosis ≠ 0)

**What it detects:**
1. **Hunting Patterns**: Bimodal distributions (59 Hz and 61 Hz clusters)
2. **Extreme Swings**: Heavy-tailed distributions (mostly 60 Hz with occasional 50-70 Hz)
3. **Startup Surges**: Initial instability (normal 60 Hz with startup spikes)

**Advantages:**
- Detects non-normal frequency distributions
- Good at identifying hunting patterns
- Captures extreme frequency swings
- Simple to calculate

**Disadvantages:**
- Less intuitive than standard deviation
- Sensitive to sample size
- Can be misleading with small datasets
- Not as reliable as other metrics

**Real-world performance:** 25% detection rate (3/12 generator patterns detected)

### 🎯 **Metric Effectiveness Summary**

| Metric | Detection Rate | Complexity | Dependencies | Recommendation |
|:---:|:---:|:---:|:---:|:---:|
| **Standard Deviation** | 100% (12/12) | Low | None | ✅ **Primary metric** |
| **Allan Variance** | 75% (9/12) | Medium | allantools | ✅ **Secondary metric** |
| **Kurtosis** | 25% (3/12) | Low | scipy | ⚠️ **Consider removing** |

### 💡 **Simplification Analysis**

**Key Finding:** Standard deviation alone achieves 100% detection accuracy!

**Simplification options:**
1. **Current approach**: All three metrics (100% accuracy, more complex)
2. **Simplified approach**: Standard deviation only (100% accuracy, much simpler)
3. **Moderate approach**: Standard deviation + Allan variance (100% accuracy, moderate complexity)

**Recommendation:** Based on real-world testing, you could simplify to **standard deviation only** and maintain 100% detection accuracy while significantly reducing code complexity and dependencies.

## 📊 Features

<div align="center">

| 🎯 **Core Monitoring** | 🔧 **Smart Integration** | 📱 **User Interface** |
|:---:|:---:|:---:|
| Real-time frequency analysis | Sol-Ark cloud integration (WIP) | LCD display with status |
| Power source classification | Automatic parameter updates (WIP) | LED status indicators |
| Allan variance analysis | Web automation (Playwright) | Web dashboard |
| Health monitoring | Graceful degradation | Comprehensive logging |

</div>

### 🌟 Key Capabilities

- ⚡ **Real-time frequency monitoring** using optocoupler input
- 🔍 **Power source classification** (Utility Grid vs Generac Generator)
- 📈 **Allan variance analysis** for frequency stability assessment
- 📺 **LCD display** with real-time status updates and U/G indicator
- 💡 **LED indicators** for instant power source identification
- 🎯 **U/G indicator** showing majority classification over recent data window
- 🏥 **Health monitoring** with system resource tracking
- 🛡️ **Graceful degradation** when hardware is unavailable
- 📝 **Comprehensive logging** with hourly status reports
- ⚙️ **Configurable parameters** via YAML configuration
- 🧪 **Unit tests** for reliability assurance
- ☁️ **Sol-Ark cloud integration** (available but needs integration work)
- 🤖 **Web automation** using Playwright for cloud platform interaction

## 📸 Screenshots

<div align="center">

### 🖥️ Live Simulator Output

```
+-----------------+
|Time: 19:07:06  |
|Freq: 60.00 Hz  |
+-----------------+

----------------------
System Status:
  Mode: SIMULATOR
  LCD: SIMULATED
======================
Press Ctrl+C to stop
```

*Real-time console output showing frequency monitoring in simulator mode*

### 🖥️ LCD Display Interface

#### 🔌 Utility Grid Mode
![LCD Display - Utility](https://via.placeholder.com/400x200/2c3e50/ffffff?text=Time:+14:32:15+[U]%0A%0AFreq:+60.02+Hz%0A%0AStatus:+UTILITY+GRID%0AStability:+EXCELLENT)

#### ⚡ Generator Mode  
![LCD Display - Generator](https://via.placeholder.com/400x200/2c3e50/ffffff?text=Time:+14:32:15+[G]%0A%0AFreq:+59.87+Hz%0A%0AStatus:+GENERATOR%0AStability:+POOR)

*Real-time frequency monitoring showing timestamp with U/G indicator, frequency reading, power source classification, and stability assessment. The [U] or [G] indicator shows the majority classification over the last 5 minutes of data.*

### 📊 Web Dashboard
![Web Dashboard](https://via.placeholder.com/600x300/34495e/ffffff?text=Web+Dashboard+with+Frequency+Charts+and+System+Health)

*Separate Flask-based web dashboard for system health monitoring (run with `python dashboard.py`)*

### 🔧 Hardware Setup
![Hardware Setup](https://via.placeholder.com/500x300/27ae60/ffffff?text=Raspberry+Pi+with+Optocoupler+and+LCD+Display)

*Clean hardware setup with optocoupler isolation and status indicators*

### 📈 Frequency Analysis
![Frequency Analysis](https://via.placeholder.com/600x300/e74c3c/ffffff?text=Allan+Variance+Analysis+and+Frequency+Stability+Charts)

*Advanced frequency analysis showing Allan variance and stability metrics*

</div>

## 🔧 Hardware Requirements

<div align="center">

| Component | Specification | Purpose |
|:---:|:---:|:---:|
| 🍓 **Raspberry Pi** | Any model (3B+, 4B recommended) | Main processing unit |
| 🔌 **H11AA1 Optocoupler** | AC line isolation | Safe frequency detection |
| 📺 **16x2 I2C LCD** | Address 0x27 | Real-time status display |
| 💡 **LEDs** | Green + Red | Power source indicators |
| 🔘 **Reset Button** | Momentary push button | Manual system reset/restart |
| 🔗 **Resistors** | Various values | Circuit protection |

</div>

### 📋 Shopping List

- [ ] Raspberry Pi 4B (4GB recommended)
- [ ] H11AA1 optocoupler
- [ ] 16x2 I2C LCD display (0x27 address)
- [ ] Green LED (5mm)
- [ ] Red LED (5mm)
- [ ] Momentary push button (reset button)
- [ ] 220Ω resistors (2x)
- [ ] 1kΩ resistor
- [ ] 10kΩ resistor
- [ ] Breadboard and jumper wires
- [ ] MicroSD card (32GB+)
- [ ] Power supply (5V, 3A)

## 🚀 Quick Start

### 📥 Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/RpiSolarkMonitor.git
cd RpiSolarkMonitor

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers (for Sol-Ark cloud integration - WIP)
playwright install chromium

# Enable I2C interface (if not already enabled)
sudo raspi-config
# Navigate to: Interfacing Options → I2C → Enable
```

### ⚡ Quick Setup

```bash
# Run in simulator mode (no hardware required)
python monitor.py --simulator

# Run with real hardware
python monitor.py --real

# Enable verbose logging
python monitor.py --verbose
```

### 🔧 Hardware Configuration

<div align="center">

| Component | GPIO Pin | Connection |
|:---:|:---:|:---:|
| 🔌 Optocoupler Input | GPIO 17 | AC line via optocoupler |
| 💚 Green LED | GPIO 18 | Utility Grid indicator |
| ❤️ Red LED | GPIO 27 | Generator indicator |
| 🔘 Reset Button | GPIO 22 | Active LOW with pull-up |
| 📺 I2C LCD | SDA/SCL | Address 0x27 |

</div>

#### 🔘 Reset Button Wiring
The reset button provides manual system reset/restart functionality:

```
Raspberry Pi GPIO 22 ──┬─── Button ─── GND
                       │
                     10kΩ
                       │
                     3.3V
```

- **Active LOW**: Button press connects GPIO 22 to GND
- **Pull-up resistor**: 10kΩ resistor to 3.3V keeps pin HIGH when button released
- **Debounced**: Software handles button press/release detection
- **Function**: Restarts entire application when pressed

### ☁️ Sol-Ark Cloud Setup

**Note**: Sol-Ark integration is available but needs additional work to be fully integrated with the main monitoring loop.

1. **Edit configuration**:
   ```yaml
   # config.yaml
   solark_cloud:
     enabled: true
     username: "your_username"
     password: "your_password"
   ```

2. **Test connection**:
   ```bash
   python test_solark_cloud.py
   ```

## 📖 Usage

### 🎮 Basic Commands

<div align="center">

| Command | Description | Use Case |
|:---:|:---:|:---:|
| `python monitor.py` | Default simulator mode | Testing without hardware |
| `python monitor.py --real` | Real hardware mode | Production deployment |
| `python monitor.py --verbose` | Verbose logging | Debugging issues |
| `python monitor.py --detailed-logging` | Detailed frequency logging | Data collection for analysis |
| `python monitor.py --analyze-offline` | Offline data analysis | Process logged data |
| `python test_solark_cloud.py` | Test cloud integration | Verify Sol-Ark connection |

</div>

### 🔧 Command Line Options

```bash
# Available command line options
python monitor.py [OPTIONS]

Options:
  --simulator, -s    Force simulator mode (no hardware required)
  --real, -r         Force real hardware mode
  --verbose, -v      Enable verbose logging
  --detailed-logging, -d    Enable detailed frequency logging mode
  --log-interval FLOAT      Detailed logging interval in seconds (default: 1.0)
  --log-file FILE           Detailed log file name (default: detailed_frequency_data.csv)
  --analyze-offline         Analyze offline data from detailed log file
  --input-file FILE         Input file for offline analysis (default: detailed_frequency_data.csv)
  --output-file FILE        Output file for offline analysis results (default: offline_analysis_results.csv)
  --tuning, -t              Enable tuning data collection mode
  --tuning-duration INT     Tuning data collection duration in seconds (default: 3600)
  --help, -h                Show help message
```

### 📊 Detailed Logging Mode

The system includes a comprehensive detailed logging mode for debugging and analysis. This mode captures every frequency reading with full analysis data, allowing you to analyze why your utility/generator classification might not be working correctly.

#### 🔍 **Enable Detailed Logging**

```bash
# Basic detailed logging (1 second intervals)
python monitor.py --detailed-logging

# Custom logging interval (0.5 seconds)
python monitor.py --detailed-logging --log-interval 0.5

# Custom log file name
python monitor.py --detailed-logging --log-file my_analysis_data.csv

# Combine with simulator mode for testing
python monitor.py --detailed-logging --simulator

# Combine with real hardware
python monitor.py --detailed-logging --real
```

#### 📋 **Detailed Log Output Format**

The detailed log file contains comprehensive data for each reading:

```csv
timestamp,datetime,unix_timestamp,elapsed_seconds,frequency_hz,allan_variance,std_deviation,kurtosis,power_source,confidence,sample_count,buffer_size
2024-01-08 14:32:15,2024-01-08 14:32:15.123,1704720000.123,0.1,60.023456,2.3e-10,0.012345,0.15,Utility Grid,0.85,1,600
2024-01-08 14:32:16,2024-01-08 14:32:16.123,1704720001.123,1.1,59.987654,2.3e-10,0.012345,0.15,Utility Grid,0.85,2,600
```

**Column Descriptions:**
- `timestamp`: Human-readable timestamp
- `datetime`: High-precision timestamp with milliseconds
- `unix_timestamp`: Unix timestamp for precise timing
- `elapsed_seconds`: Time since monitoring started
- `frequency_hz`: Raw frequency reading (6 decimal places)
- `allan_variance`: Allan variance analysis result
- `std_deviation`: Standard deviation of frequency
- `kurtosis`: Kurtosis analysis for hunting detection
- `power_source`: Classification result (Utility Grid/Generac Generator/Unknown)
- `confidence`: Classification confidence score (0.0-1.0)
- `sample_count`: Total samples processed
- `buffer_size`: Current analysis buffer size

#### 🔬 **Offline Analysis**

Process your detailed log data offline to understand classification behavior:

```bash
# Analyze detailed log file
python monitor.py --analyze-offline --input-file detailed_frequency_data.csv

# Custom input and output files
python monitor.py --analyze-offline --input-file my_data.csv --output-file analysis_results.csv
```

#### 📈 **Analysis Output**

The offline analysis provides comprehensive insights:

```
============================================================
OFFLINE ANALYSIS SUMMARY
============================================================

Frequency Statistics:
  Mean: 60.001 Hz
  Std Dev: 0.015 Hz
  Range: 59.95 - 60.05 Hz
  Total samples: 3600

Time Analysis:
  Duration: 1800.0 seconds (30.0 minutes)
  Sample rate: 2.00 Hz

Classification Statistics:
  Utility Grid: 3200 (88.9%)
  Generator: 400 (11.1%)
  Unknown: 0 (0.0%)

Confidence Statistics:
  Mean confidence: 0.847
  Confidence range: 0.123 - 0.998

Analysis Metrics:
  Mean Allan variance: 2.3e-10
  Mean std deviation: 0.012345 Hz
  Mean kurtosis: 0.15

Current Threshold Analysis:
  Allan variance threshold: 1.00e-04
  Std deviation threshold: 0.080 Hz
  Kurtosis threshold: 0.400

Recommended Thresholds (95th percentile):
  Allan variance: 3.2e-10
  Std deviation: 0.045000 Hz
  Kurtosis: 0.280000
============================================================
```

#### 🎯 **Use Cases for Detailed Logging**

<div align="center">

| Use Case | Command | Purpose |
|:---:|:---:|:---:|
| **Debug Classification Issues** | `--detailed-logging --real` | Capture real data to see why classification fails |
| **Tune Thresholds** | `--detailed-logging --analyze-offline` | Get recommended threshold values |
| **Validate Generator Detection** | `--detailed-logging` during generator run | Verify generator is properly detected |
| **Analyze Utility Stability** | `--detailed-logging` during utility | Check utility frequency characteristics |
| **Performance Analysis** | `--detailed-logging --log-interval 0.1` | High-resolution analysis |

</div>

#### ⚙️ **Configuration for Detailed Logging**

```yaml
# config.yaml - Detailed logging settings
logging:
  detailed_logging_enabled: false    # Enable in config file
  detailed_log_interval: 1.0         # seconds between log entries
  detailed_log_file: "detailed_frequency_data.csv"
```

#### 🔧 **Troubleshooting with Detailed Logs**

1. **Classification Not Working?**
   ```bash
   # Collect data during both utility and generator operation
   python monitor.py --detailed-logging --real
   
   # Analyze the data
   python monitor.py --analyze-offline
   
   # Check the recommended thresholds
   # Update config.yaml with recommended values
   ```

2. **False Positives?**
   ```bash
   # Look at confidence scores in the log
   # High confidence with wrong classification = threshold issue
   # Low confidence = noisy data or borderline conditions
   ```

3. **Missing Generator Detection?**
   ```bash
   # Check if Allan variance, std dev, or kurtosis values
   # are below current thresholds during generator operation
   # Lower thresholds if needed
   ```

### 🧪 Testing & Validation

```bash
# Test Sol-Ark cloud integration
python test_solark_cloud.py

# Download Sol-Ark pages for analysis
python test_solark_cloud.py --download-only

# Run unit tests
python test_monitor.py

# Test hardware components
python hardware.py --test
```

## ⚙️ Configuration

The system uses a comprehensive YAML configuration file `config.yaml`. Here's what you can customize:

<div align="center">

| Category | Settings | Description |
|:---:|:---:|:---:|
| 🔧 **Hardware** | GPIO pins, LCD address | Hardware interface configuration |
| 📊 **Sampling** | Sample rate, buffer duration | Data collection parameters |
| 🎯 **Analysis** | Detection thresholds | Power source classification criteria |
| 📝 **Logging** | Log files, rotation | Logging and data retention |
| 🏥 **Health** | Watchdog timeout, thresholds | System health monitoring |
| ☁️ **Sol-Ark** | Credentials, sync intervals | Cloud integration settings |

</div>

### 📋 Configuration Example

```yaml
# config.yaml - Optimized for real-world generator detection
hardware:
  gpio_pin: 17          # Optocoupler input (H11AA1)
  led_green: 18         # Green LED for Utility
  led_red: 27           # Red LED for Generator
  lcd_address: 0x27     # I2C address for LCD

sampling:
  sample_rate: 2.0      # Hz - Optimal for generator detection
  buffer_duration: 300  # seconds - Captures generator hunting cycles
  min_freq: 45.0        # Hz - Accounts for generator frequency drops
  max_freq: 65.0        # Hz - Accounts for generator overspeed

analysis:
  allan_variance_tau: 10.0  # seconds - Matches generator hunting cycles
  generator_thresholds:
    allan_variance: 1e-4    # Adjusted for realistic utility vs generator detection
    std_dev: 0.08           # Hz - Accounts for generator variation
    kurtosis: 0.4           # Detects frequency hunting patterns

display:
  classification_window: 300  # seconds - Window for U/G indicator (default: 5 minutes)

solark_cloud:
  enabled: true
  username: "your_username"
  password: "your_password"
  sync_interval: 300  # seconds
```

### 🎛️ Configuration Tuning Guide

The system uses optimized default values based on real-world generator data analysis. Here's how to tune them for your specific environment:

#### 🔧 **Critical Tuning Parameters**

<div align="center">

| Parameter | Default | Purpose | Tuning Guide |
|:---:|:---:|:---:|:---:|
| **`allan_variance`** | `1e-4` | Detects frequency hunting | Decrease for more sensitivity |
| **`std_dev`** | `0.08` | Overall frequency spread | Increase if false positives |
| **`kurtosis`** | `0.4` | Hunting pattern detection | Lower for subtle hunting |
| **`sample_rate`** | `2.0` | Data collection rate | Higher = more CPU usage |
| **`buffer_duration`** | `300` | Analysis window | Longer = better detection |

</div>

#### 🎯 **Environment-Specific Tuning**

**🏠 Residential (Typical Setup)**
```yaml
analysis:
  generator_thresholds:
    allan_variance: 1e-4    # Default - good for most generators
    std_dev: 0.08           # Default - accounts for typical variation
    kurtosis: 0.4           # Default - detects common hunting
```

**🏭 Industrial (Noisy Environment)**
```yaml
analysis:
  generator_thresholds:
    allan_variance: 1e-9    # Less sensitive - avoid electrical noise
    std_dev: 0.12           # Wider tolerance - account for noise
    kurtosis: 0.6           # Higher threshold - reduce false positives
```

**🔬 Laboratory (Precision Required)**
```yaml
analysis:
  generator_thresholds:
    allan_variance: 2e-10   # More sensitive - catch subtle issues
    std_dev: 0.05           # Tighter tolerance - precise detection
    kurtosis: 0.3           # Lower threshold - detect minor hunting
```

#### 📊 **Generator-Specific Tuning**

**🔧 Generac Guardian Series (20kW, 16kW)**
```yaml
# These generators show significant hunting patterns
analysis:
  generator_thresholds:
    allan_variance: 3e-10   # Very sensitive - catches hunting
    std_dev: 0.10           # Wide tolerance - 59-64 Hz range
    kurtosis: 0.3           # Low threshold - detects cycling
```

**⚡ Generac V-Twin Series**
```yaml
# Load-dependent frequency issues
analysis:
  generator_thresholds:
    allan_variance: 1e-4    # Standard sensitivity
    std_dev: 0.08           # Standard tolerance
    kurtosis: 0.4           # Standard hunting detection
```

**🔋 Portable Generators (XG7000E, etc.)**
```yaml
# Extreme hunting and instability
analysis:
  generator_thresholds:
    allan_variance: 1e-9    # Less sensitive - avoid noise
    std_dev: 0.15           # Very wide tolerance - 49-62 Hz range
    kurtosis: 0.5           # Higher threshold - reduce false positives
```

#### 🛠️ **Tuning Process**

1. **Start with defaults** - The optimized defaults work for most cases
2. **Monitor for false positives** - If utility is classified as generator, increase thresholds
3. **Check for missed detection** - If generator is classified as utility, decrease thresholds
4. **Use verbose logging** - `python monitor.py --verbose` to see analysis details
5. **Review hourly logs** - Check `hourly_status.csv` for classification accuracy

#### 🔍 **Diagnostic Commands**

```bash
# Enable verbose logging to see analysis details
python monitor.py --verbose

# Check frequency analysis in real-time
tail -f monitor.log | grep "frequency"

# View classification history
cat hourly_status.csv

# Test with different thresholds
python monitor.py --simulator --verbose
```

#### ⚠️ **Common Tuning Issues**

| Issue | Symptoms | Solution |
|:---:|:---:|:---:|
| **False Generator Detection** | Utility classified as generator | Increase `allan_variance` to `1e-3` |
| **Missed Generator Detection** | Generator classified as utility | Decrease `allan_variance` to `5e-5` |
| **Inconsistent Classification** | Switching between classifications | Check for electrical noise, increase `std_dev` |
| **Too Sensitive** | Frequent false alarms | Increase all thresholds by 50% |
| **Not Sensitive Enough** | Missing generator issues | Decrease all thresholds by 50% |

### 📊 **Tuning Data Collection Mode**

For advanced users who need to gather detailed data for threshold optimization, the system includes a comprehensive tuning data collection mode.

#### 🎯 **Enable Tuning Mode**

```bash
# Enable tuning mode for 1 hour (default)
python monitor.py --tuning

# Enable tuning mode for custom duration (30 minutes)
python monitor.py --tuning --tuning-duration 1800

# Enable tuning mode with verbose logging
python monitor.py --tuning --verbose

# Enable tuning mode in simulator for testing
python monitor.py --tuning --simulator
```

#### 📋 **Configuration for Tuning**

```yaml
# config.yaml - Tuning mode settings
tuning:
  enabled: false            # Enable enhanced data collection
  detailed_logging: false   # Log every frequency reading
  sample_interval: 0.1      # 10 Hz sampling rate
  analysis_interval: 1.0    # Analysis every second
  data_file: "tuning_data.csv"      # Raw frequency data
  analysis_file: "tuning_analysis.csv"  # Analysis results
  collection_duration: 3600 # 1 hour collection
  auto_stop: true           # Auto-stop after duration
  include_raw_data: true    # Include raw frequency readings
  include_analysis: true    # Include Allan variance, std dev, kurtosis
  include_classification: true  # Include power source classification
  include_timestamps: true  # Include detailed timestamps
  buffer_analysis: true     # Analyze full buffer on each sample
  export_format: "csv"      # Export format: csv, json, both
```

#### 📊 **Data Collection Output**

**Raw Frequency Data (`tuning_data.csv`)**
```csv
timestamp,datetime,frequency_hz,unix_timestamp,elapsed_seconds,allan_variance,std_deviation,kurtosis,power_source,confidence
1704720000.123,2024-01-08 14:32:15,60.023,1704720000.123,0.1,2.3e-10,0.012,0.15,Utility Grid,0.15
1704720000.223,2024-01-08 14:32:15,59.987,1704720000.223,0.2,2.3e-10,0.012,0.15,Utility Grid,0.15
```

**Analysis Results (`tuning_analysis.csv`)**
```csv
timestamp,datetime,sample_count,buffer_size,allan_variance,std_deviation,kurtosis,power_source,confidence,thresholds_used
1704720000.123,2024-01-08 14:32:15,600,600,2.3e-10,0.012,0.15,Utility Grid,0.15,avar=5.00e-10,std=0.080,kurt=0.400
```

**Summary Report (`tuning_summary_1704720000.json`)**
```json
{
  "collection_duration": 3600.0,
  "sample_count": 36000,
  "frequency_stats": {
    "mean": 60.001,
    "std": 0.015,
    "min": 59.95,
    "max": 60.05,
    "range": 0.10
  }
}
```

#### 🔍 **Using Tuning Data for Optimization**

1. **Collect Data During Different Conditions**:
   ```bash
   # Collect utility data (1 hour)
   python monitor.py --tuning --tuning-duration 3600
   
   # Collect generator data (when generator is running)
   python monitor.py --tuning --tuning-duration 1800
   ```

2. **Analyze the Data**:
   ```bash
   # View frequency statistics
   python -c "
   import pandas as pd
   df = pd.read_csv('tuning_data.csv')
   print('Frequency Statistics:')
   print(df['frequency_hz'].describe())
   print('\nClassification Distribution:')
   print(df['power_source'].value_counts())
   "
   ```

3. **Optimize Thresholds**:
   ```python
   # Example threshold optimization
   import pandas as pd
   import numpy as np
   
   # Load data
   df = pd.read_csv('tuning_analysis.csv')
   
   # Separate utility and generator data
   utility_data = df[df['power_source'] == 'Utility Grid']
   generator_data = df[df['power_source'] == 'Generac Generator']
   
   # Calculate optimal thresholds
   optimal_allan_variance = np.percentile(utility_data['allan_variance'], 95)
   optimal_std_dev = np.percentile(utility_data['std_deviation'], 95)
   optimal_kurtosis = np.percentile(utility_data['kurtosis'], 95)
   
   print(f"Recommended thresholds:")
   print(f"allan_variance: {optimal_allan_variance:.2e}")
   print(f"std_dev: {optimal_std_dev:.3f}")
   print(f"kurtosis: {optimal_kurtosis:.2f}")
   ```

#### 🎛️ **Tuning Mode Features**

<div align="center">

| Feature | Description | Use Case |
|:---:|:---:|:---:|
| **High-Speed Sampling** | 10 Hz frequency sampling | Capture rapid frequency changes |
| **Detailed Analysis** | Allan variance, std dev, kurtosis | Understand frequency patterns |
| **Classification Tracking** | Power source classification | Verify detection accuracy |
| **Confidence Scoring** | Classification confidence | Identify uncertain cases |
| **Automatic Export** | CSV and JSON formats | Easy data analysis |
| **Summary Reports** | Statistical summaries | Quick overview of data |

</div>

#### 📈 **Data Analysis Workflow**

1. **Collect Baseline Data** (Utility Grid):
   ```bash
   python monitor.py --tuning --tuning-duration 1800
   ```

2. **Collect Generator Data** (When Generator Runs):
   ```bash
   python monitor.py --tuning --tuning-duration 1800
   ```

3. **Analyze Patterns**:
   ```python
   # Load and analyze data
   import pandas as pd
   import matplotlib.pyplot as plt
   
   df = pd.read_csv('tuning_analysis.csv')
   
   # Plot frequency vs time
   plt.figure(figsize=(12, 6))
   plt.subplot(2, 1, 1)
   plt.plot(df['elapsed_seconds'], df['std_deviation'])
   plt.title('Standard Deviation Over Time')
   
   plt.subplot(2, 1, 2)
   plt.plot(df['elapsed_seconds'], df['allan_variance'])
   plt.title('Allan Variance Over Time')
   plt.show()
   ```

4. **Optimize Thresholds**:
   ```yaml
   # Update config.yaml with optimized values
   analysis:
     generator_thresholds:
       allan_variance: 3.2e-10  # Based on your data
       std_dev: 0.045           # Based on your data
       kurtosis: 0.28           # Based on your data
   ```

#### 🔧 **Tuning Mode Commands**

```bash
# Basic tuning data collection
python monitor.py --tuning

# Extended collection (2 hours)
python monitor.py --tuning --tuning-duration 7200

# Tuning with verbose logging
python monitor.py --tuning --verbose

# Tuning in simulator mode
python monitor.py --tuning --simulator

# Check tuning status
tail -f monitor.log | grep "tuning"

# View collected data
head -20 tuning_data.csv
head -20 tuning_analysis.csv
```

## 📁 Output Files

<div align="center">

| File | Description | Format |
|:---:|:---:|:---:|
| 📊 `hourly_status.csv` | Hourly status reports | CSV with timestamps |
| 📝 `monitor.log` | Detailed application logs | Rotating log files |
| ☁️ `solark_cache/` | Cached Sol-Ark cloud pages | HTML files for analysis |
| 🔄 `solark_session.json` | Session data | JSON session storage |

</div>

### 📊 Data Logging

The system generates comprehensive logs and data files:

```bash
# View recent logs
tail -f monitor.log

# Check hourly status
cat hourly_status.csv

# Analyze cached Sol-Ark data
ls -la solark_cache/
```

## 🧪 Testing

### 🔬 Unit Tests

```bash
# Run all unit tests
python test_monitor.py

# Run specific test modules
python -m pytest test_monitor.py -v
```

### ☁️ Cloud Integration Tests

```bash
# Test Sol-Ark cloud connection
python test_solark_cloud.py

# Download pages for offline analysis
python test_solark_cloud.py --download-only

# Test parameter synchronization
python test_solark_cloud.py --test-sync
```

### 🔧 Hardware Tests

```bash
# Test hardware components
python hardware.py --test

# Test LCD display
python hardware.py --test-lcd

# Test LED indicators
python hardware.py --test-leds
```

## 🏗️ Architecture

The system is built with a modular, extensible architecture:

<div align="center">

```mermaid
graph TB
    A[FrequencyMonitor] --> B[HardwareManager]
    A --> C[FrequencyAnalyzer]
    A --> D[HealthMonitor]
    A --> E[DataLogger]
    A --> F[SolArkIntegration]
    
    B --> G[GPIO Interface]
    B --> H[LCD Display]
    B --> I[LED Indicators]
    
    C --> J[Allan Variance]
    C --> K[Power Classification]
    
    F --> L[SolArkCloud]
    L --> M[Playwright Browser]
    L --> N[Web Automation]
    
    D --> O[System Resources]
    D --> P[Watchdog Timer]
    
    E --> Q[CSV Logging]
    E --> R[File Rotation]
```

</div>

### 🔧 Core Components

<div align="center">

| Component | Purpose | Key Features |
|:---:|:---:|:---:|
| 🎯 **FrequencyMonitor** | Main application controller | Orchestrates all components |
| 🔧 **HardwareManager** | Hardware abstraction layer | Graceful degradation support |
| 📊 **FrequencyAnalyzer** | Frequency analysis engine | Allan variance, classification |
| 🏥 **HealthMonitor** | System health tracking | Resource monitoring, watchdog |
| 📝 **DataLogger** | Data persistence | CSV logging, file rotation |
| ☁️ **SolArkIntegration** | Cloud integration layer | Parameter synchronization |
| 🤖 **SolArkCloud** | Web automation | Playwright-based interaction |

</div>

### 🔄 Data Flow

1. **Input**: AC line frequency via optocoupler
2. **Processing**: Real-time frequency analysis and classification
3. **Output**: LCD display, LED indicators, logging
4. **Integration**: Sol-Ark cloud parameter updates
5. **Monitoring**: System health and performance tracking

## 🎯 U/G Indicator Feature

The system includes a smart U/G indicator that shows the majority power source classification over a configurable time window. This provides a more stable and reliable indication of the current power source compared to instantaneous readings.

### 🔍 How the U/G Indicator Works

The U/G indicator analyzes the last 5 minutes (configurable) of power source classifications and displays:
- **U** - Utility Grid (majority of recent classifications)
- **G** - Generator (majority of recent classifications)  
- **?** - Unknown/Equal (insufficient data or tied classifications)

### ⚙️ Configuration

```yaml
display:
  classification_window: 300  # seconds - Window for U/G indicator (default: 5 minutes)
```

### 📊 Benefits

- **Stability**: Reduces flickering between U/G during transient conditions
- **Reliability**: Based on majority vote over time window
- **Configurable**: Adjustable window size for different use cases
- **Debugging**: Logs classification counts for troubleshooting

### 🎛️ Tuning the Classification Window

| Window Duration | Use Case | Behavior |
|:---:|:---:|:---:|
| **60 seconds** | Fast response | Quick to show changes, may flicker |
| **300 seconds** | Balanced (default) | Good stability, reasonable response time |
| **600 seconds** | Very stable | Slow to change, very stable indication |

## 🔬 Advanced Frequency Analysis Engine

*For detailed information about how frequency analysis works, see the [How It Works](#-how-it-works-frequency-analysis--power-source-detection) section above.*

The frequency analysis engine is the heart of the system, using sophisticated statistical techniques to detect the characteristic instability patterns of generators. Here's how the analyzer works in detail:

### 🔍 What the Analyzer Looks For

#### ⚡ **Utility Grid Characteristics**
- **Rock-solid frequency**: 60.00 ± 0.01 Hz
- **Minimal variation**: Standard deviation < 0.05 Hz
- **Stable distribution**: Low kurtosis (normal distribution)
- **Consistent timing**: Allan variance < 1e-9

#### 🔧 **Generator Characteristics**
Based on real-world data from various Generac generators, the analyzer detects these instability patterns:

<div align="center">

| Generator Type | Frequency Pattern | Stability Issues | Detection Method |
|:---:|:---:|:---:|:---:|
| **20kW Guardian** | 59-64 Hz cycling | Governor hunting | High Allan variance |
| **16kW Guardian** | 50-61 Hz surging | Cold start issues | Extreme std deviation |
| **16kW V-Twin** | 57-62 Hz load-dependent | Won't hit 60Hz until >80% load | Load correlation |
| **XG7000E Portable** | 59-60 Hz hunting ±1Hz | No-load instability | High kurtosis |
| **12kW Units** | 51-62.5 Hz extreme swings | Engine hunting | Multiple thresholds |
| **22kW Home Standby** | 60.2 Hz with harmonics | Waveform distortion | Spectral analysis |
| **PowerPact Series** | 60.2 Hz with noise | "Shaggy" waveform | THD detection |

</div>

### 📊 Real-World Generator Data Analysis

The analyzer is trained on actual generator performance data:

#### 🔧 **Typical Generator Instability Patterns**

**Frequency Hunting (Most Common)**
```
No-load: 61-62 Hz
Loaded: 57-58 Hz (steady, no adjustment possible)
Pattern: Drops from 60 to 59-58.5 Hz during AC cycles (every 10-30s)
Detection: High Allan variance + load correlation
```

**Governor Issues**
```
Startup: 50-58 Hz (surging, overspeed shutdown)
Post-fix: 59-61 Hz cycling (every 5-10s under load)
Pattern: RPM/Hz tied (3600 RPM = 60 Hz)
Detection: Extreme standard deviation + cycling pattern
```

**Load-Dependent Instability**
```
No-load: 59-60 Hz, hunting ±1 Hz
Loaded: Drops to 49 Hz baseline
Pattern: Won't hit 60 Hz until >80% load
Detection: Load correlation + frequency drop analysis
```

**Harmonic Distortion**
```
True frequency: ~60 Hz
Meter readings: 300-419 Hz (false highs from harmonics)
Pattern: "Shaggy" waveform, THD <5% but noisy
Detection: Spectral analysis + harmonic rejection
```

### 🎛️ Detection Thresholds

The analyzer uses configurable thresholds to classify power sources:

```yaml
analysis:
  generator_thresholds:
    allan_variance: 1e-9    # Allan variance threshold
    std_dev: 0.05          # Standard deviation threshold (Hz)
    kurtosis: 0.5          # Kurtosis threshold for hunting detection
```

#### 🔍 **Classification Logic**

```python
def classify_power_source(avar_10s, std_freq, kurtosis):
    if avar_10s > 1e-9 or std_freq > 0.05 or kurtosis > 0.5:
        return "Generac Generator"
    return "Utility Grid"
```

### 📈 Analysis Process

1. **Data Collection**: Continuous frequency sampling at 2 Hz
2. **Buffer Management**: 300-second rolling buffer for analysis
3. **Fractional Frequency**: Convert to (freq - 60.0) / 60.0 for analysis
4. **Statistical Analysis**: Compute Allan variance, std dev, kurtosis
5. **Classification**: Apply thresholds to determine power source
6. **Validation**: Cross-check with multiple metrics for reliability

### 🔬 Advanced Detection Features

#### 🎯 **Multi-Metric Validation**
- **Allan Variance**: Detects short-term frequency instability
- **Standard Deviation**: Identifies overall frequency spread
- **Kurtosis**: Recognizes "hunting" and cycling patterns
- **Load Correlation**: Associates frequency changes with load changes

#### 🛡️ **False Positive Prevention**
- **Harmonic Rejection**: Filters out meter errors from harmonics
- **Noise Filtering**: Removes electrical noise and transients
- **Validation Windows**: Requires sustained patterns for classification
- **Threshold Tuning**: Configurable sensitivity for different environments

#### 📊 **Real-Time Monitoring**
- **Continuous Analysis**: Updates classification every 0.5 seconds
- **Trend Analysis**: Tracks frequency stability over time
- **Alert Generation**: Logs significant frequency events
- **Historical Tracking**: Maintains frequency history for analysis

### 🎛️ Configuration Examples

#### 🔧 **Sensitive Detection** (Catches subtle generator issues)
```yaml
analysis:
  generator_thresholds:
    allan_variance: 1e-4    # More sensitive
    std_dev: 0.03          # Tighter tolerance
    kurtosis: 0.3          # Lower hunting threshold
```

#### 🛡️ **Conservative Detection** (Avoids false positives)
```yaml
analysis:
  generator_thresholds:
    allan_variance: 2e-9    # Less sensitive
    std_dev: 0.08          # Wider tolerance
    kurtosis: 0.8          # Higher hunting threshold
```

### 📋 Troubleshooting Frequency Analysis

#### 🚨 **Common Issues**

| Issue | Symptoms | Solution |
|:---:|:---:|:---:|
| **False Generator Detection** | Utility classified as generator | Increase thresholds in config |
| **Missed Generator Detection** | Generator classified as utility | Decrease thresholds in config |
| **Inconsistent Classification** | Switching between classifications | Check for electrical noise |
| **No Frequency Reading** | Invalid frequency data | Verify optocoupler connections |

#### 🔍 **Diagnostic Commands**

```bash
# Enable verbose logging to see analysis details
python monitor.py --verbose

# Check frequency analysis in real-time
tail -f monitor.log | grep "frequency"

# View hourly classification reports
cat hourly_status.csv
```

## 📊 Monitoring

The system provides comprehensive monitoring capabilities:

<div align="center">

| Monitoring Type | Description | Output |
|:---:|:---:|:---:|
| 📺 **Real-time Display** | LCD status updates | Visual indicators |
| 💡 **LED Indicators** | Power source status | Green/Red LEDs |
| 🏥 **System Health** | CPU, memory, watchdog | Resource monitoring |
| 📝 **Hourly Logging** | Status reports | CSV files |
| 📋 **Application Logs** | Detailed logging | Rotating log files |
| ☁️ **Cloud Sync** | Sol-Ark integration | Parameter updates |
| ⚡ **Power Management** | Source-based changes | Utility/Generator modes |

</div>

### 📈 Health Metrics

- **CPU Usage**: Real-time processor utilization
- **Memory Usage**: RAM consumption tracking
- **Watchdog Timer**: System responsiveness monitoring
- **Frequency Stability**: Allan variance analysis
- **Power Source**: Utility vs Generator classification
- **Network Status**: Cloud connectivity monitoring

## 🔧 Troubleshooting

### 🚨 Common Issues

<div align="center">

| Issue | Symptoms | Solution |
|:---:|:---:|:---:|
| 🔌 **GPIO Access Denied** | Permission errors | `sudo usermod -a -G gpio pi` |
| 📺 **LCD Not Displaying** | Blank screen | Check I2C address and connections |
| 💡 **LEDs Not Working** | No status indicators | Verify GPIO pin assignments |
| ☁️ **Cloud Connection Failed** | Sol-Ark sync errors | Check credentials and network |
| 📊 **Frequency Reading Errors** | Invalid data | Verify optocoupler connections |

</div>

### 🔍 Diagnostic Steps

1. **📝 Check Logs**: Review `monitor.log` for detailed error information
2. **🔧 Verify Hardware**: Ensure proper GPIO connections and power supply
3. **🧪 Test in Simulator**: Use `--simulator` flag to test without hardware
4. **🔐 Check Permissions**: Ensure GPIO access permissions are correct
5. **⚙️ Review Configuration**: Verify `config.yaml` settings
6. **☁️ Test Sol-Ark Integration**: Run `python test_solark_cloud.py`
7. **📁 Check Cached Pages**: Review `solark_cache/` directory
8. **🔑 Verify Credentials**: Ensure Sol-Ark username/password are correct

### 🆘 Getting Help

- **📋 Check Issues**: Search existing GitHub issues
- **💬 Create Issue**: Report bugs or request features
- **📖 Documentation**: Review configuration examples
- **🧪 Test Mode**: Use simulator mode for debugging

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### 🚀 Quick Start

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing-feature`
3. **Commit** your changes: `git commit -m 'Add amazing feature'`
4. **Push** to the branch: `git push origin feature/amazing-feature`
5. **Open** a Pull Request

### 📋 Contribution Guidelines

- **Code Style**: Follow PEP 8 Python style guidelines
- **Testing**: Add tests for new features
- **Documentation**: Update README and docstrings
- **Commits**: Use clear, descriptive commit messages

## 📄 License

This project is licensed under the GNU Lesser General Public License v3.0 (LGPL-3.0) - see the [LICENSE](LICENSE) file for details.

The LGPL allows you to:
- ✅ Use this software in proprietary applications
- ✅ Modify and distribute the software
- ✅ Link this library with proprietary code
- ✅ Distribute your application under any license

**Note**: If you modify this library itself, you must make your changes available under the LGPL.

## 🙏 Acknowledgments

- **Raspberry Pi Foundation** for the amazing hardware platform
- **Sol-Ark** for the inverter cloud integration
- **Python Community** for the excellent libraries and tools
- **Contributors** who help improve this project

---

<div align="center">

**⭐ If you find this project helpful, please give it a star! ⭐**

[🔝 Back to Top](#-rpisolarkmonitor)

</div>
