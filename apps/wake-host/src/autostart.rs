//! Starting at login, and being able to stop.
//!
//! `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — the per-user Run key,
//! which needs no elevation and no scheduled task. The desktop already wrote
//! this entry for the Python daemon; the listener owns it now, because the
//! thing that knows whether it should start at login is the thing that starts.
//!
//! Registered with the executable's own path rather than a path handed in. An
//! update that moves the binary re-registers on next run, which is the failure
//! the daemon had: the entry pointed at an interpreter in a virtual environment
//! several directories away and stopped resolving after a reinstall.

#[cfg(windows)]
mod windows {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    use windows_sys::Win32::Foundation::ERROR_SUCCESS;
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW, HKEY,
        HKEY_CURRENT_USER, KEY_READ, KEY_WRITE, REG_SZ,
    };

    const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
    /// The name the desktop already used, so switching languages does not
    /// leave two entries racing to open the same microphone.
    pub const VALUE: &str = "MarviWakeWord";

    fn wide(text: &str) -> Vec<u16> {
        OsStr::new(text).encode_wide().chain(Some(0)).collect()
    }

    fn open(access: u32) -> Option<HKEY> {
        let mut key: HKEY = std::ptr::null_mut();
        let path = wide(RUN_KEY);
        let status =
            unsafe { RegOpenKeyExW(HKEY_CURRENT_USER, path.as_ptr(), 0, access, &mut key) };
        (status == ERROR_SUCCESS).then_some(key)
    }

    /// What the Run key currently launches, if anything.
    fn registered_command() -> Option<String> {
        let key = open(KEY_READ)?;
        let name = wide(VALUE);
        let mut size = 0u32;
        let status = unsafe {
            RegQueryValueExW(
                key,
                name.as_ptr(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut size,
            )
        };
        if status != ERROR_SUCCESS || size == 0 {
            unsafe { RegCloseKey(key) };
            return None;
        }
        let mut buffer = vec![0u16; (size as usize / 2) + 1];
        let mut length = size;
        let status = unsafe {
            RegQueryValueExW(
                key,
                name.as_ptr(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                buffer.as_mut_ptr() as *mut u8,
                &mut length,
            )
        };
        unsafe { RegCloseKey(key) };
        if status != ERROR_SUCCESS {
            return None;
        }
        let end = buffer.iter().position(|c| *c == 0).unwrap_or(buffer.len());
        Some(String::from_utf16_lossy(&buffer[..end]))
    }

    /// Whether *this* listener is the one registered.
    ///
    /// Not whether the value exists. It already existed, holding the old
    /// `pythonw.exe -m marvi_agent.wake_daemon` command under the same name --
    /// so a plain existence check reports "listening at login" while what
    /// actually starts is the daemon this program replaces. A registration is
    /// not evidence that *this* thing is registered.
    pub fn registered() -> bool {
        let Some(command) = registered_command() else { return false };
        let Ok(exe) = std::env::current_exe() else { return false };
        let Some(name) = exe.file_name().and_then(|n| n.to_str()) else { return false };
        command.to_lowercase().contains(&name.to_lowercase())
    }

    pub fn set(enabled: bool) -> bool {
        let Some(key) = open(KEY_WRITE) else { return false };
        let name = wide(VALUE);
        let status = if enabled {
            let Ok(exe) = std::env::current_exe() else {
                unsafe { RegCloseKey(key) };
                return false;
            };
            // Quoted: the installed path contains spaces on most machines, and
            // an unquoted Run value silently runs the first word of it.
            let command = wide(&format!("\"{}\"", exe.display()));
            unsafe {
                RegSetValueExW(
                    key,
                    name.as_ptr(),
                    0,
                    REG_SZ,
                    command.as_ptr() as *const u8,
                    (command.len() * 2) as u32,
                )
            }
        } else {
            unsafe { RegDeleteValueW(key, name.as_ptr()) }
        };
        unsafe { RegCloseKey(key) };
        status == ERROR_SUCCESS
    }
}

#[cfg(windows)]
pub use windows::{registered, set};

#[cfg(not(windows))]
pub fn registered() -> bool {
    false
}

#[cfg(not(windows))]
pub fn set(_enabled: bool) -> bool {
    false
}
