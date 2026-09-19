from pathlib import Path
import subprocess,os,json,hashlib,socket,time,urllib.request,urllib.error,ctypes
from ctypes import wintypes
base=Path.cwd(); root=base/'.tmp/win-task-native/bootstrap-fixed-20260917/private-acl-daemon-r6';root.mkdir(exist_ok=False)
binary=base/'.tmp/windows-goal-20260916/private-acl-clean-r1/agent.exe'
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
fixture=Path(__file__).with_name('read-fixture-acl.ps1')
env=dict(os.environ,PYTHONUTF8='1'); home=root/'home';home.mkdir()
for name,value in {'HOME':home,'USERPROFILE':home,'APPDATA':home/'AppData/Roaming','LOCALAPPDATA':home/'AppData/Local','XDG_CONFIG_HOME':home/'.config','HERMES_HOME':home/'.hermes'}.items():
 env[name]=str(value);value.mkdir(parents=True,exist_ok=True)
for name in ['SIQ_AGENT_SECURITY_SIGNING_KEY_SEED','AGENTSHIELD_SIGNING_KEY_SEED']:env.pop(name,None)
assert hashlib.sha256(binary.read_bytes()).hexdigest()=='a32afce00f32c20f534885dc16a55ef62dba7f2220c22b5ee30f312f365e01c7'
report={'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'source_sha':'82a7da5b978dbbb7c72a10a97ad77976cf84a35f','source_dirty':False,'checks':[]};child=None;log=None;restores=[]
def check(name,ok,**kwargs):
 report['checks'].append(dict(name=name,passed=bool(ok),**kwargs));assert ok,name
adv=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
convert=adv.ConvertStringSecurityDescriptorToSecurityDescriptorW;convert.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.DWORD)];convert.restype=wintypes.BOOL
setsecurity=adv.SetFileSecurityW;setsecurity.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p];setsecurity.restype=wintypes.BOOL
kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
def acl(path,mode='read',saved=''):
 assert path.is_relative_to(root),'outside isolated test root'
 if mode in ('read','audit'):
  p=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-File',str(fixture),str(root),str(path),mode],capture_output=True,env=dict(os.environ,PSModulePath=str(ps.parent/'Modules')),creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
  assert p.returncode==0,'fixture descriptor read failed'
  return p.stdout.decode('utf-8-sig').strip()
 sddl=(acl(path).split('S:')[0]+('(A;OICI;GR;;;WD)' if path.is_dir() else '(A;;GR;;;WD)')) if mode=='broad' else saved
 descriptor=ctypes.c_void_p()
 if not convert(sddl,1,ctypes.byref(descriptor),None):raise ctypes.WinError(ctypes.get_last_error())
 try:
  control=sddl.split('D:',1)[1].split('(',1)[0]
  flags=4|(0x80000000 if 'P' in control else 0x20000000)
  if not setsecurity(str(path),flags,descriptor):raise ctypes.WinError(ctypes.get_last_error())
 finally:kernel.LocalFree(descriptor)
 return ''
def broaden(path):
 saved=acl(path);acl(path,'broad');restores.append((path,saved));return saved
def restore(path,saved):
 acl(path,'restore',saved);restores.remove((path,saved))
def cli(state,*args):
 current=dict(env,SIQ_AGENT_SECURITY_STATE_DIR=str(state))
 return subprocess.run([str(binary),*args],cwd=root,env=current,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=45)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path,token=''):
 req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers={'Authorization':'Bearer '+token} if token else {})
 try:
  with opener.open(req,timeout=5) as r:return r.status,r.read()
 except urllib.error.HTTPError as e:return e.code,e.read()
try:
 existing=root/'existing-wide';existing.mkdir();saved=broaden(existing);before=acl(existing)
 p=cli(existing,'init');check('existing-broad-root-init-rejected',p.returncode!=0,exit=p.returncode)
 check('existing-broad-root-no-write',not list(existing.iterdir()))
 check('existing-broad-root-not-repaired',acl(existing)==before);restore(existing,saved)
 parent=root/'broad-parent';parent.mkdir();saved=broaden(parent);before=acl(parent);state=parent/'state'
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 p=cli(state,'init','--port',str(port));check('init-creates-private-state-under-broad-parent',p.returncode==0,exit=p.returncode)
 check('ambient-parent-not-repaired',acl(parent)==before)
 log=(root/'service.private.log').open('wb')
 child=subprocess.Popen([str(binary),'serve','--port',str(port)],env=dict(env,SIQ_AGENT_SECURITY_STATE_DIR=str(state)),cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 deadline=time.monotonic()+40
 while time.monotonic()<deadline:
  assert child.poll() is None,'owned daemon exited before health'
  try:
   if get('/healthz/instance')[0]==200:break
  except OSError:pass
  time.sleep(.1)
 else:raise RuntimeError('owned health timeout')
 check('native-daemon-healthy',True)
 for label,path in [('state',state),('keys',state/'keys'),('seed',state/'keys/signing.seed'),('token',state/'token'),('recovery',state/'admin-recovery.token')]:
  facts=json.loads(acl(path,'audit'))
  check(label+'-independent-descriptor-audit',facts['owner_current'] and facts['protected'] and facts['unknown_allow_count']==0 and set(facts['allowed_classes'])=={'current_user','system','administrators'},descriptor=facts)
 token=(state/'token').read_text(encoding='utf-8');check('cached-decision-route-baseline',get('/v1/decide',token)[0]==405)
 for label,path in [('token',state/'token'),('recovery',state/'admin-recovery.token'),('seed',state/'keys/signing.seed'),('keys',state/'keys'),('root',state)]:
  content=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
  original=broaden(path);broad=acl(path)
  status,body=get('/v1/decide',token)
  check(label+'-cached-credential-rejected',status==503 and json.loads(body)=={'error':'state_private_permissions'},http_status=status)
  check(label+'-acl-not-repaired',acl(path)==broad)
  if content:check(label+'-bytes-unchanged',hashlib.sha256(path.read_bytes()).hexdigest()==content)
  restore(path,original)
  check(label+'-restored-fixture-recovers',get('/v1/decide',token)[0]==405)
 p=cli(state,'stop','--confirm-stop');check('signed-stop',p.returncode==0,exit=p.returncode)
 check('owned-daemon-exit',child.wait(timeout=15)==0)
 for label,path in [('token',state/'token'),('recovery',state/'admin-recovery.token'),('seed',state/'keys/signing.seed')]:
  original=broaden(path);before=acl(path)
  before_files={str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in state.rglob('*') if p.is_file()}
  p=cli(state,'serve','--port',str(port))
  check(label+'-unsafe-startup-rejected',p.returncode!=0,exit=p.returncode)
  after_files={str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in state.rglob('*') if p.is_file()}
  check(label+'-startup-preserves-business-files',before_files==after_files)
  check(label+'-startup-preserves-unsafe-acl',acl(path)==before)
  restore(path,original)
 restore(parent,saved);report['passed']=True
finally:
 for path,saved in list(reversed(restores)):
  restore(path,saved)
 if child is not None and child.poll() is None:child.terminate();child.wait(timeout=15);report['forced_cleanup']=True
 if log:log.close()
 report['owned_process_exited']=child is None or child.poll() is not None
 if 'port' in globals():
  with socket.socket() as sock:sock.settimeout(1);report['listener_closed']=sock.connect_ex(('127.0.0.1',port))!=0
 (root/'result.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report),flush=True)
