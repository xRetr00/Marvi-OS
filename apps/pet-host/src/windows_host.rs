use std::{
    collections::HashMap,
    env,
    ffi::c_void,
    io::{self, BufRead, Write},
    path::PathBuf,
    ptr::{null, null_mut},
    sync::{Arc, Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
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
        Input::KeyboardAndMouse::{ReleaseCapture, SetCapture},
        WindowsAndMessaging::{
            CreateWindowExW, DefWindowProcW, DispatchMessageW, GetCursorPos, GetMessageW,
            GetWindowRect, KillTimer, PostMessageW, PostQuitMessage, RegisterClassW, SetTimer,
            SetWindowPos, ShowWindow, SystemParametersInfoW, UpdateLayeredWindow, CS_HREDRAW,
            CS_VREDRAW, HTCLIENT, HTTRANSPARENT, HWND_TOPMOST, MSG, SPI_GETCLIENTAREAANIMATION,
            SWP_NOACTIVATE, SW_SHOWNA, ULW_ALPHA, WM_APP, WM_DESTROY, WM_LBUTTONDOWN, WM_LBUTTONUP,
            WM_MOUSEMOVE, WM_MOVE, WM_NCHITTEST, WM_TIMER, WNDCLASSW, WS_EX_LAYERED,
            WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_POPUP,
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
        #[serde(rename = "taskCount", default)]
        task_count: u32,
    },
    Look {
        direction: Option<i32>,
    },
    Hover {
        hover: bool,
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
    task_count: u32,
    look: Option<i32>,
    hover: bool,
    frame_index: usize,
    motion_enabled: bool,
    bounds: RECT,
    exit_requested: bool,
    completion_until: Option<Instant>,
    hit_alpha: Vec<u8>,
    drag: Option<DragState>,
}

#[derive(Clone, Copy)]
struct DragState {
    cursor: POINT,
    window: POINT,
}

impl App {
    fn current_frame(&self) -> Frame {
        self.look
            .map(gaze_frame)
            .unwrap_or_else(|| animation_frame(self.phase, self.frame_index))
    }

    fn cached_frame(&mut self, frame: Frame) -> &CachedFrame {
        let width = self.bounds.right - self.bounds.left;
        let height = sprite_height(width, self.bounds.bottom - self.bounds.top);
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PetAction {
    Voice,
    Tasks,
}

fn sprite_height(width: i32, window_height: i32) -> i32 {
    ((width * CELL_HEIGHT as i32 + CELL_WIDTH as i32 / 2) / CELL_WIDTH as i32)
        .clamp(1, window_height)
}

fn button_geometry(width: i32, height: i32) -> Option<[(i32, i32, i32); 2]> {
    let sprite = sprite_height(width, height);
    let controls = height - sprite;
    if controls < 18 {
        return None;
    }
    let radius = (width / 9).clamp(8, 14).min((controls - 4) / 2);
    let center_y = sprite + controls / 2;
    let offset = radius + 4;
    Some([
        (width / 2 - offset, center_y, radius),
        (width / 2 + offset, center_y, radius),
    ])
}

fn hit_test_button(width: i32, height: i32, x: i32, y: i32) -> Option<PetAction> {
    let buttons = button_geometry(width, height)?;
    buttons
        .iter()
        .enumerate()
        .find_map(|(index, &(cx, cy, radius))| {
            let dx = x - cx;
            let dy = y - cy;
            (dx * dx + dy * dy <= radius * radius).then_some(if index == 0 {
                PetAction::Voice
            } else {
                PetAction::Tasks
            })
        })
}

fn hit_test_alpha(alpha: &[u8], width: i32, height: i32, x: i32, y: i32) -> bool {
    if x < 0 || y < 0 || x >= width || y >= height {
        return false;
    }
    alpha
        .get((y * width + x) as usize)
        .is_some_and(|value| *value >= 24)
}

fn drag_position(drag: DragState, cursor: POINT) -> POINT {
    POINT {
        x: drag.window.x + cursor.x - drag.cursor.x,
        y: drag.window.y + cursor.y - drag.cursor.y,
    }
}

fn active_phase(phase: Phase) -> bool {
    matches!(phase, Phase::Thinking | Phase::Action | Phase::Confirmation)
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

fn set_pixel(pixels: &mut [u8], width: i32, height: i32, x: i32, y: i32, color: [u8; 4]) {
    if x < 0 || y < 0 || x >= width || y >= height {
        return;
    }
    let index = ((y * width + x) * 4) as usize;
    pixels[index..index + 4].copy_from_slice(&color);
}

fn fill_rect(
    pixels: &mut [u8],
    width: i32,
    height: i32,
    rect: (i32, i32, i32, i32),
    color: [u8; 4],
) {
    let (left, top, right, bottom) = rect;
    for y in top.max(0)..bottom.min(height) {
        for x in left.max(0)..right.min(width) {
            set_pixel(pixels, width, height, x, y, color);
        }
    }
}

fn fill_rounded_rect(
    pixels: &mut [u8],
    width: i32,
    height: i32,
    rect: (i32, i32, i32, i32),
    color: [u8; 4],
) {
    let (left, top, right, bottom) = rect;
    let radius = ((bottom - top) / 2).max(1);
    fill_rect(pixels, width, height, rect, [0, 0, 0, 0]);
    for y in top.max(0)..bottom.min(height) {
        let edge_distance = (y - top).min(bottom - 1 - y);
        let inset = (radius - edge_distance - 1).max(0);
        for x in (left + inset).max(0)..(right - inset).min(width) {
            set_pixel(pixels, width, height, x, y, color);
        }
    }
}

fn fill_circle(
    pixels: &mut [u8],
    width: i32,
    height: i32,
    cx: i32,
    cy: i32,
    radius: i32,
    color: [u8; 4],
) {
    for y in (cy - radius).max(0)..=(cy + radius).min(height - 1) {
        for x in (cx - radius).max(0)..=(cx + radius).min(width - 1) {
            let dx = x - cx;
            let dy = y - cy;
            if dx * dx + dy * dy <= radius * radius {
                set_pixel(pixels, width, height, x, y, color);
            }
        }
    }
}

fn draw_voice_icon(pixels: &mut [u8], width: i32, height: i32, cx: i32, cy: i32) {
    let color = [235, 235, 235, 255];
    for (offset, bar_height) in [(-6, 4), (-3, 8), (0, 12), (3, 8), (6, 4)] {
        fill_rounded_rect(
            pixels,
            width,
            height,
            (
                cx + offset,
                cy - bar_height / 2,
                cx + offset + 2,
                cy + (bar_height + 1) / 2,
            ),
            color,
        );
    }
}

fn draw_task_icon(pixels: &mut [u8], width: i32, height: i32, cx: i32, cy: i32, count: u32) {
    let color = [235, 235, 235, 255];
    if count == 0 {
        for row in 0..3 {
            let y = cy - 5 + row * 5;
            fill_rect(pixels, width, height, (cx - 6, y, cx - 4, y + 2), color);
            fill_rect(pixels, width, height, (cx - 2, y, cx + 6, y + 2), color);
        }
        return;
    }

    const DIGITS: [[u8; 5]; 10] = [
        [0b111, 0b101, 0b101, 0b101, 0b111],
        [0b010, 0b110, 0b010, 0b010, 0b111],
        [0b111, 0b001, 0b111, 0b100, 0b111],
        [0b111, 0b001, 0b111, 0b001, 0b111],
        [0b101, 0b101, 0b111, 0b001, 0b001],
        [0b111, 0b100, 0b111, 0b001, 0b111],
        [0b111, 0b100, 0b111, 0b101, 0b111],
        [0b111, 0b001, 0b010, 0b010, 0b010],
        [0b111, 0b101, 0b111, 0b101, 0b111],
        [0b111, 0b101, 0b111, 0b001, 0b111],
    ];
    let glyph = DIGITS[count.min(9) as usize];
    for (row, bits) in glyph.iter().enumerate() {
        for column in 0..3 {
            if bits & (1 << (2 - column)) != 0 {
                fill_rect(
                    pixels,
                    width,
                    height,
                    (
                        cx - 3 + column * 2,
                        cy - 5 + row as i32 * 2,
                        cx - 1 + column * 2,
                        cy - 3 + row as i32 * 2,
                    ),
                    color,
                );
            }
        }
    }
}

fn draw_overlay(state: &App, pixels: &mut [u8], width: i32, height: i32) {
    let sprite = sprite_height(width, height);
    let now = Instant::now();
    let status = if state.phase == Phase::Error {
        [91, 91, 216, 255] // #d85b5b danger, stored as BGRA
    } else if state.phase == Phase::Notification
        || state.completion_until.is_some_and(|until| until > now)
    {
        [102, 196, 65, 255]
    } else if matches!(
        state.phase,
        Phase::Wake | Phase::Thinking | Phase::Speaking | Phase::Action | Phase::Confirmation
    ) {
        [193, 126, 20, 255] // #147ec1 signal
    } else {
        [99, 91, 82, 255]
    };
    let line_width = (width / 4).clamp(18, 32);
    let line_height = (width / 24).clamp(4, 6);
    let line_y = sprite - line_height - 2;
    fill_rounded_rect(
        pixels,
        width,
        height,
        (
            (width - line_width) / 2,
            line_y,
            (width + line_width) / 2,
            line_y + line_height,
        ),
        status,
    );

    if !state.hover {
        return;
    }
    let Some(buttons) = button_geometry(width, height) else {
        return;
    };
    for &(cx, cy, radius) in &buttons {
        fill_circle(pixels, width, height, cx, cy, radius, [100, 100, 100, 255]);
        fill_circle(pixels, width, height, cx, cy, radius - 1, [31, 31, 31, 255]);
    }

    let (voice_x, voice_y, _) = buttons[0];
    draw_voice_icon(pixels, width, height, voice_x, voice_y);

    let (task_x, task_y, _) = buttons[1];
    draw_task_icon(pixels, width, height, task_x, task_y, state.task_count);
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

fn emit_event(value: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{value}");
    let _ = stdout.flush();
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
        task_count: 0,
        look: None,
        hover: false,
        frame_index: 0,
        motion_enabled: client_area_animation_enabled(),
        bounds,
        exit_requested: false,
        completion_until: None,
        hit_alpha: Vec::new(),
        drag: None,
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
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
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
        emit_event("{\"type\":\"ready\"}");

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
                        Command::State { phase, task_count } => {
                            if active_phase(state.phase) && phase == Phase::Ready {
                                state.completion_until =
                                    Some(Instant::now() + Duration::from_secs(2));
                            }
                            state.phase = phase;
                            state.task_count = task_count.min(9);
                            state.frame_index = 0;
                        }
                        Command::Look { direction } => {
                            state.look = direction;
                            state.frame_index = 0;
                        }
                        Command::Hover { hover } => state.hover = hover,
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
                if state
                    .completion_until
                    .is_some_and(|until| until <= Instant::now())
                {
                    state.completion_until = None;
                }
                if state.look.is_none() && state.motion_enabled {
                    state.frame_index += 1;
                }
            }
            let _ = render(hwnd);
            arm_timer(hwnd);
            0
        }
        WM_NCHITTEST => {
            let Some(app) = APP.get() else {
                return HTTRANSPARENT as LRESULT;
            };
            let state = app.lock().expect("pet model poisoned");
            let screen_x = (lparam as u32 & 0xffff) as u16 as i16 as i32;
            let screen_y = ((lparam as u32 >> 16) & 0xffff) as u16 as i16 as i32;
            let mut actual_bounds: RECT = std::mem::zeroed();
            if GetWindowRect(hwnd, &mut actual_bounds) == 0 {
                return HTTRANSPARENT as LRESULT;
            }
            let width = actual_bounds.right - actual_bounds.left;
            let height = actual_bounds.bottom - actual_bounds.top;
            let local_x = screen_x - actual_bounds.left;
            let local_y = screen_y - actual_bounds.top;
            let control = state.hover && hit_test_button(width, height, local_x, local_y).is_some();
            if control || hit_test_alpha(&state.hit_alpha, width, height, local_x, local_y) {
                HTCLIENT as LRESULT
            } else {
                HTTRANSPARENT as LRESULT
            }
        }
        WM_LBUTTONDOWN => {
            let Some(app) = APP.get() else { return 0 };
            let mut state = app.lock().expect("pet model poisoned");
            let width = state.bounds.right - state.bounds.left;
            let height = state.bounds.bottom - state.bounds.top;
            let x = (lparam as u32 & 0xffff) as u16 as i16 as i32;
            let y = ((lparam as u32 >> 16) & 0xffff) as u16 as i16 as i32;
            if hit_test_button(width, height, x, y).is_none()
                && hit_test_alpha(&state.hit_alpha, width, height, x, y)
            {
                let mut cursor: POINT = std::mem::zeroed();
                if GetCursorPos(&mut cursor) != 0 {
                    state.drag = Some(DragState {
                        cursor,
                        window: POINT {
                            x: state.bounds.left,
                            y: state.bounds.top,
                        },
                    });
                    SetCapture(hwnd);
                }
            }
            0
        }
        WM_MOUSEMOVE => {
            if wparam & 1 == 0 {
                return 0;
            }
            let Some(app) = APP.get() else { return 0 };
            let drag = app.lock().expect("pet model poisoned").drag;
            if let Some(drag) = drag {
                let mut cursor: POINT = std::mem::zeroed();
                if GetCursorPos(&mut cursor) != 0 {
                    let position = drag_position(drag, cursor);
                    SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        position.x,
                        position.y,
                        0,
                        0,
                        SWP_NOACTIVATE | windows_sys::Win32::UI::WindowsAndMessaging::SWP_NOSIZE,
                    );
                }
            }
            0
        }
        WM_LBUTTONUP => {
            let Some(app) = APP.get() else { return 0 };
            let mut state = app.lock().expect("pet model poisoned");
            if state.drag.take().is_some() {
                ReleaseCapture();
                emit_event(&format!(
                    "{{\"type\":\"moved\",\"x\":{},\"y\":{}}}",
                    state.bounds.left, state.bounds.top
                ));
                return 0;
            }
            let width = state.bounds.right - state.bounds.left;
            let height = state.bounds.bottom - state.bounds.top;
            let x = (lparam as u32 & 0xffff) as u16 as i16 as i32;
            let y = ((lparam as u32 >> 16) & 0xffff) as u16 as i16 as i32;
            match hit_test_button(width, height, x, y) {
                Some(PetAction::Voice) => emit_event("{\"type\":\"action\",\"action\":\"voice\"}"),
                Some(PetAction::Tasks) => emit_event("{\"type\":\"action\",\"action\":\"tasks\"}"),
                None => {}
            }
            0
        }
        WM_MOVE => {
            if let Some(app) = APP.get() {
                let mut actual_bounds: RECT = std::mem::zeroed();
                if GetWindowRect(hwnd, &mut actual_bounds) != 0 {
                    app.lock().expect("pet model poisoned").bounds = actual_bounds;
                }
            }
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
            let animation = if state.motion_enabled {
                state.current_frame().duration_ms
            } else {
                0
            };
            let completion = state
                .completion_until
                .and_then(|until| until.checked_duration_since(Instant::now()))
                .map(|remaining| remaining.as_millis().clamp(1, u32::MAX as u128) as u32)
                .unwrap_or(0);
            match (animation, completion) {
                (0, value) | (value, 0) => value,
                (left, right) => left.min(right),
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
    let width = bounds.right - bounds.left;
    let height = bounds.bottom - bounds.top;
    let (sprite_pixels, sprite_width, sprite_height) = {
        let cached = state.cached_frame(frame);
        (cached.pixels.clone(), cached.width, cached.height)
    };
    let mut pixels = vec![0u8; (width * height * 4) as usize];
    for row in 0..sprite_height {
        let source = (row * sprite_width * 4) as usize;
        let destination = (row * width * 4) as usize;
        let length = (sprite_width * 4) as usize;
        pixels[destination..destination + length]
            .copy_from_slice(&sprite_pixels[source..source + length]);
    }
    draw_overlay(&state, &mut pixels, width, height);
    state.hit_alpha = pixels.chunks_exact(4).map(|pixel| pixel[3]).collect();

    let screen_dc = GetDC(null_mut());
    let memory_dc = CreateCompatibleDC(screen_dc);
    let bitmap_info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width,
            biHeight: -height,
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
    std::ptr::copy_nonoverlapping(pixels.as_ptr(), bits.cast::<u8>(), pixels.len());
    let previous = SelectObject(memory_dc, bitmap as HGDIOBJ);
    let destination = POINT {
        x: bounds.left,
        y: bounds.top,
    };
    let source = POINT { x: 0, y: 0 };
    let size = SIZE {
        cx: width,
        cy: height,
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_host_keeps_sprite_and_control_geometry_separate() {
        assert_eq!(sprite_height(96, 136), 104);
        assert_eq!(
            button_geometry(96, 136),
            Some([(34, 120, 10), (62, 120, 10)])
        );
    }

    #[test]
    fn only_visible_control_circles_capture_clicks() {
        assert_eq!(hit_test_button(96, 136, 34, 120), Some(PetAction::Voice));
        assert_eq!(hit_test_button(96, 136, 62, 120), Some(PetAction::Tasks));
        assert_eq!(hit_test_button(96, 136, 48, 120), None);
        assert_eq!(hit_test_button(96, 136, 10, 20), None);
    }

    #[test]
    fn only_rendered_pixels_capture_pet_drags() {
        let alpha = [0, 24, 255, 0];
        assert!(!hit_test_alpha(&alpha, 2, 2, 0, 0));
        assert!(hit_test_alpha(&alpha, 2, 2, 1, 0));
        assert!(hit_test_alpha(&alpha, 2, 2, 0, 1));
        assert!(!hit_test_alpha(&alpha, 2, 2, 2, 1));
    }

    #[test]
    fn drag_position_preserves_the_pointer_offset() {
        let drag = DragState {
            cursor: POINT { x: 120, y: 80 },
            window: POINT { x: 40, y: 20 },
        };
        let position = drag_position(drag, POINT { x: 150, y: 105 });
        assert_eq!((position.x, position.y), (70, 45));
    }

    #[test]
    fn status_indicator_is_a_compact_rounded_pill() {
        let mut pixels = vec![255u8; 24 * 4 * 4];
        fill_rounded_rect(&mut pixels, 24, 4, (0, 0, 24, 4), [1, 2, 3, 255]);
        assert_eq!(&pixels[0..4], &[0, 0, 0, 0]);
        assert_eq!(&pixels[4..8], &[1, 2, 3, 255]);
        assert_eq!(&pixels[(23 * 4)..(24 * 4)], &[0, 0, 0, 0]);
        assert_eq!(&pixels[(24 * 4)..(25 * 4)], &[1, 2, 3, 255]);
    }
}
