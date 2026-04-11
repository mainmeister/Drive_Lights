# Drive_Lights

A Python script that monitors disk activity (read/write events) and flashes GPIO-connected LEDs. Supports Linux (using `fanotify`) and Windows (using `ReadDirectoryChangesW`).

## Features
- Monitors a specified mount point (Linux) or path (Windows).
- Uses `fanotify` (Linux) or `ReadDirectoryChangesW` (Windows) for efficient monitoring.
- Independent LEDs for read and write activity.
- Reuses LED objects for optimal performance.

## Hardware Requirements
- **Linux:** Raspberry Pi (tested on Raspberry Pi 5).
- **Windows:** Any Windows machine (GPIO support requires specific hardware or remote pin factory).
- **USB GPIO (Optional):** Use an adapter like the [MCP2221A USB to GPIO Adapter](https://www.amazon.ca/MCP2221A-Adapter-Enhances-Acquisition-Control/dp/B0F38H381V) to provide physical pins via USB on any computer.
- LEDs connected to GPIO pins (configurable via `.env`):
  - **Write LED:** Default GPIO 21
  - **Read LED:** Default GPIO 20

## Configuration
Create a `.env` file in the project root to customize pin numbers:
```env
READ_LED=20
WRITE_LED=21
```
See `.env.example` for reference.

## Installation
The project uses `uv` for dependency management.

```bash
uv sync
```

## Usage

### Linux
Run the script with root privileges (required for `fanotify`):

```bash
sudo .venv/bin/python main.py [mount_point] [--debug]
```

Example:
```bash
sudo .venv/bin/python main.py /mnt/data --debug
```

**Notes for Linux:**
- **Privileges:** Requires **root** privileges (or specific kernel capabilities).
- **Monitoring:** Monitors the entire **mount point** recursively.
- **Console Logging:** Use `--debug` to see individual events in the console.

### Windows
Run the Windows port script:

```powershell
python mainw.py [path] [--debug]
```

Example:
```powershell
python mainw.py C:\ --debug
```

**Notes for Windows:**
- **Privileges:** Depending on the monitored path, you may need to run PowerShell as **Administrator**.
- **Dependencies:** Requires the `pywin32` library, as well as `adafruit-blinka` and `hidapi` for USB GPIO support (all installed automatically by `uv sync`).
- **GPIO:** If using an adapter like the [MCP2221A](https://www.amazon.ca/MCP2221A-Adapter-Enhances-Acquisition-Control/dp/B0F38H381V), ensure you set the environment variable `BLINKA_MCP2221=1` before running the script.
- **Monitoring:** Subdirectories are monitored **recursively** by default.
- **Read Activity:** Detection of reads (access time updates) depends on your OS filesystem settings.
- **Console Logging:** Use `--debug` to see individual events in the console (useful if no GPIO hardware is present).

### Running Without Root (Optional)
If you prefer not to run the script as root manually, you have two main options:

#### Option 1: Use a Systemd Service (Recommended)
You can set up a background service that runs as your user but is granted the necessary kernel capabilities (`CAP_SYS_ADMIN`).
1. Use the provided `drive-lights.service.example` as a template.
2. Edit it to match your username and path.
3. Install it:
   ```bash
   sudo cp drive-lights.service.example /etc/systemd/system/drive-lights.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now drive-lights.service
   ```

#### Option 2: Use `sudoers` for a Specific Group
If you want to run it from the command line without entering a password, you can create a group and allow it to run this specific command as root:
1. Create a group (e.g., `diskmon`): `sudo groupadd diskmon`
2. Add your user to it: `sudo usermod -aG diskmon $USER`
3. Add this line to your `sudoers` file (via `sudo visudo`):
   ```text
   %diskmon ALL=(ALL) NOPASSWD: /path/to/.venv/bin/python /path/to/main.py *
   ```

#### Option 3: Use File Capabilities
Alternatively, you can grant the capability directly to the Python interpreter in your virtual environment:
```bash
sudo setcap cap_sys_admin+ep .venv/bin/python
```
*(Note: You'll need to re-run this if you delete and recreate your `.venv`.)*

> [!NOTE]
> This program monitors software activity on a mount point. The actual hardware mounted on this mount point may or may not show the same activity on their own hardware activity LEDs due to buffering and other factors. If you are monitoring an SSD you might be alarmed at times by the number of writes being shown on the write LED. This is only showing you the operating systems calls to the device drivers write method. It is up to the device driver when or if a physical write takes place on the physical drive.

## Project Files
- `main.py`: The core monitoring logic for Linux.
- `mainw.py`: The Windows port of the monitoring logic.
- `OVERVIEW.md`: A detailed technical overview of both monitoring implementations.
- `Sketch.fzz`, `Sketch_schem.png`: Fritzing hardware diagrams.
- `pyproject.toml`, `uv.lock`: Dependency configuration.

## Author
Wiilliam Main

## Created
2021-05-20
