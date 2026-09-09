"""Computer-use admission, privacy, API and setup contracts."""
import asyncio
import json
import threading
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from marvi_gateway.computer import ComputerUse, computer_router, register_computer_tools
from marvi_gateway.browser_privacy import capture_barrier
from marvi_gateway.tools import ToolRegistry
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.setup import catalog, tui

class Driver:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.wait = False
        self.closed = False
    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments)); self.entered.set()
        if self.wait:
            await asyncio.to_thread(self.release.wait)
        return SimpleNamespace(text='fixture result', images=[], is_error=False, error_code=None, degraded=False)
    async def list_tools_json(self):
        return json.dumps({'tools': [{'name':name,'inputSchema':{'properties':{}}} for name in ['click','get_browser_state','set_config']]})
    async def shutdown(self):
        self.closed = True

@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv('MARVI_COMPUTER_USE','true')
    driver=Driver(); s=ComputerUse(factory=lambda:driver)
    yield s,driver
    driver.release.set(); s.close()
    capture_barrier.leave('computer-use')

def test_catalog_keeps_browser_and_driver_configuration_out(service):
    s,_=service
    assert [t['name'] for t in s.catalog()['actions']] == ['click']
    with pytest.raises(ValueError): s.action('set_config',{})

def test_stop_does_not_claim_issued_action_was_cancelled(service):
    s,d=service;d.wait=True
    worker=threading.Thread(target=lambda:s.action('click',{}));worker.start()
    assert d.entered.wait(2)
    assert s.control('stop')['state']=='stopping'
    assert s.status()['active']
    with pytest.raises(RuntimeError):s.action('click',{})
    d.release.set();worker.join(3)
    assert s.status()['state']=='paused'
    s.control('resume')
    assert not s.action('list_apps',{})['is_error']

def test_private_waits_for_capture_and_blocks_new_actions(service):
    s,d=service;d.wait=True
    action=threading.Thread(target=lambda:s.action('click',{}));action.start()
    assert d.entered.wait(2)
    done=threading.Event()
    private=threading.Thread(target=lambda:(s.control('private'),done.set()));private.start()
    assert not done.wait(.1)
    d.release.set();action.join(3);private.join(3)
    assert done.is_set() and capture_barrier.blocked
    with pytest.raises(RuntimeError):s.action('get_desktop_state',{})
    s.control('resume');assert not capture_barrier.blocked

def test_confirmation_and_audit_do_not_expose_typed_text(service,tmp_path):
    s,_=service;r=ToolRegistry();register_computer_tools(r,s)
    spec=r.get('computer_action')
    args={'action':'type_text','arguments':{'text':'SECRET_CANARY'},'request_confirmation':True}
    assert spec.is_sensitive(args)
    assert not spec.is_sensitive({**args,'request_confirmation':False})
    assert 'SECRET_CANARY' not in spec.summary(args)
    runtime=RuntimeStore(audit_path=tmp_path/'audit.jsonl')
    runtime.audit('requested','computer_action',args,'SECRET_CANARY')
    assert 'SECRET_CANARY' not in (tmp_path/'audit.jsonl').read_text()

@pytest.mark.asyncio
async def test_control_api_requires_auth_and_valid_command(service,monkeypatch):
    monkeypatch.setenv('MARVI_LOCAL_TOKEN','computer-fixture')
    s,_=service;app=FastAPI();app.include_router(computer_router(s))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as c:
        assert (await c.get('/computer')).status_code==403
        c.headers['x-marvi-local']='computer-fixture'
        assert (await c.post('/computer/control',json={'command':'stop'})).status_code==200
        assert (await c.post('/computer/control',json={'command':'invalid'})).status_code==422

def test_setup_has_pinned_install_and_opt_in():
    root=Path(__file__).resolve().parents[3]
    component=catalog.get(root,'computer-use')
    assert component and component.extra['version']=='0.24.0'
    assert all(f.size and len(f.sha256)==64 for f in component.files)
    capability=next(c for c in tui.CAPABILITIES if c.key=='computer-use')
    assert capability.settings[0].name=='MARVI_COMPUTER_USE'
