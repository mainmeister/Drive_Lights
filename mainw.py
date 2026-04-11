# -----------------------------------------------------------------------------------------------------------------------
#   Title:      Drive_Lights (Windows Port)
#   Author:     Wiilliam Main
#   Created:    2021-05-20
#   Modified:   2026-04-11 (Ported to Windows ReadDirectoryChangesW)
#   Synopsys:   Monitor disk activity (read/write events) using Windows API and flash LEDs if supported.
#   Inputs:     - [path] (optional, default: C:\)
#   Config:     - READ_LED and WRITE_LED in .env file for pin customization.
# -----------------------------------------------------------------------------------------------------------------------

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import NoReturn

try:
    import win32file
    import win32con
except ImportError:
    # This script is intended for Windows; these imports will fail on Linux
    pass

from dotenv import load_dotenv

# Optional: gpiozero for GPIO lights. On Windows, this requires a remote pin factory (e.g., pigpio)
# or specific hardware drivers that support the gpiozero interface.
try:
    from gpiozero import LED, Device

    GPIO_SUPPORTED = True
except (ImportError, Exception):
    GPIO_SUPPORTED = False

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """Configuration for the Drive Lights monitor."""

    read_pin: int = 20
    write_pin: int = 21
    path: str = "C:\\"
    blink_duration: float = 0.01

    @classmethod
    def from_env_and_args(cls, args: argparse.Namespace) -> "Config":
        """Load configuration from environment variables and CLI arguments."""
        load_dotenv()
        return cls(
            read_pin=int(os.getenv("READ_LED", cls.read_pin)),
            write_pin=int(os.getenv("WRITE_LED", cls.write_pin)),
            path=args.path,
        )


class LEDController:
    """Manages the read and write LEDs activity."""

    def __init__(self, config: Config) -> None:
        self.read_led = None
        self.write_led = None
        self.blink_duration = config.blink_duration

        if GPIO_SUPPORTED:
            try:
                # On Windows, you might need to specify a remote pin factory
                # e.g., Device.pin_factory = ...
                self.read_led = LED(config.read_pin)
                self.write_led = LED(config.write_pin)
            except Exception as e:
                logger.warning(
                    f"Could not initialize GPIO: {e}. Activity will be logged only."
                )
        else:
            logger.info(
                "GPIO/gpiozero not supported on this platform. Activity will be logged to console (DEBUG)."
            )

    def blink_read(self) -> None:
        """Flash the read activity LED."""
        if self.read_led:
            self._blink(self.read_led)
        else:
            logger.debug("Read activity detected.")

    def blink_write(self) -> None:
        """Flash the write activity LED."""
        if self.write_led:
            self._blink(self.write_led)
        else:
            logger.debug("Write activity detected.")

    def _blink(self, led_device: LED) -> None:
        """Flash the LED for a short duration."""
        try:
            led_device.blink(
                on_time=float(self.blink_duration),
                off_time=0.0,
                n=1,
                background=True,
            )
        except Exception:
            pass


class WindowsMonitor:
    """Monitors a path for read/write events using ReadDirectoryChangesW."""

    def __init__(self, config: Config, led_controller: LEDController) -> None:
        self.path: str = config.path
        self.leds: LEDController = led_controller
        self.h_dir = None

    def _initialize_monitor(self) -> None:
        """Initialize the directory handle for monitoring."""
        if sys.platform != "win32":
            raise RuntimeError("This monitor requires Windows and the pywin32 library.")

        try:
            # FILE_LIST_DIRECTORY is required for ReadDirectoryChangesW
            # FILE_FLAG_BACKUP_SEMANTICS is mandatory when opening a handle to a directory
            self.h_dir = win32file.CreateFile(
                self.path,
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ
                | win32con.FILE_SHARE_WRITE
                | win32con.FILE_SHARE_DELETE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
        except Exception as e:
            raise OSError(f"Failed to open handle for {self.path}: {e}")

    def run(self) -> NoReturn:
        """Read and process events in a loop."""
        self._initialize_monitor()
        logger.info(f"Monitoring {self.path}... Press Ctrl+C to stop.")

        # Define what we want to monitor
        # Note: FILE_NOTIFY_CHANGE_LAST_ACCESS captures reads (if enabled in OS)
        notify_filter = (
            win32con.FILE_NOTIFY_CHANGE_FILE_NAME
            | win32con.FILE_NOTIFY_CHANGE_DIR_NAME
            | win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES
            | win32con.FILE_NOTIFY_CHANGE_SIZE
            | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE
            | win32con.FILE_NOTIFY_CHANGE_LAST_ACCESS
            | win32con.FILE_NOTIFY_CHANGE_SECURITY
        )

        try:
            while True:
                # ReadDirectoryChangesW is synchronous here and blocks until events occur
                # The 3rd parameter (True) indicates recursive monitoring of subdirectories.
                results = win32file.ReadDirectoryChangesW(
                    self.h_dir,
                    8192,  # Buffer size
                    True,  # Recursive
                    notify_filter,
                    None,
                    None,
                )

                for action, file_name in results:
                    # Windows Action Codes:
                    # 1: Created, 2: Deleted, 3: Updated, 4: Renamed from, 5: Renamed to

                    # Heuristic mapping for 'Drive Lights':
                    # Creations, deletions, and renames are treated as 'Write' events.
                    # Updates (3) can be reads or writes.
                    # Since ReadDirectoryChangesW doesn't specify which filter flag triggered the event,
                    # we trigger the write LED for visibility, but could split it if needed.

                    if action in (1, 2, 4, 5):
                        self.leds.blink_write()
                    elif action == 3:
                        # Many 'reads' (access time updates) also trigger action 3.
                        # For a 'Drive Lights' feel, we blink the write LED.
                        self.leds.blink_write()

                        # Optional: If you want to see a separate 'Read' blink,
                        # you can trigger it here as well, since 3 often covers both.
                        # self.leds.blink_read()

        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down.")
            sys.exit(0)
        finally:
            if self.h_dir:
                win32file.CloseHandle(self.h_dir)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor a path for read/write events using Windows ReadDirectoryChangesW."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="C:\\",
        help="The path or drive to monitor (default: C:\\)",
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

    led_controller = LEDController(config)
    monitor = WindowsMonitor(config, led_controller)
    monitor.run()


if __name__ == "__main__":
    main()
