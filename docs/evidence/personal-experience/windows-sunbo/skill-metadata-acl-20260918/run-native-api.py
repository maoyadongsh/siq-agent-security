from pathlib import Path
import subprocess,os,json,hashlib,ctypes
from ctypes import wintypes
base=Path.cwd();build=base/'.tmp/windows-goal-20260916/skill-private-clean-r1';provenance=json.loads((build/'results.json').read_text(encoding='utf-8'))
assert provenance['source_sha']=='6a6e47ce17801074ae5d3e3244928b417814cc08'
assert provenance['binary_sha256']=='b2a37de466b86634f36627f9bdd51347a4213ae4f135ca814228b8a761eeed19'
assert not provenance['source_dirty'] and any(c['name']=='native-build' and c['exit']==0 for c in provenance['checks'])
binary=build/'agent.exe';assert hashlib.sha256(binary.read_bytes()).hexdigest()==provenance['binary_sha256']
root=base/'.tmp/win-task-native/bootstrap-fixed-20260917/skill-native-private-replay';root.mkdir(exist_ok=False);home=root/'home';home.mkdir();state=root/'state'
fixture=Path(__file__).with_name('read-fixture-acl.ps1')
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
env={k:v for k,v in os.environ.items() if not k.startswith(('SIQ_','AGENTSHIELD_')) and k not in ('WORKBUDDY_CONFIG_DIR','CODEBUDDY_CONFIG_DIR')}
env.update(SIQ_AGENT_SECURITY_STATE_DIR=str(state),HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData/Roaming'),LOCALAPPDATA=str(home/'AppData/Local'),HERMES_HOME=str(home/'.hermes'),PYTHONUTF8='1')
for key in ['APPDATA','LOCALAPPDATA','HERMES_HOME']:Path(env[key]).mkdir(parents=True,exist_ok=True)
host=home/'.openclaw';host.mkdir();config=host/'openclaw.json';original_config=b'{"gateway":{"mode":"local"},"fixture":"retain"}\n';config.write_bytes(original_config)
report={'source_sha':provenance['source_sha'],'binary_sha256':provenance['binary_sha256'],'method':'native SIQ daemon and API against isolated synthetic OpenClaw profile; host/model not invoked','checks':[],'commands':[]};restores=[]
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
try:
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 check('init',cli('01-init','init','--port',str(port))==0)
 source=root/'source';source.mkdir();content=b'---\nname: acl-fixture\ndescription: Read a synthetic report.\n---\nRead a report.\n';(source/'SKILL.md').write_bytes(content)
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
 check('owned-daemon-healthy',True)
 code=api('02-pairing','POST','/v1/session/pairing',credential=(state/'admin-recovery.token').read_text().strip(),headers={'X-SIQ-Local-CLI':'1'})['code']
 session=api('03-pair','POST','/v1/pair',{'code':code},credential='')['session']
 instance='hi-'+hashlib.sha256(host.as_posix().lower().encode()).hexdigest()[:32]
 rows=api('04-instances','GET','/v1/adapter/instances?platform=openclaw')['instances'];check('synthetic-profile-discovered',any(r['instance_id']==instance for r in rows))
 iid='si-'+'a'*32;actor='acl-fixture-human'
 imported=api('05-import','POST','/v1/skill-imports',{'schema_version':'local-skill-import-create/v1','import_id':iid,'source_kind':'local_dir','path':str(source),'actor_id':actor},want=201)
 record=imported['import']
 draft=api('06-permissions','POST','/v1/skill-imports/'+iid+'/permissions',{'schema_version':'local-skill-import-permission-create/v1','request_id':'ip-'+'b'*32,'artifact_digest':record['artifact_digest'],'analysis_sha256':record['analysis_sha256'],'instance_id':instance,'actor_id':actor},want=201)
 gid=draft['grant']['grant_id'];gpath='/v1/grants/'+gid
 patched=api('07-tools','POST',gpath+'/patch-desired',{'expected_revision':draft['state_revision'],'actor_id':actor,'tools':['read']})
 revision=patched['state_revision'];challenge=api('08-challenge','POST',gpath+'/challenge',{'expected_revision':revision,'actor_id':actor})['challenge']
 approved=api('09-approve','POST',gpath+'/approve',{'expected_revision':revision,'actor_id':actor,'challenge_id':challenge['challenge_id'],'nonce':challenge['nonce']})
 plan=api('10-stage','POST','/v1/skill-installations/plans',{'schema_version':'local-skill-install-stage-create/v1','request_id':'is-'+'c'*32,'grant_id':gid,'expected_revision':approved['state_revision'],'instance_id':instance,'directory_name':'acl-fixture','actor_id':actor},want=201)['plan']
 plans=state/'skill-installations/plans';planfile=plans/(plan['plan_id']+'.json');route='/v1/skill-installations/plans/'+plan['plan_id']
 for label,path in [('metadata-root',plans.parent),('plans',plans),('plan',planfile)]:
  facts=json.loads(acl(path,'audit'));check(label+'-independent-acl',facts['owner_current'] and facts['protected'] and facts['unknown_allow_count']==0 and set(facts['allowed_classes'])=={'current_user','system','administrators'},descriptor=facts)
 for index,(label,path) in enumerate([('plan',planfile),('plans',plans),('metadata-root',plans.parent)]):
  saved=acl(path);setacl(path,saved.split('S:')[0]+'(A;;GR;;;WD)');restores.append((path,saved));wide=acl(path);before_host=snapshot(home);before_metadata=snapshot(plans.parent)
  status,body=request('GET',route);check(label+'-cached-read-denied',status==409 and body.get('error')=='skill_install_changed',http_status=status)
  check(label+'-target-preserved',snapshot(home)==before_host);check(label+'-metadata-preserved',snapshot(plans.parent)==before_metadata);check(label+'-acl-not-repaired',acl(path)==wide)
  setacl(path,saved);restores.remove((path,saved));api('11-restored-'+str(index),'GET',route)
 installed=api('12-install','POST','/v1/skill-installations/apply',{'schema_version':'local-skill-install-apply/v1','plan_id':plan['plan_id'],'plan_signature':plan['signature'],'actor_id':actor,'confirm_install':True})
 check('installed-unverified',installed['status']=='installed_unverified' and installed['operation']['runtime_verified'] is False and installed['plan']['runtime_verified'] is False)
 target=host/'skills/acl-fixture/SKILL.md';check('actual-content-copied',target.read_bytes()==content)
 installroute='/v1/skill-installations/operations/'+installed['install_id']
 for index,path in enumerate(sorted((state/'skill-installations/operations').glob('*.json'))):
  facts=json.loads(acl(path,'audit'));check('operation-'+str(index)+'-independent-acl',facts['owner_current'] and facts['protected'] and facts['unknown_allow_count']==0 and set(facts['allowed_classes'])=={'current_user','system','administrators'},descriptor=facts)
  original=acl(path);setacl(path,original.split('S:')[0]+'(A;;GR;;;WD)');restores.append((path,original));wide=acl(path);before_host=snapshot(home);before_metadata=snapshot(state/'skill-installations')
  status,body=request('GET',installroute);check('operation-'+str(index)+'-wide-read-denied',status==409 and body.get('error')=='skill_install_changed',http_status=status)
  check('operation-'+str(index)+'-target-preserved',snapshot(home)==before_host);check('operation-'+str(index)+'-metadata-preserved',snapshot(state/'skill-installations')==before_metadata);check('operation-'+str(index)+'-acl-not-repaired',acl(path)==wide)
  setacl(path,original);restores.remove((path,original))
 view=api('13-removal-preview','GET',installroute+'/removal')
 removed=api('14-remove','POST',installroute+'/removal',{'schema_version':'local-skill-install-remove/v1','operation_signature':installed['operation']['signature'],'expected_grant_revision':view['state_revision'],'expected_binding_signature':view['binding_signature'],'actor_id':actor,'confirm_remove':True})
 check('owned-target-removed',not target.exists());check('original-config-preserved',config.read_bytes()==original_config)
 check('signed-stop',cli('15-stop','stop','--confirm-stop')==0);check('owned-daemon-exit',child.wait(timeout=15)==0)
 report['passed']=True
finally:
 for path,saved in reversed(restores):setacl(path,saved)
 if child is not None and child.poll() is None:child.terminate();child.wait(timeout=15);report['forced_cleanup']=True
 if log:log.close()
 report['all_fixture_acls_restored']=True;report['owned_process_exited']=child is None or child.poll() is not None;report['model_calls']=0
 if 'port' in globals():
  with socket.socket() as sock:sock.settimeout(1);report['listener_closed']=sock.connect_ex(('127.0.0.1',port))!=0
 save();print(json.dumps({'passed':report.get('passed',False),'checks':len(report['checks']),'http':len(report.get('http',[])),'source_sha':report['source_sha'],'owned_process_exited':report['owned_process_exited']}),flush=True)
