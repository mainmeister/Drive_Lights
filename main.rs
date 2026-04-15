use std::env;
use std::ffi::CString;
use std::io::{self};
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::Duration;

use clap::Parser;
use dotenvy::dotenv;
use log::{error, info, LevelFilter};
use rppal::gpio::{Gpio};

// Fanotify constants from <sys/fanotify.h>
const FAN_CLASS_NOTIF: u32 = 0x00000000;
const FAN_MARK_ADD: u32 = 0x00000001;
const FAN_MARK_MOUNT: u32 = 0x00000010;
const FAN_ACCESS: u64 = 0x00000001;
const FAN_MODIFY: u64 = 0x00000002;
const FAN_EVENT_METADATA_LEN: usize = std::mem::size_of::<libc::fanotify_event_metadata>();

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// The mount point to monitor
    #[arg(default_value = "/")]
    mount_point: String,

    /// Enable debug logging
    #[arg(short, long)]
    debug: bool,
}

struct Config {
    read_pin: u8,
    write_pin: u8,
    mount_point: String,
    blink_duration: Duration,
}

impl Config {
    fn from_env_and_args(args: &Args) -> Self {
        dotenv().ok();
        let read_pin = env::var("READ_LED")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(20);
        let write_pin = env::var("WRITE_LED")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(21);
        
        Config {
            read_pin,
            write_pin,
            mount_point: args.mount_point.clone(),
            blink_duration: Duration::from_millis(10),
        }
    }
}

enum LedMessage {
    BlinkRead,
    BlinkWrite,
}

fn start_led_controller(config: &Config) -> Result<Sender<LedMessage>, String> {
    let (tx, rx) = mpsc::channel::<LedMessage>();
    let read_pin_num = config.read_pin;
    let write_pin_num = config.write_pin;
    let blink_duration = config.blink_duration;

    thread::spawn(move || {
        let gpio = match Gpio::new() {
            Ok(g) => g,
            Err(e) => {
                error!("Failed to initialize GPIO: {}", e);
                return;
            }
        };

        let mut read_led = match gpio.get(read_pin_num).map(|p| p.into_output()) {
            Ok(p) => p,
            Err(e) => {
                error!("Failed to get pin {}: {}", read_pin_num, e);
                return;
            }
        };

        let mut write_led = match gpio.get(write_pin_num).map(|p| p.into_output()) {
            Ok(p) => p,
            Err(e) => {
                error!("Failed to get pin {}: {}", write_pin_num, e);
                return;
            }
        };

        info!("LED Controller started with pins: read={}, write={}", read_pin_num, write_pin_num);

        while let Ok(msg) = rx.recv() {
            match msg {
                LedMessage::BlinkRead => {
                    read_led.set_high();
                    thread::sleep(blink_duration);
                    read_led.set_low();
                }
                LedMessage::BlinkWrite => {
                    write_led.set_high();
                    thread::sleep(blink_duration);
                    write_led.set_low();
                }
            }
            // Simple drain to avoid excessive blinking if events are too frequent
            while let Ok(_) = rx.try_recv() {}
        }
    });

    Ok(tx)
}

fn main() -> io::Result<()> {
    let args = Args::parse();
    
    let log_level = if args.debug {
        LevelFilter::Debug
    } else {
        LevelFilter::Info
    };
    
    env_logger::Builder::new()
        .filter(None, log_level)
        .init();

    let config = Config::from_env_and_args(&args);

    let led_tx = match start_led_controller(&config) {
        Ok(tx) => tx,
        Err(e) => {
            error!("Failed to start LED controller: {}", e);
            return Err(io::Error::new(io::ErrorKind::Other, e));
        }
    };

    let fd = unsafe { libc::fanotify_init(FAN_CLASS_NOTIF, libc::O_RDONLY as u32) };
    if fd < 0 {
        let err = io::Error::last_os_error();
        error!("Failed to initialize fanotify: {}. Ensure you have CAP_SYS_ADMIN capabilities.", err);
        return Err(err);
    }

    let mount_point_cstr = CString::new(config.mount_point.clone()).unwrap();
    let mask = (FAN_ACCESS | FAN_MODIFY) as u64;
    let mark_res = unsafe {
        libc::fanotify_mark(
            fd,
            FAN_MARK_ADD | FAN_MARK_MOUNT,
            mask,
            libc::AT_FDCWD,
            mount_point_cstr.as_ptr(),
        )
    };

    if mark_res < 0 {
        let err = io::Error::last_os_error();
        error!("Failed to mark mount point {}: {}", config.mount_point, err);
        unsafe { libc::close(fd) };
        return Err(err);
    }

    info!("Monitoring {}... Press Ctrl+C to stop.", config.mount_point);

    let mut buffer = [0u8; 4096];
    loop {
        let bytes_read = unsafe { libc::read(fd, buffer.as_mut_ptr() as *mut libc::c_void, buffer.len()) };
        if bytes_read < 0 {
            let err = io::Error::last_os_error();
            error!("Error reading from fanotify fd: {}", err);
            break;
        }

        let mut offset = 0;
        while offset + FAN_EVENT_METADATA_LEN <= bytes_read as usize {
            let metadata = unsafe {
                &*(buffer.as_ptr().add(offset) as *const libc::fanotify_event_metadata)
            };

            if metadata.fd >= 0 {
                if (metadata.mask & FAN_MODIFY) != 0 {
                    let _ = led_tx.send(LedMessage::BlinkWrite);
                } else if (metadata.mask & FAN_ACCESS) != 0 {
                    let _ = led_tx.send(LedMessage::BlinkRead);
                }
                unsafe { libc::close(metadata.fd) };
            }

            offset += metadata.event_len as usize;
        }
    }

    unsafe { libc::close(fd) };
    Ok(())
}
