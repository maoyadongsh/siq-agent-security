from pathlib import Path
import subprocess,os,json,hashlib,ctypes
from ctypes import wintypes
base=Path.cwd();build=base/'.tmp/windows-goal-20260916/intent-private-clean-r1';provenance=json.loads((build/'results.json').read_text(encoding='utf-8'))
assert provenance['source_sha']=='a968d6194e41f4924653b39684a7fa4d8dfd0bcb'
assert provenance['binary_sha256']=='4724100e1b74aa16960e7f1b9eb2e9f7a80f7bd05d5d3ebee4aa7692e1bf1d1b'
assert not provenance['source_dirty'] and any(c['name']=='native-build' and c['exit']==0 for c in provenance['checks'])
binary=build/'agent.exe';assert hashlib.sha256(binary.read_bytes()).hexdigest()==provenance['binary_sha256']
root=base/'.tmp/win-task-native/bootstrap-fixed-20260917/intent-native-private-r1';root.mkdir(exist_ok=False);home=root/'home';home.mkdir();state=root/'state'
fixture=Path(__file__).with_name('read-fixture-acl.ps1')
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
env={k:v for k,v in os.environ.items() if not k.startswith(('SIQ_','AGENTSHIELD_')) and k not in ('WORKBUDDY_CONFIG_DIR','CODEBUDDY_CONFIG_DIR')}
env.update(SIQ_AGENT_SECURITY_STATE_DIR=str(state),HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData/Roaming'),LOCALAPPDATA=str(home/'AppData/Local'),HERMES_HOME=str(home/'.hermes'),PYTHONUTF8='1')
for key in ['APPDATA','LOCALAPPDATA','HERMES_HOME']:Path(env[key]).mkdir(parents=True,exist_ok=True)
host=home/'.openclaw';host.mkdir();config=host/'openclaw.json';original_config=b'{"gateway":{"mode":"local"},"fixture":"retain"}\n';config.write_bytes(original_config)
report={'source_sha':provenance['source_sha'],'binary_sha256':provenance['binary_sha256'],'method':'native SIQ authority management and decision API with synthetic Hermes session; no host/model invocation','checks':[],'commands':[]};restores=[]
def save(): (root/'result.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
def check(name,ok,**kw):
 report['checks'].append(dict(name=name,passed=bool(ok),**kw));save();assert ok,name
def cli(label,*args):
 with (root/(label+'.stdout.private')).open('wb') as out,(root/(label+'.stderr.private')).open('wb') as err:
  p=subprocess.run([str(binary),*args],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
 report['commands'].append({'label':label,'args':list(args),'exit':p.returncode});save();return p.returncode
def acl(path,mode='read'):
 assert path.is_relative_to(root)
 p=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-File',str(fixture),str(root),str(path),mode],env=dict(os.environ,PSModulePath=str(ps.parent/'Modules')),capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
 assert p.returncode==0,'independent descriptor query failed'
 return p.stdout.decode('utf-8-sig').strip()
adv=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
convert=adv.ConvertStringSecurityDescriptorToSecurityDescriptorW;convert.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.DWORD)];convert.restype=wintypes.BOOL
setsecurity=adv.SetFileSecurityW;setsecurity.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.c_void_p];setsecurity.restype=wintypes.BOOL
kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
def setacl(path,sddl):
 assert path.is_relative_to(root)
 descriptor=ctypes.c_void_p()
 if not convert(sddl,1,ctypes.byref(descriptor),None):raise ctypes.WinError(ctypes.get_last_error())
 try:
  control=sddl.split('D:',1)[1].split('(',1)[0];flags=4|(0x80000000 if 'P' in control else 0x20000000)
  if not setsecurity(str(path),flags,descriptor):raise ctypes.WinError(ctypes.get_last_error())
 finally:kernel.LocalFree(descriptor)
def snapshot(directory):
 return {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}
import socket,time,urllib.request,urllib.error
child=None;log=None;session=''
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(method,path,body=None,credential=None,headers=None):
 h={'Content-Type':'application/json'};h.update(headers or {})
 token=session if credential is None else credential
 if token:h['Authorization']='Bearer '+token
 data=None if body is None else json.dumps(body).encode('utf-8')
 req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=data,headers=h,method=method)
 try:
  with opener.open(req,timeout=65) as r:status,raw=r.status,r.read()
 except urllib.error.HTTPError as e:status,raw=e.code,e.read()
 return status,json.loads(raw) if raw else {}
def api(label,method,path,body=None,want=200,**kw):
 status,out=request(method,path,body,**kw)
 report.setdefault('http',[]).append({'label':label,'method':method,'path':path,'status':status,'error':out.get('error')});save()
 (root/(label+'.response.private.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 assert status==want,(label,status,out.get('error'))
 return out
renamed=[]
try:
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 check('init',cli('01-init','init','--port',str(port))==0)
 log=(root/'daemon.private.log').open('wb')
 child=subprocess.Popen([str(binary),'serve','--port',str(port)],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 deadline=time.monotonic()+40
 while time.monotonic()<deadline:
  assert child.poll() is None,'owned daemon exited'
  try:
   if request('GET','/healthz/instance',credential='')[0]==200:break
  except OSError:pass
  time.sleep(.1)
 else:raise RuntimeError('health timeout')
 check('native-daemon-healthy',True)
 code=api('02-pairing','POST','/v1/session/pairing',credential=(state/'admin-recovery.token').read_text().strip(),headers={'X-SIQ-Local-CLI':'1'})['code']
 session=api('03-pair','POST','/v1/pair',{'code':code},credential='')['session'];decision_token=(state/'token').read_text().strip()
 contract={'schema_version':'intent/v2','intent_id':'int-native-acl','task_id':'task-native-acl','principal':{'type':'user','id':'fixture-human'},'agent':{'id':'fixture-agent','platform':'hermes'},'purpose':'Read isolated synthetic report','allowed_tools':['read_file'],'allowed_effects':['file.read'],'resource_constraints':[],'parameter_constraints':[],'issued_at':'2026-01-01T00:00:00Z','valid_from':'2026-01-01T00:00:00Z','expires_at':'2099-01-01T00:00:00Z','authority':{'issuer':'local-admin','revision':'r1','evidence_ids':[]}}
 issued=api('04-issue','POST','/v1/intents',contract,want=201)
 before=snapshot(state/'intents');again=api('05-repeat','POST','/v1/intents',contract,want=201)
 check('repeat-same-authority',again['signature']==issued['signature']);check('repeat-no-scratch-or-rewrite',snapshot(state/'intents')==before)
 binding=api('06-bind','POST','/v1/intent-bindings',{'platform':'hermes','session_id':'fixture-session','agent_id':'fixture-agent','intent_id':issued['intent_id']},want=201)
 req={'platform':'hermes','session_id':'fixture-session','agent_id':'fixture-agent','tool':'read_file','params':{'path':str(root/'fixture.txt')}}
 (root/'fixture.txt').write_text('synthetic report',encoding='utf-8')
 baseline=api('07-decision','POST','/v1/decide',req,credential=decision_token)
 check('baseline-authority-valid',baseline['authority_status']=='valid')
 intentfile=state/'intents'/(issued['intent_id']+'.json');bindingfile=state/'intent-bindings'/(binding['binding_id']+'.json');revocationdir=state/'intent-binding-revocations'
 for label,path in [('intents',intentfile.parent),('intent',intentfile),('bindings',bindingfile.parent),('binding',bindingfile),('binding-revocations',revocationdir),('intent-revocations',state/'intent-revocations'),('contexts',state/'context-assertions')]:
  facts=json.loads(acl(path,'audit'));check(label+'-independent-acl',facts['owner_current'] and facts['protected'] and facts['unknown_allow_count']==0 and set(facts['allowed_classes'])=={'current_user','system','administrators'},descriptor=facts)
 def authority_snapshot():
  return {name:snapshot(state/name) for name in ('intents','intent-bindings','intent-binding-revocations','intent-revocations','context-assertions')}
 for index,(label,path) in enumerate([('intent',intentfile),('intents',intentfile.parent),('binding',bindingfile),('bindings',bindingfile.parent),('empty-revocations',revocationdir)]):
  original=acl(path);setacl(path,original.split('S:')[0]+'(A;;GR;;;WD)');restores.append((path,original));wide=acl(path);before=authority_snapshot();before_home=snapshot(home)
  denied=api('08-denied-'+str(index),'POST','/v1/decide',req,credential=decision_token)
  check(label+'-invalid-authority-denied',denied['action']=='deny' and denied['effective_action']=='deny' and denied['authority_status']=='invalid',reason_code=denied['reason_code'])
  check(label+'-authority-bytes-preserved',authority_snapshot()==before);check(label+'-host-preserved',snapshot(home)==before_home);check(label+'-acl-not-repaired',acl(path)==wide)
  setacl(path,original);restores.remove((path,original))
  restored=api('09-restored-'+str(index),'POST','/v1/decide',req,credential=decision_token);check(label+'-restored-authority-valid',restored['authority_status']=='valid')
 assert revocationdir.is_relative_to(root) and not list(revocationdir.iterdir())
 retained=revocationdir.with_name('intent-binding-revocations-fixture-retained');assert not retained.exists();revocationdir.rename(retained);renamed.append((retained,revocationdir))
 missing=api('10-missing-dir','POST','/v1/decide',req,credential=decision_token);check('missing-revocation-directory-denies',missing['authority_status']=='invalid' and missing['action']=='deny',reason_code=missing['reason_code'])
 retained.rename(revocationdir);renamed.clear()
 revoked=api('11-revoke','POST','/v1/intents/'+issued['intent_id']+'/revoke',{'expected_intent_digest':issued['digest']})
 stopped=api('12-revoked-decision','POST','/v1/decide',req,credential=decision_token);check('explicit-revocation-denies',stopped['action']=='deny' and stopped['reason_code']=='intent_revoked')
 revfile=state/'intent-revocations'/(issued['intent_id']+'.json');facts=json.loads(acl(revfile,'audit'));check('revocation-independent-acl',facts['owner_current'] and facts['protected'] and facts['unknown_allow_count']==0 and set(facts['allowed_classes'])=={'current_user','system','administrators'},descriptor=facts)
 check('signed-stop',cli('13-stop','stop','--confirm-stop')==0);check('owned-daemon-exit',child.wait(timeout=15)==0)
 check('receipt-signatures-verify',cli('14-verify','verify','--chain','local')==0)
 report['passed']=True
finally:
 for path,saved in reversed(restores):setacl(path,saved)
 for retained,original in reversed(renamed):retained.rename(original)
 if child is not None and child.poll() is None:child.terminate();child.wait(timeout=15);report['forced_cleanup']=True
 if log:log.close()
 report['all_fixture_acls_restored']=True;report['all_fixture_directories_restored']=True;report['owned_process_exited']=child is None or child.poll() is not None;report['model_calls']=0
 if 'port' in globals():
  with socket.socket() as sock:sock.settimeout(1);report['listener_closed']=sock.connect_ex(('127.0.0.1',port))!=0
 save();print(json.dumps({'passed':report.get('passed',False),'checks':len(report['checks']),'http':len(report.get('http',[])),'source_sha':report['source_sha'],'owned_process_exited':report['owned_process_exited']}),flush=True)
