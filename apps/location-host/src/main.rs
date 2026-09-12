use serde_json::{json, Value};
use windows::{
    core::HSTRING,
    Devices::Geolocation::{GeolocationAccessStatus, Geolocator, PositionAccuracy},
    Foundation::TimeSpan,
    Security::Authorization::AppCapabilityAccess::{AppCapability, AppCapabilityAccessStatus},
    Win32::System::WinRT::{RoInitialize, RO_INIT_MULTITHREADED},
};

fn locate(request: bool) -> windows::core::Result<Value> {
    unsafe { RoInitialize(RO_INIT_MULTITHREADED)? };
    // Only the explicit foreground action may display Windows consent. Passive
    // refreshes check first, so startup/revocation never creates a prompt.
    let allowed = if request {
        Geolocator::RequestAccessAsync()?.join()? == GeolocationAccessStatus::Allowed
    } else {
        AppCapability::Create(&HSTRING::from("location"))?.CheckAccess()?
            == AppCapabilityAccessStatus::Allowed
    };
    if !allowed {
        return Ok(json!({"status": "denied"}));
    }
    let locator = Geolocator::new()?;
    locator.SetDesiredAccuracy(PositionAccuracy::Default)?;
    let position = locator
        .GetGeopositionAsyncWithAgeAndTimeout(
            TimeSpan {
                Duration: 60 * 10_000_000,
            },
            TimeSpan {
                Duration: 20 * 10_000_000,
            },
        )?
        .join()?;
    let coord = position.Coordinate()?;
    let point = coord.Point()?.Position()?;
    Ok(json!({
        "status": "ready",
        "latitude": point.Latitude,
        "longitude": point.Longitude,
        "accuracy_m": coord.Accuracy()?,
        "timestamp": (coord.Timestamp()?.UniversalTime - 116_444_736_000_000_000_i64) as f64 / 10_000_000.0,
        "source": match coord.PositionSource()?.0 {
            0 => "Windows cellular", 1 => "Windows satellite", 2 => "Windows Wi-Fi",
            3 => "Windows IP address", 5 => "Windows default location",
            6 => "Windows coarse location", _ => "Windows location",
        },
    }))
}

fn main() {
    let request = std::env::args().nth(1).as_deref() == Some("--request");
    let result = locate(request).unwrap_or_else(|error| {
        let status = if error.code().0 as u32 == 0x80070005 {
            "denied"
        } else {
            "unavailable"
        };
        json!({"status": status})
    });
    println!("{result}");
}
