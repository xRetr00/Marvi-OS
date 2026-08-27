//! One microphone, 16 kHz mono, into a channel.
//!
//! cpal rather than raw WASAPI: this has to survive a headset being unplugged
//! mid-sentence, a default device changing under it, and a machine where the
//! only input is 48 kHz stereo. That is a lot of platform behaviour to reimplement
//! for a program whose actual job is three matrix multiplications.
//!
//! ## Named, never numbered
//!
//! Device indices are assigned in enumeration order and move when a headset is
//! plugged in or Windows reorders its endpoints, so an index saved today points
//! at something else next week. The daemon learned this and resolved by name;
//! so does this.
//!
//! ## Resampling
//!
//! The models want 16 kHz. Most microphones offer 44.1 or 48 kHz and nothing
//! else, so the input stream runs at whatever the device supports and the
//! samples are decimated here. Linear, because the signal is already band
//! limited by the time it matters and the wake model is not a mastering chain.

use std::sync::mpsc::{Receiver, SyncSender};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Device, SampleFormat, Stream, StreamConfig};

use crate::detector::SAMPLE_RATE;

/// Enough room for a few hops. Full means the detector fell behind, and the
/// right answer then is to drop audio rather than grow without limit -- a
/// wake word that lags further behind reality every minute is worse than one
/// that missed a word.
const QUEUE: usize = 8;

pub struct Microphone {
    /// Held because dropping it stops the stream.
    _stream: Stream,
    pub name: String,
    pub samples: Receiver<Vec<i16>>,
}

fn choose(wanted: &str) -> Option<Device> {
    let host = cpal::default_host();
    let wanted = wanted.trim();
    if !wanted.is_empty() {
        if let Ok(mut devices) = host.input_devices() {
            if let Some(found) =
                devices.find(|device| device.name().map(|name| name == wanted).unwrap_or(false))
            {
                return Some(found);
            }
        }
        // A chosen device that has gone away must not silence the wake word
        // for good. The default is a worse answer than the one asked for and a
        // far better one than nothing.
        eprintln!("microphone {wanted:?} is unavailable; using the default");
    }
    host.default_input_device()
}

/// Open a microphone and start delivering 16 kHz mono blocks.
pub fn open(wanted: &str) -> Result<Microphone, String> {
    let device = choose(wanted).ok_or_else(|| "no usable microphone".to_string())?;
    let name = device.name().unwrap_or_else(|_| "unknown".into());
    let supported = device
        .default_input_config()
        .map_err(|error| format!("{name}: {error}"))?;
    let rate = supported.sample_rate().0;
    let channels = supported.channels() as usize;
    let format = supported.sample_format();
    let config: StreamConfig = supported.into();

    let (sender, receiver) = std::sync::mpsc::sync_channel::<Vec<i16>>(QUEUE);
    let stride = (rate as f32 / SAMPLE_RATE as f32).max(1.0);

    // The callback runs on the audio thread. It must not allocate much, must
    // not block, and must never panic -- a panic there takes the stream down
    // with no way to report why.
    let deliver = move |mono: Vec<i16>| {
        let _ = sender.try_send(mono);
    };
    let stream = match format {
        SampleFormat::I16 => build(&device, &config, channels, stride, deliver, |s: i16| s),
        SampleFormat::F32 => build(&device, &config, channels, stride, deliver, |s: f32| {
            (s.clamp(-1.0, 1.0) * 32_767.0) as i16
        }),
        SampleFormat::U16 => build(&device, &config, channels, stride, deliver, |s: u16| {
            (i32::from(s) - 32_768) as i16
        }),
        other => return Err(format!("{name}: unsupported sample format {other:?}")),
    }
    .map_err(|error| format!("{name}: {error}"))?;

    stream.play().map_err(|error| format!("{name}: {error}"))?;
    Ok(Microphone { _stream: stream, name, samples: receiver })
}

fn build<T, F>(
    device: &Device,
    config: &StreamConfig,
    channels: usize,
    stride: f32,
    deliver: impl Fn(Vec<i16>) + Send + 'static,
    convert: F,
) -> Result<Stream, cpal::BuildStreamError>
where
    T: cpal::SizedSample + Send + 'static,
    F: Fn(T) -> i16 + Send + 'static,
{
    let mut carry = 0.0f32;
    device.build_input_stream(
        config,
        move |data: &[T], _: &cpal::InputCallbackInfo| {
            // First channel only. Mixing would be more faithful and the models
            // were trained on one microphone, not on a room sum.
            let mut mono = Vec::with_capacity(data.len() / channels);
            let mut position = carry;
            let frames = data.len() / channels.max(1);
            while (position as usize) < frames {
                let index = position as usize * channels;
                mono.push(convert(data[index]));
                position += stride;
            }
            carry = position - frames as f32;
            if !mono.is_empty() {
                deliver(mono);
            }
        },
        move |error| eprintln!("microphone error: {error}"),
        None,
    )
}

/// The microphone Windows would pick, which is what this opens when nothing
/// is chosen. Reported rather than inferred: the enumeration order is not the
/// preference order, and labelling the first device "default" put a game
/// controller at the top of the settings picker.
pub fn default_microphone() -> String {
    cpal::default_host()
        .default_input_device()
        .and_then(|device| device.name().ok())
        .unwrap_or_default()
}

/// Every input device, by name, for the settings page.
pub fn microphones() -> Vec<String> {
    cpal::default_host()
        .input_devices()
        .map(|devices| devices.filter_map(|device| device.name().ok()).collect())
        .unwrap_or_default()
}

pub type Blocks = SyncSender<Vec<i16>>;
