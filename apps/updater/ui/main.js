// Marvi Bootstrap renderer. Operational stages and raw output are deliberately
// separate: a package-manager line may enter the log, but it can never replace
// the current stage or move the progress bar.

const stageText = document.getElementById('stage-text');
const statusEl = document.getElementById('status');
const statusMark = document.getElementById('status-mark');
const statusHeading = document.getElementById('status-heading');
const statusMessage = document.getElementById('status-message');
const statusHelp = document.getElementById('status-help');
const spinner = document.getElementById('spinner');
const title = document.getElementById('title');
const channelEl = document.getElementById('channel');
const logEl = document.getElementById('log');
const logPane = document.getElementById('log-pane');
const logCount = document.getElementById('log-count');
const gpuAsk = document.getElementById('gpu-ask');
const gpuPrompt = document.getElementById('gpu-prompt');
const bar = document.getElementById('bar');
const barFill = document.getElementById('bar-fill');
const progressPercent = document.getElementById('progress-percent');
const stepCount = document.getElementById('step-count');
const stageList = document.getElementById('stage-list');
const closeRow = document.getElementById('close-row');
const detailsToggle = document.getElementById('details-toggle');
const detailsLabel = document.getElementById('details-label');

const MAX_LINES = 800;
const tauri = window.__TAURI__;

let stages = [];
let currentStageId = null;
let terminalStatus = null;
let lines = 0;

if (!tauri || typeof tauri.event !== 'object') {
  stageText.textContent = 'Installer runtime unavailable';
} else {
  void bind(tauri);
}

function setProgress(percent) {
  const safe = Math.max(0, Math.min(100, Number(percent) || 0));
  barFill.style.width = `${safe}%`;
  bar.setAttribute('aria-valuenow', String(safe));
  progressPercent.textContent = `${Math.round(safe)}%`;
}

function renderStages() {
  stageList.replaceChildren();
  const activeIndex = stages.findIndex((stage) => stage.id === currentStageId);
  const allDone = terminalStatus === 'ok';

  stages.forEach((stage, index) => {
    const item = document.createElement('li');
    const isActive = !terminalStatus && index === activeIndex;
    const failed = terminalStatus && terminalStatus !== 'ok' && index === activeIndex;
    const done = allDone || (activeIndex >= 0 && index < activeIndex);
    item.className = failed ? 'failed' : isActive ? 'running' : done ? 'done' : 'pending';

    const number = document.createElement('span');
    number.className = 'stage-number';
    number.textContent = String(index + 1).padStart(2, '0');

    const label = document.createElement('span');
    label.className = 'stage-name';
    label.textContent = stage.title;

    const marker = document.createElement('span');
    marker.className = 'stage-state';
    marker.setAttribute('aria-hidden', 'true');
    marker.textContent = failed ? '×' : isActive ? '••' : done ? '✓' : '·';

    item.append(number, label, marker);
    stageList.append(item);
  });

  const completed = allDone ? stages.length : Math.max(0, activeIndex);
  stepCount.textContent = stages.length
    ? `${completed} OF ${stages.length} STAGES COMPLETE`
    : 'WAITING FOR INSTALLER';
}

function appendLog(line) {
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  const entry = document.createElement('div');
  entry.className = 'log-line';
  if (/^(warning|npm warn|warn)/i.test(line)) entry.classList.add('warning');
  if (/^(error|npm error|fatal)|failed|aborted/i.test(line)) entry.classList.add('error');
  if (/^===/.test(line)) entry.classList.add('boundary');
  entry.textContent = line;
  logEl.append(entry);

  while (logEl.childElementCount > MAX_LINES) logEl.firstElementChild?.remove();
  lines += 1;
  logCount.textContent = `${lines} ${lines === 1 ? 'LINE' : 'LINES'}`;
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;
}

function setDetails(open) {
  logPane.hidden = !open;
  detailsToggle.setAttribute('aria-expanded', String(open));
  detailsToggle.classList.toggle('open', open);
  detailsLabel.textContent = open ? 'HIDE DETAILS' : 'SHOW DETAILS';
  if (open) logEl.scrollTop = logEl.scrollHeight;
}

async function bind(runtime) {
  await Promise.all([
    runtime.event.listen('meta', (event) => {
      const payload = event.payload || {};
      const mode = payload.mode === 'install' ? 'INSTALLING' : payload.mode === 'update' ? 'UPDATING' : 'CHECKING';
      title.textContent = mode;
      if (payload.channel) {
        channelEl.textContent = `${payload.channel.toUpperCase()} CHANNEL`;
        channelEl.hidden = false;
      }
      stages = Array.isArray(payload.stages) ? payload.stages : [];
      renderStages();
    }),

    runtime.event.listen('progress', (event) => {
      const payload = event.payload || {};
      if (!payload.stageId) return;
      currentStageId = payload.stageId;
      stageText.textContent = payload.title || 'Working';
      setProgress(payload.percent);
      renderStages();
    }),

    runtime.event.listen('log', (event) => {
      const payload = event.payload || {};
      if (typeof payload.line === 'string' && payload.line.length) appendLog(payload.line);
    }),

    runtime.event.listen('ask-gpu', (event) => {
      const payload = event.payload || {};
      gpuPrompt.textContent = payload.prompt || 'Use the GPU for models that support it?';
      gpuAsk.hidden = false;
      const answer = (useGpu) => {
        gpuAsk.hidden = true;
        runtime.event.emit('gpu-answer', { useGpu });
      };
      document.getElementById('gpu-yes').onclick = () => answer(true);
      document.getElementById('gpu-no').onclick = () => answer(false);
    }),

    runtime.event.listen('done', (event) => {
      const payload = event.payload || {};
      const succeeded = payload.status === 'ok';
      terminalStatus = payload.status || 'failed';
      spinner.classList.add('done');
      statusEl.hidden = false;
      statusEl.classList.add(terminalStatus);
      statusMark.textContent = succeeded ? '[OK]' : '[!]';
      statusHeading.textContent = succeeded ? 'Completed successfully' : 'Action needs attention';
      statusMessage.textContent = payload.message || 'The updater finished without a result.';
      statusHelp.textContent = succeeded
        ? 'Marvi OS is ready. This window will close automatically.'
        : 'Marvi OS was left unchanged or restored. Review the technical details, then close and try again.';
      stageText.textContent = succeeded ? 'All stages completed' : 'Installer stopped safely';
      if (payload.status) title.textContent = payload.status.toUpperCase();
      if (succeeded) setProgress(100);
      else {
        barFill.classList.add('failed');
        setDetails(true);
        closeRow.hidden = false;
        document.getElementById('close').focus();
      }
      renderStages();
    })
  ]);

  // Rust waits for this before sending metadata, preventing startup events
  // from disappearing before WebView listeners exist.
  await runtime.event.emit('ui-ready', {});

  document.getElementById('close').onclick = () => runtime.event.emit('close-window', {});
  detailsToggle.onclick = () => setDetails(logPane.hidden);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !closeRow.hidden) runtime.event.emit('close-window', {});
  });
}
