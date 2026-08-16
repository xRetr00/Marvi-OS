//! Minimal CLI parser for the bootstrap binary.
//!
//! Contract (kept in sync with `apps/desktop/src/main/updater.ts`):
//!
//! ```text
//! marvi-bootstrap.exe check   --install-root <dir> --channel release|dev
//! marvi-bootstrap.exe update  --install-root <dir> --channel release|dev
//!                             --desktop-pid <pid> [--relaunch-exe <path>] [--no-relaunch]
//! marvi-bootstrap.exe install --install-root <dir> --channel release|dev
//!                             [--repo <url>] [--relaunch-exe <path>]
//! ```

use marvi_bootstrap_core::Channel;

pub const DEFAULT_REPO: &str = "https://github.com/xRetr00/Marvi-OS.git";

/// Default install location for the no-argument installer path.
pub fn default_install_root() -> String {
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| ".".to_string());
    format!("{}\\Marvi OS\\install", base.trim_end_matches('\\'))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Check,
    Update,
    Install,
}

#[derive(Debug, Clone)]
pub struct Cli {
    pub mode: Mode,
    pub install_root: String,
    pub channel: Channel,
    pub repo: String,
    pub desktop_pid: Option<u32>,
    pub relaunch_exe: Option<String>,
    pub no_relaunch: bool,
}

impl Cli {
    pub fn usage() -> String {
        "usage: marvi-bootstrap (check|update|install) --install-root <dir> --channel <release|dev> [options]"
            .to_string()
    }
}

/// Parse argv (without the program name). Returns an error string on failure.
pub fn parse<I: IntoIterator<Item = String>>(args: I) -> Result<Cli, String> {
    let args: Vec<String> = args.into_iter().collect();
    if args.is_empty() {
        // Double-clicked with no arguments: behave like an installer into the
        // default per-user location (no elevation required).
        return Ok(Cli {
            mode: Mode::Install,
            install_root: default_install_root(),
            channel: Channel::Release,
            repo: DEFAULT_REPO.to_string(),
            desktop_pid: None,
            relaunch_exe: None,
            no_relaunch: false,
        });
    }

    let mode = match args[0].as_str() {
        "check" => Mode::Check,
        "update" => Mode::Update,
        "install" => Mode::Install,
        other => return Err(format!("unknown mode {other:?}\n{}", Cli::usage())),
    };

    let mut install_root: Option<String> = None;
    let mut channel: Option<Channel> = None;
    let mut repo: Option<String> = None;
    let mut desktop_pid: Option<u32> = None;
    let mut relaunch_exe: Option<String> = None;
    let mut no_relaunch = false;

    let mut i = 1;
    while i < args.len() {
        let key = args[i].as_str();
        let mut value = || -> Result<String, String> {
            i += 1;
            args.get(i)
                .cloned()
                .ok_or_else(|| format!("missing value for {key}"))
        };
        match key {
            "--install-root" => install_root = Some(value()?),
            "--channel" => {
                let v = value()?;
                channel = Some(
                    Channel::parse(&v)
                        .ok_or_else(|| format!("unknown channel {v:?} (expected release|dev)"))?,
                );
            }
            "--repo" => repo = Some(value()?),
            "--desktop-pid" => {
                let v = value()?;
                desktop_pid = Some(
                    v.parse()
                        .map_err(|_| format!("invalid --desktop-pid {v:?}"))?,
                );
            }
            "--relaunch-exe" => relaunch_exe = Some(value()?),
            "--no-relaunch" => no_relaunch = true,
            other => return Err(format!("unknown option {other:?}\n{}", Cli::usage())),
        }
        i += 1;
    }

    let install_root =
        install_root.ok_or_else(|| format!("--install-root is required\n{}", Cli::usage()))?;
    let channel = channel.unwrap_or_default();

    Ok(Cli {
        mode,
        install_root,
        channel,
        repo: repo.unwrap_or_else(|| DEFAULT_REPO.to_string()),
        desktop_pid,
        relaunch_exe,
        no_relaunch,
    })
}
