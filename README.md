# Drive_Lights

A Python script that monitors disk activity (read/write events) using `fanotify` and flashes GPIO-connected LEDs on a Raspberry Pi.

## Features
- Monitors a specified mount point (default: `/`).
- Uses `fanotify` for efficient kernel-level monitoring of filesystem events.
- Independent LEDs for read and write activity.
- Reuses LED objects for optimal performance.

## Hardware Requirements
- Raspberry Pi (tested on Raspberry Pi 5).
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
Run the script with root privileges (required for `fanotify`):

```bash
sudo .venv/bin/python main.py [mount_point]
```

Example:
```bash
sudo .venv/bin/python main.py /mnt/data
```

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
- `main.py`: The core monitoring logic.
- `OVERVIEW.md`: A detailed technical overview of `main.py`.
- `Sketch.fzz`, `Sketch_schem.png`: Fritzing hardware diagrams.
- `pyproject.toml`, `uv.lock`: Dependency configuration.

## Author
Wiilliam Main

## Created
2021-05-20
