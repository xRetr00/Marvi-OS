use std::{
    collections::HashMap,
    env,
    ffi::c_void,
    io::{self, BufRead},
    path::PathBuf,
    ptr::{null, null_mut},
    sync::{Arc, Mutex, OnceLock},
    thread,
};

use image::{imageops::FilterType, DynamicImage, GenericImageView, RgbaImage};
use serde::Deserialize;
use windows_sys::Win32::{
    Foundation::{COLORREF, HWND, LPARAM, LRESULT, POINT, RECT, SIZE, WPARAM},
    Graphics::Gdi::{
        CreateCompatibleDC, CreateDIBSection, DeleteDC, DeleteObject, GetDC, ReleaseDC,
        SelectObject, AC_SRC_ALPHA, AC_SRC_OVER, BITMAPINFO, BITMAPINFOHEADER, BI_RGB,
        BLENDFUNCTION, DIB_RGB_COLORS, HBITMAP, HGDIOBJ,
    },
    System::LibraryLoader::GetModuleHandleW,
    UI::{
        HiDpi::{SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2},
        WindowsAndMessaging::{
            CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, KillTimer,
            PostMessageW, PostQuitMessage, RegisterClassW, SetTimer, SetWindowPos, ShowWindow,
            SystemParametersInfoW, UpdateLayeredWindow, CS_HREDRAW, CS_VREDRAW, HWND_TOPMOST, MSG,
            SPI_GETCLIENTAREAANIMATION, SWP_NOACTIVATE, SW_SHOWNA, ULW_ALPHA, WM_APP, WM_DESTROY,
            WM_TIMER, WNDCLASSW, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
            WS_EX_TRANSPARENT, WS_POPUP,
        },
    },
};

use crate::animation::{animation_frame, gaze_frame, Frame, Phase};

const CELL_WIDTH: u32 = 192;
const CELL_HEIGHT: u32 = 208;
const TIMER_ID: usize = 1;
const WM_MODEL_CHANGED: u32 = WM_APP + 1;

static APP: OnceLock<Arc<Mutex<App>>> = OnceLock::new();

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "kebab-case")]
enum Command {
    State {
        phase: Phase,
    },
    Look {
        direction: Option<i32>,
    },
    Bounds {
        x: i32,
        y: i32,
        width: i32,
        height: i32,
    },
    Exit,
}

struct CachedFrame {
    pixels: Vec<u8>,
    width: i32,
    height: i32,
}

struct App {
    atlas: DynamicImage,
    frames: HashMap<(u32, u32, i32, i32), CachedFrame>,
    phase: Phase,
    look: Option<i32>,
    frame_index: usize,
    motion_enabled: bool,
    bounds: RECT,
    exit_requested: bool,
}

impl App {
    fn current_frame(&self) -> Frame {
        self.look
            .map(gaze_frame)
            .unwrap_or_else(|| animation_frame(self.phase, self.frame_index))
    }

    fn cached_frame(&mut self, frame: Frame) -> &CachedFrame {
        let width = self.bounds.right - self.bounds.left;
        let height = self.bounds.bottom - self.bounds.top;
        self.frames
            .entry((frame.row, frame.column, width, height))
            .or_insert_with(|| {
                let crop = self
                    .atlas
                    .crop_imm(
                        frame.column * CELL_WIDTH,
                        frame.row * CELL_HEIGHT,
                        CELL_WIDTH,
                        CELL_HEIGHT,
                    )
                    .to_rgba8();
                let scaled = image::imageops::resize(
                    &crop,
                    width.max(1) as u32,
                    height.max(1) as u32,
                    FilterType::Lanczos3,
                );
                CachedFrame {
                    pixels: premultiplied_bgra(&scaled),
                    width,
                    height,
                }
            })
    }
}

fn premultiplied_bgra(image: &RgbaImage) -> Vec<u8> {
    let mut output = Vec::with_capacity(image.len());
    for pixel in image.pixels() {
        let alpha = pixel[3] as u16;
        output.push(((pixel[2] as u16 * alpha + 127) / 255) as u8);
        output.push(((pixel[1] as u16 * alpha + 127) / 255) as u8);
        output.push(((pixel[0] as u16 * alpha + 127) / 255) as u8);
        output.push(pixel[3]);
    }
    output
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

fn parse_args() -> Result<(PathBuf, RECT), String> {
    let mut atlas = None;
    let mut x = 0;
    let mut y = 0;
    let mut width = 96;
    let mut height = 104;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {arg}"))?;
        match arg.as_str() {
            "--atlas" => atlas = Some(PathBuf::from(value)),
            "--x" => x = value.parse().map_err(|_| "invalid --x")?,
            "--y" => y = value.parse().map_err(|_| "invalid --y")?,
            "--width" => width = value.parse().map_err(|_| "invalid --width")?,
            "--height" => height = value.parse().map_err(|_| "invalid --height")?,
            _ => return Err(format!("unknown argument: {arg}")),
        }
    }
    let atlas = atlas.ok_or("--atlas is required")?;
    if width <= 0 || height <= 0 {
        return Err("window dimensions must be positive".into());
    }
    Ok((
        atlas,
        RECT {
            left: x,
            top: y,
            right: x + width,
            bottom: y + height,
        },
    ))
}

pub fn run() -> Result<(), String> {
    let (atlas_path, bounds) = parse_args()?;
    let atlas = image::open(&atlas_path)
        .map_err(|error| format!("cannot decode {}: {error}", atlas_path.display()))?;
    if atlas.dimensions() != (CELL_WIDTH * 8, CELL_HEIGHT * 11) {
        return Err(format!(
            "atlas must be 1536x2288, got {}x{}",
            atlas.width(),
            atlas.height()
        ));
    }

    let app = Arc::new(Mutex::new(App {
        atlas,
        frames: HashMap::new(),
        phase: Phase::Ready,
        look: None,
        frame_index: 0,
        motion_enabled: client_area_animation_enabled(),
        bounds,
        exit_requested: false,
    }));
    APP.set(app.clone()).map_err(|_| "app initialized twice")?;

    unsafe {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        let instance = GetModuleHandleW(null());
        let class_name = wide("MarviPetHostWindow");
        let class = WNDCLASSW {
            style: CS_HREDRAW | CS_VREDRAW,
            lpfnWndProc: Some(window_proc),
            hInstance: instance,
            lpszClassName: class_name.as_ptr(),
            ..std::mem::zeroed()
        };
        if RegisterClassW(&class) == 0 {
            return Err("RegisterClassW failed".into());
        }

        let hwnd = CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class_name.as_ptr(),
            wide("Marvi Pet").as_ptr(),
            WS_POPUP,
            bounds.left,
            bounds.top,
            bounds.right - bounds.left,
            bounds.bottom - bounds.top,
            null_mut(),
            null_mut(),
            instance,
            null(),
        );
        if hwnd.is_null() {
            return Err("CreateWindowExW failed".into());
        }
        render(hwnd)?;
        ShowWindow(hwnd, SW_SHOWNA);
        arm_timer(hwnd);
        println!("{{\"type\":\"ready\"}}");

        start_stdin_thread(hwnd, app);
        let mut message: MSG = std::mem::zeroed();
        while GetMessageW(&mut message, null_mut(), 0, 0) > 0 {
            DispatchMessageW(&message);
        }
    }
    Ok(())
}

fn start_stdin_thread(hwnd: HWND, app: Arc<Mutex<App>>) {
    let hwnd_value = hwnd as usize;
    thread::spawn(move || {
        let hwnd = hwnd_value as HWND;
        for line in io::stdin().lock().lines() {
            let Ok(line) = line else { break };
            match serde_json::from_str::<Command>(&line) {
                Ok(command) => {
                    let mut state = app.lock().expect("pet model poisoned");
                    match command {
                        Command::State { phase } => {
                            state.phase = phase;
                            state.frame_index = 0;
                        }
                        Command::Look { direction } => {
                            state.look = direction;
                            state.frame_index = 0;
                        }
                        Command::Bounds {
                            x,
                            y,
                            width,
                            height,
                        } if width > 0 && height > 0 => {
                            state.bounds = RECT {
                                left: x,
                                top: y,
                                right: x + width,
                                bottom: y + height,
                            };
                            state
                                .frames
                                .retain(|(_, _, cached_width, cached_height), _| {
                                    *cached_width == width && *cached_height == height
                                });
                        }
                        Command::Bounds { .. } => continue,
                        Command::Exit => state.exit_requested = true,
                    }
                    drop(state);
                    unsafe { PostMessageW(hwnd, WM_MODEL_CHANGED, 0, 0) };
                }
                Err(error) => eprintln!("marvi-pet-host: ignored command: {error}"),
            }
        }
    });
}

fn client_area_animation_enabled() -> bool {
    let mut enabled = 1i32;
    let ok = unsafe {
        SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION,
            0,
            (&mut enabled as *mut i32).cast(),
            0,
        )
    };
    ok == 0 || enabled != 0
}

unsafe extern "system" fn window_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        WM_TIMER => {
            if let Some(app) = APP.get() {
                let mut state = app.lock().expect("pet model poisoned");
                if state.look.is_none() && state.motion_enabled {
                    state.frame_index += 1;
                }
            }
            let _ = render(hwnd);
            arm_timer(hwnd);
            0
        }
        WM_MODEL_CHANGED => {
            let (bounds, exit_requested) = APP
                .get()
                .map(|app| {
                    let state = app.lock().expect("pet model poisoned");
                    (state.bounds, state.exit_requested)
                })
                .unwrap();
            if exit_requested {
                PostQuitMessage(0);
                return 0;
            }
            SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                bounds.left,
                bounds.top,
                bounds.right - bounds.left,
                bounds.bottom - bounds.top,
                SWP_NOACTIVATE,
            );
            let _ = render(hwnd);
            arm_timer(hwnd);
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

unsafe fn arm_timer(hwnd: HWND) {
    KillTimer(hwnd, TIMER_ID);
    let duration = APP
        .get()
        .map(|app| {
            let state = app.lock().expect("pet model poisoned");
            if state.motion_enabled {
                state.current_frame().duration_ms
            } else {
                0
            }
        })
        .unwrap_or(0);
    if duration > 0 {
        SetTimer(hwnd, TIMER_ID, duration, None);
    }
}

unsafe fn render(hwnd: HWND) -> Result<(), String> {
    let app = APP.get().ok_or("app not initialized")?;
    let mut state = app.lock().map_err(|_| "pet model poisoned")?;
    let frame = state.current_frame();
    let bounds = state.bounds;
    let cached = state.cached_frame(frame);

    let screen_dc = GetDC(null_mut());
    let memory_dc = CreateCompatibleDC(screen_dc);
    let bitmap_info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: cached.width,
            biHeight: -cached.height,
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB,
            ..std::mem::zeroed()
        },
        ..std::mem::zeroed()
    };
    let mut bits: *mut c_void = null_mut();
    let bitmap: HBITMAP = CreateDIBSection(
        screen_dc,
        &bitmap_info,
        DIB_RGB_COLORS,
        &mut bits,
        null_mut(),
        0,
    );
    if bitmap.is_null() || bits.is_null() {
        if !memory_dc.is_null() {
            DeleteDC(memory_dc);
        }
        if !screen_dc.is_null() {
            ReleaseDC(null_mut(), screen_dc);
        }
        return Err("CreateDIBSection failed".into());
    }
    std::ptr::copy_nonoverlapping(
        cached.pixels.as_ptr(),
        bits.cast::<u8>(),
        cached.pixels.len(),
    );
    let previous = SelectObject(memory_dc, bitmap as HGDIOBJ);
    let destination = POINT {
        x: bounds.left,
        y: bounds.top,
    };
    let source = POINT { x: 0, y: 0 };
    let size = SIZE {
        cx: cached.width,
        cy: cached.height,
    };
    let blend = BLENDFUNCTION {
        BlendOp: AC_SRC_OVER as u8,
        BlendFlags: 0,
        SourceConstantAlpha: 255,
        AlphaFormat: AC_SRC_ALPHA as u8,
    };
    let ok = UpdateLayeredWindow(
        hwnd,
        screen_dc,
        &destination,
        &size,
        memory_dc,
        &source,
        COLORREF::default(),
        &blend,
        ULW_ALPHA,
    );
    SelectObject(memory_dc, previous);
    DeleteObject(bitmap as HGDIOBJ);
    DeleteDC(memory_dc);
    ReleaseDC(null_mut(), screen_dc);
    if ok == 0 {
        Err("UpdateLayeredWindow failed".into())
    } else {
        Ok(())
    }
}
