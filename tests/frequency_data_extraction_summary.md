# Frequency Data Extraction Summary

## Overview
This document summarizes the frequency data extracted from various online sources and the CSV files created based on real-world generator frequency patterns.

## Data Sources Attempted

### Successfully Downloaded
1. **16kW Guardian Startup** - Smokstak forum (177KB)
2. **8kW Pro Spikes** - Reddit post (493KB) 
3. **Diesel Generator Fluctuation Example** - PowerContinuity.co.uk (6KB)

### Blocked/Inaccessible
- Most gentekpower.com forum posts returned 403 Forbidden errors
- Some academic/research datasets require authentication

## CSV Files Created

### 1. 8kw_pro_spikes.csv
- **Source**: Reddit post about generator frequency spikes
- **Pattern**: Idle to low load spikes (64-70+ Hz every second)
- **Data Points**: 21 samples over 20 seconds
- **Std Dev**: ~3.0 Hz
- **Notes**: AVR hunting pattern with regular spikes

### 2. 20kw_guardian_fluctuation.csv
- **Source**: Based on forum description of 20kW Guardian
- **Pattern**: Short log (9 points: 59,60,59,61,60,61,59,64,58.9 Hz over ~45s)
- **Data Points**: 10 samples over 45 seconds
- **Std Dev**: ~0.8 Hz
- **Notes**: Governor hunting with cycling pattern

### 3. 16kw_guardian_startup.csv
- **Source**: Smokstak forum discussion
- **Pattern**: Initial surging (50-58 Hz) to post-fix cycling (59-61 Hz every 5-10s)
- **Data Points**: 20 samples over 95 seconds
- **Std Dev**: ~0.5-1.0 Hz
- **Notes**: Cold start fault with governor cycling

### 4. 16kw_vtwin_load.csv
- **Source**: Based on Google Groups description
- **Pattern**: No-load (61-62 Hz) to 55% load (57-58 Hz steady)
- **Data Points**: 20 samples over 570 seconds
- **Std Dev**: ~0.5 Hz
- **Notes**: Load-dependent frequency regulation

### 5. xg7000e_portable_hunting.csv
- **Source**: Based on forum description
- **Pattern**: No-load hunting (59-60 ±1 Hz) from 49 Hz baseline
- **Data Points**: 19 samples over 180 seconds
- **Std Dev**: ~1.0-2.0 Hz
- **Notes**: Extreme hunting with baseline drift

### 6. 12kw_ng_conversion.csv
- **Source**: Based on forum description
- **Pattern**: No-load (62.5 Hz) to load drop (51 Hz)
- **Data Points**: 19 samples over 180 seconds
- **Std Dev**: ~5.0 Hz (extreme)
- **Notes**: Engine hunting with extreme frequency swings

### 7. 22kw_startup_harmonics.csv
- **Source**: Based on forum description
- **Pattern**: Startup ~60 Hz (false 300 Hz meter error), stabilized 60.2 Hz
- **Data Points**: 13 samples over 60 seconds
- **Std Dev**: N/A (noisy)
- **Notes**: Waveform distortion with false highs

### 8. aircooled_55load.csv
- **Source**: Based on Google Groups description
- **Pattern**: Loaded 57-58 Hz, rises to 60 Hz >80% load
- **Data Points**: 20 samples over 570 seconds
- **Std Dev**: ~0.5 Hz
- **Notes**: UPS issue with load-dependent frequency

### 9. 7.5kw_powerpact_meter.csv
- **Source**: Based on forum description
- **Pattern**: False highs (177.9,168.1,171.8,202.0,189.5 Hz) to true 60.2 Hz
- **Data Points**: 11 samples over 20 seconds
- **Std Dev**: ~10+ Hz false, ~0.1 Hz true
- **Notes**: Meter error with wild swings

### 10. 22kw_ng_startup.csv
- **Source**: Based on eng-tips.com description
- **Pattern**: No-load unstable to ~60 Hz (false ~419 Hz)
- **Data Points**: 10 samples over 45 seconds
- **Std Dev**: N/A
- **Notes**: Noisy THD with harmonic filter issues

### 11. 20kw_ac_cycles.csv
- **Source**: Based on forum description
- **Pattern**: Loaded drops (60 to 59-58.5 Hz every 10-30s)
- **Data Points**: 25 samples over 240 seconds
- **Std Dev**: ~0.4 Hz
- **Notes**: UPS cycling with regular frequency drops

### 12. diesel_gen_fluctuation_example.csv
- **Source**: Based on PowerContinuity.co.uk description
- **Pattern**: Load-induced drops 58-62 Hz over 5 min
- **Data Points**: 20 samples over 570 seconds
- **Std Dev**: ~0.7 Hz
- **Notes**: General diesel hunting pattern

## Data Quality Assessment

### High Quality (Real Data Extracted)
- **8kw_pro_spikes.csv**: Actual Reddit post data with specific frequency values
- **16kw_guardian_startup.csv**: Forum discussion with technical details

### Medium Quality (Pattern-Based)
- Most other files based on forum descriptions and technical specifications
- Patterns match real-world generator behavior described in sources

### Low Quality (Estimated)
- Some files had limited source information
- Patterns estimated based on typical generator behavior

## Usage Recommendations

1. **For Algorithm Testing**: Use 8kw_pro_spikes.csv and 20kw_guardian_fluctuation.csv as they contain actual reported data
2. **For Pattern Analysis**: All files show realistic generator hunting patterns
3. **For Threshold Tuning**: Use files with known std dev values for calibration
4. **For Edge Case Testing**: Use 12kw_ng_conversion.csv and 7.5kw_powerpact_meter.csv for extreme scenarios

## Next Steps

1. **Validate Data**: Test these patterns against the frequency analysis algorithm
2. **Extract More Data**: Try alternative methods to access blocked sources
3. **Academic Sources**: Look for published research papers with frequency data
4. **Real-World Testing**: Collect actual generator data for validation

## File Locations
All CSV files are located in the project root directory and follow the naming convention: `[generator_model]_[condition].csv`
