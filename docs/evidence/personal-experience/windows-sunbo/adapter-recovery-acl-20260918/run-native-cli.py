from pathlib import Path
import subprocess,os,json,hashlib,ctypes
from ctypes import wintypes
base=Path.cwd();build=base/'.tmp/windows-goal-20260916/adapter-private-clean-r1';provenance=json.loads((build/'results.json').read_text(encoding='utf-8'))
assert provenance['source_sha']=='17763748f957606bd04f0608cc90ee917a2f2aad'
assert provenance['binary_sha256']=='7199ffb61c80aa1e407106e5030be1cff0cd0d71d5a57755a21884d47853308b'
assert not provenance['source_dirty'] and any(c['name']=='native-build' and c['exit']==0 for c in provenance['checks'])
binary=build/'agent.exe';assert hashlib.sha256(binary.read_bytes()).hexdigest()==provenance['binary_sha256']
root=base/'.tmp/win-task-native/bootstrap-fixed-20260917/adapter-native-private-r1';root.mkdir(exist_ok=False);home=root/'home';home.mkdir();state=root/'state'
fixture=root/'read-acl.ps1';original=Path(__file__).with_name('read-fixture-acl.ps1').read_text(encoding='utf-8').split('$existingDacl =')[0].replace('private-acl-daemon-r6','adapter-native-private-r1');fixture.write_text(original,encoding='utf-8',newline='\n')
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
env={k:v for k,v in os.environ.items() if not k.startswith(('SIQ_','AGENTSHIELD_')) and k not in ('WORKBUDDY_CONFIG_DIR','CODEBUDDY_CONFIG_DIR')}
env.update(SIQ_AGENT_SECURITY_STATE_DIR=str(state),HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData/Roaming'),LOCALAPPDATA=str(home/'AppData/Local'),HERMES_HOME=str(home/'.hermes'),PYTHONUTF8='1')
for key in ['APPDATA','LOCALAPPDATA','HERMES_HOME']:Path(env[key]).mkdir(parents=True,exist_ok=True)
host=home/'.openclaw';host.mkdir();config=host/'openclaw.json';original_config=b'{"gateway":{"mode":"local"},"fixture":"retain"}\n';config.write_bytes(original_config)
report={'source_sha':provenance['source_sha'],'binary_sha256':provenance['binary_sha256'],'method':'native SIQ CLI against isolated synthetic OpenClaw profile; host/model not invoked','checks':[],'commands':[]};restores=[]
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
try:
 check('init',cli('01-init','init')==0)
 before=snapshot(home)
 check('preview-install',cli('02-preview','adapter','preview','openclaw','install')==0)
 check('preview-host-unchanged',snapshot(home)==before)
 check('install',cli('03-install','adapter','install','openclaw')==0)
 key=state/'adapter-backup.key';transactions=state/'adapter-transactions';sealed=list(transactions.glob('*.sealed'));ends=list(transactions.glob('*.end.json'))
 check('one-sealed-plan-and-result',len(sealed)==1 and len(ends)==1)
 for label,path in [('key',key),('plans',transactions),('sealed',sealed[0]),('result',ends[0])]:
  facts=json.loads(acl(path,'audit'));check(label+'-independent-acl',facts['owner_current'] and facts['protected'] and facts['unknown_allow_count']==0 and set(facts['allowed_classes'])=={'current_user','system','administrators'},descriptor=facts)
 for index,(label,path) in enumerate([('key',key),('sealed',sealed[0]),('plans',transactions),('operations',state/'adapter-operations'),('writer',state/'adapter-write')]):
  saved=acl(path);setacl(path,saved.split('S:')[0]+'(A;;GR;;;WD)');restores.append((path,saved));wide=acl(path);before_host=snapshot(home);before_state=snapshot(state)
  check(label+'-unsafe-preview-denied',cli('04-deny-'+str(index),'adapter','preview','openclaw','uninstall')!=0)
  check(label+'-host-preserved',snapshot(home)==before_host)
  check(label+'-state-preserved',snapshot(state)==before_state)
  check(label+'-acl-not-repaired',acl(path)==wide)
  setacl(path,saved);restores.remove((path,saved))
 check('uninstall',cli('05-uninstall','adapter','uninstall','openclaw')==0)
 check('original-config-restored',config.read_bytes()==original_config)
 report['passed']=True
finally:
 for path,saved in reversed(restores):setacl(path,saved)
 report['all_fixture_acls_restored']=True;report['service_started']=False;report['model_calls']=0;save()
 print(json.dumps({'passed':report.get('passed',False),'checks':len(report['checks']),'commands':len(report['commands']),'source_sha':report['source_sha']}),flush=True)
