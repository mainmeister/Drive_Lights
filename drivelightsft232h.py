#!/usr/bin/env python3
import argparse
import os
import sys
import time
import ctypes
import select

# Set environment variable for FT232H before importing board
os.environ['BLINKA_FT232H'] = '1'

try:
    import board
    import digitalio
except ImportError:
    print("Error: adafruit-blinka not installed. Please install it with 'pip install adafruit-blinka'.")
    sys.exit(1)

# fanotify constants (from <linux/fanotify.h>)
FAN_CLASS_NOTIF = 0x00000000
FAN_CLOEXEC = 0x00000001
FAN_MARK_ADD = 0x00000001
FAN_MARK_MOUNT = 0x00000010

FAN_ACCESS = 0x00000001
FAN_MODIFY = 0x00000002
# Not strictly necessary for FAN_MARK_MOUNT but included for safety
FAN_EVENT_ON_CHILD = 0x08000000

# fanotify_event_metadata structure
class FanotifyEventMetadata(ctypes.Structure):
    _fields_ = [
        ("event_len", ctypes.c_uint32),
        ("vers", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8),
        ("metadata_len", ctypes.c_uint16),
        ("mask", ctypes.c_uint64),
        ("fd", ctypes.c_int32),
        ("pid", ctypes.c_int32),
    ]

# Setup libc calls
libc = ctypes.CDLL("libc.so.6", use_errno=True)

# int fanotify_init(unsigned int flags, unsigned int event_f_flags);
libc.fanotify_init.argtypes = [ctypes.c_uint, ctypes.c_uint]
libc.fanotify_init.restype = ctypes.c_int

# int fanotify_mark(int fanotify_fd, unsigned int flags, uint64_t mask, int dirfd, const char *pathname);
libc.fanotify_mark.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint64, ctypes.c_int, ctypes.c_char_p]
libc.fanotify_mark.restype = ctypes.c_int

# ssize_t read(int fd, void *buf, size_t count);
libc.read.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
libc.read.restype = ctypes.c_ssize_t

def main():
    # Root check
    if os.geteuid() != 0:
        print("Error: This script must be run as root to use fanotify. Try: sudo python drivelightsft232h.py")
        sys.exit(1)

    # Command line arguments
    parser = argparse.ArgumentParser(description="Drive activity lights using FT232H and fanotify.")
    parser.add_argument("--mount", default="/", help="Mount point to monitor (default: '/')")
    parser.add_argument("--read", default="C0", help="FT232H pin for read activity (default: 'C0')")
    parser.add_argument("--write", default="C1", help="FT232H pin for write activity (default: 'C1')")
    args = parser.parse_args()

    # Get pin IDs from board module
    try:
        read_pin_id = getattr(board, args.read)
        write_pin_id = getattr(board, args.write)
    except AttributeError:
        print(f"Error: Invalid pin name '{args.read}' or '{args.write}'. Available pins on FT232H include C0-C7, D4-D7, etc.")
        sys.exit(1)

    # Initialize LEDs
    try:
        read_led = digitalio.DigitalInOut(read_pin_id)
        read_led.direction = digitalio.Direction.OUTPUT
        read_led.value = False

        write_led = digitalio.DigitalInOut(write_pin_id)
        write_led.direction = digitalio.Direction.OUTPUT
        write_led.value = False
    except Exception as e:
        print(f"Error initializing FT232H GPIO: {e}")
        sys.exit(1)

    # Initialize fanotify
    # Use FAN_CLASS_NOTIF for notification-only
    # os.O_RDONLY is the event_f_flags (flags used for opening files in events)
    fd = libc.fanotify_init(FAN_CLASS_NOTIF | FAN_CLOEXEC, os.O_RDONLY)
    if fd == -1:
        errno_val = ctypes.get_errno()
        print(f"Error: fanotify_init failed: {os.strerror(errno_val)} (errno {errno_val})")
        sys.exit(1)

    # Mark the mount point for access (read) and modify (write) events
    mask = FAN_ACCESS | FAN_MODIFY
    res = libc.fanotify_mark(fd, FAN_MARK_ADD | FAN_MARK_MOUNT, mask, -1, args.mount.encode())
    if res == -1:
        errno_val = ctypes.get_errno()
        print(f"Error: fanotify_mark failed for '{args.mount}': {os.strerror(errno_val)}")
        os.close(fd)
        sys.exit(1)

    print(f"Monitoring activity on mount: '{args.mount}'")
    print(f"Read LED (Pin {args.read}) and Write LED (Pin {args.write}) initialized.")
    print("Press Ctrl+C to stop.")

    flash_duration = 0.05  # Flash duration in seconds (50ms)
    last_read_event = 0
    last_write_event = 0

    try:
        buf_size = 16384  # Larger buffer for many simultaneous events
        buf = ctypes.create_string_buffer(buf_size)

        while True:
            # Calculate timeout for select based on when LEDs should turn off
            now = time.time()
            timeout = None
            
            if read_led.value:
                remaining = (last_read_event + flash_duration) - now
                timeout = max(0, remaining)
            
            if write_led.value:
                remaining = (last_write_event + flash_duration) - now
                if timeout is None or remaining < timeout:
                    timeout = max(0, remaining)

            # select waits for data on fanotify fd or the next LED turn-off time
            r, _, _ = select.select([fd], [], [], timeout)

            if r:
                # Read events from fanotify
                n = libc.read(fd, buf, buf_size)
                if n < 0:
                    errno_val = ctypes.get_errno()
                    if errno_val == 4:  # EINTR (interrupted by signal)
                        continue
                    print(f"Error reading fanotify events: {os.strerror(errno_val)}")
                    break
                
                offset = 0
                while offset + ctypes.sizeof(FanotifyEventMetadata) <= n:
                    metadata = FanotifyEventMetadata.from_buffer(buf, offset)
                    
                    if metadata.mask & FAN_ACCESS:
                        read_led.value = True
                        last_read_event = time.time()
                    
                    if metadata.mask & FAN_MODIFY:
                        write_led.value = True
                        last_write_event = time.time()

                    # In notification mode, fanotify returns an open file descriptor for the event
                    # We must close it to avoid leaking FDs
                    if metadata.fd >= 0:
                        os.close(metadata.fd)
                    
                    if metadata.event_len < ctypes.sizeof(FanotifyEventMetadata):
                        break
                    offset += metadata.event_len
            else:
                # Timeout reached, turn off LEDs if they've been on long enough
                now = time.time()
                if read_led.value and now - last_read_event >= flash_duration:
                    read_led.value = False
                if write_led.value and now - last_write_event >= flash_duration:
                    write_led.value = False

    except KeyboardInterrupt:
        print("\nStopping activity monitoring...")
    except Exception as e:
        print(f"\nError in event loop: {e}")
    finally:
        # Cleanup
        os.close(fd)
        # Ensure LEDs are off
        try:
            read_led.value = False
            write_led.value = False
            read_led.deinit()
            write_led.deinit()
        except:
            pass
        print("Cleanup complete. Goodbye.")

if __name__ == "__main__":
    main()
