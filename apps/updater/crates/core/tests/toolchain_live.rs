//! Does the toolchain provisioning actually work?
//!
//! This is a network test, ignored by default. It exists because the `uv`
//! installer was broken from the day it was written and nobody found out: on a
//! machine that already had `uv`, the code never ran. The unit tests could not
//! catch it, because the bug was in how the command reached the shell.
//!
//!     cargo test -p marvi-bootstrap-core --test toolchain_live -- --ignored

use marvi_bootstrap_core::toolchain::{Tool, ensure_toolchain, status};

#[test]
#[ignore = "downloads uv and Node"]
fn uv_and_node_are_installed_into_the_state_directory() {
    // A narrowed PSModulePath is the condition that broke this in CI: Astral's
    // install script calls `Get-ExecutionPolicy`, and that cmdlet cannot
    // autoload without the system module path. Reproduced here so the fix is
    // exercised on a developer machine too, where PSModulePath is usually fine.
    unsafe {
        std::env::set_var("PSModulePath", r"C:\nonexistent\Modules");
    }

    let state = std::env::temp_dir().join(format!("marvi-toolchain-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&state);
    std::fs::create_dir_all(&state).unwrap();

    let mut lines = Vec::new();
    let paths = ensure_toolchain(&state, "v22.11.0", &mut |line| {
        println!("  {line}");
        lines.push(line.to_string());
    })
    .expect("provisioning failed");

    for tool in [Tool::Uv, Tool::Node] {
        let found = status(&state, tool);
        assert!(found.found, "{} not installed: {}", tool.name(), found.detail);
        assert!(found.managed, "{} was borrowed from PATH", tool.name());
    }
    assert!(!paths.is_empty(), "the build gets no PATH additions");
    assert!(!lines.is_empty(), "the installer reported nothing at all");

    let _ = std::fs::remove_dir_all(&state);
}

/// The handoff, against a real build. Ignored: it writes to the user's PATH
/// and Desktop, which is exactly what makes it worth checking by hand.
///
///     cargo test -p marvi-bootstrap-core --test toolchain_live -- --ignored handoff
#[test]
#[ignore = "writes to the user's PATH and Desktop"]
fn the_handoff_finds_the_built_app_and_installs_the_command() {
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("..");
    let repo = repo.canonicalize().expect("repo root");
    let state = marvi_bootstrap_core::state_dir();

    marvi_bootstrap_core::install_cli_shim(&repo, &state, &mut |line| println!("  {line}"))
        .expect("the marvi command was not installed");
    marvi_bootstrap_core::create_shortcuts(&repo, &mut |line| println!("  {line}"))
        .expect("no shortcut was created");
}
