#!/usr/bin/env python3
"""
Debug script for Sol-Ark login process

This script helps debug the login process by showing what elements are found
and allowing step-by-step interaction with the login page.
"""

import asyncio
import logging
from solark_cloud import SolArkCloud

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def debug_login():
    """Debug the login process step by step"""
    print("Sol-Ark Login Debug")
    print("=" * 40)
    
    solark = SolArkCloud()
    
    try:
        # Initialize browser
        print("Initializing browser...")
        if not await solark.initialize():
            print("ERROR: Failed to initialize browser")
            return False
        print("Browser initialized successfully")
        
        # Navigate to login page
        print(f"Navigating to: {solark.base_url}")
        await solark.page.goto(solark.base_url)
        await solark.page.wait_for_load_state('networkidle')
        
        # Wait for JavaScript to load and form elements to be ready
        print("Waiting for login form to load...")
        try:
            await solark.page.wait_for_selector('input[placeholder="Please input your E-mail"]', timeout=15000)
            print("Login form loaded successfully")
        except Exception as e:
            print(f"Warning: Login form may not be fully loaded: {e}")
        
        # Save the page
        await solark._save_page_to_cache("debug_login.html")
        print("Page saved to solark_cache/debug_login.html")
        
        # Get page title and URL
        title = await solark.page.title()
        url = solark.page.url
        print(f"Page title: {title}")
        print(f"Current URL: {url}")
        
        # Look for login form elements
        print("\nLooking for login form elements...")
        
        # Check for email/username inputs
        email_inputs = await solark.page.query_selector_all('input[type="email"], input[type="text"], input[placeholder*="email"], input[placeholder*="Email"], input[placeholder*="E-mail"]')
        print(f"Found {len(email_inputs)} email/username input fields:")
        for i, input_elem in enumerate(email_inputs):
            placeholder = await input_elem.get_attribute('placeholder')
            name = await input_elem.get_attribute('name')
            id_attr = await input_elem.get_attribute('id')
            print(f"  {i+1}. placeholder='{placeholder}', name='{name}', id='{id_attr}'")
        
        # Check for password inputs
        password_inputs = await solark.page.query_selector_all('input[type="password"]')
        print(f"\nFound {len(password_inputs)} password input fields:")
        for i, input_elem in enumerate(password_inputs):
            placeholder = await input_elem.get_attribute('placeholder')
            name = await input_elem.get_attribute('name')
            id_attr = await input_elem.get_attribute('id')
            print(f"  {i+1}. placeholder='{placeholder}', name='{name}', id='{id_attr}'")
        
        # Check for checkboxes
        checkboxes = await solark.page.query_selector_all('input[type="checkbox"]')
        print(f"\nFound {len(checkboxes)} checkboxes:")
        for i, checkbox in enumerate(checkboxes):
            name = await checkbox.get_attribute('name')
            id_attr = await checkbox.get_attribute('id')
            value = await checkbox.get_attribute('value')
            print(f"  {i+1}. name='{name}', id='{id_attr}', value='{value}'")
        
        # Check for buttons
        buttons = await solark.page.query_selector_all('button, input[type="submit"]')
        print(f"\nFound {len(buttons)} buttons:")
        for i, button in enumerate(buttons):
            text = await button.text_content()
            button_type = await button.get_attribute('type')
            class_name = await button.get_attribute('class')
            disabled = await button.get_attribute('disabled')
            print(f"  {i+1}. text='{text}', type='{button_type}', class='{class_name}', disabled='{disabled}'")
        
        # Try to fill the form
        print("\nAttempting to fill login form...")
        
        # Fill email field
        if email_inputs:
            email_input = email_inputs[0]  # Use first email input
            print(f"Filling email field: {await email_input.get_attribute('placeholder')}")
            await email_input.fill(solark.username)
            print("Email filled successfully")
        else:
            print("ERROR: No email input found")
            return False
        
        # Fill password field
        if password_inputs:
            password_input = password_inputs[0]  # Use first password input
            print(f"Filling password field: {await password_input.get_attribute('placeholder')}")
            await password_input.fill(solark.password)
            print("Password filled successfully")
        else:
            print("ERROR: No password input found")
            return False
        
        # Check terms checkbox if present
        if checkboxes:
            terms_checkbox = None
            for checkbox in checkboxes:
                name = await checkbox.get_attribute('name')
                if name == 'type' or 'agreement' in (await checkbox.get_attribute('class') or '').lower():
                    terms_checkbox = checkbox
                    break
            
            if terms_checkbox:
                print("Checking terms agreement checkbox...")
                await terms_checkbox.check()
                print("Terms checkbox checked")
            else:
                print("No terms checkbox found")
        
        # Look for login button
        login_button = None
        for button in buttons:
            text = await button.text_content()
            if text and ('log in' in text.lower() or 'login' in text.lower() or 'sign in' in text.lower()):
                login_button = button
                break
        
        if login_button:
            print(f"Found login button: '{await login_button.text_content()}'")
            disabled = await login_button.get_attribute('disabled')
            print(f"Button disabled: {disabled}")
            
            if not disabled:
                print("Clicking login button...")
                await login_button.click()
                print("Login button clicked")
                
                # Wait for navigation
                try:
                    await solark.page.wait_for_load_state('networkidle', timeout=10000)
                    new_url = solark.page.url
                    print(f"Navigation completed. New URL: {new_url}")
                    
                    # Save the result page
                    await solark._save_page_to_cache("debug_after_login.html")
                    print("Post-login page saved to solark_cache/debug_after_login.html")
                    
                    # Check if login was successful
                    if 'login' not in new_url.lower():
                        print("SUCCESS: Login appears to have worked!")
                        return True
                    else:
                        print("WARNING: Still on login page - login may have failed")
                        return False
                        
                except Exception as e:
                    print(f"Navigation timeout or error: {e}")
                    return False
            else:
                print("ERROR: Login button is disabled")
                return False
        else:
            print("ERROR: No login button found")
            return False
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        # Keep browser open for a moment so you can see what happened
        print("\nKeeping browser open for 10 seconds so you can see the result...")
        await asyncio.sleep(10)
        await solark.cleanup()

if __name__ == "__main__":
    asyncio.run(debug_login())
