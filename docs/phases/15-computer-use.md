# Phase 15 — Computer use and application control

Status: implemented, acceptance checks in progress, 2026-09-09.

The user reported completing and testing the browser phase and requested
computer use. This is user acceptance, not evidence that every historical
automated soak ran. The embedded browser remains separate.

## Contract

Cua Driver SDK and Windows binary 0.24.0 are reused unchanged under MIT.
Gateway owns admission, confirmation, audit and the SDK connection. The SDK
creates its private worker through inherited pipes under Electron's supervised
Gateway process tree. No public daemon is exposed.

- Setup installs the hash-verified `computer-use` component and exposes
  `MARVI_COMPUTER_USE`. Off by default; restart after enabling.
- `computer_tools`, `computer_action`, `computer_status`, `computer_control`
  expose desktop/app discovery, launch, window management, inspection and input.
- Browser attachment, recording, driver configuration and screenshot file
  outputs are not exposed by this adapter.
- Gateway retains model-selected confirmation and YOLO. Trusted worker
  configuration avoids a second policy contradicting these product modes.
- Stop closes admission and drains issued work. Private input shares the browser
  barrier and waits for capture/model delivery before acknowledgment.
- Fresh snapshot/element tokens accompany untrusted observations. Requested
  screenshot interpretation uses the configured Vision provider. Images remain
  transient and are not stored by this adapter.
- Island shows `Marvi is using the computer`, Stop/Private input/Resume,
  stopping and connection-loss states. Confirmation UI retains priority.

## Selection and evidence

Web review identified Terminator as a Windows SDK alternative; UFO2 as a larger
Windows framework; Agent S3, UI-TARS and Holo3 as agent/model alternatives.
Their benchmarks do not establish a head-to-head driver winner. Cua is selected
for its released private-worker SDK and structured Windows targets.

- Native metadata: driver 0.24.0, contract 0.7.0 on Windows.
- Setup verified and unpacked the 27,922,060-byte x86-64 release archive.
- `scripts/qualify-computer-use.py`: real worker and disposable WinForms app;
  launch, fresh UIA tokens, field entry, background button invocation,
  independently verified file, private capture rejection/resume, app close.
- One run: launch 4382.95 ms; observations 1671.39/1606.02 ms; set-value
  7.12 ms; click 1291.86 ms; close 28.21 ms. Ryzen 5 3600X, 16 GB RAM,
  RTX 3060 12 GB. These are fixture timings, not model/VRAM measurements.
- 35 Gateway/setup/tool tests, four Island tests and 26 voice-bridge tests passed.

Application compatibility and foreground fallback remain upstream limitations.
This does not isolate applications from other same-account Windows processes.
