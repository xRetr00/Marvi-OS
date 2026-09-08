"""Fixture-only end-to-end host protocol proof; never use account credentials."""
import http.server
import json
import os
import threading
import time
from pathlib import Path

from marvi_gateway.browser_workspace import BrowserWorkspace
from marvi_gateway.workspace import Workspace


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/download':
            self.send_response(200)
            self.send_header('Content-Disposition', 'attachment; filename=fixture.txt')
            self.end_headers()
            self.wfile.write(b'embedded browser download')
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>Embedded fixture</h1><label>Name <input id="name"></label><button onclick="document.querySelector(\'output\').textContent=document.querySelector(\'input\').value">Apply</button><output></output><a href="/download">Download</a>')

    def log_message(self, *_args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f'http://127.0.0.1:{server.server_port}'
root = Path('output/embedded-workspace').resolve()
root.mkdir(parents=True, exist_ok=True)
service = BrowserWorkspace(root / 'browser', workspace=Workspace(root), allowed_origins=(origin,))
service.register_host(os.environ['MARVI_TEST_HOST'], os.environ['MARVI_TEST_TOKEN'])
try:
    sid = service.start(url=origin)['id']
    print('SESSION ' + sid, flush=True)

    def current():
        return next(s for s in service.status()['sessions'] if s['id'] == sid)

    def wait():
        end = time.monotonic() + 45
        while time.monotonic() < end:
            state = current()
            if state['state'] not in {'starting', 'running', 'resuming'}:
                return state
            time.sleep(.1)
        raise AssertionError('Browser operation timed out')

    state = wait()
    assert state['state'] == 'ready', {k: state.get(k) for k in ('state', 'detail', 'error_type')}
    assert state['host'] == 'embedded'
    for index, (action, args) in enumerate([
        ('fill', {'selector': '#name', 'text': 'fixture result'}),
        ('click', {'role': 'button', 'name': 'Apply'}),
        ('screenshot', {}),
    ]):
        service.action(sid, current()['revision'], action, args, str(index))
        assert wait()['state'] == 'ready', action
    private = service.control(sid, current()['revision'], 'private')
    assert private['state'] == 'private' and not private['tabs'] and private['result'] is None
    service.control(sid, private['revision'], 'resume')
    assert wait()['state'] == 'ready'
    service.action(sid, current()['revision'], 'click', {'role': 'link', 'name': 'Download'}, 'download')
    wait()
    end = time.monotonic() + 20
    while not current().get('download') and time.monotonic() < end:
        time.sleep(.1)
    item = current().get('download')
    assert item and item['bytes'] == 25, 'download'
    saved = service.export(sid, item['artifact'], f'fixture-{sid}.txt')
    assert Path(saved['path']).read_bytes() == b'embedded browser download'
    service.control(sid, current()['revision'], 'close')
    assert current()['state'] == 'closed'
    print(json.dumps({'embedded_actions': True, 'private_resume': True, 'download_export': True, 'close': True}), flush=True)
finally:
    service.close()
    server.shutdown()
