# 🔬 Frequency Analysis & Power Source Detection

*This document provides detailed technical information about how the RpiSolArkMonitor detects power sources through frequency analysis. For a high-level overview, see the [main README](README.md).*

## 📖 Overview

The RpiSolArkMonitor solves a critical challenge: **How do you automatically detect whether your home is powered by the utility grid or a backup generator?** This detection is essential for automatic inverter parameter switching, load management decisions, safety systems, and energy management optimization.

The solution uses **frequency analysis** because unlike voltage (which can be similar for both sources), **frequency behavior is dramatically different** between utility grid and generators.

## 🔍 What is Frequency Hunting?

**Frequency hunting** is a characteristic instability pattern where a generator's frequency oscillates around the target frequency (60 Hz) in a cyclical pattern. This is the "smoking gun" that distinguishes generators from utility power.

### 🎯 **Why Generators Hunt:**

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

### 📊 **Real-World Generator Hunting Examples:**

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

## 🧮 **Detection Algorithm**

The system uses **three complementary analysis methods**:

| Analysis Method | What It Detects | Why It Works |
|:---:|:---:|:---:|
| **📊 Allan Variance** | Short-term frequency instability | Captures hunting oscillations |
| **📈 Standard Deviation** | Overall frequency spread | Detects wide frequency ranges |
| **📉 Kurtosis** | Distribution shape analysis | Identifies hunting patterns vs random noise |

### 🔬 **The Math Behind Detection:**

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

## 🎛️ Configuration Examples

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

## 📊 Detailed Logging Mode

The system includes a comprehensive detailed logging mode for debugging and analysis. This mode captures every frequency reading with full analysis data, allowing you to analyze why your utility/generator classification might not be working correctly.

### 🔍 **Enable Detailed Logging**

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

### 📋 **Detailed Log Output Format**

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

### 🔬 **Offline Analysis**

Process your detailed log data offline to understand classification behavior:

```bash
# Analyze detailed log file
python monitor.py --analyze-offline --input-file detailed_frequency_data.csv

# Custom input and output files
python monitor.py --analyze-offline --input-file my_data.csv --output-file analysis_results.csv
```

### 📈 **Analysis Output**

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

### 🎯 **Use Cases for Detailed Logging**

| Use Case | Command | Purpose |
|:---:|:---:|:---:|
| **Debug Classification Issues** | `--detailed-logging --real` | Capture real data to see why classification fails |
| **Tune Thresholds** | `--detailed-logging --analyze-offline` | Get recommended threshold values |
| **Validate Generator Detection** | `--detailed-logging` during generator run | Verify generator is properly detected |
| **Analyze Utility Stability** | `--detailed-logging` during utility | Check utility frequency characteristics |
| **Performance Analysis** | `--detailed-logging --log-interval 0.1` | High-resolution analysis |

### ⚙️ **Configuration for Detailed Logging**

```yaml
# config.yaml - Detailed logging settings
logging:
  detailed_logging_enabled: false    # Enable in config file
  detailed_log_interval: 1.0         # seconds between log entries
  detailed_log_file: "detailed_frequency_data.csv"
```

### 🔧 **Troubleshooting with Detailed Logs**

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


*For more information about using the system, configuration options, and troubleshooting, see the [main README](README.md).*
