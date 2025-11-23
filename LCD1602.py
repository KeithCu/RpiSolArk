#!/usr/bin/env python3
import time
import subprocess
import os

# Hardware imports with graceful degradation
try:
    import smbus
    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False
    print("Warning: smbus not available. Running in simulation mode.")


def is_raspberry_pi():
    """Check if running on a Raspberry Pi by examining device tree or cpuinfo."""
    # Method 1: Check /proc/device-tree/model (most reliable)
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().strip()
            if 'Raspberry Pi' in model:
                return True
    except (IOError, FileNotFoundError):
        pass
    
    # Method 2: Check /proc/cpuinfo (fallback)
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo:
                return True
    except (IOError, FileNotFoundError):
        pass
    
    return False


def is_i2c_available():
    """Check if I2C is enabled and available on the system."""
    # Check if I2C device exists
    if os.path.exists('/dev/i2c-1'):
        return True
    if os.path.exists('/dev/i2c-0'):
        return True
    return False

class CharLCD1602(object):
    def __init__(self):
        # Check if we're on a Raspberry Pi with hardware
        self.is_rpi = is_raspberry_pi()
        self.i2c_available = is_i2c_available()
        self.smbus_available = SMBUS_AVAILABLE
        
        # Hardware is only available if we're on a Pi, I2C is enabled, and smbus works
        self.hardware_available = self.is_rpi and self.i2c_available and self.smbus_available
        
        self.BLEN = 1  # turn on/off background light
        self.PCF8574_address = 0x27  # I2C address of the PCF8574 chip.
        self.PCF8574A_address = 0x3f  # I2C address of the PCF8574A chip.
        self.LCD_ADDR = self.PCF8574_address
        
        # Initialize bus only if hardware is available
        if self.hardware_available:
            try:
                # Note you need to change the bus number to 0 if running on a revision 1 Raspberry Pi.
                self.bus = smbus.SMBus(1)
            except Exception as e:
                print(f"Warning: Could not initialize SMBus: {e}")
                self.hardware_available = False
                self.bus = None
        else:
            self.bus = None  
    def write_word(self,addr, data):
        if not self.hardware_available or self.bus is None:
            return  # Skip hardware operations if not available
        temp = data
        if self.BLEN == 1:
            temp |= 0x08
        else:
            temp &= 0xF7
        self.bus.write_byte(addr ,temp)

    def send_command(self,comm):
        # Send bit7-4 firstly
        buf = comm & 0xF0
        buf |= 0x04               # RS = 0, RW = 0, EN = 1
        self.write_word(self.LCD_ADDR ,buf)
        time.sleep(0.002)
        buf &= 0xFB               # Make EN = 0
        self.write_word(self.LCD_ADDR ,buf)
        # Send bit3-0 secondly
        buf = (comm & 0x0F) << 4
        buf |= 0x04               # RS = 0, RW = 0, EN = 1
        self.write_word(self.LCD_ADDR ,buf)
        time.sleep(0.002)
        buf &= 0xFB               # Make EN = 0
        self.write_word(self.LCD_ADDR ,buf)

    def send_data(self,data):
        # Send bit7-4 firstly
        buf = data & 0xF0
        buf |= 0x05               # RS = 1, RW = 0, EN = 1
        self.write_word(self.LCD_ADDR ,buf)
        time.sleep(0.002)
        buf &= 0xFB               # Make EN = 0
        self.write_word(self.LCD_ADDR ,buf)
        # Send bit3-0 secondly
        buf = (data & 0x0F) << 4
        buf |= 0x05               # RS = 1, RW = 0, EN = 1
        self.write_word(self.LCD_ADDR ,buf)
        time.sleep(0.002)
        buf &= 0xFB               # Make EN = 0
        self.write_word(self.LCD_ADDR ,buf)

    def i2c_scan(self):
        if not self.hardware_available:
            # Return empty list in simulation mode
            return []
        try:
            cmd = "i2cdetect -y 1 |awk \'NR>1 {$1=\"\";print}\'"
            result = subprocess.check_output(cmd, shell=True).decode()
            result = result.replace("\n", "").replace(" --", "")
            i2c_list = result.split(' ')
            return i2c_list
        except Exception as e:
            print(f"Warning: I2C scan failed: {e}")
            return []

    def init_lcd(self,addr=None, bl=1):
        # If not on Raspberry Pi or hardware not available, return False
        if not self.hardware_available:
            if not self.is_rpi:
                print("LCD initialization failed: Not running on Raspberry Pi hardware")
            elif not self.i2c_available:
                print("LCD initialization failed: I2C not available (check if I2C is enabled)")
            elif not self.smbus_available:
                print("LCD initialization failed: smbus library not available")
            return False
            
        i2c_list = self.i2c_scan()
#         print(f"i2c_list: {i2c_list}")
        if addr is None:
            if '27' in i2c_list:
                self.LCD_ADDR = self.PCF8574_address
            elif '3f' in i2c_list:
                self.LCD_ADDR = self.PCF8574A_address
            else:
                print("LCD initialization failed: I2C address 0x27 or 0x3f not found on bus")
                return False
        else:
            self.LCD_ADDR = addr
            addr_hex = str(hex(addr)).strip('0x')
            if addr_hex not in i2c_list:
                print(f"LCD initialization failed: I2C address {hex(addr)} not found on bus")
                return False
        self.BLEN = bl
        try:
            self.send_command(0x33) # Must initialize to 8-line mode at first
            time.sleep(0.005)
            self.send_command(0x32) # Then initialize to 4-line mode
            time.sleep(0.005)
            self.send_command(0x28) # 2 Lines & 5*7 dots
            time.sleep(0.005)
            self.send_command(0x0C) # Enable display without cursor
            time.sleep(0.005)
            self.send_command(0x01) # Clear Screen
            self.bus.write_byte(self.LCD_ADDR, 0x08)
        except Exception as e:
            print(f"LCD initialization failed during hardware setup: {e}")
            return False
        else:
            return True

    def clear(self):
        if not self.hardware_available:
            return  # Skip in simulation mode
        self.send_command(0x01) # Clear Screen

    def openlight(self):  # Enable the backlight
        if not self.hardware_available or self.bus is None:
            return  # Skip in simulation mode
        self.BLEN = 1
        self.bus.write_byte(self.LCD_ADDR, 0x08)

    def closelight(self):  # Disable the backlight
        if not self.hardware_available or self.bus is None:
            return  # Skip in simulation mode
        self.BLEN = 0
        self.bus.write_byte(self.LCD_ADDR, 0x00)

    def set_backlight(self, on: bool):
        """Set backlight on or off."""
        if not self.hardware_available or self.bus is None:
            return  # Skip in simulation mode
        if on:
            self.openlight()
        else:
            self.closelight()

    def write(self,x, y, str):
        if not self.hardware_available:
            return  # Skip in simulation mode
        if x < 0:
            x = 0
        if x > 15:
            x = 15
        if y <0:
            y = 0
        if y > 1:
            y = 1
        # Move cursor
        addr = 0x80 + 0x40 * y + x
        self.send_command(addr)
        for chr in str:
            self.send_data(ord(chr))
    def display_num(self,x, y, num):
        if not self.hardware_available:
            return  # Skip in simulation mode
        addr = 0x80 + 0x40 * y + x
        self.send_command(addr)
        self.send_data(num)
        
def loop():
    count = 0
    while(True):
        lcd1602.clear()
        lcd1602.write(0, 0, '  Hello World!  ' )# display CPU temperature
        lcd1602.write(0, 1, '  Counter: ' + str(count) )   # display the time
        time.sleep(1)
        count += 1
def destroy():
    lcd1602.clear()
lcd1602 = CharLCD1602()  
if __name__ == '__main__':
    print ('Program is starting ... ')
    lcd1602.init_lcd(addr=None, bl=1)
    try:
        loop()
    except KeyboardInterrupt:
        destroy()

