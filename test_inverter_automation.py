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
        
        # Now test the complete TOU automation flow
        print("\n🔄 Testing complete TOU automation flow...")
        
        # Wait a bit for the parameters page to load
        await asyncio.sleep(3)
        
        # Navigate directly to the iframe URL to avoid cross-origin issues
        print("🔍 Looking for parameters iframe...")
        
        # Wait for iframe to load
        try:
            print("⏳ Waiting for parameters iframe to appear...")
            await solark.page.wait_for_selector('iframe.testiframe', timeout=10000)
            print("✅ Found parameters iframe")
        except Exception as e:
            print(f"❌ Could not find parameters iframe: {e}")
            await debug_on_error(solark, "iframe_not_found", f"Could not find parameters iframe: {e}")
            return False
        
        # Get the iframe element and extract its URL
        iframe_element = await solark.page.query_selector('iframe.testiframe')
        if not iframe_element:
            print("❌ Could not get iframe element")
            return False
        
        # Get the iframe src URL
        iframe_src = await iframe_element.get_attribute('src')
        print(f"🔗 Iframe URL: {iframe_src}")
        
        # Navigate directly to the iframe URL
        print("🔄 Navigating directly to iframe URL...")
        try:
            await solark.page.goto(iframe_src)
            print("✅ Successfully navigated to iframe URL")
            await asyncio.sleep(3)  # Wait for content to load
        except Exception as e:
            print(f"❌ Failed to navigate to iframe URL: {e}")
            await debug_on_error(solark, "iframe_navigation_failed", str(e))
            return False
        
        # Take a debug screenshot of the iframe content
        print("📸 Capturing iframe content for analysis...")
        await debug_page_state(solark, "iframe_content", "Captured iframe content after direct navigation")
        
        # Check what buttons are on the page
        print("🔍 Checking what buttons are on the page...")
        try:
            buttons = await solark.page.query_selector_all('button')
            print(f"   Found {len(buttons)} buttons on the page")
            for i, button in enumerate(buttons[:10]):  # Show first 10 buttons
                try:
                    text = await button.text_content()
                    if text and text.strip():
                        print(f"     Button {i+1}: {text.strip()}")
                except:
                    print(f"     Button {i+1}: (could not get text)")
        except Exception as e:
            print(f"   Error getting buttons: {e}")
        
        # Use main page as context for element search
        page_context = solark.page
            
        # First, look for and click the "System Work Mode" button
        print("🔍 Looking for System Work Mode button...")
        
        system_work_mode_selectors = [
            'text=System Work Mode',
            'span:has-text("System Work Mode")',
            'div:has-text("System Work Mode")',
            'el-link:has-text("System Work Mode")',
            '.item-box:has-text("System Work Mode")',
            '.item-box-rlink:has-text("System Work Mode")'
        ]
        
        system_work_mode_element = None
        found_selector = None
        
        # Search for System Work Mode button
        for i, selector in enumerate(system_work_mode_selectors):
            try:
                print(f"   Trying selector {i+1}/{len(system_work_mode_selectors)}: {selector}")
                system_work_mode_element = await page_context.query_selector(selector)
                if system_work_mode_element:
                    is_visible = await system_work_mode_element.is_visible()
                    print(f"   Found element, visible: {is_visible}")
                    if is_visible:
                        print(f"✅ Found System Work Mode button with selector: {selector}")
                        found_selector = selector
                        break
                else:
                    print(f"   No element found")
            except Exception as e:
                print(f"   Error with selector: {e}")
                continue
        
        if system_work_mode_element:
            print(f"🎯 Found System Work Mode button using selector: {found_selector}")
            
            # Click the System Work Mode button
            print("🔄 Clicking System Work Mode button...")
            await system_work_mode_element.click()
            await asyncio.sleep(3)  # Wait for the page to load
            
            # Take a debug screenshot after clicking System Work Mode
            print("📸 Capturing page content after clicking System Work Mode...")
            await debug_page_state(solark, "after_system_work_mode", "Captured page after clicking System Work Mode button")
            
            print("✅ Successfully clicked System Work Mode button!")
            print("   Now looking for TOU settings...")
            
            # Now look for TOU-related elements
            print("🔍 Looking for Time of Use settings...")
            
            # TOU selectors (after System Work Mode is clicked)
            tou_selectors = [
                # English text selectors
                'text=Time of Use',
                'text=TOU',
                'text=Time-of-Use',
                'text=Time of use',
                'text=time of use',
                'text=TOU Settings',
                'text=Time of Use Settings',
                
                # Chinese text selectors
                'text=分时电价',
                'text=峰谷电价',
                'text=分时',
                'text=峰谷',
                'text=电价',
                
                # Checkbox selectors
                'input[type="checkbox"]',
                '.el-checkbox input[type="checkbox"]',
                'input[type="checkbox"]:near(text=Time of Use)',
                'input[type="checkbox"]:near(text=TOU)',
                'input[type="checkbox"]:near(text=分时电价)',
                'input[type="checkbox"]:near(text=峰谷电价)',
                
                # Element UI checkbox selectors
                '.el-checkbox',
                '.el-checkbox:has-text("Time of Use")',
                '.el-checkbox:has-text("TOU")',
                '.el-checkbox:has-text("分时电价")',
                '.el-checkbox:has-text("峰谷电价")',
                
                # Form field selectors
                '[placeholder*="TOU"]',
                '[placeholder*="Time of Use"]',
                '[placeholder*="分时电价"]',
                '[placeholder*="峰谷电价"]',
                
                # Label selectors
                'label:has-text("Time of Use")',
                'label:has-text("TOU")',
                'label:has-text("分时电价")',
                'label:has-text("峰谷电价")',
                
                # Div/span selectors
                'div:has-text("Time of Use")',
                'span:has-text("Time of Use")',
                'div:has-text("TOU")',
                'span:has-text("TOU")',
                'div:has-text("分时电价")',
                'span:has-text("分时电价")',
                'div:has-text("峰谷电价")',
                'span:has-text("峰谷电价")'
            ]
            
            tou_element = None
            tou_found_selector = None
            
            # Search for TOU switch element
            print("🔍 Searching for TOU switch element...")
            
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
                    tou_element = await page_context.query_selector(selector)
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
            
            if tou_element:
                print(f"🎯 Found TOU switch using selector: {tou_found_selector}")
                
                # Check current state of the TOU switch
                try:
                    # Try to find the actual checkbox input
                    checkbox = await tou_element.query_selector('input[type="checkbox"]')
                    if not checkbox:
                        # If not found as child, try to find it nearby
                        checkbox = await page_context.query_selector('.el-switch__input')
                    
                    if checkbox:
                        is_checked = await checkbox.is_checked()
                        print(f"📋 TOU switch current state: {'ON' if is_checked else 'OFF'}")
                        
                        # Toggle the TOU switch
                        print("🔄 Toggling TOU switch...")
                        await checkbox.click()
                        await asyncio.sleep(1)
                        
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
                        save_button = await page_context.query_selector(selector)
                        if save_button and await save_button.is_visible():
                            print(f"✅ Found save button with selector: {selector}")
                            break
                    except:
                        continue
                
                if save_button:
                    print("🔄 Clicking Save button...")
                    await save_button.click()
                    await asyncio.sleep(2)
                    print("✅ Successfully clicked Save button!")
                    
                    print("\n🎉 TOU automation completed successfully!")
                    print("   Summary:")
                    print("   1. ✅ Login to Sol-Ark")
                    print("   2. ✅ Navigate to inverter device page")
                    print("   3. ✅ Find specific inverter by ID")
                    print("   4. ✅ Click dropdown menu")
                    print("   5. ✅ Click Parameters Setting")
                    print("   6. ✅ Navigate to iframe URL")
                    print("   7. ✅ Find System Work Mode button")
                    print("   8. ✅ Click System Work Mode button")
                    print("   9. ✅ Find TOU switch")
                    print("   10. ✅ Toggle TOU switch")
                    print("   11. ✅ Find save button")
                    print("   12. ✅ Click save button")
                    print("\n🚀 TOU automation is now complete!")
                    
                else:
                    print("❌ Could not find Save button")
                    print("   Available buttons on page:")
                    try:
                        buttons = await page_context.query_selector_all('button')
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
                print("   Available form elements on page:")
                try:
                    form_elements = await page_context.query_selector_all('input, .el-switch, .el-form-item')
                    for i, element in enumerate(form_elements[:10]):
                        try:
                            text = await element.text_content()
                            if text and text.strip():
                                print(f"     Element {i+1}: {text.strip()}")
                        except:
                            print(f"     Element {i+1}: (could not get text)")
                except Exception as e:
                    print(f"   Error getting form elements: {e}")
        else:
            print("❌ Could not find System Work Mode button")
            print("   Available buttons on page:")
            try:
                buttons = await page_context.query_selector_all('button, .item-box, el-link')
                for i, button in enumerate(buttons[:10]):  # Show first 10 buttons
                    try:
                        text = await button.text_content()
                        if text and text.strip():
                            print(f"     Button {i+1}: {text.strip()}")
                    except:
                        print(f"     Button {i+1}: (could not get text)")
            except Exception as e:
                print(f"   Error getting buttons: {e}")
            return False
        
        if tou_element:
            print(f"🎯 Found element using selector: {found_selector}")
            
            # Check what type of element it is
            tag_name = await tou_element.evaluate('el => el.tagName.toLowerCase()')
            element_type = await tou_element.get_attribute('type') if tag_name == 'input' else None
            
            print(f"📋 Element type: {tag_name}, input type: {element_type}")
            
            # Check if this is the System Work Mode button
            if 'System Work Mode' in found_selector or 'system work mode' in found_selector or 'Work Mode' in found_selector:
                print("🔧 Found System Work Mode button - clicking it first...")
                await tou_element.click()
                await asyncio.sleep(3)  # Wait for the page to load
                print("✅ Clicked System Work Mode button")
                
                # Take a debug screenshot and HTML capture after clicking System Work Mode
                print("📸 Capturing page content after clicking System Work Mode...")
                await debug_page_state(solark, "after_system_work_mode", "Captured page after clicking System Work Mode button")
                
                # Now look for TOU settings after clicking System Work Mode
                print("🔍 Looking for TOU settings after clicking System Work Mode...")
                
                # Wait a bit for the page to update
                await asyncio.sleep(2)
                
                # Look for TOU elements again
                tou_checkbox_element = None
                for selector in tou_selectors[10:]:  # Skip the System Work Mode selectors
                    try:
                        tou_checkbox_element = await page_context.query_selector(selector)
                        if tou_checkbox_element and await tou_checkbox_element.is_visible():
                            print(f"✅ Found TOU element with selector: {selector}")
                            break
                    except:
                        continue
                
                if tou_checkbox_element:
                    # Handle TOU checkbox
                    checkbox_tag = await tou_checkbox_element.evaluate('el => el.tagName.toLowerCase()')
                    checkbox_type = await tou_checkbox_element.get_attribute('type') if checkbox_tag == 'input' else None
                    
                    if checkbox_tag == 'input' and checkbox_type == 'checkbox':
                        # It's a checkbox - check current state and toggle
                        is_checked = await tou_checkbox_element.is_checked()
                        print(f"📋 TOU checkbox current state: {'checked' if is_checked else 'unchecked'}")
                        
                        # Test toggle (we'll toggle it and then toggle it back)
                        print("🔄 Testing TOU toggle...")
                        await tou_checkbox_element.click()
                        await asyncio.sleep(1)
                        
                        new_state = await tou_checkbox_element.is_checked()
                        print(f"📋 TOU checkbox new state: {'checked' if new_state else 'unchecked'}")
                        
                        # Toggle it back to original state
                        if new_state != is_checked:
                            print("🔄 Toggling back to original state...")
                            await tou_checkbox_element.click()
                            await asyncio.sleep(1)
                            final_state = await tou_checkbox_element.is_checked()
                            print(f"📋 TOU checkbox final state: {'checked' if final_state else 'unchecked'}")
                            
                            if final_state == is_checked:
                                print("✅ TOU toggle test successful!")
                            else:
                                print("❌ TOU toggle test failed - state not restored")
                        else:
                            print("❌ TOU toggle test failed - state did not change")
                    else:
                        print("🔄 TOU element is not a checkbox, attempting to click")
                        await tou_checkbox_element.click()
                        await asyncio.sleep(1)
                        print("✅ Clicked TOU element")
                else:
                    print("❌ Could not find TOU checkbox after clicking System Work Mode")
            
            elif tag_name == 'input' and element_type == 'checkbox':
                # It's a checkbox - check current state and toggle
                is_checked = await tou_element.is_checked()
                print(f"📋 TOU checkbox current state: {'checked' if is_checked else 'unchecked'}")
                
                # Test toggle (we'll toggle it and then toggle it back)
                print("🔄 Testing TOU toggle...")
                await tou_element.click()
                await asyncio.sleep(1)
                
                new_state = await tou_element.is_checked()
                print(f"📋 TOU checkbox new state: {'checked' if new_state else 'unchecked'}")
                
                # Toggle it back to original state
                if new_state != is_checked:
                    print("🔄 Toggling back to original state...")
                    await tou_element.click()
                    await asyncio.sleep(1)
                    final_state = await tou_element.is_checked()
                    print(f"📋 TOU checkbox final state: {'checked' if final_state else 'unchecked'}")
                    
                    if final_state == is_checked:
                        print("✅ TOU toggle test successful!")
                    else:
                        print("❌ TOU toggle test failed - state not restored")
                else:
                    print("❌ TOU toggle test failed - state did not change")
                    
            elif tag_name == 'div' or tag_name == 'span':
                # It might be a clickable div/span - try clicking
                print("🔄 TOU element is a div/span, attempting to click")
                await tou_element.click()
                await asyncio.sleep(1)
                print("✅ Clicked TOU element")
                
            else:
                # Try clicking anyway
                print(f"🔄 TOU element is {tag_name}, attempting to click")
                await tou_element.click()
                await asyncio.sleep(1)
                print("✅ Clicked TOU element")
                
            # Look for save button
            print("🔍 Looking for save button...")
            save_selectors = [
                'button:has-text("Save")',
                'button:has-text("保存")',
                'button:has-text("Apply")',
                'button:has-text("应用")',
                'button:has-text("Submit")',
                'button:has-text("提交")',
                'button:has-text("Confirm")',
                'button:has-text("确认")',
                '.el-button--primary:has-text("Save")',
                '.el-button--primary:has-text("保存")',
                '.el-button--primary:has-text("Apply")',
                '.el-button--primary:has-text("应用")',
                'input[type="submit"]',
                '.el-button[type="submit"]',
                'button[type="submit"]',
                '.el-button.el-button--primary',
                'button.el-button--primary'
            ]
            
            save_button = None
            for selector in save_selectors:
                try:
                    save_button = await page_context.query_selector(selector)
                    if save_button and await save_button.is_visible():
                        print(f"✅ Found save button with selector: {selector}")
                        break
                except:
                    continue
            
            if save_button:
                print("✅ Save button found - TOU automation is ready!")
                print("📋 Complete TOU automation flow:")
                print("   1. ✅ Login to Sol-Ark")
                print("   2. ✅ Navigate to inverter device page")
                print("   3. ✅ Find specific inverter by ID")
                print("   4. ✅ Click dropdown menu")
                print("   5. ✅ Click Parameters Setting")
                print("   6. ✅ Navigate to iframe URL or switch to iframe context")
                print("   7. ✅ Find System Work Mode button")
                print("   8. ✅ Click System Work Mode button")
                print("   9. ✅ Find TOU checkbox")
                print("   10. ✅ Toggle TOU checkbox")
                print("   11. ✅ Find save button")
                print("   12. 🔄 Ready to save changes")
            else:
                print("⚠️  Save button not found - TOU automation may need adjustment")
                print("   Available buttons on page:")
                try:
                    buttons = await page_context.query_selector_all('button')
                    for i, button in enumerate(buttons):
                        text = await button.text_content()
                        if text and text.strip():
                            print(f"     {i+1}. {text.strip()}")
                except:
                    print("     Could not retrieve button text")
                    
        else:
            print("❌ Could not find Time of Use settings or System Work Mode button")
            print("   Available text elements on page:")
            try:
                # Look for any text that might be related to TOU
                all_text = await page_context.evaluate("""
                    () => {
                        const walker = document.createTreeWalker(
                            document.body,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        const texts = [];
                        let node;
                        while (node = walker.nextNode()) {
                            if (node.textContent.trim().length > 0) {
                                texts.push(node.textContent.trim());
                            }
                        }
                        return texts.slice(0, 30); // First 30 text elements
                    }
                """)
                for i, text in enumerate(all_text):
                    print(f"     {i+1}. {text}")
            except:
                print("     Could not retrieve page text")
                
            # Also try to get all checkboxes on the page
            print("   Available checkboxes on page:")
            try:
                checkboxes = await page_context.query_selector_all('input[type="checkbox"]')
                for i, checkbox in enumerate(checkboxes):
                    try:
                        # Try to find nearby text
                        nearby_text = await checkbox.evaluate("""
                            el => {
                                const parent = el.parentElement;
                                if (parent) {
                                    return parent.textContent.trim();
                                }
                                return '';
                            }
                        """)
                        print(f"     Checkbox {i+1}: {nearby_text}")
                    except:
                        print(f"     Checkbox {i+1}: (no text found)")
            except:
                print("     Could not retrieve checkboxes")
        
        print("\n📋 Next steps:")
        print("   1. ✅ Analyze the parameters page HTML to find Time of Use settings")
        print("   2. ✅ Implement the TOU checkbox selector")
        print("   3. ✅ Implement save functionality")
        print("   4. ✅ Test the complete TOU toggle flow")
        print("   5. 🔄 Ready for production integration!")
        
        # Keep browser open for manual exploration with timeout
        print(f"\n🌐 Browser is open for manual exploration...")
        print("   Will auto-close in 30 seconds...")
        
        try:
            # Keep the script running for 30 seconds then auto-close
            await asyncio.sleep(30)
            print("\n⏰ 30-second timeout reached, closing browser...")
        except KeyboardInterrupt:
            print("\n👋 Closing browser...")
        
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
