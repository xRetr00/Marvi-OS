// Marvi Bootstrap window: stream progress from the Rust task and render the
// final status. Uses the Tauri global API (withGlobalTauri) so no npm bundle
// is needed for this tiny binary.

const stageText = document.getElementById('stage-text');
const statusEl = document.getElementById('status');
const spinner = document.getElementById('spinner');
const title = document.getElementById('title');
const channelEl = document.getElementById('channel');
const logEl = document.getElementById('log');
const gpuAsk = document.getElementById('gpu-ask');
const gpuPrompt = document.getElementById('gpu-prompt');
const bar = document.getElementById('bar');
const barFill = document.getElementById('bar-fill');
const closeRow = document.getElementById('close-row');

// An install prints thousands of lines. Keeping all of them makes the window
// slow for no benefit; the last screenful is what anyone reads.
const MAX_LINES = 400;

const tauri = window.__TAURI__;

// Guarded rather than returned from: this is a classic script, so a top-level
// `return` is a parse error and the whole file - every listener below it -
// silently never runs. The window then sits on "PREPARING" through the entire
// install with no progress and no result.
if (!tauri || typeof tauri.event !== 'object') {
  stageText.textContent = 'runtime unavailable';
} else {
  bind(tauri);
}

function append(line) {
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  logEl.textContent += `${line}\n`;
  const lines = logEl.textContent.split('\n');
  if (lines.length > MAX_LINES) {
    logEl.textContent = lines.slice(-MAX_LINES).join('\n');
  }
  // Follow the tail unless the user scrolled up to read something.
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;
}

function bind(tauri) {
  tauri.event.listen('meta', (event) => {
    const p = event.payload || {};
    const mode =
      p.mode === 'install' ? 'INSTALLING' : p.mode === 'update' ? 'UPDATING' : 'CHECKING';
    title.textContent = mode;
    if (p.channel) channelEl.textContent = p.channel.toUpperCase();
  });

  tauri.event.listen('progress', (event) => {
    const p = event.payload || {};
    if (!p.stage) return;
    stageText.textContent = p.stage;
    const percent = Math.max(0, Math.min(100, Number(p.percent) || 0));
    barFill.style.width = `${percent}%`;
    bar.setAttribute('aria-valuenow', String(percent));
    append(p.stage);
  });

  // The Rust side asks and then blocks until the answer comes back, because
  // the choice decides which PyTorch build the next step downloads.
  tauri.event.listen('ask-gpu', (event) => {
    const p = event.payload || {};
    gpuPrompt.textContent = p.prompt || 'Use the GPU for models that support it?';
    gpuAsk.hidden = false;
    const answer = (useGpu) => {
      gpuAsk.hidden = true;
      append(useGpu ? 'using the GPU' : 'using the CPU');
      tauri.event.emit('gpu-answer', { useGpu });
    };
    document.getElementById('gpu-yes').onclick = () => answer(true);
    document.getElementById('gpu-no').onclick = () => answer(false);
  });

  tauri.event.listen('done', (event) => {
    const p = event.payload || {};
    spinner.classList.add('done');
    statusEl.hidden = false;
    statusEl.classList.add(p.status || 'failed');
    statusEl.textContent = p.message || 'finished';
    append(p.message || 'finished');
    if (p.status) title.textContent = p.status.toUpperCase();
    // Full only when it worked. A failure that fills the bar reads as success.
    if (p.status === 'ok') {
      barFill.style.width = '100%';
      bar.setAttribute('aria-valuenow', '100');
    }
    barFill.classList.add(p.status === 'ok' ? 'ok' : 'failed');
    closeRow.hidden = false;
    document.getElementById('close').focus();
  });

  // Rust exits on this rather than the window closing itself, so no extra
  // window capability is needed for the one button this app has.
  document.getElementById('close').onclick = () => tauri.event.emit('close-window', {});
}
