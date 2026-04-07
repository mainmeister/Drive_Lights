The `main.py` script is the core of the **Drive_Lights** project. Its purpose is to monitor a filesystem (like your SD card or an external drive) for read and write operations and flash physical LEDs connected to the Raspberry Pi's GPIO pins to provide a visual indicator of disk activity.

Here is a breakdown of how the code works:

---

### 1. Hardware Control (GPIO)
The script uses the `gpiozero` library to control the LEDs.
- **Pin Factory:** It specifically attempts to use `LGPIOFactory` (lines 23-27), which is the recommended backend for newer Raspberry Pi hardware (like the Pi 5) to ensure reliable pin control.
- **Environment Variables:** The script uses `python-dotenv` to load pin configurations from a `.env` file (lines 19-20 and 31-32).
- **LED Initialization:** It defines two LED objects (lines 34-35):
    - **Read LED:** Default GPIO 20 (can be changed via `READ_LED` in `.env`).
    - **Write LED:** Default GPIO 21 (can be changed via `WRITE_LED` in `.env`).
- **The `blink` function:** This function (lines 37-49) triggers a very short pulse (0.01 seconds). It uses `background=True` so that the main monitoring loop isn't paused while the LED is flashing.

### 2. Kernel-Level Monitoring (Fanotify)
Instead of constantly polling files (which would be slow and resource-intensive), the script uses **`fanotify`**, a powerful Linux kernel feature.
- **`ctypes` & `libc`:** Since Python doesn't have a built-in high-level wrapper for `fanotify`, the script uses `ctypes` to talk directly to the C standard library (`libc`) (line 51).
- **Initialization:** The `_initialize_fanotify` method (lines 60-72) sets up a "fanotify group" and marks a specific mount point (like `/`) to be watched for two types of events:
    - `FAN_ACCESS`: Triggered when a file is read.
    - `FAN_MODIFY`: Triggered when a file is written to or modified.

### 3. The Event Loop (`run` method)
The heart of the script is the `while True` loop inside the `FanotifyMonitor.run` method (lines 80-98):
1. **Reading Events:** It reads raw binary data from the `fanotify` file descriptor. This data contains a series of metadata structures describing what happened.
2. **Unpacking Metadata:** It uses the `struct` module (line 87) to "unpack" the binary data into readable Python variables (like the event length, the event mask, and the file descriptor of the file being accessed).
3. **Logic Switch:**
    - If the `mask` contains `FAN_MODIFY`, it calls `blink(write_led)`.
    - If the `mask` contains `FAN_ACCESS`, it calls `blink(read_led)`.
4. **Cleanup:** It immediately closes the file descriptor (`event_fd`) created by the kernel for that specific event (line 96) to prevent the system from running out of available file handles.

### 4. Command Line Interface
The script uses `argparse` (lines 114-121) to allow flexibility:
- You can run it simply as `sudo python main.py` to monitor the root filesystem.
- Or specify a mount point, such as `sudo python main.py /media/external_drive`.

### Summary of Execution Flow
1. **Startup:** Initialize GPIO pins and parse the target mount point.
2. **Setup:** Tell the Linux kernel: "Notify me whenever anything on this drive is read or changed."
3. **Monitor:** Wait for the kernel to send data.
4. **Action:** When data arrives, identify if it's a read or write and pulse the corresponding LED.
5. **Repeat:** Continue until the user stops the script with `Ctrl+C`.

**Note:** Because `fanotify` interacts directly with the kernel, the script **must** be run with root privileges (e.g., using `sudo`).