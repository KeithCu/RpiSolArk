#!/usr/bin/env python3
"""
Simple Playwright test to bypass dependency warnings
"""

import time
from playwright.sync_api import sync_playwright

def test_playwright_simple():
    """Test if Playwright works despite dependency warnings"""
    print("🧪 Testing Playwright with dependency warnings...")
    
    try:
        with sync_playwright() as p:
            print("✅ Playwright context created successfully!")
            
            # Try to launch browser
            print("🌐 Launching browser...")
            browser = p.chromium.launch(headless=False)  # Non-headless so you can see it
            
            print("✅ Browser launched successfully!")
            
            # Create a page
            page = browser.new_page()
            print("✅ Page created successfully!")
            
            # Navigate to a simple page
            print("🌐 Navigating to example.com...")
            page.goto("https://keithcu.com")
            
            # Get page title
            title = page.title()
            print(f"📋 Page title: {title}")
            
            # Take a screenshot
            page.screenshot(path="test_screenshot.png")
            print("📸 Screenshot saved as test_screenshot.png")
            
            # Wait a bit so you can see the browser
            print("⏳ Waiting 5 seconds so you can see the browser...")
            time.sleep(5)
            
            # Close browser
            browser.close()
            print("✅ Browser closed successfully!")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("🎉 Playwright test completed successfully!")
    return True

if __name__ == "__main__":
    test_playwright_simple()
