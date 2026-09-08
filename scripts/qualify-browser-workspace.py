"""Fixture-only end-to-end host protocol proof; never use account credentials."""
import http.server
import json
import os
import threading
import sys
import time
from pathlib import Path

from marvi_gateway.browser_workspace import BrowserWorkspace
from marvi_gateway.workspace import Workspace


class Fixture(http.server.BaseHTTPRequestHandler):
    imported_cookie = False
    def do_GET(self):
        Fixture.imported_cookie |= 'marvi-fixture=imported-cookie' in self.headers.get('Cookie', '')
        if self.path == '/download':
            self.send_response(200)
            self.send_header('Content-Disposition', 'attachment; filename=fixture.txt')
            self.end_headers()
            self.wfile.write(b'embedded browser download')
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>Embedded fixture</h1><label>Name <input id="name"></label><label>Password <input type="password"></label><button onclick="document.querySelector(\'output\').textContent=document.querySelector(\'input\').value">Apply</button><output></output><a href="/download">Download</a>')

    def log_message(self, *_args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f'http://127.0.0.1:{server.server_port}'
root = Path(os.environ['MARVI_TEST_DIRECTORY'])
root.mkdir(parents=True, exist_ok=True)
service = BrowserWorkspace(root / 'browser', workspace=Workspace(root), allowed_origins=(origin,))
service.register_host(os.environ['MARVI_TEST_HOST'], os.environ['MARVI_TEST_TOKEN'])
try:
    print('ORIGIN ' + origin, flush=True)
    assert sys.stdin.readline().strip() == 'imported'
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
    assert Fixture.imported_cookie
    for index, (action, args) in enumerate([
        ('fill', {'selector': '#name', 'text': 'fixture result'}),
        ('click', {'role': 'button', 'name': 'Apply'}),
        ('screenshot', {}),
    ]):
        service.action(sid, current()['revision'], action, args, str(index))
        assert wait()['state'] == 'ready', action
    private = service.control(sid, current()['revision'], 'private')
    assert private['state'] == 'private' and not private['tabs'] and private['result'] is None
    print('PRIVATE ' + sid, flush=True)
    assert sys.stdin.readline().strip() == 'filled'
    try:
        service.image(sid, private['revision'], '')
        raise AssertionError('Private image capture must fail')
    except ValueError:
        pass
    service.control(sid, private['revision'], 'resume')
    assert wait()['state'] == 'ready'
    assert 'MARVI_PRIVATE_CANARY_9031' not in json.dumps(current())
    service.action(sid, current()['revision'], 'click', {'role': 'link', 'name': 'Download'}, 'download')
    wait()
    end = time.monotonic() + 20
    while not current().get('download') and time.monotonic() < end:
        time.sleep(.1)
    item = current().get('download')
    assert item and item['bytes'] == 25, 'download'
    saved = service.export(sid, item['artifact'], f'fixture-{sid}.txt')
    assert Path(saved['path']).read_bytes() == b'embedded browser download'
    original_tab = current()['tabs'][0]['id']
    service.action(sid, current()['revision'], 'new_tab', {'tab_id': original_tab, 'url': origin}, 'second-tab')
    assert wait()['state'] == 'ready'
    assert len(current()['tabs']) == 2
    second_tab = next(tab['id'] for tab in current()['tabs'] if tab['id'] != original_tab)
    service.action(sid, current()['revision'], 'close_tab', {'tab_id': second_tab}, 'close-second-tab')
    assert wait()['state'] == 'ready'
    assert [tab['id'] for tab in current()['tabs']] == [original_tab]
    for cycle in range(30):
        revision = current()['revision']
        private = service.control(sid, revision, 'private')
        assert not private['tabs'] and private['result'] is None
        try:
            service.action(sid, revision, 'read', {'tab_id': original_tab}, f'stale-{cycle}')
            raise AssertionError('Stale action accepted')
        except ValueError:
            pass
        service.control(sid, private['revision'], 'resume')
        assert wait()['state'] == 'ready'
        assert 'MARVI_PRIVATE_CANARY_9031' not in json.dumps(current())
    service.control(sid, current()['revision'], 'pause')
    service.action(sid, current()['revision'], 'navigate', {'tab_id': original_tab, 'url': origin}, 'manual-navigation', manual=True)
    assert wait()['state'] == 'paused'
    service.control(sid, current()['revision'], 'resume')
    assert wait()['state'] == 'ready'
    service.control(sid, current()['revision'], 'close')
    assert current()['state'] == 'closed'
    print(json.dumps({'embedded_actions': True, 'cookie_import': True, 'encrypted_password_import_private_fill': True, 'private_resume_cycles': 30, 'exact_tab_routing': True, 'manual_navigation_preserves_pause': True, 'download_export': True, 'close': True}), flush=True)
finally:
    service.close()
    server.shutdown()
