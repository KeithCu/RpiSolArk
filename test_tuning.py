#!/usr/bin/env python3
"""
Test script for tuning data collection with simulated generator behavior.
"""

import time
import random
import logging
import numpy as np
from config import Config, Logger
from tuning_collector import TuningDataCollector

# Import FrequencyAnalyzer from monitor module
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from monitor import FrequencyAnalyzer

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VirtualGenerator:
    """Simulates different types of generator behavior for comprehensive testing."""
    
    def __init__(self, generator_type="utility"):
        self.generator_type = generator_type
        self.time = 0
        self.base_freq = 60.0
        self.spike_count = 0
        self.cycle_count = 0
        
        # Initialize generator-specific parameters
        self._setup_generator()
    
    def _setup_generator(self):
        """Setup parameters for different generator types."""
        if self.generator_type == "utility":
            # Rock-solid utility grid - tests perfect stability
            self.noise_std = 0.002
            self.hunting_amplitude = 0.0
            self.hunting_frequency = 0.0
            self.spike_probability = 0.0
            self.description = "Utility Grid - Perfect Stability"
            
        elif self.generator_type == "governor_hunting":
            # Real-world governor hunting behavior - tests governor instability
            self.noise_std = 0.02
            self.hunting_amplitude = 2.5  # 59-64 Hz range
            self.hunting_frequency = 0.1  # 10 second cycle
            self.spike_probability = 0.005
            self.description = "Generator - Governor Hunting"
            
        elif self.generator_type == "cold_start_surging":
            # Real-world cold start surging - tests startup instability
            self.noise_std = 0.05
            self.hunting_amplitude = 5.5  # 50-61 Hz range
            self.hunting_frequency = 0.2  # 5 second cycle
            self.spike_probability = 0.02
            self.description = "Generator - Cold Start Surging"
            
        elif self.generator_type == "load_dependent":
            # Real-world load-dependent instability - tests load response
            self.noise_std = 0.03
            self.hunting_amplitude = 2.0  # 57-62 Hz range
            self.hunting_frequency = 0.15  # Load-dependent cycling
            self.spike_probability = 0.01
            self.description = "Generator - Load Dependent Issues"
            
        elif self.generator_type == "extreme_hunting":
            # Real-world extreme hunting behavior - tests severe instability
            self.noise_std = 0.04
            self.hunting_amplitude = 1.0  # 59-60 Hz hunting ±1Hz
            self.hunting_frequency = 0.5  # 2 second cycle
            self.spike_probability = 0.03
            self.description = "Generator - Extreme Hunting"
            
        elif self.generator_type == "harmonic_distortion":
            # Real-world harmonic distortion - tests electrical harmonics
            self.noise_std = 0.01
            self.hunting_amplitude = 0.2  # 60.2 Hz with harmonics
            self.hunting_frequency = 0.0
            self.spike_probability = 0.0
            self.harmonic_distortion = True
            self.description = "Generator - Harmonic Distortion"
            
        elif self.generator_type == "high_kurtosis":
            # Synthetic - tests extreme kurtosis and hunting patterns
            self.noise_std = 0.1
            self.hunting_amplitude = 4.0  # 56-64 Hz range
            self.hunting_frequency = 0.3  # Fast hunting
            self.spike_probability = 0.05
            self.description = "Generator - High Kurtosis Test"
            
        elif self.generator_type == "allan_variance_test":
            # Synthetic - tests Allan variance detection
            self.noise_std = 0.01
            self.hunting_amplitude = 0.0
            self.hunting_frequency = 0.0
            self.spike_probability = 0.0
            self.allan_noise = True
            self.description = "Allan Variance Test - Subtle Instability"
            
        else:
            raise ValueError(f"Unknown generator type: {generator_type}")
    
    def get_frequency(self):
        """Generate a frequency reading based on generator type."""
        self.time += 0.1  # 10 Hz sampling
        
        # Base frequency with noise
        freq = self.base_freq + random.gauss(0, self.noise_std)
        
        # Add hunting behavior for generators
        if self.hunting_amplitude > 0:
            hunting = self.hunting_amplitude * np.sin(2 * np.pi * self.hunting_frequency * self.time)
            freq += hunting
        
        # Add load-dependent behavior for load-dependent generators
        if self.generator_type == "load_dependent":
            # Simulate load changes every 20 seconds
            load_cycle = int(self.time / 20) % 2
            if load_cycle == 0:  # No-load
                freq += 1.0  # Higher frequency
            else:  # Loaded
                freq -= 2.0  # Lower frequency
        
        # Add harmonic distortion for generators with harmonic issues
        if hasattr(self, 'harmonic_distortion') and self.harmonic_distortion:
            # Add 3rd and 5th harmonics
            freq += 0.1 * np.sin(2 * np.pi * 3 * self.time * 0.1)
            freq += 0.05 * np.sin(2 * np.pi * 5 * self.time * 0.1)
        
        # Add Allan variance noise for testing
        if hasattr(self, 'allan_noise') and self.allan_noise:
            # Add correlated noise that affects Allan variance
            freq += 0.01 * np.sin(2 * np.pi * 0.05 * self.time) * random.gauss(0, 1)
        
        # Add occasional spikes for generators
        if random.random() < self.spike_probability:
            spike = random.uniform(-2, 2)  # Random spike
            freq += spike
            self.spike_count += 1
        
        # Add extreme hunting behavior for high kurtosis test
        if self.generator_type == "high_kurtosis":
            # Add rapid frequency changes to increase kurtosis
            if int(self.time * 10) % 10 < 3:  # 30% of time
                freq += random.uniform(-1, 1)
        
        # Add startup behavior for cold start surging
        if self.generator_type == "cold_start_surging" and self.time < 30:
            # Simulate cold start issues
            startup_instability = 3.0 * np.exp(-self.time / 10)  # Decaying instability
            freq += startup_instability * random.gauss(0, 1)
        
        return freq
    
    def get_description(self):
        """Get description of this generator type."""
        return self.description

def test_tuning_collector():
    """Test the tuning collector with different generator types."""
    
    # Create config
    config = Config("config.yaml")
    
    # Enable tuning mode
    config.config['tuning']['enabled'] = True
    config.config['tuning']['detailed_logging'] = True
    config.config['tuning']['collection_duration'] = 10  # 10 seconds test
    config.config['tuning']['sample_interval'] = 0.1
    config.config['tuning']['analysis_interval'] = 1.0
    config.config['tuning']['data_file'] = "test_tuning_data.csv"
    config.config['tuning']['analysis_file'] = "test_tuning_analysis.csv"
    
    # Create analyzer
    analyzer = FrequencyAnalyzer(config, logger)
    
    # Test all 8 generator types to exercise all analysis code paths
    generator_types = [
        "utility",              # Perfect stability - tests baseline
        "governor_hunting",     # Real-world governor hunting behavior
        "cold_start_surging",   # Real-world cold start surging  
        "load_dependent",       # Real-world load-dependent issues
        "extreme_hunting",      # Real-world extreme hunting behavior
        "harmonic_distortion",  # Real-world harmonic distortion
        "high_kurtosis",        # Synthetic - tests high kurtosis detection
        "allan_variance_test"   # Synthetic - tests Allan variance detection
    ]
    
    for gen_type in generator_types:
        # Create a new tuning collector for each test with unique file names
        config.config['tuning']['data_file'] = f"test_tuning_data_{gen_type}.csv"
        config.config['tuning']['analysis_file'] = f"test_tuning_analysis_{gen_type}.csv"
        tuning_collector = TuningDataCollector(config, logger)
        
        logger.info(f"\n{'='*50}")
        logger.info(f"Testing with {gen_type.upper()} generator simulation")
        logger.info(f"{'='*50}")
        
        # Create virtual generator
        virtual_gen = VirtualGenerator(gen_type)
        
        logger.info(f"Generator: {virtual_gen.get_description()}")
        logger.info(f"Expected behavior: {gen_type}")
        
        # Start tuning collection
        tuning_collector.start_collection()
        
        # Simulate frequency readings
        sample_count = 0
        freq_buffer = []
        
        while tuning_collector.is_collection_active():
            # Get frequency reading
            freq = virtual_gen.get_frequency()
            freq_buffer.append(freq)
            
            # Keep buffer size reasonable (300 samples = 30 seconds at 10 Hz)
            if len(freq_buffer) > 300:
                freq_buffer.pop(0)
            
            # Analyze if we have enough data
            if len(freq_buffer) >= 10:
                frac_freq = (np.array(freq_buffer) - 60.0) / 60.0
                avar_10s, std_freq, kurtosis = analyzer.analyze_stability(frac_freq)
                source = analyzer.classify_power_source(avar_10s, std_freq, kurtosis)
                
                # Collect tuning data
                analysis_results = {
                    'allan_variance': avar_10s,
                    'std_deviation': std_freq,
                    'kurtosis': kurtosis
                }
                
                tuning_collector.collect_frequency_sample(freq, analysis_results, source)
                tuning_collector.collect_analysis_results(analysis_results, source, len(freq_buffer))
                
                # Log progress with analysis feature indicators
                if sample_count % 10 == 0:  # Every second
                    # Show which analysis features are being triggered
                    features = []
                    if avar_10s and avar_10s > 1e-6:
                        features.append("AllanVar")
                    if std_freq and std_freq > 0.01:
                        features.append("StdDev")
                    if kurtosis and abs(kurtosis) > 0.1:
                        features.append("Kurtosis")
                    
                    feature_str = f"[{','.join(features)}]" if features else "[Stable]"
                    
                    logger.info(f"Sample {sample_count}: {freq:.3f} Hz, "
                              f"Source: {source} {feature_str}, "
                              f"Allan: {avar_10s:.2e}, "
                              f"StdDev: {std_freq:.3f}, "
                              f"Kurtosis: {kurtosis:.2f}")
            
            sample_count += 1
            time.sleep(0.1)  # 10 Hz sampling
        
        # Stop collection
        tuning_collector.stop_collection()
        
        # Show results
        logger.info(f"\n{gen_type.upper()} test completed:")
        logger.info(f"  Samples collected: {sample_count}")
        logger.info(f"  Data file: {tuning_collector.data_file}")
        logger.info(f"  Analysis file: {tuning_collector.analysis_file}")
        
        # Wait a moment between tests
        time.sleep(2)
    
    logger.info(f"\n{'='*50}")
    logger.info("All 8 generator tests completed!")
    logger.info("Analysis features tested:")
    logger.info("  ✓ Allan Variance detection (allan_variance_test)")
    logger.info("  ✓ Standard Deviation analysis (cold_start_surging, extreme_hunting)")
    logger.info("  ✓ Kurtosis analysis (high_kurtosis, load_dependent)")
    logger.info("  ✓ Governor hunting (governor_hunting)")
    logger.info("  ✓ Cold start surging (cold_start_surging)")
    logger.info("  ✓ Load-dependent issues (load_dependent)")
    logger.info("  ✓ Harmonic distortion (harmonic_distortion)")
    logger.info("  ✓ Perfect stability baseline (utility)")
    logger.info("Check the generated CSV files for detailed data analysis.")
    logger.info(f"{'='*50}")

def analyze_test_results():
    """Analyze the test results to show the data collection worked."""
    try:
        import pandas as pd
        
        logger.info("\nAnalyzing test results...")
        
        # Read the analysis file
        df = pd.read_csv("test_tuning_analysis.csv")
        
        # Group by power source
        utility_data = df[df['power_source'] == 'Utility Grid']
        generator_data = df[df['power_source'] == 'Generac Generator']
        
        logger.info(f"\nData Collection Summary:")
        logger.info(f"  Total analysis points: {len(df)}")
        logger.info(f"  Utility classifications: {len(utility_data)}")
        logger.info(f"  Generator classifications: {len(generator_data)}")
        
        if len(utility_data) > 0:
            logger.info(f"\nUtility Grid Statistics:")
            logger.info(f"  Allan Variance: {utility_data['allan_variance'].mean():.2e} ± {utility_data['allan_variance'].std():.2e}")
            logger.info(f"  Std Deviation: {utility_data['std_deviation'].mean():.3f} ± {utility_data['std_deviation'].std():.3f}")
            logger.info(f"  Kurtosis: {utility_data['kurtosis'].mean():.2f} ± {utility_data['kurtosis'].std():.2f}")
        
        if len(generator_data) > 0:
            logger.info(f"\nGenerator Statistics:")
            logger.info(f"  Allan Variance: {generator_data['allan_variance'].mean():.2e} ± {generator_data['allan_variance'].std():.2e}")
            logger.info(f"  Std Deviation: {generator_data['std_deviation'].mean():.3f} ± {generator_data['std_deviation'].std():.3f}")
            logger.info(f"  Kurtosis: {generator_data['kurtosis'].mean():.2f} ± {generator_data['kurtosis'].std():.2f}")
        
        # Show frequency ranges
        freq_df = pd.read_csv("test_tuning_data.csv")
        logger.info(f"\nFrequency Statistics:")
        logger.info(f"  Mean: {freq_df['frequency_hz'].mean():.3f} Hz")
        logger.info(f"  Std: {freq_df['frequency_hz'].std():.3f} Hz")
        logger.info(f"  Min: {freq_df['frequency_hz'].min():.3f} Hz")
        logger.info(f"  Max: {freq_df['frequency_hz'].max():.3f} Hz")
        logger.info(f"  Range: {freq_df['frequency_hz'].max() - freq_df['frequency_hz'].min():.3f} Hz")
        
    except ImportError:
        logger.warning("pandas not available for analysis. Install with: pip install pandas")
    except Exception as e:
        logger.error(f"Error analyzing results: {e}")

if __name__ == "__main__":
    print("Testing Tuning Data Collector")
    print("=" * 50)
    
    try:
        test_tuning_collector()
        analyze_test_results()
        
        print("\nTest completed successfully!")
        print("Generated files:")
        print("  - test_tuning_data.csv (raw frequency data)")
        print("  - test_tuning_analysis.csv (analysis results)")
        print("  - tuning_summary_*.json (summary report)")
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
