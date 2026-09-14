"""Confirm three sharing cases with native ERROR_SHARING_VIOLATION evidence.

The first probe's Python CRT exception did not retain winerror=32. This follow-up
uses a second native CreateFileW call to prove the exclusive handle is effective.
The initial probe and its reported failures remain unchanged.
"""
import ctypes
import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

helper_path=Path(__file__).with_name('probe.py')
spec=importlib.util.spec_from_file_location('windows_path_probe',helper_path)
helper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
repo=helper.REPO
binary=repo/'.tmp/win-task-native/build/siq-candidate-windows-amd64.exe'
parent=repo/'.tmp/win-p03-next/paths'
output=Path(__file__).with_name('sharing-results-20260914.json')
assert not output.exists() and helper.digest(binary.read_bytes())==helper.EXPECTED_BINARY
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo).strip()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip()
root=Path(tempfile.mkdtemp(prefix='sharing-native-',dir=parent))
logs=root/'private-logs';logs.mkdir()
checks=[]
commands=[]

def run(name,state):
    started=time.monotonic()
    proc=subprocess.run([str(binary),'init','--port','47631'],env={**os.environ,'SIQ_AGENT_SECURITY_STATE_DIR':str(state),'AGENTSHIELD_STATE_DIR':str(state)},capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW,check=False)
    index=len(commands)
    (logs/f'{index:03d}.stdout').write_bytes(proc.stdout)
    (logs/f'{index:03d}.stderr').write_bytes(proc.stderr)
    command={'case':name,'argv':['init','--port','47631'],'exit_code':proc.returncode,'elapsed_seconds':round(time.monotonic()-started,3),'stdout_sha256':helper.digest(proc.stdout),'stderr_sha256':helper.digest(proc.stderr)}
    commands.append(command)
    return proc.returncode

for name,filename in (('exclusive_config','config.json'),('exclusive_marker','state-format.json'),('exclusive_instance','local-instance.json')):
    state=root/name
    assert run(name,state)==0
    before=helper.snapshot(state)
    target=state/filename
    handle=helper.open_handle(target,0)
    second_error=None
    closed=False
    try:
        second=helper.kernel.CreateFileW(str(target),0x80000000,7,None,3,0,None)
        if second==helper.INVALID_HANDLE:
            second_error=ctypes.get_last_error()
        else:
            assert helper.kernel.CloseHandle(second)
        rejected=run(name,state)
    finally:
        closed=bool(helper.kernel.CloseHandle(handle))
    after_release=helper.snapshot(state)
    recovery=run(name,state)
    after_recovery=helper.snapshot(state)
    ok=second_error==32 and rejected==1 and closed and recovery==0 and before==after_release==after_recovery
    checks.append({'name':name,'status':'pass' if ok else 'fail','native_second_open_error':second_error,'init_while_locked_exit':rejected,'exclusive_handle_closed':closed,'init_after_release_exit':recovery,'before':before,'after_release':after_release,'after_recovery':after_recovery,'persistent_state_unchanged':before==after_release==after_recovery})
    print(json.dumps({'case':name,'status':checks[-1]['status'],'native_conflict':second_error}),flush=True)

initial_path=Path(__file__).with_name('results-20260914.json')
initial=json.loads(initial_path.read_text(encoding='utf-8'))
supplemental=[]
for case in initial['checks']:
    if 'after_status' in case:
        supplemental.append({'case':case['name'],'status_exit_zero':case['status_exit']==0,'diagnostic_snapshot_unchanged':case['after_init']==case['after_status']})
assert all(case['status_exit_zero'] and case['diagnostic_snapshot_unchanged'] for case in supplemental)
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo).strip()
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip()==head
helper.write_new(output,{'schema_version':'windows-sharing-native-confirmation/v1','recorded_at':datetime.datetime.now(datetime.UTC).isoformat(),'candidate_sha':helper.CANDIDATE,'checkout_head':head,'source_dirty':False,'binary_sha256':helper.EXPECTED_BINARY,'method':'native_cli','probe_sha256':helper.digest(Path(__file__).read_bytes()),'helper_sha256':helper.digest(helper_path.read_bytes()),'initial_observations_sha256':helper.digest(initial_path.read_bytes()),'initial_report_retained':True,'initial_lock_reason':'Python CRT OSError did not preserve Win32 sharing error 32; this was measurement failure, not evidence of an ineffective handle','commands':commands,'checks':checks,'supplemental_initial_readonly_assertions':supplemental,'limits':['Only existing initialization metadata reads; no signed publish/rename race claim','No timestamp or transient-file trace assertion','No host or second-user test','Private fixtures retained']})
raise SystemExit(0 if all(case['status']=='pass' for case in checks) else 1)
