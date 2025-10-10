#!/usr/bin/env python3
"""
LCD Time and Temperature Display using LCD1602
Displays CPU temperature and current time on 16x2 LCD
"""

import smbus
from time import sleep, strftime
from datetime import datetime
from LCD1602 import CharLCD1602

# Initialize LCD
lcd1602 = CharLCD1602()

def get_cpu_temp():
    """Get CPU temperature from file /sys/class/thermal/thermal_zone0/temp"""
    try:
        tmp = open('/sys/class/thermal/thermal_zone0/temp')
        cpu = tmp.read()
        tmp.close()
        return '{:.2f}'.format(float(cpu)/1000) + ' C'
    except Exception as e:
        print(f"Error reading temperature: {e}")
        return 'N/A C'

def get_time_now():
    """Get system time"""
    return datetime.now().strftime(' %H:%M:%S')

def loop():
    """Main display loop"""
    lcd1602.init_lcd()
    count = 0
    
    while(True):
        lcd1602.clear()
        lcd1602.write(0, 0, 'CPU: ' + get_cpu_temp())  # display CPU temperature
        lcd1602.write(0, 1, get_time_now())  # display the time
        sleep(1)

def destroy():
    """Clean up on exit"""
    lcd1602.clear()

if __name__ == '__main__':
    print('Program is starting...')
    try:
        loop()
    except KeyboardInterrupt:
        destroy()
