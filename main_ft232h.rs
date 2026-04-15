use anyhow::{anyhow, Result};
use clap::Parser;
use nix::poll::{poll, PollFd, PollFlags, PollTimeout};
use nix::unistd::geteuid;
use std::os::fd::BorrowedFd;
use std::time::{Duration, Instant};
use std::process;
use std::ptr;
use std::mem;
use libloading::{Library, Symbol};

/// Drive activity lights using FT232H and fanotify.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Mount point to monitor
    #[arg(long, default_value = "/")]
    mount: String,

    /// FT232H pin for read activity (default: C0)
    #[arg(long, default_value = "C0")]
    read_pin: String,

    /// FT232H pin for write activity (default: C1)
    #[arg(long, default_value = "C1")]
    write_pin: String,
}

// FTDI constants
const FTDI_VID: u16 = 0x0403;
const FTDI_PID: u16 = 0x6014; // FT232H

// fanotify constants
const FAN_CLASS_NOTIF: u32 = 0x00000000;
const FAN_CLOEXEC: u32 = 0x00000001;
const FAN_MARK_ADD: u32 = 0x00000001;
const FAN_MARK_MOUNT: u32 = 0x00000010;
const FAN_ACCESS: u64 = 0x00000001;
const FAN_MODIFY: u64 = 0x00000002;

#[repr(C)]
struct FanotifyEventMetadata {
    event_len: u32,
    vers: u8,
    reserved: u8,
    metadata_len: u16,
    mask: u64,
    fd: i32,
    pid: i32,
}

struct Ft232h {
    context: *mut libc::c_void,
    high_byte_value: u8,
    high_byte_direction: u8,
    
    // Function symbols
    _ftdi_new: Symbol<'static, unsafe extern "C" fn() -> *mut libc::c_void>,
    _ftdi_usb_open: Symbol<'static, unsafe extern "C" fn(*mut libc::c_void, i32, i32) -> i32>,
    _ftdi_set_bitmode: Symbol<'static, unsafe extern "C" fn(*mut libc::c_void, u8, u8) -> i32>,
    ftdi_write_data: Symbol<'static, unsafe extern "C" fn(*mut libc::c_void, *const u8, i32) -> i32>,
    ftdi_usb_close: Symbol<'static, unsafe extern "C" fn(*mut libc::c_void) -> i32>,
    ftdi_free: Symbol<'static, unsafe extern "C" fn(*mut libc::c_void)>,

    _lib: Library,
}

impl Ft232h {
    fn open() -> Result<Self> {
        let lib = unsafe { Library::new("libftdi1.so.2")? };
        
        let ftdi_new: Symbol<unsafe extern "C" fn() -> *mut libc::c_void> = unsafe { lib.get(b"ftdi_new")? };
        let ftdi_usb_open: Symbol<unsafe extern "C" fn(*mut libc::c_void, i32, i32) -> i32> = unsafe { lib.get(b"ftdi_usb_open")? };
        let ftdi_set_bitmode: Symbol<unsafe extern "C" fn(*mut libc::c_void, u8, u8) -> i32> = unsafe { lib.get(b"ftdi_set_bitmode")? };
        let ftdi_write_data: Symbol<unsafe extern "C" fn(*mut libc::c_void, *const u8, i32) -> i32> = unsafe { lib.get(b"ftdi_write_data")? };
        let ftdi_usb_close: Symbol<unsafe extern "C" fn(*mut libc::c_void) -> i32> = unsafe { lib.get(b"ftdi_usb_close")? };
        let ftdi_free: Symbol<unsafe extern "C" fn(*mut libc::c_void)> = unsafe { lib.get(b"ftdi_free")? };

        // Make them 'static to keep them in the struct
        let ftdi_new_s = unsafe { mem::transmute::<Symbol<unsafe extern "C" fn() -> *mut libc::c_void>, Symbol<'static, unsafe extern "C" fn() -> *mut libc::c_void>>(ftdi_new) };
        let ftdi_usb_open_s = unsafe { mem::transmute::<Symbol<unsafe extern "C" fn(*mut libc::c_void, i32, i32) -> i32>, Symbol<'static, unsafe extern "C" fn(*mut libc::c_void, i32, i32) -> i32>>(ftdi_usb_open) };
        let ftdi_set_bitmode_s = unsafe { mem::transmute::<Symbol<unsafe extern "C" fn(*mut libc::c_void, u8, u8) -> i32>, Symbol<'static, unsafe extern "C" fn(*mut libc::c_void, u8, u8) -> i32>>(ftdi_set_bitmode) };
        let ftdi_write_data_s = unsafe { mem::transmute::<Symbol<unsafe extern "C" fn(*mut libc::c_void, *const u8, i32) -> i32>, Symbol<'static, unsafe extern "C" fn(*mut libc::c_void, *const u8, i32) -> i32>>(ftdi_write_data) };
        let ftdi_usb_close_s = unsafe { mem::transmute::<Symbol<unsafe extern "C" fn(*mut libc::c_void) -> i32>, Symbol<'static, unsafe extern "C" fn(*mut libc::c_void) -> i32>>(ftdi_usb_close) };
        let ftdi_free_s = unsafe { mem::transmute::<Symbol<unsafe extern "C" fn(*mut libc::c_void)>, Symbol<'static, unsafe extern "C" fn(*mut libc::c_void)>>(ftdi_free) };

        let context = unsafe { (ftdi_new_s)() };
        if context.is_null() {
            return Err(anyhow!("ftdi_new failed"));
        }

        let res = unsafe { (ftdi_usb_open_s)(context, FTDI_VID as i32, FTDI_PID as i32) };
        if res < 0 {
            unsafe { (ftdi_free_s)(context); }
            return Err(anyhow!("ftdi_usb_open failed: {}", res));
        }

        // Set Bitmode (MPSSE mode)
        let res = unsafe { (ftdi_set_bitmode_s)(context, 0, 0x02) };
        if res < 0 {
            unsafe { (ftdi_usb_close_s)(context); (ftdi_free_s)(context); }
            return Err(anyhow!("ftdi_set_bitmode failed: {}", res));
        }

        Ok(Self {
            context,
            high_byte_value: 0,
            high_byte_direction: 0,
            _ftdi_new: ftdi_new_s,
            _ftdi_usb_open: ftdi_usb_open_s,
            _ftdi_set_bitmode: ftdi_set_bitmode_s,
            ftdi_write_data: ftdi_write_data_s,
            ftdi_usb_close: ftdi_usb_close_s,
            ftdi_free: ftdi_free_s,
            _lib: lib,
        })
    }

    fn set_pin(&mut self, pin_idx: u8, value: bool) -> Result<()> {
        if value {
            self.high_byte_value |= 1 << pin_idx;
        } else {
            self.high_byte_value &= !(1 << pin_idx);
        }
        self.high_byte_direction |= 1 << pin_idx;

        self.update_high_byte()
    }

    fn update_high_byte(&mut self) -> Result<()> {
        let cmd = [0x82, self.high_byte_value, self.high_byte_direction];
        let res = unsafe { (self.ftdi_write_data)(self.context, cmd.as_ptr(), cmd.len() as i32) };
        if res < 0 {
            return Err(anyhow!("ftdi_write_data failed: {}", res));
        }
        Ok(())
    }
}

impl Drop for Ft232h {
    fn drop(&mut self) {
        unsafe {
            (self.ftdi_usb_close)(self.context);
            (self.ftdi_free)(self.context);
        }
    }
}

fn parse_pin_name(name: &str) -> Result<u8> {
    if name.starts_with('C') {
        let idx = name[1..].parse::<u8>()?;
        if idx <= 7 {
            return Ok(idx);
        }
    }
    Err(anyhow!("Invalid pin name: {}", name))
}

fn main() -> Result<()> {
    // Display banner
    println!("Drivelights v{}", env!("CARGO_PKG_VERSION"));
    println!("Author: William Main");
    println!("Compiled: {}", env!("BUILD_DATE"));
    println!("Description: This program monitors filesystem activity using fanotify and drives activity LEDs via an FT232H chip.");
    println!("             It provides visual feedback for read and write operations on a specified mount point.");
    println!();

    // Root check
    if !geteuid().is_root() {
        println!("Error: This program must be run as root to use fanotify.");
        process::exit(1);
    }

    let args = Args::parse();

    let read_pin_idx = parse_pin_name(&args.read_pin)?;
    let write_pin_idx = parse_pin_name(&args.write_pin)?;

    // Initialize FT232H
    let mut ft232h = match Ft232h::open() {
        Ok(f) => f,
        Err(e) => {
            println!("Error initializing FT232H (libftdi1): {}", e);
            process::exit(1);
        }
    };

    // Ensure LEDs are off
    ft232h.set_pin(read_pin_idx, false)?;
    ft232h.set_pin(write_pin_idx, false)?;

    // Initialize fanotify using libc
    let fan_fd = unsafe {
        libc::fanotify_init(FAN_CLASS_NOTIF | FAN_CLOEXEC, libc::O_RDONLY as u32)
    };
    if fan_fd == -1 {
        return Err(anyhow!("fanotify_init failed: {}", std::io::Error::last_os_error()));
    }

    let mount_c = std::ffi::CString::new(args.mount.clone())?;
    let res = unsafe {
        libc::fanotify_mark(fan_fd, FAN_MARK_ADD | FAN_MARK_MOUNT, FAN_ACCESS | FAN_MODIFY, -1, mount_c.as_ptr())
    };
    if res == -1 {
        unsafe { libc::close(fan_fd); }
        return Err(anyhow!("fanotify_mark failed for '{}': {}", args.mount, std::io::Error::last_os_error()));
    }

    println!("Monitoring activity on mount: '{}'", args.mount);
    println!("Read LED (Pin {}) and Write LED (Pin {}) initialized.", args.read_pin, args.write_pin);
    println!("Press Ctrl+C to stop.");

    let flash_duration = Duration::from_millis(50);
    let mut last_read_event: Option<Instant> = None;
    let mut last_write_event: Option<Instant> = None;
    let mut read_led_on = false;
    let mut write_led_on = false;

    let fan_borrowed_fd = unsafe { BorrowedFd::borrow_raw(fan_fd) };
    let mut fds = [PollFd::new(fan_borrowed_fd, PollFlags::POLLIN)];
    let mut buf = [0u8; 16384];

    loop {
        // Calculate timeout
        let now = Instant::now();
        let mut timeout_duration = None;

        if read_led_on {
            if let Some(last) = last_read_event {
                let elapsed = now.duration_since(last);
                if elapsed >= flash_duration {
                    timeout_duration = Some(Duration::ZERO);
                } else {
                    timeout_duration = Some(flash_duration - elapsed);
                }
            }
        }

        if write_led_on {
            if let Some(last) = last_write_event {
                let elapsed = now.duration_since(last);
                let remaining = if elapsed >= flash_duration {
                    Duration::ZERO
                } else {
                    flash_duration - elapsed
                };
                
                match timeout_duration {
                    Some(t) if remaining < t => timeout_duration = Some(remaining),
                    None => timeout_duration = Some(remaining),
                    _ => {}
                }
            }
        }

        let poll_timeout = match timeout_duration {
            Some(d) => PollTimeout::try_from(d).unwrap_or(PollTimeout::ZERO),
            None => PollTimeout::NONE,
        };

        let ret = poll(&mut fds, poll_timeout)?;

        if ret > 0 {
            // Read events from fanotify
            let n = unsafe {
                libc::read(fan_fd, buf.as_mut_ptr() as *mut libc::c_void, buf.len())
            };
            if n < 0 {
                let err = std::io::Error::last_os_error();
                if err.raw_os_error() == Some(4) { // EINTR
                    continue;
                }
                println!("Error reading fanotify events: {}", err);
                break;
            }

            let mut offset = 0;
            while offset + mem::size_of::<FanotifyEventMetadata>() <= n as usize {
                let metadata = unsafe {
                    ptr::read_unaligned(buf.as_ptr().add(offset) as *const FanotifyEventMetadata)
                };

                if metadata.mask & FAN_ACCESS != 0 {
                    if !read_led_on {
                        ft232h.set_pin(read_pin_idx, true)?;
                        read_led_on = true;
                    }
                    last_read_event = Some(Instant::now());
                }
                if metadata.mask & FAN_MODIFY != 0 {
                    if !write_led_on {
                        ft232h.set_pin(write_pin_idx, true)?;
                        write_led_on = true;
                    }
                    last_write_event = Some(Instant::now());
                }

                if metadata.fd >= 0 {
                    unsafe { libc::close(metadata.fd); }
                }

                if metadata.event_len < mem::size_of::<FanotifyEventMetadata>() as u32 {
                    break;
                }
                offset += metadata.event_len as usize;
            }
        } else {
            // Timeout reached, turn off LEDs
            let now = Instant::now();
            if read_led_on {
                if let Some(last) = last_read_event {
                    if now.duration_since(last) >= flash_duration {
                        let _ = ft232h.set_pin(read_pin_idx, false);
                        read_led_on = false;
                    }
                }
            }
            if write_led_on {
                if let Some(last) = last_write_event {
                    if now.duration_since(last) >= flash_duration {
                        let _ = ft232h.set_pin(write_pin_idx, false);
                        write_led_on = false;
                    }
                }
            }
        }
    }

    Ok(())
}
