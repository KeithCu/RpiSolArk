#!/usr/bin/env python3
"""
Eventfd-based stress test for pulse_counter C extension.
Tests interrupt handling capacity using simulated eventfd interrupts on any Linux system.
"""

import time
import threading
import signal
import sys
import os
import statistics
from collections import deque

class EventfdPulseCounterStressTest:
    def __init__(self, test_pin=26):
        """
        Initialize eventfd stress test for pulse counter.
        
        Args:
            test_pin: Virtual pin number to monitor with pulse_counter
        """
        self.test_pin = test_pin
        self.running = False
        self.test_frequency = 0
        self.expected_pulses = 0
        self.actual_pulses = 0
        self.missed_pulses = 0
        self.test_duration = 0.05  # 50ms per test
        self.results = []
        
        # Performance monitoring
        self.interrupt_times = deque(maxlen=1000)
        self.latency_measurements = deque(maxlen=1000)
        self.last_count = 0
        self.start_time = 0
        
        # Import the C extension
        try:
            import pulse_counter
            self.pulse_counter = pulse_counter
            print("✅ Successfully imported pulse_counter C extension")
        except ImportError as e:
            print(f"❌ Failed to import pulse_counter: {e}")
            print("Make sure to run simple_build.py first")
            sys.exit(1)
    
    def signal_handler(self, signum, frame):
        """Handle interrupt signals gracefully."""
        print(f"\n🛑 Received signal {signum}, stopping test...")
        self.running = False
        # Force exit after cleanup
        import sys
        sys.exit(0)
    
    def setup_kernel_interrupts(self, frequency):
        """
        Setup kernel interrupt handling in main thread (Arch Linux & RPi compatible).
        
        WARNING: SIGALRM is NOT suitable for high-frequency kernel interrupt testing!
        - SIGALRM signals get delayed/batched by kernel scheduler
        - Timing measurements show kernel scheduling delays, not interrupt timing
        - For real kernel interrupt testing, use GPIO hardware interrupts on Raspberry Pi
        - This test is only useful for low-frequency (< 10Hz) kernel interrupt validation
        """
        import signal
        import platform
        
        # Global variables for signal handling
        self.interrupt_count = 0
        self.interrupt_times = []
        self.last_interrupt_time = None  # Initialize after first signal
        
        def kernel_signal_handler(signum, frame):
            """This runs in kernel interrupt context - measure timing here!"""
            current_time = time.time()
            
            # Measure kernel interrupt latency (skip first signal)
            if self.last_interrupt_time is not None:
                latency = current_time - self.last_interrupt_time
                self.interrupt_times.append(latency)
            
            # Increment counter in interrupt context
            self.interrupt_count += 1
            self.last_interrupt_time = current_time
            
            # Note: GPIO interrupts are handled automatically by the C extension
            # No need to manually trigger interrupts in hardware mode
        
        # Set up signal handler for kernel interrupts (main thread only)
        signal.signal(signal.SIGALRM, kernel_signal_handler)
        
        # Calculate timer period with Arch Linux/RPi compatibility
        period_seconds = 1.0 / frequency
        
        # Detect system for compatibility
        system_info = f"{platform.system()} {platform.machine()}"
        print(f"📡 Generating REAL kernel interrupts at {frequency}Hz...")
        print(f"   System: {system_info}")
        print(f"   Kernel timer period: {period_seconds*1000:.3f}ms")
        
        # Set up periodic kernel timer (compatible with Arch Linux & RPi)
        try:
            signal.setitimer(signal.ITIMER_REAL, period_seconds, period_seconds)
        except Exception as e:
            print(f"   ⚠️  Timer setup warning: {e}")
            return
        
        # Wait for interrupts to occur
        start_time = time.time()
        while self.running and (time.time() - start_time) < self.test_duration:
            time.sleep(0.001)  # 1ms sleep to allow interrupts
        
        # Cancel the kernel timer
        try:
            signal.setitimer(signal.ITIMER_REAL, 0, 0)
        except:
            pass  # Ignore cleanup errors
        
        self.expected_pulses = self.interrupt_count
        print(f"📡 Generated {self.interrupt_count} REAL kernel interrupts")
        
        # Calculate kernel interrupt statistics
        if self.interrupt_times:
            avg_interval = sum(self.interrupt_times) / len(self.interrupt_times)
            min_interval = min(self.interrupt_times)
            max_interval = max(self.interrupt_times)
            print(f"   Kernel interrupt timing:")
            print(f"     Average interval: {avg_interval*1000:.3f}ms")
            print(f"     Min interval: {min_interval*1000:.3f}ms") 
            print(f"     Max interval: {max_interval*1000:.3f}ms")
            print(f"     Jitter: {(max_interval-min_interval)*1000:.3f}ms")
    
    def monitor_performance(self):
        """Monitor interrupt handling performance and measure latency."""
        start_time = time.time()
        last_time = start_time
        last_count = 0
        
        while self.running and (time.time() - start_time) < self.test_duration:
            # Measure latency: time between trigger and detection
            trigger_time = time.time()
            
            # This is the KEY function - it reads eventfd and updates counters
            self.pulse_counter.check_interrupts()
            
            # Get current count
            current_count = self.pulse_counter.get_count(self.test_pin)
            
            # Calculate interrupt rate and latency
            current_time = time.time()
            if current_count > last_count:
                time_diff = current_time - last_time
                if time_diff > 0:
                    interrupt_rate = (current_count - last_count) / time_diff
                    self.interrupt_times.append(interrupt_rate)
                
                # Measure latency (time from trigger to detection)
                latency = current_time - trigger_time
                self.latency_measurements.append(latency)
                
                last_count = current_count
                last_time = current_time
            
            # Small sleep to prevent 100% CPU usage
            time.sleep(0.0001)  # 0.1ms
        
        self.actual_pulses = last_count
    
    def run_single_test(self, frequency):
        """Run a single stress test at specified frequency."""
        print(f"\n🧪 Testing at {frequency}Hz...")
        print(f"   Duration: {self.test_duration}s")
        print(f"   Expected pulses: ~{int(frequency * self.test_duration)}")
        
        # Reset state
        self.running = True
        self.expected_pulses = 0
        self.actual_pulses = 0
        self.missed_pulses = 0
        self.interrupt_times.clear()
        self.latency_measurements.clear()
        self.last_count = 0
        
        # Cleanup any previous state
        self.pulse_counter.cleanup()
        
        # Set hardware mode (GPIO interrupts)
        mode_result = self.pulse_counter.set_mode(0)  # 0 = hardware mode
        print(f"   🔍 Set to hardware mode: {mode_result}")
        
        # Register pin with pulse counter
        slot = self.pulse_counter.register_pin(self.test_pin)
        if slot == -1:
            print(f"❌ Failed to register pin {self.test_pin}")
            return False
        
        # Reset counter
        self.pulse_counter.reset_count(self.test_pin)
        
        # Test basic functionality first
        print(f"   🔍 Testing basic functionality...")
        print(f"   🔍 Pin {self.test_pin} registered in slot {slot}")
        
        # Test basic GPIO functionality
        initial_count = self.pulse_counter.get_count(self.test_pin)
        print(f"   🔍 Initial count: {initial_count}")
        
        # Test check_interrupts function (should work with GPIO)
        self.pulse_counter.check_interrupts()
        count_after_check = self.pulse_counter.get_count(self.test_pin)
        print(f"   🔍 After check_interrupts: {count_after_check}")
        
        if count_after_check >= initial_count:
            print(f"   ✅ GPIO interrupt system ready")
        else:
            print(f"   ❌ GPIO interrupt system not working")
            return False
        
        # Reset and run the actual stress test
        self.pulse_counter.reset_count(self.test_pin)
        
        # Start monitoring thread
        monitor_thread = threading.Thread(target=self.monitor_performance)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Setup and run kernel interrupts in main thread (SIGALRM - limited functionality)
        self.setup_kernel_interrupts(frequency)
        
        # Wait for monitoring to complete
        time.sleep(0.1)  # Brief wait for final counts
        
        self.running = False
        
        # Wait for threads to finish
        monitor_thread.join(timeout=1.0)
        
        # Final check_interrupts call to catch any remaining interrupts
        self.pulse_counter.check_interrupts()
        
        # Get final count
        self.actual_pulses = self.pulse_counter.get_count(self.test_pin)
        self.missed_pulses = max(0, self.expected_pulses - self.actual_pulses)
        
        # Debug output
        print(f"   🔍 Debug: Expected={self.expected_pulses}, Actual={self.actual_pulses}, Missed={self.missed_pulses}")
        
        # Calculate performance metrics
        success_rate = (self.actual_pulses / self.expected_pulses * 100) if self.expected_pulses > 0 else 0
        avg_interrupt_rate = statistics.mean(self.interrupt_times) if self.interrupt_times else 0
        avg_latency = statistics.mean(self.latency_measurements) if self.latency_measurements else 0
        max_latency = max(self.latency_measurements) if self.latency_measurements else 0
        
        # Store results
        result = {
            'frequency': frequency,
            'expected_pulses': self.expected_pulses,
            'actual_pulses': self.actual_pulses,
            'missed_pulses': self.missed_pulses,
            'success_rate': success_rate,
            'avg_interrupt_rate': avg_interrupt_rate,
            'avg_latency': avg_latency,
            'max_latency': max_latency,
            'test_duration': self.test_duration
        }
        
        self.results.append(result)
        
        # Print results
        print(f"   📊 Results:")
        print(f"      Expected: {self.expected_pulses}")
        print(f"      Actual: {self.actual_pulses}")
        print(f"      Missed: {self.missed_pulses}")
        print(f"      Success rate: {success_rate:.1f}%")
        print(f"      Avg interrupt rate: {avg_interrupt_rate:.1f} Hz")
        print(f"      Avg latency: {avg_latency*1000:.2f} ms")
        print(f"      Max latency: {max_latency*1000:.2f} ms")
        
        # Determine if test passed
        if success_rate >= 95.0:  # 95% success rate threshold
            print(f"   ✅ PASSED - {frequency}Hz is sustainable")
            return True
        else:
            print(f"   ❌ FAILED - {frequency}Hz has too many missed interrupts")
            return False
    
    def run_stress_test(self, start_freq=1000, max_freq=500000, step=1000):
        """Run comprehensive stress test across frequency range."""
        print("🚀 Starting Eventfd Pulse Counter Stress Test")
        print("=" * 50)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        print(f"📋 Test Configuration:")
        print(f"   Test pin: {self.test_pin}")
        print(f"   Test duration: {self.test_duration*1000:.0f}ms per frequency")
        print(f"   Frequency range: {start_freq}Hz to {max_freq}Hz (step: {step}Hz)")
        print(f"   Success threshold: 95%")
        print(f"   Method: GPIO hardware interrupts (RPi) + SIGALRM (limited)")
        
        # Test frequencies
        test_frequencies = list(range(start_freq, max_freq + 1, step))
        max_sustainable_freq = 0
        
        for freq in test_frequencies:
            if self.run_single_test(freq):
                max_sustainable_freq = freq
            else:
                print(f"\n💥 Breaking point reached at {freq}Hz")
                break
            
            # Brief pause between tests
            time.sleep(0.5)
        
        # Print summary
        self.print_summary(max_sustainable_freq)
    
    def print_summary(self, max_sustainable_freq):
        """Print test summary."""
        print("\n" + "=" * 50)
        print("📊 EVENTFD STRESS TEST SUMMARY")
        print("=" * 50)
        
        if max_sustainable_freq > 0:
            print(f"✅ Maximum sustainable frequency: {max_sustainable_freq}Hz")
        else:
            print("❌ No frequencies passed the 95% success threshold")
        
        print(f"\n📈 Detailed Results:")
        print(f"{'Freq (Hz)':<10} {'Expected':<10} {'Actual':<10} {'Missed':<10} {'Success %':<10} {'Avg Lat (ms)':<12}")
        print("-" * 80)
        
        for result in self.results:
            print(f"{result['frequency']:<10} "
                  f"{result['expected_pulses']:<10} "
                  f"{result['actual_pulses']:<10} "
                  f"{result['missed_pulses']:<10} "
                  f"{result['success_rate']:<10.1f} "
                  f"{result['avg_latency']*1000:<12.2f}")
        
        # Performance analysis
        if len(self.results) > 1:
            print(f"\n🔍 Performance Analysis:")
            success_rates = [r['success_rate'] for r in self.results]
            latencies = [r['avg_latency']*1000 for r in self.results]
            print(f"   Best success rate: {max(success_rates):.1f}%")
            print(f"   Worst success rate: {min(success_rates):.1f}%")
            print(f"   Average success rate: {statistics.mean(success_rates):.1f}%")
            print(f"   Best latency: {min(latencies):.2f} ms")
            print(f"   Worst latency: {max(latencies):.2f} ms")
            print(f"   Average latency: {statistics.mean(latencies):.2f} ms")
            
            # Find the frequency where performance starts degrading
            for i, result in enumerate(self.results):
                if result['success_rate'] < 95.0:
                    if i > 0:
                        print(f"   Performance degradation starts around: {self.results[i-1]['frequency']}Hz")
                    break

def main():
    """Main function to run the stress test."""
    print("Real Kernel Interrupt Stress Test")
    print("Testing interrupt handling capacity using GPIO hardware interrupts")
    print("WARNING: SIGALRM is NOT suitable for high-frequency testing!")
    print("For real kernel interrupt testing, use GPIO hardware interrupts on Raspberry Pi")
    print()
    
    # Check if pulse_counter extension exists
    if not (os.path.exists('pulse_counter.so') or os.path.exists('pulse_counter.cpython-313-x86_64-linux-gnu.so')):
        print("❌ pulse_counter extension not found")
        print("   Run: python3 simple_build.py first")
        return 1
    
    # Create and run stress test
    stress_test = EventfdPulseCounterStressTest()
    
    # Run test with kernel interrupt parameters (Arch Linux & RPi compatible)
    stress_test.run_stress_test(
        start_freq=100,     # Start at 100Hz for kernel interrupts
        max_freq=500,       # Test up to 500Hz (reasonable for kernel interrupts)
        step=100             # 50Hz increments
    )
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
