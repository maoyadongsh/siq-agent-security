from pathlib import Path
import json,base64,hashlib,copy
from jsonschema import Draft7Validator
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
b=Path.cwd();out=b/'.tmp/windows-goal-20260916/grant-produced-contract-r4'
raw=(out/'produced.json').read_bytes();data=json.loads(raw);pub=Ed25519PublicKey.from_public_bytes(base64.b64decode(data['public_key']))
schema=json.loads((b/'.tmp/win-resource-facts-20260918/packages/contracts/grant.v2.schema.json').read_text(encoding='utf-8'));validator=Draft7Validator(schema)
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
def digest(x):return hashlib.sha256(canon(x)).hexdigest()
results=[]
for row in data['rows']:
 g=row['grant'];validator.validate(g);signed=copy.deepcopy(g);signature=signed.pop('signature');pub.verify(bytes.fromhex(signature),canon(signed))
 p=copy.deepcopy(g)
 for f in ['status','effective_readback','signature','signing_schema']:p.pop(f,None)
 for f in p['facts']:
  if f['domain']=='tool':
   if f['state'] in ['declared','effective']:f['state']='runtime_eligible'
  else:f.pop('state',None)
  for key in ['authority','authority_revision','readback_evidence_id']:f.pop(key,None)
 p['digest_schema']='grant-permissions/v2';assert digest(p)==row['permission_digest']
 keys=['grant_id','admission_id','subject','platform','facts','default_effect','hermes_toolset_allowlist','openclaw_tool_policy','desired_policy_ref','overlap_conflicts','enforcement_mode','status','expires_at']
 bind={k:g.get(k) for k in keys};bind.update(digest_schema='grant-approval-binding/v2',schema_version=g['schema_version'],filesystem_profile=g['filesystem_profile'],filesystem_bindings=g['filesystem_bindings']);assert digest(bind)==row['binding_digest']
 tools=set();resources=set()
 for f in g['facts']:
  if f['effect'] in ['allow','require_approval']:
   tools.add(f['domain']+':'+f['action']);resources.add(f['domain']+'|'+f['resource']['type']+'|'+f['resource']['value'])
 for t in g.get('hermes_toolset_allowlist',[]):tools.add('hermes:'+t)
 for name,prefix in [('allow','openclaw:allow:'),('require_approval','openclaw:req:')]:
  for t in g.get('openclaw_tool_policy',{}).get(name,[]):tools.add(prefix+t)
 scope=dict(tools=sorted(tools),resources=sorted(resources),digest_schema='grant-approval-scope/v2',schema_version=g['schema_version'],filesystem_profile=g['filesystem_profile'],filesystem_bindings=g['filesystem_bindings']);assert digest(scope)==row['scope_digest']
 results.append({'platform':g['platform'],'status':g['status'],'schema_valid':True,'signature_valid':True,'permission_digest_matches':True,'approval_binding_matches':True,'approval_scope_matches':True,'filesystem_binding_count':len(g['filesystem_bindings'])})
result={'source_sha':'a24e029b177c110a97637f3c6902ab99670b33b7','method':'native Go component producer + independent Python verification','production_authority':False,'source_dirty':False,'input_sha256':hashlib.sha256(raw).hexdigest(),'rows':results,'exit':0}
(out/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(result))
