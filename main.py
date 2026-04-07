#-----------------------------------------------------------------------------------------------------------------------
#   Title:      Drive_Lights
#   Author:     Wiilliam Main
#   Created:    2021-05-20
#   Synopsys:   When there are GPIO pins available, flash a LED for reads and writes
#   Inputs:     -p pin#
#               pin# is the gpio pin to flash
#-----------------------------------------------------------------------------------------------------------------------
from gpiozero import LED, Device
from gpiozero.pins.lgpio import LGPIOFactory
import os
import ctypes
import struct
import argparse
import sys
from typing import NoReturn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize the pin factory
try:
    Device.pin_factory = LGPIOFactory()
except ImportError:
    # If LGPIOFactory is not available, let gpiozero choose the best one
    pass

# Initialize LEDs once
# Default to 20 for reads and 21 for writes
read_pin = int(os.getenv("READ_LED", 20))
write_pin = int(os.getenv("WRITE_LED", 21))

write_led = LED(write_pin)
read_led = LED(read_pin)

def blink(led_device: LED):
    """
    Flash the LED for a short duration.
    Reusing the LED object avoids frequent thread creation/destruction issues.
    """
    try:
        # on_time=0.01: High for 0.01 second
        # off_time=0: No low time needed after the pulse
        # n=1: Do this only once
        # background=True: Script continues running immediately
        led_device.blink(on_time=0.01, off_time=0, n=1, background=True)
    except Exception:
        pass

# Fanotify constants from <sys/fanotify.h>
FAN_CLASS_NOTIF = 0x00000000
FAN_MARK_ADD = 0x00000001
FAN_MARK_MOUNT = 0x00000010
FAN_ACCESS = 0x00000001
FAN_MODIFY = 0x00000002
FAN_EVENT_METADATA_LEN = 24  # Size of fanotify_event_metadata

libc = ctypes.CDLL("libc.so.6")

class FanotifyMonitor:
    """Monitors a mount point for read/write events using fanotify."""

    def __init__(self, mount_path: str) -> None:
        self.mount_path: str = mount_path
        self.fd: int = -1

    def _initialize_fanotify(self) -> None:
        """Initialize the fanotify group and mark the mount point."""
        self.fd = libc.fanotify_init(FAN_CLASS_NOTIF, os.O_RDONLY)
        if self.fd < 0:
            raise OSError("Failed to initialize fanotify. Are you root?")

        mask: int = FAN_ACCESS | FAN_MODIFY
        result: int = libc.fanotify_mark(
            self.fd, FAN_MARK_ADD | FAN_MARK_MOUNT, mask, -1,
            self.mount_path.encode('utf-8')
        )
        if result < 0:
            raise OSError(f"Failed to mark mount point: {self.mount_path}")

    def run(self) -> NoReturn:
        """Read and process events in a loop."""
        self._initialize_fanotify()
        #print(f"Monitoring {self.mount_path}... Press Ctrl+C to stop.")

        try:
            while True:
                # Read event metadata from the file descriptor
                data = os.read(self.fd, 4096)
                offset = 0
                while offset + FAN_EVENT_METADATA_LEN <= len(data):
                    # Unpack header: event_len (I), vers (B), reserved (B),
                    # metadata_len (H), mask (Q), fd (i), pid (i)
                    header = struct.unpack_from("IBBHQii", data, offset)
                    event_len, _, _, _, mask, event_fd, pid = header

                    if event_fd >= 0:
                        if mask & FAN_ACCESS or mask & FAN_MODIFY:
                            if mask & FAN_MODIFY:
                                blink(write_led)           #flash write led
                            else:
                                blink(read_led)           #flash read led
                        os.close(event_fd)

                    offset += event_len
        except KeyboardInterrupt:
            sys.exit(0)
        finally:
            if self.fd >= 0:
                os.close(self.fd)

    @staticmethod
    def _get_path_from_fd(fd: int) -> str:
        """Retrieve the file path from its file descriptor via /proc."""
        try:
            return os.readlink(f"/proc/self/fd/{fd}")
        except FileNotFoundError:
            return "Unknown"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor a mount point for read/write events using fanotify.")
    parser.add_argument(
        "mount_point",
        nargs="?",
        default="/",
        help="The mount point to monitor (default: /)"
    )
    args = parser.parse_args()

    # Initialize the FanotifyMonitor with the specified mount point
    monitor = FanotifyMonitor(args.mount_point)
    # Start the monitor
    monitor.run()
