#!/usr/bin/env python3
"""
Simple build script for the GIL-safe pulse counter C extension.
Uses modern Python build tools without deprecated distutils.
"""

import os
import sys
import subprocess
import logging

def setup_logging():
    """Setup logging for the build process."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger('simple_build')

def build_with_setuptools():
    """Build using setuptools (modern approach)."""
    logger = setup_logging()
    logger.info("Building C extension with setuptools...")
    
    try:
        from setuptools import setup, Extension
        from setuptools.command.build_ext import build_ext
        
        # Define the extension
        extension = Extension(
            'pulse_counter',
            sources=['pulse_counter.c'],
            libraries=['pthread'],
            extra_compile_args=['-fPIC'],
            extra_link_args=['-shared']
        )
        
        # Build the extension
        setup(
            name='pulse_counter',
            ext_modules=[extension],
            cmdclass={'build_ext': build_ext},
            script_args=['build_ext', '--inplace']
        )
        
        logger.info("✅ C extension built successfully with setuptools")
        return True
        
    except ImportError as e:
        logger.error(f"setuptools not available: {e}")
        logger.info("Install with: pip install setuptools")
        return False
    except Exception as e:
        logger.error(f"setuptools build failed: {e}")
        return False

def build_with_gcc_direct():
    """Build directly with gcc (fallback method)."""
    logger = setup_logging()
    logger.info("Building C extension directly with gcc...")
    
    try:
        import sysconfig
        
        # Get Python include directory
        include_dir = sysconfig.get_path('include')
        
        # Build command
        build_cmd = [
            'gcc',
            '-shared',
            '-fPIC',
            '-o', 'pulse_counter.so',
            'pulse_counter.c',
            '-I', include_dir,
            '-lpthread'
        ]
        
        logger.info(f"Running: {' '.join(build_cmd)}")
        result = subprocess.run(build_cmd, check=True, capture_output=True, text=True)
        
        logger.info("✅ C extension built successfully with gcc")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"gcc build failed: {e}")
        logger.error(f"stderr: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Direct gcc build failed: {e}")
        return False

def test_extension():
    """Test the built extension."""
    logger = setup_logging()
    logger.info("Testing built extension...")
    
    try:
        import pulse_counter
        
        # Test basic functionality
        slot = pulse_counter.register_pin(26)
        if slot == -1:
            logger.error("❌ Pin registration failed")
            return False
        
        pulse_counter.reset_count(26)
        count = pulse_counter.get_count(26)
        if count != 0:
            logger.error(f"❌ Initial count should be 0, got {count}")
            return False
        
        logger.info("✅ Extension test passed")
        return True
        
    except ImportError as e:
        logger.error(f"Cannot import extension: {e}")
        return False
    except Exception as e:
        logger.error(f"Extension test failed: {e}")
        return False

def main():
    """Main build function."""
    print("Simple C Extension Build Script")
    print("=" * 40)
    
    # Check if source file exists
    if not os.path.exists('pulse_counter.c'):
        print("❌ pulse_counter.c not found")
        return 1
    
    # Try setuptools first (modern approach)
    print("\n1. Trying setuptools build...")
    if build_with_setuptools():
        if test_extension():
            print("\n✅ Build successful with setuptools!")
            return 0
    
    # Fallback to direct gcc build
    print("\n2. Trying direct gcc build...")
    if build_with_gcc_direct():
        if test_extension():
            print("\n✅ Build successful with gcc!")
            return 0
    
    print("\n❌ All build methods failed")
    print("\nTroubleshooting:")
    print("• Install setuptools: pip install setuptools")
    print("• Install gcc: sudo apt-get install gcc")
    print("• Install Python dev headers: sudo apt-get install python3-dev")
    print("• Check file permissions")
    
    return 1

if __name__ == "__main__":
    sys.exit(main())
