#!/usr/bin/env python3
"""
Test script for Sol-Ark inverter automation.
This script tests the simplified TOU toggle functionality.
"""

import yaml
from solark_cloud import SolArkCloud

def take_debug_screenshot(solark, filename_prefix, reason="debug"):
    """Take a screenshot for debugging purposes"""
    try:
        screenshot_file = f"{filename_prefix}.png"
        solark.page.screenshot(path=screenshot_file)
        print(f"📸 Screenshot saved: {screenshot_file} ({reason})")
        return screenshot_file
    except Exception as e:
        print(f"❌ Failed to take screenshot: {e}")
        return None

def download_debug_html(solark, filename_prefix, reason="debug"):
    """Download HTML content for debugging purposes"""
    try:
        html_content = solark.page.content()
        html_file = f"{filename_prefix}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"📥 HTML saved: {html_file} ({reason})")
        return html_file
    except Exception as e:
        print(f"❌ Failed to download HTML: {e}")
        return None

def debug_page_state(solark, stage_name, reason="debug"):
    """Take screenshot and download HTML at any stage for debugging"""
    print(f"\n🔍 Debug: {stage_name} - {reason}")
    take_debug_screenshot(solark, f"debug_{stage_name}", reason)
    download_debug_html(solark, f"debug_{stage_name}", reason)

def debug_on_error(solark, error_context, error_message):
    """Take debug screenshots and HTML when an error occurs"""
    print(f"\n🚨 Error Debug: {error_context}")
    print(f"   Error: {error_message}")
    take_debug_screenshot(solark, f"error_{error_context}", f"Error: {error_message}")
    download_debug_html(solark, f"error_{error_context}", f"Error: {error_message}")

# Debug Strategy:
# - Only take screenshots/HTML when there's an issue
# - Use debug_on_error() for failures to capture the problematic state
# - Use debug_page_state() for manual debugging when needed
# - No automatic success screenshots - only when manually requested
#
# Manual debugging examples:
#   await debug_page_state(solark, "after_login", "Manual debug")
#   await debug_page_state(solark, "parameters_page", "Manual debug")

def test_inverter_automation():
    """Test the complete inverter automation flow."""
    
    print("🚀 Starting Sol-Ark Inverter Automation Test")
    print("=" * 50)
    
    # Load configuration
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to load config.yaml: {e}")
        return False
    
    # Get inverter ID from primary optocoupler (new multi-inverter format)
    inverter_id = None
    if 'hardware' in config and 'optocoupler' in config['hardware'] and 'primary' in config['hardware']['optocoupler']:
        primary_config = config['hardware']['optocoupler']['primary']
        
        # Check for new multi-inverter format
        if 'inverters' in primary_config and primary_config['inverters']:
            # Use first enabled inverter
            for inverter in primary_config['inverters']:
                if inverter.get('enabled', True) and inverter.get('id'):
                    inverter_id = inverter['id']
                    break
        # Fallback to legacy format
        elif 'solark_inverter_id' in primary_config:
            inverter_id = primary_config['solark_inverter_id']
        
        if inverter_id:
            print(f"✅ Found inverter ID: {inverter_id}")
        else:
            print("❌ No inverter ID configured for primary optocoupler")
            return False
    else:
        print("❌ No optocoupler configuration found")
        return False
    
    # Initialize Sol-Ark Cloud
    print("\n🌐 Initializing Sol-Ark Cloud...")
    solark = SolArkCloud('config.yaml')
    
    try:
        # Initialize browser
        if not solark.initialize():
            print("❌ Failed to initialize browser")
            return False
        print("✅ Browser initialized")
        
        # Login
        print("\n🔐 Logging in...")
        if solark.login():
            print("✅ Login successful")
        else:
            print("❌ Login failed")
            debug_on_error(solark, "login_failed", "Login attempt failed")
            return False
        
        # Test TOU toggle functionality
        print(f"\n🎯 Testing TOU toggle for inverter {inverter_id}")
        
        # Test enabling TOU
        print("\n🔄 Testing TOU enable...")
        result = solark.toggle_time_of_use(True, inverter_id)
        if result:
            print("✅ TOU enable test successful")
        else:
            print("❌ TOU enable test failed")
            debug_on_error(solark, "tou_enable_failed", "TOU enable test failed")
            return False
        
        # Test disabling TOU
        print("\n🔄 Testing TOU disable...")
        result = solark.toggle_time_of_use(False, inverter_id)
        if result:
            print("✅ TOU disable test successful")
        else:
            print("❌ TOU disable test failed")
            debug_on_error(solark, "tou_disable_failed", "TOU disable test failed")
            return False
        
        print("\n🎉 TOU automation test completed successfully!")
        print("   Summary:")
        print("   1. ✅ Login to Sol-Ark")
        print("   2. ✅ Navigate to inverter device page")
        print("   3. ✅ Find specific inverter by ID")
        print("   4. ✅ Click dropdown menu")
        print("   5. ✅ Click Parameters Setting")
        print("   6. ✅ Find TOU switch")
        print("   7. ✅ Toggle TOU switch (enable)")
        print("   8. ✅ Toggle TOU switch (disable)")
        print("   9. ✅ Find save button")
        print("   10. ✅ Click save button")
        print("\n🚀 TOU automation is working correctly!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during automation: {e}")
        if 'solark' in locals():
            debug_on_error(solark, "automation_failed", str(e))
        return False
    finally:
        try:
            solark.cleanup()
        except Exception as e:
            print(f"⚠️ Error during cleanup: {e}")

if __name__ == "__main__":
    test_inverter_automation()
