//! Marvi Bootstrap entrypoint: a tiny installer + updater for Marvi OS.
//!
//! Three modes:
//! - `check`   headless: print update availability as JSON on stdout.
//! - `update`  windowed: fast-forward / checkout the channel target, rebuild,
//!             relaunch. Handed off from the Electron app.
//! - `install` windowed: clone + build + atomically swap into place.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod cli;

use cli::Mode;

fn main() {
    let args = match cli::parse(std::env::args().skip(1)) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2);
        }
    };

    match args.mode {
        Mode::Check => run_check(&args),
        Mode::Update | Mode::Install => app::run(args),
    }
}

fn run_check(args: &cli::Cli) {
    let out = marvi_bootstrap_core::check(std::path::Path::new(&args.install_root), args.channel);
    println!("{}", serde_json::to_string(&out).unwrap_or_else(|_| "{}".into()));
    if out.error.is_some() {
        std::process::exit(2);
    }
}
