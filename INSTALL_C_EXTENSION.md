# GIL-Safe C Extension Installation Guide

This guide helps you build and install the GIL-safe pulse counter C extension for optimal dual optocoupler performance.

## Quick Start

```bash
# Install Python dependencies
pip install -r requirements.txt

# Build the C extension
python simple_build.py

# Test the installation
python test_callback_gil_solutions.py
```

## Detailed Installation

### 1. Install System Dependencies

```bash
# Install compiler and Python development headers
sudo apt-get update
sudo apt-get install gcc python3-dev

# Verify installation
gcc --version
python3-config --includes
```

### 2. Install Python Dependencies

```bash
# Install required Python packages
pip install -r requirements.txt

# Verify setuptools is available
python -c "import setuptools; print('setuptools available')"
```

### 3. Build the C Extension

Choose one of these methods:

#### Method A: Simple Build Script (Recommended)
```bash
python simple_build.py
```

#### Method B: Setuptools Build
```bash
python setup.py build_ext --inplace
```

#### Method C: Direct GCC Build
```bash
gcc -shared -fPIC -o pulse_counter.so pulse_counter.c -I$(python3-config --includes) -lpthread
```

### 4. Verify Installation

```bash
# Test the C extension
python -c "import pulse_counter; print('C extension loaded successfully')"

# Run comprehensive tests
python test_callback_gil_solutions.py
```

## Troubleshooting

### Common Issues

#### 1. "gcc not found"
```bash
sudo apt-get install gcc
```

#### 2. "Python.h not found"
```bash
sudo apt-get install python3-dev
```

#### 3. "setuptools not available"
```bash
pip install setuptools wheel
```

#### 4. "Permission denied"
```bash
# Make sure you have write permissions in the directory
chmod 755 .
```

#### 5. "ImportError: No module named pulse_counter"
```bash
# Check if the .so file was created
ls -la pulse_counter.so

# If not, rebuild with verbose output
python simple_build.py
```

### Performance Verification

After installation, you should see:

```
✅ C extension loaded successfully
✅ GIL-safe counter with C extension available
✅ Dual optocoupler measurement is truly simultaneous
✅ Maximum accuracy for critical applications
```

## Benefits of C Extension

- **GIL-Free Interrupts**: GPIO callbacks run without Python GIL
- **Maximum Accuracy**: No Python overhead in interrupt context
- **Optimal Performance**: Minimal CPU usage on RPi4
- **True Simultaneity**: Both optocouplers count at exactly the same time

## Fallback Options

If the C extension fails to build, the system will automatically fall back to:

1. **Python Counter**: Minor GIL issues but functional
2. **Polling Method**: No GIL issues but CPU intensive

## System Requirements

- **Python**: 3.7 or higher
- **GCC**: 4.8 or higher
- **OS**: Linux (tested on Raspberry Pi OS)
- **Hardware**: Raspberry Pi 4 recommended

## Troubleshooting Commands

```bash
# Check Python version
python3 --version

# Check GCC version
gcc --version

# Check Python headers
python3-config --includes

# Check setuptools
python -c "import setuptools; print(setuptools.__version__)"

# Test import
python -c "import pulse_counter; print('Success')"
```

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Run `python test_callback_gil_solutions.py` for detailed diagnostics
3. Ensure all system dependencies are installed
4. Verify file permissions in your project directory
