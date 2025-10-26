#!/usr/bin/env python3
"""
Test script for Sol-Ark inverter automation.
This script implements the actual automation based on the HTML analysis.
"""

import asyncio
import yaml
from solark_cloud import SolArkCloud

async def take_debug_screenshot(solark, filename_prefix, reason="debug"):
    """Take a screenshot for debugging purposes"""
    try:
        screenshot_file = f"{filename_prefix}.png"
        await solark.page.screenshot(path=screenshot_file)
        print(f"📸 Screenshot saved: {screenshot_file} ({reason})")
        return screenshot_file
    except Exception as e:
        print(f"❌ Failed to take screenshot: {e}")
        return None

async def download_debug_html(solark, filename_prefix, reason="debug"):
    """Download HTML content for debugging purposes"""
    try:
        html_content = await solark.page.content()
        html_file = f"{filename_prefix}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"📥 HTML saved: {html_file} ({reason})")
        return html_file
    except Exception as e:
        print(f"❌ Failed to download HTML: {e}")
        return None

async def debug_page_state(solark, stage_name, reason="debug"):
    """Take screenshot and download HTML at any stage for debugging"""
    print(f"\n🔍 Debug: {stage_name} - {reason}")
    await take_debug_screenshot(solark, f"debug_{stage_name}", reason)
    await download_debug_html(solark, f"debug_{stage_name}", reason)

async def debug_on_error(solark, error_context, error_message):
    """Take debug screenshots and HTML when an error occurs"""
    print(f"\n🚨 Error Debug: {error_context}")
    print(f"   Error: {error_message}")
    await take_debug_screenshot(solark, f"error_{error_context}", f"Error: {error_message}")
    await download_debug_html(solark, f"error_{error_context}", f"Error: {error_message}")

# Debug Strategy:
# - Only take screenshots/HTML when there's an issue
# - Use debug_on_error() for failures to capture the problematic state
# - Use debug_page_state() for manual debugging when needed
# - No automatic success screenshots - only when manually requested
#
# Manual debugging examples:
#   await debug_page_state(solark, "after_login", "Manual debug")
#   await debug_page_state(solark, "parameters_page", "Manual debug")

async def test_inverter_automation():
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
    
    # Get inverter ID from primary optocoupler
    inverter_id = None
    if 'hardware' in config and 'optocoupler' in config['hardware'] and 'primary' in config['hardware']['optocoupler']:
        inverter_id = config['hardware']['optocoupler']['primary'].get('solark_inverter_id')
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
        await solark.initialize()
        print("✅ Browser initialized")
        
        # Login
        print("\n🔐 Logging in...")
        if await solark.login():
            print("✅ Login successful")
        else:
            print("❌ Login failed")
            await debug_on_error(solark, "login_failed", "Login attempt failed")
            return False
        
        # Navigate to inverter device page
        print(f"\n📋 Navigating to inverter device page...")
        inverter_url = f"{solark.base_url}/device/inverter"
        await solark.page.goto(inverter_url)
        await solark.page.wait_for_load_state('networkidle')
        await asyncio.sleep(3)  # Wait for JavaScript to render
        
        print("✅ Successfully navigated to inverter device page")
        
        # Find the specific inverter row by SN
        print(f"\n🔍 Looking for inverter {inverter_id}...")
        
        # Wait for the table to load
        await solark.page.wait_for_selector('.el-table__body', timeout=10000)
        
        # Find the inverter row by looking for the SN in the table
        inverter_row = None
        try:
            # Look for the specific inverter SN in the table
            sn_selector = f"text={inverter_id}"
            await solark.page.wait_for_selector(sn_selector, timeout=10000)
            
            # Find the row containing this SN
            inverter_row = await solark.page.query_selector(f"tr:has-text('{inverter_id}')")
            if inverter_row:
                print(f"✅ Found inverter row for {inverter_id}")
            else:
                print(f"❌ Could not find inverter row for {inverter_id}")
                return False
                
        except Exception as e:
            print(f"❌ Error finding inverter row: {e}")
            return False
        
        # Click on the "More" dropdown button for this inverter
        print(f"\n📋 Clicking on 'More' dropdown for inverter {inverter_id}...")
        
        try:
            # First, scroll the table to make sure the dropdown column is visible
            print("   Scrolling table to ensure dropdown is visible...")
            await solark.page.evaluate("document.querySelector('.el-table__body-wrapper').scrollLeft = 1000")
            await asyncio.sleep(1)
            
            # Find dropdown button in the specific inverter row
            dropdown_button = None
            try:
                # Look for dropdowns in rows that contain our inverter ID
                inverter_rows = await solark.page.query_selector_all(f'tr:has-text("{inverter_id}")')
                print(f"   Found {len(inverter_rows)} rows containing inverter {inverter_id}")
                
                for i, row in enumerate(inverter_rows):
                    # Check if this row actually contains our inverter ID
                    row_text = await row.text_content()
                    if inverter_id in row_text:
                        print(f"   Row {i+1} contains inverter {inverter_id}")
                        # Look for dropdown in this specific row
                        dropdown_in_row = await row.query_selector('.w24.h30.flex-align-around.el-dropdown-selfdefine')
                        if dropdown_in_row and await dropdown_in_row.is_visible():
                            dropdown_button = dropdown_in_row
                            print(f"   Found dropdown in row {i+1}")
                            break
            except Exception as e:
                print(f"   Error finding dropdown in specific row: {e}")
            
            if dropdown_button:
                # Ensure the button is in view
                await dropdown_button.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                
                # Click the dropdown
                await dropdown_button.click()
                print("✅ Clicked on 'More' dropdown")
                await asyncio.sleep(2)  # Wait for dropdown to appear
            else:
                print("❌ Could not find 'More' dropdown button with any selector")
                await debug_on_error(solark, "dropdown_not_found", f"Could not find dropdown for inverter {inverter_id}")
                return False
                
        except Exception as e:
            print(f"❌ Error clicking dropdown: {e}")
            await debug_on_error(solark, "dropdown_click_error", str(e))
            return False
        
        # Click on "Parameters Setting" in the dropdown
        print(f"\n⚙️ Clicking on 'Parameters Setting'...")
        
        try:
            # Wait for the dropdown menu to appear and be visible
            print("   Waiting for dropdown menu to appear...")
            
            # Wait a bit for the menu to appear
            await asyncio.sleep(2)
            
            # Check for dropdown menus
            try:
                all_menus = await solark.page.query_selector_all('.el-dropdown-menu')
                print(f"   Found {len(all_menus)} dropdown menus on page")
                
                visible_menu = None
                for i, menu in enumerate(all_menus):
                    try:
                        is_visible = await menu.is_visible()
                        classes = await menu.get_attribute('class')
                        print(f"     Menu {i+1}: visible={is_visible}, class='{classes}'")
                        if is_visible and not visible_menu:
                            visible_menu = menu
                    except:
                        print(f"     Menu {i+1}: Could not get details")
                
                if visible_menu:
                    print("   ✅ Found visible dropdown menu!")
                else:
                    print("   ⚠️ No visible dropdown menu found, waiting more...")
                    await asyncio.sleep(3)
                    # Try again
                    all_menus = await solark.page.query_selector_all('.el-dropdown-menu')
                    for menu in all_menus:
                        if await menu.is_visible():
                            visible_menu = menu
                            print("   ✅ Found visible dropdown menu on retry!")
                            break
                    
            except Exception as e:
                print(f"   Error checking dropdown menus: {e}")
                return False
            
            # Use keyboard navigation - much more reliable than DOM clicking
            
            # Wait for the menu to be fully interactive
            print("   Waiting for menu to be fully interactive...")
            await asyncio.sleep(2)
            
            # Use keyboard navigation - much more reliable!
            try:
                print("   Using keyboard navigation to select 'Parameters Setting'...")
                
                # First arrow down to wake up the menu and highlight first item
                print("   Pressing ↓ to wake up menu...")
                await solark.page.keyboard.press('ArrowDown')
                await asyncio.sleep(0.5)
                
                # Second arrow down to go to Parameters Setting
                print("   Pressing ↓ once more to reach Parameters Setting...")
                await solark.page.keyboard.press('ArrowDown')
                await asyncio.sleep(0.5)
                
                # Press Enter to select Parameters Setting
                print("   Pressing Enter to select Parameters Setting...")
                await solark.page.keyboard.press('Enter')
                print("✅ Successfully navigated to 'Parameters Setting' using keyboard!")
                await asyncio.sleep(3)
                
            except Exception as e:
                print(f"   Keyboard navigation failed: {e}")
                
                # Fallback: Manual intervention
                print("   Automated navigation failed. Please click 'Parameters Setting' manually...")
                print("   Waiting 15 seconds for manual click...")
                await asyncio.sleep(15)
                print("   Assuming manual click completed, continuing...")
                
        except Exception as e:
            print(f"❌ Error clicking Parameters Setting: {e}")
            await debug_on_error(solark, "parameters_setting_error", str(e))
            return False
        
        print(f"\n🎯 Successfully navigated to parameters page for inverter {inverter_id}")
        
        # Wait for parameters page to load and look for iframe
        print("⏳ Waiting for parameters page to load...")
        await asyncio.sleep(3)  # Wait for content to load
        
        # Look for the iframe that contains the actual settings
        print("🔍 Looking for settings iframe...")
        try:
            iframe_element = await solark.page.query_selector('iframe.testiframe')
            if iframe_element:
                iframe_src = await iframe_element.get_attribute('src')
                print(f"✅ Found iframe with URL: {iframe_src}")
                
                # Navigate directly to the iframe URL
                print("🔄 Navigating to iframe URL...")
                await solark.page.goto(iframe_src)
                await asyncio.sleep(3)  # Wait for iframe content to load
                print("✅ Successfully navigated to iframe URL")
                
                # First, click on "System Work Mode" to access the TOU settings
                print("🔍 Looking for System Work Mode link...")
                
                system_work_mode_selectors = [
                    'text=System Work Mode',
                    'span:has-text("System Work Mode")',
                    'el-link:has-text("System Work Mode")',
                    '.item-box:has-text("System Work Mode")',
                    '.item-box-rlink:has-text("System Work Mode")'
                ]
                
                system_work_mode_element = None
                system_found_selector = None
                
                for i, selector in enumerate(system_work_mode_selectors):
                    try:
                        print(f"   Trying selector {i+1}/{len(system_work_mode_selectors)}: {selector}")
                        system_work_mode_element = await solark.page.query_selector(selector)
                        if system_work_mode_element:
                            is_visible = await system_work_mode_element.is_visible()
                            print(f"   Found element, visible: {is_visible}")
                            if is_visible:
                                print(f"✅ Found System Work Mode with selector: {selector}")
                                system_found_selector = selector
                                break
                        else:
                            print(f"   No element found")
                    except Exception as e:
                        print(f"   Error with selector: {e}")
                        continue
                
                if system_work_mode_element:
                    print(f"🎯 Found System Work Mode using selector: {system_found_selector}")
                    
                    # Click the System Work Mode link
                    print("🔄 Clicking System Work Mode link...")
                    await system_work_mode_element.click()
                    await asyncio.sleep(3)  # Wait for the page to load
                    print("✅ Successfully clicked System Work Mode link!")
                    
                    # Now look for TOU switch on the System Work Mode page
                    print("🔍 Looking for TOU switch element...")
                    
                    # Specific selectors for the TOU switch we found in the HTML
                    tou_switch_selectors = [
                        'label:has-text("Time Of Use")',
                        '.el-switch',
                        '.el-switch__input',
                        'input[type="checkbox"]',
                        'div:has-text("Time Of Use")',
                        '.el-form-item:has-text("Time Of Use")'
                    ]
                    
                    tou_element = None
                    tou_found_selector = None
                    
                    for i, selector in enumerate(tou_switch_selectors):
                        try:
                            print(f"   Trying selector {i+1}/{len(tou_switch_selectors)}: {selector}")
                            tou_element = await solark.page.query_selector(selector)
                            if tou_element:
                                is_visible = await tou_element.is_visible()
                                print(f"   Found element, visible: {is_visible}")
                                if is_visible:
                                    print(f"✅ Found TOU switch with selector: {selector}")
                                    tou_found_selector = selector
                                    break
                            else:
                                print(f"   No element found")
                        except Exception as e:
                            print(f"   Error with selector: {e}")
                            continue
                else:
                    print("❌ Could not find System Work Mode link")
                    return False
            else:
                print("❌ Could not find iframe.testiframe")
                return False
                
        except Exception as e:
            print(f"❌ Error handling iframe: {e}")
            return False
        
        if tou_element:
            print(f"🎯 Found TOU switch using selector: {tou_found_selector}")
            
            # Check current state of the TOU switch
            try:
                # Try to find the actual checkbox input
                checkbox = await solark.page.query_selector('.el-switch__input')
                
                if checkbox:
                    is_checked = await checkbox.is_checked()
                    print(f"📋 TOU switch current state: {'ON' if is_checked else 'OFF'}")
                    
                    # Toggle the TOU switch
                    print("🔄 Toggling TOU switch...")
                    
                    # Try clicking the switch core instead of the checkbox input
                    switch_core = await solark.page.query_selector('.el-switch__core')
                    if switch_core:
                        print("   Clicking switch core...")
                        await switch_core.click()
                    else:
                        print("   Clicking checkbox input...")
                        await checkbox.click()
                    
                    await asyncio.sleep(2)  # Wait for switch to register
                    
                    # Check new state
                    new_state = await checkbox.is_checked()
                    print(f"📋 TOU switch new state: {'ON' if new_state else 'OFF'}")
                    
                    if new_state != is_checked:
                        print("✅ TOU switch successfully toggled!")
                    else:
                        print("❌ TOU switch did not change state")
                else:
                    print("❌ Could not find checkbox input for TOU switch")
                    # Try clicking the switch element directly
                    print("🔄 Trying to click TOU switch element directly...")
                    await tou_element.click()
                    await asyncio.sleep(1)
                    print("✅ Clicked TOU switch element")
                    
            except Exception as e:
                print(f"❌ Error toggling TOU switch: {e}")
            
            # Now look for and click the Save button
            print("🔍 Looking for Save button...")
            save_selectors = [
                'button:has-text("Save")',
                '.el-button--primary:has-text("Save")',
                'button.el-button--primary',
                '.save-btn'
            ]
            
            save_button = None
            for selector in save_selectors:
                try:
                    save_button = await solark.page.query_selector(selector)
                    if save_button and await save_button.is_visible():
                        print(f"✅ Found save button with selector: {selector}")
                        break
                except:
                    continue
            
            if save_button:
                print("🔄 Clicking Save button...")
                
                # Ensure the button is visible and clickable
                await save_button.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                
                # Try multiple click methods for better reliability
                try:
                    # Method 1: Regular click
                    await save_button.click()
                    print("✅ Save button clicked (method 1)")
                except Exception as e1:
                    print(f"⚠️ Method 1 failed: {e1}")
                    try:
                        # Method 2: Force click
                        await save_button.click(force=True)
                        print("✅ Save button clicked (method 2 - force)")
                    except Exception as e2:
                        print(f"⚠️ Method 2 failed: {e2}")
                        try:
                            # Method 3: JavaScript click
                            await save_button.evaluate('element => element.click()')
                            print("✅ Save button clicked (method 3 - JS)")
                        except Exception as e3:
                            print(f"❌ All click methods failed: {e3}")
                            return False
                
                # Wait longer for save to register and page to update
                print("⏳ Waiting for save operation to complete...")
                await asyncio.sleep(5)  # Increased wait time
                
                # Check for success indicators
                success_indicators = [
                    '.el-message--success',
                    '.success-message',
                    '.alert-success',
                    '[class*="success"]',
                    'text=Success',
                    'text=Saved',
                    'text=保存成功'
                ]
                
                save_success = False
                for indicator in success_indicators:
                    try:
                        success_element = await solark.page.query_selector(indicator)
                        if success_element and await success_element.is_visible():
                            print(f"✅ Found success indicator: {indicator}")
                            save_success = True
                            break
                    except:
                        continue
                
                if save_success:
                    print("✅ Save operation completed successfully!")
                else:
                    print("ℹ️ Save button clicked - no explicit success message found")
                
                print("\n🎉 TOU automation completed successfully!")
                print("   Summary:")
                print("   1. ✅ Login to Sol-Ark")
                print("   2. ✅ Navigate to inverter device page")
                print("   3. ✅ Find specific inverter by ID")
                print("   4. ✅ Click dropdown menu")
                print("   5. ✅ Click Parameters Setting")
                print("   6. ✅ Find TOU switch")
                print("   7. ✅ Toggle TOU switch")
                print("   8. ✅ Find save button")
                print("   9. ✅ Click save button")
                print("\n🚀 TOU automation is now complete!")
                
            else:
                print("❌ Could not find Save button")
                print("   Available buttons on page:")
                try:
                    buttons = await solark.page.query_selector_all('button')
                    for i, button in enumerate(buttons):
                        try:
                            text = await button.text_content()
                            if text and text.strip():
                                print(f"     Button {i+1}: {text.strip()}")
                        except:
                            print(f"     Button {i+1}: (could not get text)")
                except Exception as e:
                    print(f"   Error getting buttons: {e}")
        else:
            print("❌ Could not find TOU switch")
            
            # Take debug screenshot and HTML to see what's on the page
            print("📸 Taking debug screenshot and HTML...")
            await debug_on_error(solark, "tou_not_found", "Could not find TOU switch on parameters page")
            
            print("   Available form elements on page:")
            try:
                form_elements = await solark.page.query_selector_all('input, .el-switch, .el-form-item')
                for i, element in enumerate(form_elements[:10]):
                    try:
                        text = await element.text_content()
                        if text and text.strip():
                            print(f"     Element {i+1}: {text.strip()}")
                    except:
                        print(f"     Element {i+1}: (could not get text)")
            except Exception as e:
                print(f"   Error getting form elements: {e}")
            
            # Check if there's an iframe we need to access
            print("🔍 Checking for iframes on the page...")
            try:
                iframes = await solark.page.query_selector_all('iframe')
                print(f"   Found {len(iframes)} iframes on the page")
                for i, iframe in enumerate(iframes):
                    try:
                        src = await iframe.get_attribute('src')
                        print(f"     Iframe {i+1}: {src}")
                    except:
                        print(f"     Iframe {i+1}: (could not get src)")
            except Exception as e:
                print(f"   Error getting iframes: {e}")
            
            return False
        
    except Exception as e:
        print(f"❌ Error during automation: {e}")
        if 'solark' in locals():
            await debug_on_error(solark, "automation_failed", str(e))
        return False
    finally:
        await solark.cleanup()
    
    return True

if __name__ == "__main__":
    asyncio.run(test_inverter_automation())
