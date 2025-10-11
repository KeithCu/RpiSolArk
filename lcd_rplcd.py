#!/usr/bin/env python3
"""
LCD1602 Display Controller using RPLCD Library
Replaces the custom LCD1602.py with the more robust RPLCD library
"""

import time
import sys
import subprocess
from RPLCD.i2c import CharLCD

class LCD1602_RPLCD:
    def __init__(self, address=0x27, port=1, cols=16, rows=2, backlight_enabled=True, auto_detect=True):
        """
        Initialize LCD using RPLCD library
        
        Args:
            address (int): I2C address (0x27 or 0x3f)
            port (int): I2C port (usually 1 on Raspberry Pi)
            cols (int): Number of columns (16 for 1602)
            rows (int): Number of rows (2 for 1602)
            backlight_enabled (bool): Initial backlight state
            auto_detect (bool): Auto-detect I2C address if specified address fails
        """
        self.address = address
        self.port = port
        self.cols = cols
        self.rows = rows
        self.backlight_enabled = backlight_enabled
        
        # Try to initialize with specified address, fallback to auto-detection
        if auto_detect and address is not None:
            self.address = self._detect_i2c_address(address, port)
            print(f"Auto-detected I2C address: 0x{self.address:02x}")
        
        # Initialize the LCD with compatibility mode for better stability
        print(f"Initializing LCD with address: 0x{self.address:02x}, port: {port}")
        self.lcd = CharLCD(
            i2c_expander='PCF8574',
            address=self.address,
            port=port,
            cols=cols,
            rows=rows,
            dotsize=8,
            charmap='A02',
            auto_linebreaks=True,
            backlight_enabled=backlight_enabled,
        )
        print("LCD initialized successfully")
    
    def _detect_i2c_address(self, preferred_address, port):
        """Detect I2C address, similar to the old LCD1602.py logic"""
        try:
            # Scan for I2C devices
            cmd = f"i2cdetect -y {port} | awk 'NR>1 {{$1=\"\";print}}'"
            result = subprocess.check_output(cmd, shell=True).decode()
            result = result.replace("\n", "").replace(" --", "")
            i2c_list = result.split(' ')
            
            # Convert to hex strings for comparison
            i2c_hex_list = [hex(int(addr, 16))[2:] for addr in i2c_list if addr.strip()]
            
            # Try preferred address first
            preferred_hex = hex(preferred_address)[2:]
            if preferred_hex in i2c_hex_list:
                return preferred_address
            
            # Try common LCD addresses
            for addr in [0x27, 0x3f]:
                addr_hex = hex(addr)[2:]
                if addr_hex in i2c_hex_list:
                    return addr
            
            # If no LCD found, return preferred address (will fail gracefully)
            return preferred_address
            
        except Exception:
            # If detection fails, return preferred address
            return preferred_address
        
    def clear(self):
        """Clear the LCD display"""
        self.lcd.clear()
        
    def write(self, x, y, text):
        """
        Write text to LCD at specified position
        
        Args:
            x (int): Column position (0-15)
            y (int): Row position (0-1)
            text (str): Text to display
        """
        # Clamp coordinates to valid ranges
        x = max(0, min(x, self.cols - 1))
        y = max(0, min(y, self.rows - 1))
        
        # Set cursor position
        self.lcd.cursor_pos = (y, x)
        # Write the text
        self.lcd.write_string(text)
        
    def write_string(self, text):
        """Write string starting at current cursor position"""
        self.lcd.write_string(text)
        
    def set_cursor(self, x, y):
        """Set cursor position"""
        x = max(0, min(x, self.cols - 1))
        y = max(0, min(y, self.rows - 1))
        self.lcd.cursor_pos = (y, x)
        
    def cursor_on(self):
        """Turn on cursor"""
        self.lcd.cursor_mode = 'line'
        
    def cursor_off(self):
        """Turn off cursor"""
        self.lcd.cursor_mode = 'hide'
        
    def blink_on(self):
        """Turn on cursor blinking"""
        self.lcd.cursor_mode = 'blink'
        
    def blink_off(self):
        """Turn off cursor blinking"""
        self.lcd.cursor_mode = 'hide'
        
    def set_backlight(self, state):
        """
        Turn backlight on or off
        
        Args:
            state (bool): True to turn on, False to turn off
        """
        self.lcd.backlight_enabled = state
        self.backlight_enabled = state
        
    def backlight_on(self):
        """Turn on the backlight"""
        self.set_backlight(True)
        
    def backlight_off(self):
        """Turn off the backlight"""
        self.set_backlight(False)
        
    def toggle_backlight(self):
        """Toggle backlight state"""
        self.set_backlight(not self.backlight_enabled)
        
    def create_char(self, location, pattern):
        """
        Create a custom character
        
        Args:
            location (int): Character location (0-7)
            pattern (list): 8-byte pattern for the character
        """
        self.lcd.create_char(location, pattern)
        
    def write_char(self, char):
        """Write a single character at current cursor position"""
        self.lcd.write_string(char)
        
    def display_num(self, x, y, num):
        """Display a number at specified position"""
        self.write(x, y, str(num))
        
    def close(self):
        """Close the LCD connection"""
        self.lcd.close()

def loop():
    """Original counter demo"""
    lcd = LCD1602_RPLCD()
    count = 0
    try:
        while True:
            lcd.clear()
            lcd.write(0, 0, '  Hello World!  ')
            lcd.write(0, 1, '  Counter: ' + str(count))
            time.sleep(1)
            count += 1
    except KeyboardInterrupt:
        lcd.clear()
        lcd.close()

def backlight_demo():
    """Demonstrate backlight control functionality"""
    print("Backlight Demo - Press Ctrl+C to exit")
    lcd = LCD1602_RPLCD()
    
    try:
        lcd.clear()
        lcd.write(0, 0, 'Backlight Demo')
        lcd.write(0, 1, 'Press Ctrl+C')
        time.sleep(2)
        
        while True:
            # Turn on backlight
            lcd.backlight_on()
            lcd.write(0, 1, 'Backlight: ON ')
            time.sleep(2)
            
            # Turn off backlight
            lcd.backlight_off()
            lcd.write(0, 1, 'Backlight: OFF')
            time.sleep(2)
            
    except KeyboardInterrupt:
        lcd.backlight_on()  # Turn backlight on before exiting
        lcd.clear()
        lcd.close()

def cursor_demo():
    """Demonstrate cursor control functionality"""
    print("Cursor Demo - Press Ctrl+C to exit")
    lcd = LCD1602_RPLCD()
    
    try:
        lcd.clear()
        lcd.write(0, 0, 'Cursor Demo')
        
        # Show different cursor modes
        modes = [
            ('hide', 'No Cursor'),
            ('line', 'Line Cursor'),
            ('blink', 'Blink Cursor')
        ]
        
        while True:
            for mode, description in modes:
                lcd.cursor_mode = mode
                lcd.write(0, 1, description)
                time.sleep(2)
                
    except KeyboardInterrupt:
        lcd.cursor_off()
        lcd.clear()
        lcd.close()

def custom_char_demo():
    """Demonstrate custom character creation"""
    print("Custom Character Demo - Press Ctrl+C to exit")
    lcd = LCD1602_RPLCD()
    
    try:
        # Create custom characters
        # Heart symbol
        heart = [
            0b00000,
            0b01010,
            0b11111,
            0b11111,
            0b01110,
            0b00100,
            0b00000,
            0b00000
        ]
        
        # Smiley face
        smiley = [
            0b00000,
            0b00000,
            0b01010,
            0b00000,
            0b00000,
            0b10001,
            0b01110,
            0b00000
        ]
        
        lcd.create_char(0, heart)
        lcd.create_char(1, smiley)
        
        lcd.clear()
        lcd.write(0, 0, 'Custom Chars:')
        lcd.write(0, 1, '\x00 \x01 \x00 \x01')
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        lcd.clear()
        lcd.close()

if __name__ == '__main__':
    print('RPLCD LCD1602 Program starting...')
    
    if len(sys.argv) > 1:
        demo = sys.argv[1].lower()
        if demo == 'backlight':
            backlight_demo()
        elif demo == 'cursor':
            cursor_demo()
        elif demo == 'custom':
            custom_char_demo()
        else:
            print("Unknown demo. Available demos: backlight, cursor, custom")
    else:
        print("Usage: python lcd_rplcd.py [demo]")
        print("  No argument: Run counter demo")
        print("  'backlight': Run backlight control demo")
        print("  'cursor': Run cursor control demo")
        print("  'custom': Run custom character demo")
        try:
            loop()
        except KeyboardInterrupt:
            pass
