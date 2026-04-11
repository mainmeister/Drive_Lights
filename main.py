# -----------------------------------------------------------------------------------------------------------------------
#   Title:      Drive_Lights
#   Author:     Wiilliam Main
#   Created:    2021-05-20
#   Modified:   2026-04-10 (Refactored)
#   Synopsys:   Monitor disk activity (read/write events) and flash GPIO LEDs.
#   Inputs:     - [mount_point] (optional, default: /)
#   Config:     - READ_LED and WRITE_LED in .env file for pin customization.
# -----------------------------------------------------------------------------------------------------------------------

import argparse
import ctypes
import logging
import os
import struct
import sys
from dataclasses import dataclass
from typing import NoReturn

from dotenv import load_dotenv
from gpiozero import LED, Device
from gpiozero.pins.lgpio import LGPIOFactory

# Fanotify constants from <sys/fanotify.h>
FAN_CLASS_NOTIF = 0x00000000
FAN_MARK_ADD = 0x00000001
FAN_MARK_MOUNT = 0x00000010
FAN_ACCESS = 0x00000001
FAN_MODIFY = 0x00000002
FAN_EVENT_METADATA_LEN = 24  # Size of fanotify_event_metadata

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """Configuration for the Drive Lights monitor."""

    read_pin: int = 20
    write_pin: int = 21
    mount_point: str = "/"
    blink_duration: float = 0.01

    @classmethod
    def from_env_and_args(cls, args: argparse.Namespace) -> "Config":
        """Load configuration from environment variables and CLI arguments."""
        load_dotenv()
        return cls(
            read_pin=int(os.getenv("READ_LED", cls.read_pin)),
            write_pin=int(os.getenv("WRITE_LED", cls.write_pin)),
            mount_point=args.mount_point,
        )


class LEDController:
    """Manages the read and write LEDs activity."""

    def __init__(self, config: Config) -> None:
        self.read_led = LED(config.read_pin)
        self.write_led = LED(config.write_pin)
        self.blink_duration = config.blink_duration

    def blink_read(self) -> None:
        """Flash the read activity LED."""
        self._blink(self.read_led)

    def blink_write(self) -> None:
        """Flash the write activity LED."""
        self._blink(self.write_led)

    def _blink(self, led_device: LED) -> None:
        """
        Flash the LED for a short duration.
        Reusing the LED object avoids frequent thread creation/destruction issues.
        """
        try:
            # on_time=0.01: High for 0.01 second
            # off_time=0: No low time needed after the pulse
            # n=1: Do this only once
            # background=True: Script continues running immediately
            led_device.blink(
                on_time=float(self.blink_duration),  # type: ignore[reportArgumentType]
                off_time=0.0,  # type: ignore[reportArgumentType]
                n=1,
                background=True,
            )
        except Exception:
            # Silently handle cases where background thread cannot be created
            pass


class FanotifyMonitor:
    """Monitors a mount point for read/write events using fanotify."""

    def __init__(self, config: Config, led_controller: LEDController) -> None:
        self.mount_path: str = config.mount_point
        self.leds: LEDController = led_controller
        self.libc = ctypes.CDLL("libc.so.6")
        self.fd: int = -1

    def _initialize_fanotify(self) -> None:
        """Initialize the fanotify group and mark the mount point."""
        self.fd = self.libc.fanotify_init(FAN_CLASS_NOTIF, os.O_RDONLY)
        if self.fd < 0:
            raise OSError(
                "Failed to initialize fanotify. Ensure you have CAP_SYS_ADMIN capabilities "
                "(e.g., run as root or set up a systemd service with AmbientCapabilities)."
            )

        mask: int = FAN_ACCESS | FAN_MODIFY
        result: int = self.libc.fanotify_mark(
            self.fd,
            FAN_MARK_ADD | FAN_MARK_MOUNT,
            mask,
            -1,
            self.mount_path.encode("utf-8"),
        )
        if result < 0:
            os.close(self.fd)
            self.fd = -1
            raise OSError(f"Failed to mark mount point: {self.mount_path}")

    def run(self) -> NoReturn:
        """Read and process events in a loop."""
        self._initialize_fanotify()
        logger.info(f"Monitoring {self.mount_path}... Press Ctrl+C to stop.")

        try:
            while True:
                # Read event metadata from the file descriptor
                data = os.read(self.fd, 4096)
                offset = 0
                while offset + FAN_EVENT_METADATA_LEN <= len(data):
                    # Unpack header: event_len (I), vers (B), reserved (B),
                    # metadata_len (H), mask (Q), fd (i), pid (i)
                    header = struct.unpack_from("IBBHQii", data, offset)
                    event_len, _, _, _, mask, event_fd, _ = header

                    if event_fd >= 0:
                        try:
                            if mask & FAN_MODIFY:
                                self.leds.blink_write()
                            elif mask & FAN_ACCESS:
                                self.leds.blink_read()
                        finally:
                            os.close(event_fd)

                    offset += event_len
        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down.")
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


def setup_gpio() -> None:
    """Initialize the pin factory for gpiozero."""
    try:
        Device.pin_factory = LGPIOFactory()
    except (ImportError, Exception):
        # If LGPIOFactory is not available, let gpiozero choose the best one
        pass


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor a mount point for read/write events using fanotify."
    )
    parser.add_argument(
        "mount_point",
        nargs="?",
        default="/",
        help="The mount point to monitor (default: /)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to see individual activity events.",
    )
    return parser.parse_args()


def main() -> None:
    """Application entry point."""
    args = parse_args()
    if args.debug:
        logger.setLevel(logging.DEBUG)
    config = Config.from_env_and_args(args)

    setup_gpio()

    led_controller = LEDController(config)
    monitor = FanotifyMonitor(config, led_controller)
    monitor.run()


if __name__ == "__main__":
    main()
