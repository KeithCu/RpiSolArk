#!/usr/bin/env python3
"""
Run all individual improvement tests to see which optimizations help.
This will help you decide which improvements are necessary for your setup.
"""

import subprocess
import sys
import os

def run_test(script_name, description):
    """Run a test script and display results."""
    print(f"\n{'='*60}")
    print(f"🧪 {description}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run([sys.executable, script_name], 
                              capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"❌ Test failed with return code {result.returncode}")
            print(result.stderr)
    except subprocess.TimeoutExpired:
        print("⏰ Test timed out after 2 minutes")
    except Exception as e:
        print(f"❌ Error running test: {e}")

def main():
    """Run all improvement tests."""
    print("🎯 COMPREHENSIVE OPTCOUPLER IMPROVEMENT TESTING")
    print("=" * 60)
    print("This will run all individual improvement tests")
    print("to help you decide which optimizations are necessary.")
    print("=" * 60)
    
    # List of tests to run
    tests = [
        ("test_critical_improvements.py", "Critical Improvements Test"),
        ("test_debouncing_impact.py", "Debouncing Impact Test"),
        ("test_individual_improvements.py", "Complete Individual Tests"),
    ]
    
    for script, description in tests:
        if os.path.exists(script):
            run_test(script, description)
        else:
            print(f"⚠️  Script {script} not found, skipping...")
    
    print(f"\n🏁 ALL TESTS COMPLETED!")
    print(f"💡 Review the results above to see which improvements help your setup")
    print(f"💡 Focus on tests that show significant accuracy improvements")
    print(f"💡 You can run individual tests with: python <script_name>")

if __name__ == "__main__":
    main()
