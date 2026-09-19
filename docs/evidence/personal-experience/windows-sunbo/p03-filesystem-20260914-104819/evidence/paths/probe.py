"""Native Windows path and file-sharing observations in a private fixture root.

The probe never serves HTTP, emits credentials, alters production state, or
removes a fixture. Filesystem snapshots exclude timestamps and include NTFS
attributes, link counts and security descriptor hashes. All raw CLI output is
retained only beneath the supplied private root.
"""
import argparse
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

EXPECTED_BINARY='4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74'
CANDIDATE='ebc472f2e46aa7de837afe9d6a0ed422eef51cd0'
REPO=Path(__file__).resolve().parents[3]
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
advapi=ctypes.WinDLL('advapi32',use_last_error=True)
kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
kernel.CreateFileW.restype=wintypes.HANDLE
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
kernel.CloseHandle.restype=wintypes.BOOL
kernel.GetFinalPathNameByHandleW.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
kernel.GetFinalPathNameByHandleW.restype=wintypes.DWORD
advapi.GetFileSecurityW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
advapi.GetFileSecurityW.restype=wintypes.BOOL
INVALID_HANDLE=ctypes.c_void_p(-1).value
class StreamData(ctypes.Structure):
    _fields_=[('size',ctypes.c_longlong),('name',wintypes.WCHAR*296)]
kernel.FindFirstStreamW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(StreamData),wintypes.DWORD]
kernel.FindFirstStreamW.restype=wintypes.HANDLE
kernel.FindNextStreamW.argtypes=[wintypes.HANDLE,ctypes.POINTER(StreamData)]
kernel.FindNextStreamW.restype=wintypes.BOOL
kernel.FindClose.argtypes=[wintypes.HANDLE]
kernel.FindClose.restype=wintypes.BOOL

def digest(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()
def write_new(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')

def security_hash(path):
    path=str(path.absolute())
    if not path.startswith('\\\\?\\'): path='\\\\?\\'+path
    needed=wintypes.DWORD()
    advapi.GetFileSecurityW(str(path),7,None,0,ctypes.byref(needed))
    if not needed.value: raise ctypes.WinError(ctypes.get_last_error())
    buffer=ctypes.create_string_buffer(needed.value)
    if not advapi.GetFileSecurityW(str(path),7,buffer,len(buffer),ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return digest(buffer.raw[:needed.value])

def snapshot(root):
    entries=[]
    for path in [root]+sorted(root.rglob('*')):
        info=path.lstat()
        if info.st_file_attributes & 0x400: raise RuntimeError('unexpected reparse point in path fixture')
        entries.append({'relative_path':path.relative_to(root).as_posix(),'mode':info.st_mode,
                        'attributes':info.st_file_attributes,'links':info.st_nlink,
                        'content_sha256':digest(path.read_bytes()) if path.is_file() else None,
                        'named_streams':named_streams(path),
                        'security_descriptor_sha256':security_hash(path)})
    return {'tree_sha256':digest(encoded(entries)),'entries':len(entries),'files':sum(x['content_sha256'] is not None for x in entries)}

def named_streams(path):
    spelling=str(path.absolute())
    if not spelling.startswith('\\\\?\\'): spelling='\\\\?\\'+spelling
    data=StreamData()
    handle=kernel.FindFirstStreamW(spelling,0,ctypes.byref(data),0)
    if handle==INVALID_HANDLE:
        if ctypes.get_last_error()==38: return []
        raise ctypes.WinError(ctypes.get_last_error())
    result=[]
    try:
        while True:
            if data.name!='::$DATA':
                result.append({'name':data.name,'size':data.size,'sha256':digest(Path(spelling+data.name).read_bytes())})
            if not kernel.FindNextStreamW(handle,ctypes.byref(data)):
                if ctypes.get_last_error()!=38: raise ctypes.WinError(ctypes.get_last_error())
                break
    finally: kernel.FindClose(handle)
    return sorted(result,key=lambda value:value['name'])

def open_handle(path,share,access=0x80000000,directory=False):
    handle=kernel.CreateFileW(str(path),access,share,None,3,0x02000000 if directory else 0,None)
    if handle==INVALID_HANDLE: raise ctypes.WinError(ctypes.get_last_error())
    return handle

def final_path(path):
    handle=open_handle(path,7,access=0,directory=True)
    try:
        buffer=ctypes.create_unicode_buffer(32768)
        length=kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
        if not length or length>=len(buffer): raise ctypes.WinError(ctypes.get_last_error())
        value=buffer.value
        return value[4:] if value.startswith('\\\\?\\') else value
    finally: kernel.CloseHandle(handle)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--test-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if os.name!='nt' or args.out.exists() or not args.out.parent.is_dir(): parser.error('Windows and an existing output directory/new output are required')
    binary=args.binary.resolve(strict=True)
    assert digest(binary.read_bytes())==EXPECTED_BINARY
    parent=args.test_root.resolve(strict=True)
    assert parent.is_dir() and not (parent.lstat().st_file_attributes & 0x400)
    current_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO).decode().strip()
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=REPO).strip()
    assert not subprocess.check_output(['git','diff','--name-only',CANDIDATE,current_head,'--','apps/agentshield'],cwd=REPO).strip()
    root=Path(tempfile.mkdtemp(prefix='paths-',dir=parent))
    logs=root/'private-logs';logs.mkdir()
    cases=root/'cases';cases.mkdir()
    results=[]
    commands=[]

    def run(case,state,*argv):
        sequence=len(commands)
        env={**os.environ,'SIQ_AGENT_SECURITY_STATE_DIR':str(state),'AGENTSHIELD_STATE_DIR':str(state)}
        started=time.monotonic()
        try:
            proc=subprocess.run([str(binary),*argv],env=env,capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW,check=False)
            stdout,stderr,code=proc.stdout,proc.stderr,proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout,stderr,code=exc.stdout or b'',exc.stderr or b'',None
        (logs/f'{sequence:03d}.stdout').write_bytes(stdout)
        (logs/f'{sequence:03d}.stderr').write_bytes(stderr)
        try: payload=json.loads(stdout)
        except (ValueError,UnicodeError): payload={}
        observation={'case':case,'argv':list(argv),'exit_code':code,'elapsed_seconds':round(time.monotonic()-started,3),
                     'stdout_sha256':digest(stdout),'stderr_sha256':digest(stderr),
                     'status':payload.get('status'),'compatible':payload.get('compatible')}
        commands.append(observation)
        print(json.dumps({'case':case,'command':argv[0],'exit':code},ensure_ascii=False),flush=True)
        return observation,payload

    def path_case(name,leaf,transform=None):
        case_root=cases/name;case_root.mkdir()
        requested=str(case_root/leaf)
        canonical_data=None
        if name=='lower_drive':
            baseline,canonical_data=run(name,requested,'init','--port','47631')
            assert baseline['exit_code']==0
        if transform: requested=transform(requested)
        before=snapshot(case_root)
        init,data=run(name,requested,'init','--port','47631')
        after_init=snapshot(case_root)
        status,_=run(name,requested,'state-status')
        after_status=snapshot(case_root)
        actual=None
        if init['exit_code']==0:
            actual=final_path(requested)
            stripped=requested[4:] if requested.startswith('\\\\?\\') else requested
            identity_exact=actual.casefold()==stripped.casefold()
            repeat,again=run(name,requested,'init','--port','47631')
            after_repeat=snapshot(case_root)
            same_instance=data.get('instance_id')==again.get('instance_id') and data.get('state_directory_id')==again.get('state_directory_id')
            if canonical_data:
                same_instance=same_instance and all(data.get(key)==canonical_data.get(key) for key in ('instance_id','state_directory_id'))
            ok=identity_exact and status['compatible'] is True and repeat['exit_code']==0 and same_instance and after_init==after_repeat
            outcome='supported_without_alias' if ok else 'accepted_with_alias_or_identity_mismatch'
        else:
            identity_exact=None;repeat=None;after_repeat=after_status;same_instance=None
            ok=init['exit_code'] is not None and before==after_status
            outcome='rejected_without_persistent_effects' if ok else 'rejected_after_persistent_changes_or_timeout'
        relative_actual=os.path.relpath(actual,case_root) if actual else None
        result={'name':name,'status':'pass' if ok else 'fail','input_leaf':leaf,'input_transform':transform.__name__ if transform else 'none',
                'outcome':outcome,'init_exit':init['exit_code'],'status_exit':status['exit_code'],'compatible':status['compatible'],
                'actual_relative_path':relative_actual,'exact_path_identity':identity_exact,'same_instance_on_repeat':same_instance,
                'before':before,'after_init':after_init,'after_status':after_status,'after_repeat':after_repeat,
                'status_read_only':after_init==after_status}
        results.append(result)

    def lower_drive(value): return value[0].lower()+value[1:]
    def extended_path(value): return '\\\\?\\'+value
    for name,leaf,transform in (
        ('unicode_spaces','中文 空格状态',None),('lower_drive','CaseState',lower_drive),
        ('trailing_dot','target.',None),('trailing_space','target ',None),
        ('reserved_nul','NUL',None),('reserved_con_extension','CON.txt',None),
        ('ads_component','target:stream',None),
        ('long_path',str(Path(*(['segment-'+('x'*45)]*5))/'中文状态'),None),
        ('extended_path','extended-state',extended_path),
    ):
        path_case(name,leaf,transform)

    for name,filename,read_only in (
        ('exclusive_config','config.json',False),('exclusive_marker','state-format.json',False),
        ('exclusive_instance','local-instance.json',False),('readonly_config','config.json',True),
        ('readonly_marker','state-format.json',True),
    ):
        state=cases/name
        initialized,_=run(name,state,'init','--port','47631')
        assert initialized['exit_code']==0
        target=state/filename
        if read_only: os.chmod(target,0o400)
        before=snapshot(state)
        handle=None
        lock_proved=None
        if not read_only:
            handle=open_handle(target,0)
            try:
                target.read_bytes()
                lock_proved=False
            except OSError as exc: lock_proved=exc.winerror==32
        try:
            checked,body=run(name,state,'init','--port','47631')
        finally:
            if handle is not None: kernel.CloseHandle(handle)
        after=snapshot(state)
        recovered,_=run(name,state,'init','--port','47631')
        after_recovery=snapshot(state)
        expected_exit=0 if read_only else 1
        ok=checked['exit_code']==expected_exit and before==after==after_recovery and recovered['exit_code']==0 and (read_only or lock_proved)
        results.append({'name':name,'status':'pass' if ok else 'fail','file':filename,'read_only_fixture':read_only,
                        'sharing_violation_proved':lock_proved,'init_exit':checked['exit_code'],
                        'recovery_init_exit':recovered['exit_code'],'after_recovery':after_recovery,
                        'before':before,'after':after,'persistent_state_unchanged':before==after,
                        'scope':'Existing initialization metadata read; no claim about signed version publication or replacement races'})
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=REPO).strip()
    assert clean and subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO).decode().strip()==current_head
    report={'schema_version':'windows-path-sharing-observations/v1','recorded_at':datetime.datetime.now(datetime.UTC).isoformat(),
            'candidate_sha':CANDIDATE,'checkout_head':current_head,'source_dirty':False,'runtime_tree_equal_to_candidate':True,
            'binary_sha256':EXPECTED_BINARY,'probe_sha256':digest(Path(__file__).read_bytes()),
            'platform':'windows/amd64','method':'native_cli','commands':commands,'checks':results,
            'snapshot_scope':'Entry names, default/named-stream content hashes, modes, link counts, Windows attributes and owner/group/DACL descriptor hashes; no timestamps or transient-file tracing',
            'limits':['No real host integration','No signed publication/rename race assertion','No other-user login test','UNC/network share and second volume not tested','Private fixtures/logs retained; no cleanup or lock deletion performed']}
    write_new(args.out,report)
    summary={status:sum(row['status']==status for row in results) for status in ('pass','fail')}
    print(json.dumps({'completed':summary,'output':args.out.name}))
    return 1 if summary['fail'] else 0

if __name__=='__main__': raise SystemExit(main())
