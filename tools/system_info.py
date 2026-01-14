# System Information Tool - Displays system information
"""
Displays basic system information including OS, Python version, and disk usage.
"""

import sys
import os
import platform

def main():
    print("=" * 50)
    print("SYSTEM INFORMATION")
    print("=" * 50)
    print()
    
    # OS Info
    print(f"OS: {platform.system()} {platform.release()}")
    print(f"Platform: {platform.platform()}")
    print(f"Architecture: {platform.machine()}")
    print()
    
    # Python Info
    print(f"Python Version: {sys.version}")
    print(f"Python Executable: {sys.executable}")
    print()
    
    # Disk Info
    try:
        statvfs = os.statvfs('/')
        total = statvfs.f_blocks * statvfs.f_frsize
        free = statvfs.f_bavail * statvfs.f_frsize
        used = total - free
        
        print(f"Disk Total: {format_bytes(total)}")
        print(f"Disk Used: {format_bytes(used)}")
        print(f"Disk Free: {format_bytes(free)}")
        print(f"Disk Usage: {100 * used / total:.1f}%")
    except Exception as e:
        print(f"Could not get disk info: {e}")
    
    print()
    print("=" * 50)

def format_bytes(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.2f} PB"

if __name__ == '__main__':
    main()
