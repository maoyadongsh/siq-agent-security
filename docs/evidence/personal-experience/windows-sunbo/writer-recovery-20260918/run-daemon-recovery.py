import os,subprocess,socket,time,json,hashlib,urllib.request
from pathlib import Path
base=Path.cwd();root=base/'.tmp/win-task-native/bootstrap-fixed-20260917/writer-daemon-r1';root.mkdir(exist_ok=False)
old=base/'.tmp/windows-goal-20260916/hermes-startup-checks-r1/agent.exe';new=base/'.tmp/windows-goal-20260916/writer-recovery-checks-r1/agent.exe';assert new.is_file()
state=root/'state';home=root/'home';home.mkdir();env=dict(os.environ,SIQ_AGENT_SECURITY_STATE_DIR=str(state),HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData/Roaming'),LOCALAPPDATA=str(home/'AppData/Local'),XDG_CONFIG_HOME=str(home/'.config'),HERMES_HOME=str(home/'.hermes'))
for p in [home/'AppData/Roaming',home/'AppData/Local',home/'.config',home/'.hermes']:p.mkdir(parents=True,exist_ok=True)
report={'old_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'new_sha256':hashlib.sha256(new.read_bytes()).hexdigest(),'source_sha':'84c84a1d990f3783c2afe53e9a9657f6c21b4ffd','checks':[]};child=None;log=None
assert report['old_sha256']=='08b43f749f716d042a4d2a3a0219e605a9ebeee05f5eda66c742de9064f67658'
assert report['new_sha256']=='2ab5c2ac7a290da64ec6faad72c822fcec7adfdd96de592862455caef4897f14'
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def cli(binary,args):return subprocess.run([str(binary),*args],cwd=root,env=env,capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
def check(name,ok,**details):
 report['checks'].append(dict(name=name,passed=bool(ok),**details));assert ok,name

def start(binary,label):
 global child,log
 log=(root/(label+'.private.log')).open('wb');child=subprocess.Popen([str(binary),'serve','--port',str(port)],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  assert child.poll() is None, 'owned service exited before healthy'
  try:
   with opener.open(f'http://127.0.0.1:{port}/healthz/instance',timeout=1) as r:
    if r.status==200:break
  except OSError:time.sleep(.1)
 else:raise RuntimeError('owned service health timeout')
 check(label+'-healthy',True)

def crash():
 child.kill();code=child.wait(timeout=15);log.close();check('owned-daemon-abnormal-exit',code!=0,exit=code)

def preserved():
 paths=[p for p in state.rglob('*') if p.is_file() and (p.name in ['config.json','local-instance.json','state-format.json','token','signing.seed'] or p.parent.name=='keys')]
 return {str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
try:
 p=cli(old,['init','--port',str(port)]);check('old-init',p.returncode==0,exit=p.returncode)
 start(old,'old-service');before=preserved();assert any('signing.seed' in p for p in before)
 oldlock=(state/'serve.lock').read_bytes()
 p=cli(new,['init','--port',str(port)]);check('live-old-writer-denied',p.returncode!=0 and b'write lock held' in p.stderr,exit=p.returncode)
 check('live-old-lock-unchanged',(state/'serve.lock').read_bytes()==oldlock)
 crash()
 p=cli(old,['init','--port',str(port)]);check('old-binary-reproduces-dead-lock-failure',p.returncode!=0 and b'write lock held' in p.stderr,exit=p.returncode)
 check('old-failure-preserves-identity',preserved()==before)
 p=cli(new,['init','--port',str(port)]);check('new-binary-recovers-old-crash',p.returncode==0,exit=p.returncode)
 stale=list(state.glob('serve.lock.stale.*'));check('old-crash-lock-preserved',len(stale)==1 and stale[0].read_bytes()==oldlock)
 check('identity-and-configuration-preserved',preserved()==before)
 start(new,'new-service');newlock=(state/'serve.lock').read_bytes()
 p=cli(new,['init','--port',str(port)]);check('live-new-writer-denied',p.returncode!=0 and b'write lock held' in p.stderr,exit=p.returncode)
 crash()
 p=cli(new,['init','--port',str(port)]);check('new-binary-recovers-own-crash',p.returncode==0,exit=p.returncode)
 stale=list(state.glob('serve.lock.stale.*'));check('both-crash-locks-preserved',len(stale)==2 and {p.read_bytes() for p in stale}=={oldlock,newlock})
 check('second-recovery-preserves-identity',preserved()==before)
 start(new,'recovered-service')
 p=cli(new,['stop','--confirm-stop']);check('signed-normal-stop',p.returncode==0,exit=p.returncode)
 code=child.wait(timeout=15);log.close();check('recovered-daemon-normal-exit',code==0,exit=code)
 check('normal-stop-releases-writer',not (state/'serve.lock').exists())
 report['passed']=True
finally:
 if child is not None and child.poll() is None:
  child.terminate();child.wait(timeout=15);report['forced_cleanup']=True
 if log is not None and not log.closed:log.close()
 with socket.socket() as s:s.settimeout(1);report['listener_closed']=s.connect_ex(('127.0.0.1',port))!=0
 report['owned_process_exited']=child is None or child.poll() is not None
 (root/'result.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report),flush=True)
