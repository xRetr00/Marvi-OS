// Marvi Bootstrap window: stream progress from the Rust task and render the
// final status. Uses the Tauri global API (withGlobalTauri) so no npm bundle
// is needed for this tiny binary.

const stageText = document.getElementById('stage-text');
const statusEl = document.getElementById('status');
const spinner = document.getElementById('spinner');
const title = document.getElementById('title');
const channelEl = document.getElementById('channel');

const tauri = window.__TAURI__;
if (!tauri || typeof tauri.event !== 'object') {
  stageText.textContent = 'runtime unavailable';
  return;
}

tauri.event.listen('meta', (event) => {
  const p = event.payload || {};
  const mode =
    p.mode === 'install' ? 'INSTALLING' : p.mode === 'update' ? 'UPDATING' : 'CHECKING';
  title.textContent = mode;
  if (p.channel) channelEl.textContent = p.channel.toUpperCase();
});

tauri.event.listen('progress', (event) => {
  const p = event.payload || {};
  if (p.stage) stageText.textContent = p.stage;
});

tauri.event.listen('done', (event) => {
  const p = event.payload || {};
  spinner.classList.add('done');
  statusEl.hidden = false;
  statusEl.classList.add(p.status || 'failed');
  statusEl.textContent = p.message || 'finished';
  if (p.status) title.textContent = p.status.toUpperCase();
});
