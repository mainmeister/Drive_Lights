# Drive_Lights

A Python script that monitors disk activity (read/write events) using `fanotify` and flashes GPIO-connected LEDs on a Raspberry Pi.

## Features
- Monitors a specified mount point (default: `/`).
- Uses `fanotify` for efficient kernel-level monitoring of filesystem events.
- Independent LEDs for read and write activity.
- Reuses LED objects for optimal performance.

## Hardware Requirements
- Raspberry Pi (tested on Raspberry Pi 5).
- LEDs connected to GPIO pins:
  - **Write LED:** GPIO 21
  - **Read LED:** GPIO 20

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

> [!NOTE]
> This program monitors software activity on a mount point. The actual hardware mounted on this mount point may or may not show the same activity on their own hardware activity LEDs due to buffering and other factors. If you are monitoring an SSD you might be alarmed at times by the number of writes being shown on the write LED. This is only showing you the operating systems calls to the device drivers write method. It is up to the device driver when or if a physical write takes place on the physical drive.

## Project Files
- `main.py`: The core monitoring logic.
- `overview.md`: A detailed technical overview of `main.py`.
- `Sketch.fzz`, `Sketch_schem.png`: Fritzing hardware diagrams.
- `pyproject.toml`, `uv.lock`: Dependency configuration.

## Author
Wiilliam Main

## Created
2021-05-20
