#!/usr/bin/env python3
"""
Analyze how close current thresholds are to their limits based on test data.
"""

import os
import sys
import csv
import numpy as np
from typing import List, Dict, Tuple

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def load_frequency_data(filepath: str) -> List[float]:
    """Load frequency data from CSV file."""
    frequencies = []
    
    try:
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'frequency_hz' in row:
                    freq = float(row['frequency_hz'])
                    frequencies.append(freq)
                elif 'frequency' in row:
                    freq = float(row['frequency'])
                    frequencies.append(freq)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return []
    
    return frequencies

def analyze_threshold_margins():
    """Analyze how close current thresholds are to their limits."""
    
    # Load actual thresholds from config.yaml
    config = Config()
    current_thresholds = {
        'allan_variance': config.get('analysis.generator_thresholds.allan_variance'),
        'std_dev': config.get('analysis.generator_thresholds.std_dev'),
        'kurtosis': config.get('analysis.generator_thresholds.kurtosis')
    }
    
    print("THRESHOLD MARGIN ANALYSIS")
    print("=" * 60)
    print(f"Current Thresholds:")
    print(f"  Allan Variance: {current_thresholds['allan_variance']:.2e}")
    print(f"  Std Deviation: {current_thresholds['std_dev']:.3f} Hz")
    print(f"  Kurtosis: {current_thresholds['kurtosis']:.3f}")
    print()
    
    test_dir = os.path.dirname(__file__)
    csv_files = [f for f in os.listdir(test_dir) if f.endswith('.csv') and not f.startswith('test_')]
    
    # Collect all metrics
    all_metrics = []
    
    for filename in csv_files:
        filepath = os.path.join(test_dir, filename)
        frequencies = load_frequency_data(filepath)
        
        if not frequencies:
            continue
            
        freq_array = np.array(frequencies)
        
        # Calculate metrics
        std_freq = np.std(freq_array)
        
        # Calculate fractional frequency for Allan variance
        frac_freq = (freq_array - 60.0) / 60.0
        
        # Allan variance calculation
        try:
            if len(frac_freq) > 1:
                diff = np.diff(frac_freq)
                allan_var = np.var(diff) / 2.0
            else:
                allan_var = 0.0
        except:
            allan_var = 0.0
        
        # Kurtosis
        try:
            from scipy import stats
            kurtosis = stats.kurtosis(frac_freq)
        except:
            kurtosis = 0.0
        
        all_metrics.append({
            'filename': filename,
            'allan_variance': allan_var,
            'std_deviation': std_freq,
            'kurtosis': kurtosis
        })
    
    # Analyze margins
    print("THRESHOLD MARGIN ANALYSIS")
    print("=" * 60)
    
    # Allan Variance Analysis
    allan_values = [m['allan_variance'] for m in all_metrics]
    allan_above_threshold = [v for v in allan_values if v > current_thresholds['allan_variance']]
    allan_below_threshold = [v for v in allan_values if v <= current_thresholds['allan_variance']]
    
    print(f"Allan Variance Analysis:")
    print(f"  Values above threshold: {len(allan_above_threshold)}/{len(allan_values)} ({len(allan_above_threshold)/len(allan_values):.1%})")
    if allan_above_threshold:
        min_above = min(allan_above_threshold)
        max_above = max(allan_above_threshold)
        print(f"  Range above threshold: {min_above:.2e} - {max_above:.2e}")
        print(f"  Closest to threshold: {min_above:.2e} (margin: {min_above/current_thresholds['allan_variance']:.1f}x)")
    
    if allan_below_threshold:
        max_below = max(allan_below_threshold)
        print(f"  Highest below threshold: {max_below:.2e} (margin: {current_thresholds['allan_variance']/max_below:.1f}x)")
    
    print()
    
    # Standard Deviation Analysis
    std_values = [m['std_deviation'] for m in all_metrics]
    std_above_threshold = [v for v in std_values if v > current_thresholds['std_dev']]
    std_below_threshold = [v for v in std_values if v <= current_thresholds['std_dev']]
    
    print(f"Standard Deviation Analysis:")
    print(f"  Values above threshold: {len(std_above_threshold)}/{len(std_values)} ({len(std_above_threshold)/len(std_values):.1%})")
    if std_above_threshold:
        min_above = min(std_above_threshold)
        max_above = max(std_above_threshold)
        print(f"  Range above threshold: {min_above:.3f} - {max_above:.3f} Hz")
        print(f"  Closest to threshold: {min_above:.3f} Hz (margin: {min_above/current_thresholds['std_dev']:.1f}x)")
    
    if std_below_threshold:
        max_below = max(std_below_threshold)
        print(f"  Highest below threshold: {max_below:.3f} Hz (margin: {current_thresholds['std_dev']/max_below:.1f}x)")
    
    print()
    
    # Kurtosis Analysis
    kurtosis_values = [m['kurtosis'] for m in all_metrics]
    kurtosis_above_threshold = [v for v in kurtosis_values if v > current_thresholds['kurtosis']]
    kurtosis_below_threshold = [v for v in kurtosis_values if v <= current_thresholds['kurtosis']]
    
    print(f"Kurtosis Analysis:")
    print(f"  Values above threshold: {len(kurtosis_above_threshold)}/{len(kurtosis_values)} ({len(kurtosis_above_threshold)/len(kurtosis_values):.1%})")
    if kurtosis_above_threshold:
        min_above = min(kurtosis_above_threshold)
        max_above = max(kurtosis_above_threshold)
        print(f"  Range above threshold: {min_above:.3f} - {max_above:.3f}")
        print(f"  Closest to threshold: {min_above:.3f} (margin: {min_above/current_thresholds['kurtosis']:.1f}x)")
    
    if kurtosis_below_threshold:
        max_below = max(kurtosis_below_threshold)
        print(f"  Highest below threshold: {max_below:.3f} (margin: {current_thresholds['kurtosis']/max_below:.1f}x)")
    
    print()
    
    # Individual file analysis
    print("INDIVIDUAL FILE THRESHOLD ANALYSIS")
    print("=" * 60)
    
    for metric in all_metrics:
        filename = metric['filename']
        allan_var = metric['allan_variance']
        std_dev = metric['std_deviation']
        kurtosis = metric['kurtosis']
        
        print(f"\n{filename}")
        print("-" * 40)
        
        # Allan variance
        if allan_var > current_thresholds['allan_variance']:
            margin = allan_var / current_thresholds['allan_variance']
            print(f"  Allan Variance: {allan_var:.2e} (ABOVE by {margin:.1f}x)")
        else:
            margin = current_thresholds['allan_variance'] / allan_var if allan_var > 0 else float('inf')
            print(f"  Allan Variance: {allan_var:.2e} (below by {margin:.1f}x)")
        
        # Standard deviation
        if std_dev > current_thresholds['std_dev']:
            margin = std_dev / current_thresholds['std_dev']
            print(f"  Std Deviation: {std_dev:.3f} Hz (ABOVE by {margin:.1f}x)")
        else:
            margin = current_thresholds['std_dev'] / std_dev if std_dev > 0 else float('inf')
            print(f"  Std Deviation: {std_dev:.3f} Hz (below by {margin:.1f}x)")
        
        # Kurtosis
        if kurtosis > current_thresholds['kurtosis']:
            margin = kurtosis / current_thresholds['kurtosis']
            print(f"  Kurtosis: {kurtosis:.3f} (ABOVE by {margin:.1f}x)")
        else:
            margin = current_thresholds['kurtosis'] / kurtosis if kurtosis > 0 else float('inf')
            print(f"  Kurtosis: {kurtosis:.3f} (below by {margin:.1f}x)")
    
    # Safety margin analysis
    print(f"\nSAFETY MARGIN ANALYSIS")
    print("=" * 60)
    
    # Find the closest values to thresholds
    closest_allan_above = min(allan_above_threshold) if allan_above_threshold else None
    closest_std_above = min(std_above_threshold) if std_above_threshold else None
    closest_kurtosis_above = min(kurtosis_above_threshold) if kurtosis_above_threshold else None
    
    print(f"Closest values to thresholds:")
    if closest_allan_above:
        margin = closest_allan_above / current_thresholds['allan_variance']
        print(f"  Allan Variance: {closest_allan_above:.2e} (margin: {margin:.1f}x)")
    else:
        print(f"  Allan Variance: No values above threshold")
    
    if closest_std_above:
        margin = closest_std_above / current_thresholds['std_dev']
        print(f"  Std Deviation: {closest_std_above:.3f} Hz (margin: {margin:.1f}x)")
    else:
        print(f"  Std Deviation: No values above threshold")
    
    if closest_kurtosis_above:
        margin = closest_kurtosis_above / current_thresholds['kurtosis']
        print(f"  Kurtosis: {closest_kurtosis_above:.3f} (margin: {margin:.1f}x)")
    else:
        print(f"  Kurtosis: No values above threshold")
    
    # Recommendations
    print(f"\nRECOMMENDATIONS")
    print("=" * 60)
    
    if closest_std_above and closest_std_above / current_thresholds['std_dev'] < 2.0:
        print("WARNING: Standard deviation threshold is very close to actual data!")
        print(f"   Consider increasing std_dev threshold to {closest_std_above * 1.5:.3f} Hz for safety margin")
    
    if closest_allan_above and closest_allan_above / current_thresholds['allan_variance'] < 2.0:
        print("WARNING: Allan variance threshold is very close to actual data!")
        print(f"   Consider increasing allan_variance threshold to {closest_allan_above * 1.5:.2e} for safety margin")
    
    if closest_kurtosis_above and closest_kurtosis_above / current_thresholds['kurtosis'] < 2.0:
        print("WARNING: Kurtosis threshold is very close to actual data!")
        print(f"   Consider increasing kurtosis threshold to {closest_kurtosis_above * 1.5:.3f} for safety margin")
    
    if not (closest_std_above and closest_std_above / current_thresholds['std_dev'] < 2.0) and \
       not (closest_allan_above and closest_allan_above / current_thresholds['allan_variance'] < 2.0) and \
       not (closest_kurtosis_above and closest_kurtosis_above / current_thresholds['kurtosis'] < 2.0):
        print("GOOD: All thresholds have adequate safety margins")
        print("   Current thresholds are well-positioned for reliable detection")

if __name__ == "__main__":
    analyze_threshold_margins()
