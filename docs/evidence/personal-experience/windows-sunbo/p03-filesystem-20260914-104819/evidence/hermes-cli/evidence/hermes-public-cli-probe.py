"""Two public Hermes CLI cases with a synthetic loopback model; no dispatcher mocks."""
import ast
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parents[3]
CODE = Path(os.environ['LOCALAPPDATA']) / 'hermes/hermes-agent'
PYTHON = CODE / 'venv/Scripts/python.exe'
BINARY = REPO / '.tmp/win-task-native/build/siq-candidate-windows-amd64.exe'
BINARY_HASH = '4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74'
CANDIDATE = 'ebc472f2e46aa7de837afe9d6a0ed422eef51cd0'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as out:
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.write('\n')

GUARD = r'''import os, sys
try:
 import json
 from pathlib import Path
 root=Path(os.environ['SIQ_PRIVATE_ROOT']).resolve()
 code=Path(os.environ['SIQ_HERMES_CODE']).resolve()
 real_user=Path(os.environ['SIQ_REAL_USER_ROOT']).resolve()
 runtimes=[Path(sys.base_prefix).resolve(),Path(sys.prefix).resolve()]
 allowed_ports={int(x) for x in os.environ['SIQ_ALLOWED_PORTS'].split(',')}
 log=os.open(str(root/'guard-events.private.jsonl'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 def inside(path,parent): return path.is_relative_to(parent)
 def record(kind,event): os.write(log,(json.dumps({'kind':kind,'event':event})+'\n').encode())
 def reject(event):
  record('denied',event)
  raise PermissionError('private fixture guard denied '+event)
 def guard(event,args):
  if event=='socket.connect':
   address=args[1]
   if not isinstance(address,tuple) or address[0]!='127.0.0.1' or address[1] not in allowed_ports: reject(event)
   record('allowed_loopback_connect',str(address[1]))
  elif event=='socket.getaddrinfo':
   if args[0] not in ('127.0.0.1','localhost'): reject(event)
  elif event in ('subprocess.Popen','os.system','os.exec','os.spawn'): reject(event)
  elif event in ('winreg.SetValue','winreg.SetValueEx','winreg.DeleteKey','winreg.DeleteValue','winreg.CreateKey'): reject(event)
  elif event=='open' and isinstance(args[0],(str,bytes)):
   path=Path(os.fsdecode(args[0])).resolve(strict=False)
   mode=args[1] or ''; flags=args[2] or 0
   writing=any(c in mode for c in 'wax+') or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
   if writing and not inside(path,root): reject(event)
   if not inside(path,root) and (path.name in ('.env','.op.env','auth.json','credentials.json','config.yaml') or (inside(path,real_user) and not inside(path,code) and not any(inside(path,p) for p in runtimes))): reject(event)
  elif event in ('os.remove','os.rmdir','os.mkdir','os.rename','os.link','os.symlink','shutil.copyfile','os.chmod','os.truncate'):
   paths=args[:2] if event in ('os.rename','os.link','os.symlink','shutil.copyfile') else args[:1]
   for raw in paths:
    if isinstance(raw,(str,bytes)) and not inside(Path(os.fsdecode(raw)).resolve(strict=False),root): reject(event)
 sys.addaudithook(guard)
 (root/'guard-loaded.txt').write_text('python-audit-guard; not OS sandbox\n',encoding='utf-8')
except BaseException:
 os._exit(85)
'''

def main():
    started=time.monotonic()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    assert head.startswith('973')
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=REPO).strip()
    assert not subprocess.check_output(['git','diff','--name-only',CANDIDATE,head,'--','apps/agentshield','adapters/runtime/hermes-agentshield'],cwd=REPO).strip()
    assert sha(BINARY)==BINARY_HASH and PYTHON.is_file()
    markers={name:(CODE/name).exists() for name in ('.env','.update-incomplete','.lazy-refresh-incomplete')}
    assert not any(markers.values()), 'source configuration/recovery marker blocks execution'
    source_names=('hermes_cli/main.py','hermes_constants.py','hermes_cli/plugins.py','agent/tool_executor.py','model_tools.py','hermes_cli/runtime_provider_backends.py')
    source_before={name:sha(CODE/name) for name in source_names}
    parent=REPO/'.tmp/win-p03-next/hermes-public-cli'
    parent.mkdir(parents=True,exist_ok=True)
    assert parent.resolve().is_relative_to((REPO/'.tmp/win-p03-next').resolve())
    root=Path(tempfile.mkdtemp(prefix='public-cli-',dir=parent))
    rows=[]
    for label,enabled in (('A_control',False),('B_siq_offline',True)):
        case=root/label; case.mkdir()
        profile=case/'hermes/profiles/probe'; profile.mkdir(parents=True)
        workspace=case/'workspace'; workspace.mkdir()
        home=case/'home'; home.mkdir()
        temporary=case/'tmp'; temporary.mkdir()
        guard_dir=case/'guard'; guard_dir.mkdir()
        ast.parse(GUARD)
        (guard_dir/'sitecustomize.py').write_text(GUARD,encoding='utf-8')
        target=workspace/'synthetic-output.txt'
        content='private Hermes CLI control marker\n'
        reserve=socket.socket(); reserve.bind(('127.0.0.1',0)); denied_port=reserve.getsockname()[1]
        requests=[]; protocol_errors=[]
        class Provider(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def respond(self,body):
                raw=json.dumps(body).encode()
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def do_GET(self):
                requests.append({'method':'GET','route':self.path})
                if self.path=='/v1/models': self.respond({'object':'list','data':[{'id':'siq-synthetic-fixture','object':'model','created':0,'owned_by':'fixture'}]})
                else: self.send_error(404)
            def do_POST(self):
                try:
                    size=int(self.headers.get('Content-Length','0')); assert 0<size<2_000_000
                    body=json.loads(self.rfile.read(size)); assert self.path=='/v1/chat/completions'
                    names=[x.get('function',{}).get('name') for x in body.get('tools',[])]
                    results=[x for x in body.get('messages',[]) if x.get('role')=='tool']
                    requests.append({'method':'POST','route':self.path,'stream':bool(body.get('stream')),'file_tool_available':'write_file' in names,'tool_result_count':len(results),'tool_results':results})
                    if 'write_file' in names and not results:
                        message={'role':'assistant','content':None,'tool_calls':[{'id':'siq-native-write-1','type':'function','function':{'name':'write_file','arguments':json.dumps({'path':str(target),'content':content})}}]}; finish='tool_calls'
                    else: message={'role':'assistant','content':'Synthetic local fixture complete.'}; finish='stop'
                    base={'id':'siq-local-fixture','created':0,'model':'siq-synthetic-fixture'}
                    if body.get('stream'):
                        if 'tool_calls' in message: message['tool_calls'][0]['index']=0
                        chunks=[{**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':message,'finish_reason':None}]},{**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{},'finish_reason':finish}]}]
                        raw=(''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n').encode()
                        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
                    else: self.respond({**base,'object':'chat.completion','choices':[{'index':0,'message':message,'finish_reason':finish}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
                except Exception as exc:
                    protocol_errors.append(type(exc).__name__)
                    self.send_error(500,'synthetic protocol failure')
        model=ThreadingHTTPServer(('127.0.0.1',0),Provider)
        model.daemon_threads=True
        thread=threading.Thread(target=model.serve_forever,daemon=True); thread.start()
        endpoint=f'http://127.0.0.1:{model.server_port}/v1'
        config={'model':{'provider':'custom','default':'siq-synthetic-fixture','base_url':endpoint,'api_mode':'chat_completions'},'terminal':{'env':'local','cwd':str(workspace)},'plugins':{'enabled':['siq-agent-security'] if enabled else []},'memory':{'memory_enabled':False,'user_profile_enabled':False,'provider':''},'telemetry':{'shared_metrics':{'enabled':False,'send':False}},'updates':{'check':False},'local_runtime':{'enabled':False},'compression':{'enabled':False},'auxiliary':{'title_generation':{'enabled':False},'background_review':{'enabled':False}},'mcp_servers':{},'display':{'streaming':False}}
        (profile/'config.yaml').write_text(json.dumps(config),encoding='utf-8')
        (profile/'.env').write_text('',encoding='utf-8')
        plugin_hashes={}
        if enabled:
            plugin=profile/'plugins/siq-agent-security'; plugin.mkdir(parents=True)
            for name in ('__init__.py','plugin.yaml'):
                source=REPO/'adapters/runtime/hermes-agentshield'/name
                shutil.copyfile(source,plugin/name); plugin_hashes[name]=sha(source)
            token=case/'synthetic-siQ-token'; token.write_text('fixture-only-'+('x'*64),encoding='utf-8')
            write_json(plugin/'config.json',{'endpoint':f'http://127.0.0.1:{denied_port}','token_path':str(token),'enforcement_mode':'block','timeout_s':1,'agent_id':'private-native-probe'})
        env={key:os.environ[key] for key in ('SystemRoot','WINDIR','COMSPEC','PATHEXT','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE') if key in os.environ}
        env.update({'PATH':str(PYTHON.parent)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32'),'HOME':str(home),'USERPROFILE':str(home),'APPDATA':str(home/'AppData/Roaming'),'LOCALAPPDATA':str(home/'AppData/Local'),'TEMP':str(temporary),'TMP':str(temporary),'HERMES_HOME':str(profile),'CUSTOM_BASE_URL':endpoint,'NO_PROXY':'127.0.0.1,localhost','PYTHONPATH':str(guard_dir)+os.pathsep+str(CODE),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1','SIQ_PRIVATE_ROOT':str(case),'SIQ_HERMES_CODE':str(CODE),'SIQ_REAL_USER_ROOT':str(Path.home()),'SIQ_ALLOWED_PORTS':f'{model.server_port},{denied_port}','SIQ_AGENT_SECURITY_STATE_DIR':str(case/'siq-state'),'HERMES_ENABLE_PROJECT_PLUGINS':'0'})
        argv=[str(PYTHON),'-m','hermes_cli.main','chat','--provider','custom','--model','siq-synthetic-fixture','--toolsets','file','--max-turns','3','--run-budget','40','--ignore-rules','--quiet','--oneshot','-q','Write the private synthetic fixture marker using write_file.']
        before=time.monotonic(); timed_out=False
        try:
            proc=subprocess.Popen(argv,cwd=workspace,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            try: stdout,stderr=proc.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                timed_out=True; proc.kill(); stdout,stderr=proc.communicate(timeout=10)
        finally:
            model.shutdown(); model.server_close(); thread.join(timeout=2); reserve.close()
        (case/'stdout.private.log').write_bytes(stdout); (case/'stderr.private.log').write_bytes(stderr)
        write_json(case/'provider-requests.private.json',requests)
        events=[json.loads(x) for x in (case/'guard-events.private.jsonl').read_text().splitlines()] if (case/'guard-events.private.jsonl').exists() else []
        denies=[x for x in events if x['kind']=='denied']
        tool_results=[x for req in requests for x in req.get('tool_results',[])]
        text=json.dumps(tool_results)
        block_seen='siq-agent-security' in text and 'blocked (fail-closed)' in text
        wrote=target.exists() and target.read_text(encoding='utf-8')==content
        passed=(case/'guard-loaded.txt').exists() and proc.returncode==0 and not timed_out and not denies and not protocol_errors and bool(tool_results) and ((not target.exists() and block_seen) if enabled else wrote)
        row={'case':label,'status':'pass' if passed else 'blocked','exit_code':proc.returncode,'host_pid':proc.pid,'process_reaped':proc.poll() is not None,'elapsed_seconds':round(time.monotonic()-before,3),'timed_out':timed_out,'guard_loaded':(case/'guard-loaded.txt').exists(),'guard_denials':denies,'model_request_count':len(requests),'full_tool_result_seen':bool(tool_results),'siq_fail_closed_tool_result':block_seen,'target_exists':target.exists(),'expected_control_content_written':wrote,'plugin_install_method':'copied exact repository plugin files into new private profile; enabled via supported config' if enabled else 'no SIQ plugin','preexisting_plugin_configuration':False,'plugin_hashes':plugin_hashes,'argv_public':['<HERMES_PYTHON>',*argv[1:]],'raw_directory_relative':label,'protocol_errors':protocol_errors}
        rows.append(row); print(json.dumps({k:row[k] for k in ('case','status','exit_code','model_request_count','guard_denials','target_exists')}),flush=True)
        if not passed: break
    source_after={name:sha(CODE/name) for name in source_names}
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=REPO).strip()
    report={'schema_version':'hermes-public-cli-synthetic-observations/v1','candidate_sha':CANDIDATE,'checkout_head':head,'source_dirty':not clean,'binary_sha256':BINARY_HASH,'harness_sha256':sha(Path(__file__)),'entrypoint':'installed venv Python -m hermes_cli.main chat; public CLI, unchanged host dispatcher','host_version_from_prior_source_inventory':'0.21.2','host_python_sha256':sha(PYTHON),'source_files_before':source_before,'source_files_unchanged':source_before==source_after,'source_markers_present':markers,'checks':rows,'elapsed_seconds':round(time.monotonic()-started,3),'limits':['Synthetic loopback provider controls model outputs only; no real model or paid API','Python audit guard is not an OS sandbox; denies subprocesses and non-fixture networking','Offline SIQ token is synthetic and grants no authority; no live decision service or signed receipt claim','New manual plugin installation in a private profile; does not test production configuration migration','No native matrix promotion without independent raw/tool-effect review']}
    write_json(root/'report.json',report)
    print(json.dumps({'report_relative':root.relative_to(REPO).as_posix()+'/report.json','cases':len(rows),'source_unchanged':source_before==source_after,'clean':clean}),flush=True)
    return 0 if len(rows)==2 and all(x['status']=='pass' for x in rows) else 3

if __name__=='__main__': raise SystemExit(main())
