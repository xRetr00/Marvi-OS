use serde::Deserialize;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    Sleep,
    Ready,
    Wake,
    Listening,
    Thinking,
    Speaking,
    Action,
    Notification,
    Confirmation,
    Error,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Frame {
    pub row: u32,
    pub column: u32,
    pub duration_ms: u32,
}

const IDLE: &[u32] = &[280, 110, 110, 140, 140, 320];
const RUN_RIGHT: &[u32] = &[120, 120, 120, 120, 120, 120, 120, 220];
const WAVE: &[u32] = &[140, 140, 140, 280];
const JUMP: &[u32] = &[140, 140, 140, 140, 280];
const FAILED: &[u32] = &[140, 140, 140, 140, 140, 140, 140, 240];
const WAIT: &[u32] = &[150, 150, 150, 150, 150, 260];
const RUN: &[u32] = &[120, 120, 120, 120, 120, 220];
const REVIEW: &[u32] = &[150, 150, 150, 150, 150, 280];

fn sequence(phase: Phase) -> (u32, &'static [u32]) {
    match phase {
        Phase::Wake => (3, WAVE),
        Phase::Thinking => (7, RUN),
        Phase::Speaking => (8, REVIEW),
        Phase::Action => (1, RUN_RIGHT),
        Phase::Notification => (4, JUMP),
        Phase::Confirmation => (6, WAIT),
        Phase::Error => (5, FAILED),
        Phase::Sleep | Phase::Ready | Phase::Listening => (0, IDLE),
    }
}

pub fn animation_frame(phase: Phase, index: usize) -> Frame {
    let (row, durations) = sequence(phase);
    let column = index % durations.len();
    Frame {
        row,
        column: column as u32,
        duration_ms: durations[column],
    }
}

pub fn gaze_frame(direction: i32) -> Frame {
    let normalized = direction.rem_euclid(16) as u32;
    Frame {
        row: if normalized < 8 { 9 } else { 10 },
        column: normalized % 8,
        duration_ms: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn phase_rows_match_the_v2_pet_contract() {
        assert_eq!(animation_frame(Phase::Ready, 0).row, 0);
        assert_eq!(animation_frame(Phase::Wake, 0).row, 3);
        assert_eq!(animation_frame(Phase::Thinking, 0).row, 7);
        assert_eq!(animation_frame(Phase::Speaking, 0).row, 8);
        assert_eq!(animation_frame(Phase::Action, 0).row, 1);
        assert_eq!(animation_frame(Phase::Notification, 0).row, 4);
        assert_eq!(animation_frame(Phase::Confirmation, 0).row, 6);
        assert_eq!(animation_frame(Phase::Error, 0).row, 5);
    }

    #[test]
    fn frame_timings_and_wrap_are_exact() {
        assert_eq!(animation_frame(Phase::Ready, 0).duration_ms, 280);
        assert_eq!(animation_frame(Phase::Ready, 5).duration_ms, 320);
        assert_eq!(
            animation_frame(Phase::Ready, 6),
            animation_frame(Phase::Ready, 0)
        );
    }

    #[test]
    fn gaze_wraps_across_the_two_direction_rows() {
        assert_eq!(
            gaze_frame(0),
            Frame {
                row: 9,
                column: 0,
                duration_ms: 0
            }
        );
        assert_eq!(
            gaze_frame(15),
            Frame {
                row: 10,
                column: 7,
                duration_ms: 0
            }
        );
        assert_eq!(gaze_frame(16), gaze_frame(0));
        assert_eq!(gaze_frame(-1), gaze_frame(15));
    }
}
