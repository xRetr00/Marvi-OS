#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

mod animation;

#[cfg(windows)]
mod windows_host;

#[cfg(windows)]
fn main() {
    if let Err(error) = windows_host::run() {
        eprintln!("marvi-pet-host: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(windows))]
fn main() {
    eprintln!("marvi-pet-host is currently a Windows-only spike");
    std::process::exit(1);
}
