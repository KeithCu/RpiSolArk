#!/usr/bin/env python3
"""
Simple Playwright test to bypass dependency warnings
"""

import asyncio
from playwright.async_api import async_playwright

async def test_playwright_simple():
    """Test if Playwright works despite dependency warnings"""
    print("🧪 Testing Playwright with dependency warnings...")
    
    try:
        async with async_playwright() as p:
            print("✅ Playwright context created successfully!")
            
            # Try to launch browser
            print("🌐 Launching browser...")
            browser = await p.chromium.launch(headless=False)  # Non-headless so you can see it
            
            print("✅ Browser launched successfully!")
            
            # Create a page
            page = await browser.new_page()
            print("✅ Page created successfully!")
            
            # Navigate to a simple page
            print("🌐 Navigating to example.com...")
            await page.goto("https://example.com")
            
            # Get page title
            title = await page.title()
            print(f"📋 Page title: {title}")
            
            # Take a screenshot
            await page.screenshot(path="test_screenshot.png")
            print("📸 Screenshot saved as test_screenshot.png")
            
            # Wait a bit so you can see the browser
            print("⏳ Waiting 5 seconds so you can see the browser...")
            await asyncio.sleep(5)
            
            # Close browser
            await browser.close()
            print("✅ Browser closed successfully!")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("🎉 Playwright test completed successfully!")
    return True

if __name__ == "__main__":
    asyncio.run(test_playwright_simple())
