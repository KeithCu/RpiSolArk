#!/usr/bin/env python3
"""
Test script for Sol-Ark Cloud integration

This script helps test the Sol-Ark cloud integration and download website pages
for analysis. Run this to understand the website structure and test functionality.
"""

import asyncio
import logging
import sys
from pathlib import Path
from solark_cloud import SolArkCloud, SolArkCloudError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_solark_cloud():
    """Test Sol-Ark cloud integration"""
    print("Sol-Ark Cloud Integration Test")
    print("=" * 40)
    
    # Check if config exists
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("ERROR: config.yaml not found!")
        print("Please create config.yaml with your Sol-Ark credentials.")
        return False
    
    try:
        # Initialize Sol-Ark cloud
        solark = SolArkCloud()
        
        # Check if credentials are configured
        if not solark.username or not solark.password:
            print("ERROR: Sol-Ark credentials not configured!")
            print("Please add your username and password to config.yaml under solark_cloud section.")
            return False
        
        print(f"Username: {solark.username}")
        print(f"Base URL: {solark.base_url}")
        print(f"Cache directory: {solark.cache_dir}")
        print()
        
        # Initialize browser
        print("Initializing browser...")
        if not await solark.initialize():
            print("ERROR: Failed to initialize browser")
            return False
        print("+ Browser initialized")
        
        # Test login
        print("Testing login...")
        if not await solark.login():
            print("ERROR: Login failed")
            return False
        print("+ Login successful")
        
        # Test TOU toggle functionality (core feature)
        test_inverter_id = "2207079903"  # Example inverter ID
        print(f"\nTesting TOU toggle for inverter {test_inverter_id}")
        
        # Test enabling TOU
        print("Testing TOU enable...")
        result = await solark.toggle_time_of_use(True, test_inverter_id)
        if result:
            print("+ TOU enable successful")
        else:
            print("ERROR: TOU enable failed")
        
        # Test disabling TOU
        print("Testing TOU disable...")
        result = await solark.toggle_time_of_use(False, test_inverter_id)
        if result:
            print("+ TOU disable successful")
        else:
            print("ERROR: TOU disable failed")
        
        # Test sync
        print("\nTesting data sync...")
        sync_result = await solark.sync_data()
        if sync_result.get('status') == 'success':
            print("+ Sync successful")
            print(f"  Plant ID: {sync_result.get('plant_id')}")
            print(f"  Parameters: {sync_result.get('parameter_count')}")
        else:
            print(f"ERROR: Sync failed - {sync_result.get('message')}")
        
        # Show cached files
        print(f"\nCached files in {solark.cache_dir}:")
        cache_files = list(solark.cache_dir.glob("*"))
        if cache_files:
            for file in cache_files:
                print(f"  - {file.name}")
        else:
            print("  No cached files found")
        
        print("\n+ Test completed successfully!")
        return True
        
    except SolArkCloudError as e:
        print(f"ERROR: {e}")
        return False
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        return False
    finally:
        # Cleanup
        try:
            await solark.cleanup()
            print("+ Browser cleanup completed")
        except:
            pass

async def download_pages_only():
    """Download pages without making changes"""
    print("Sol-Ark Cloud Page Downloader")
    print("=" * 40)
    
    try:
        solark = SolArkCloud()
        
        if not solark.username or not solark.password:
            print("ERROR: Sol-Ark credentials not configured!")
            return False
        
        print("Initializing browser...")
        if not await solark.initialize():
            return False
        
        print("Logging in...")
        if not await solark.login():
            return False
        
        print("Testing TOU toggle to generate cached pages...")
        test_inverter_id = "2207079903"
        await solark.toggle_time_of_use(True, test_inverter_id)
        
        print(f"Pages saved to: {solark.cache_dir}")
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        await solark.cleanup()

def main():
    """Main function"""
    if len(sys.argv) > 1 and sys.argv[1] == "--download-only":
        success = asyncio.run(download_pages_only())
    else:
        success = asyncio.run(test_solark_cloud())
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
