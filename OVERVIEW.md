The `main.py` and `mainw.py` scripts are the core of the **Drive_Lights** project. Their purpose is to monitor a filesystem (like your SD card, an external drive, or a Windows directory) for read and write operations and flash physical LEDs connected to GPIO pins to provide a visual indicator of disk activity.

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

### 2. Linux: Kernel-Level Monitoring (Fanotify)
Instead of constantly polling files (which would be slow and resource-intensive), the Linux script (`main.py`) uses **`fanotify`**, a powerful kernel feature.
- **`ctypes` & `libc`:** Since Python doesn't have a built-in high-level wrapper for `fanotify`, the script uses `ctypes` to talk directly to the C standard library (`libc`) (line 51).
- **Initialization:** The `_initialize_fanotify` method (lines 60-72) sets up a "fanotify group" and marks a specific mount point (like `/`) to be watched for two types of events:
    - `FAN_ACCESS`: Triggered when a file is read.
    - `FAN_MODIFY`: Triggered when a file is written to or modified.

### 3. Windows: Directory Changes (ReadDirectoryChangesW)
The Windows port (`mainw.py`) uses the Windows API via `pywin32`.
- **`ReadDirectoryChangesW`:** This function allows the script to monitor a directory (and subdirectories) for changes.
- **Monitoring Filter:** It listens for several types of notifications:
    - `FILE_NOTIFY_CHANGE_FILE_NAME`, `FILE_NOTIFY_CHANGE_DIR_NAME`
    - `FILE_NOTIFY_CHANGE_ATTRIBUTES`, `FILE_NOTIFY_CHANGE_SIZE`
    - `FILE_NOTIFY_CHANGE_LAST_WRITE`, `FILE_NOTIFY_CHANGE_LAST_ACCESS`
- **Action Mapping:** 
    - Creations, deletions, and renames are treated as **Write** events.
    - Updates (Action Code 3) often cover both reads and writes.

### 4. The Event Loop
Both scripts implement a `run` method containing a `while True` loop:

#### Linux (`main.py`)
1. **Reading Events:** It reads raw binary data from the `fanotify` file descriptor.
2. **Unpacking Metadata:** It uses the `struct` module to "unpack" the binary data into readable variables (event mask, file descriptor).
3. **Logic Switch:**
    - If the `mask` contains `FAN_MODIFY`, it calls `blink_write()`.
    - If the `mask` contains `FAN_ACCESS`, it calls `blink_read()`.
4. **Cleanup:** It immediately closes the file descriptor created by the kernel.

#### Windows (`mainw.py`)
1. **Waiting for Changes:** `ReadDirectoryChangesW` blocks until changes occur in the monitored path.
2. **Processing Results:** It receives a list of tuples containing the action type and the filename.
3. **Logic Switch:**
    - Action codes 1 (Created), 2 (Deleted), 4 (Renamed from), 5 (Renamed to) trigger `blink_write()`.
    - Action code 3 (Updated) triggers `blink_write()` (as it covers most file modifications).

### 5. Command Line Interface
Both scripts use `argparse` to allow flexibility:
- **Linux:** `sudo python main.py [mount_point] [--debug]` (default: `/`)
- **Windows:** `python mainw.py [path] [--debug]` (default: `C:\`)
- **--debug:** Enables `DEBUG` level logging to see individual activity events in the console (especially useful for testing or when physical LEDs are not connected).

### Summary of Execution Flow
1. **Startup:** Initialize configurations and (if on Linux) the pin factory.
2. **Setup:** 
    - **Linux:** Tell the kernel: "Notify me whenever anything on this drive is read or changed."
    - **Windows:** Request notifications for directory changes in the specified path.
3. **Monitor:** Wait for events (blocks until they arrive).
4. **Action:** When events arrive, identify if it's a read or write (or mapped to one) and pulse the corresponding LED.
5. **Repeat:** Continue until interrupted.

**Note:** The Linux script requires root privileges for `fanotify`. The Windows script requires the `pywin32` library and may require administrative privileges depending on the monitored path.