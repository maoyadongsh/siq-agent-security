"""Risk acceptance input, object lookup and terminal state probes, real HTTP/PG."""
import json
from datetime import datetime, timedelta, timezone

from common import write_json

REJECTIONS = {'rb_empty_owner':422,'rb_blank_owner':422,'rb_long_owner':422,'rb_owner_control':422,
              'rb_blank_reason':422,'rb_extreme_expiry':422,'rb_cross_unprivileged':404,
              'rb_missing_unprivileged':404,'rb_own_unprivileged':403,'rb_cross_privileged':404,
              'rb_repeat_accept':409,'rb_resolved_accept':409}
CASES = {'rb_native_confirm':200,'rb_other_confirm':200,'rb_rules':200,'rb_findings':200,
         'rb_ack':200,'rb_accept_acknowledged':200,'rb_accept_open':200,'rb_resolve':200,
         'rb_final_findings':200,**REJECTIONS}
ASSERTIONS = ['rb_actual_rule_subjects','rb_open_control','rb_acknowledged_control','rb_resolution_control']
ASSERTIONS += [case+'_unchanged' for case in REJECTIONS]


def run(request, identity, sql, check, fault, events, out, a, b, command, python, api_dir, env, rows):
    o={}
    def record(name,value):
        o[name]=value;events.add('risk_observation',name=name,value=value);return value
    def snapshot(fid):
        return {'finding':sql('SELECT id,status,owner_user_id,risk_acceptance FROM finding WHERE id=%s',(fid,)),
                'audit':sql('SELECT id,action,actor_id FROM audit_event WHERE resource_id=%s ORDER BY id',(fid,)),
                'outbox':sql("SELECT id,event_type,payload FROM outbox_event WHERE payload->>'resource_ref'=%s ORDER BY id",(fid,))}
    def post(case,fid,auth,body):
        record(case+'_before',snapshot(fid));value=request(case,'POST',f'/api/v1/findings/{fid}/accept-risk',auth,body)
        record(case+'_after',snapshot(fid));return value
    try:
        native=json.loads((out/'native-enterprise-observations.json').read_text());asset=record('native_asset',native['asset'])
        other=record('synthetic_asset',next(x for x in native['assets'] if x['name']=='fixture-a'))
        request('rb_native_confirm','POST','/api/v1/candidates/'+asset['id']+'/confirm',a,{})
        request('rb_other_confirm','POST','/api/v1/candidates/'+other['id']+'/confirm',a,{})
        request('rb_rules','POST','/api/v1/findings/run-rules',a)
        findings=request('rb_findings','GET','/api/v1/findings',a)
        primary=next(x['id'] for x in findings if x['asset_id']==asset['id'] and x['rule_id']=='no-effective-permissions')
        open_control=next(x['id'] for x in findings if x['asset_id']==asset['id'] and x['rule_id']=='unowned-confirmed-agent')
        resolved=next(x['id'] for x in findings if x['asset_id']==other['id'] and x['rule_id']=='no-effective-permissions')
        record('subjects',{'primary':primary,'open_control':open_control,'resolved_control':resolved})
        body={'owner_user_id':'risk-owner','reason':'owned acceptance control','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        # Existing-object low-permission and foreign-object low-permission are separate.
        post('rb_cross_unprivileged',primary,identity('tp07-b','boundary-viewer'),body)
        post('rb_missing_unprivileged','missing-boundary-finding',identity(actor='boundary-viewer'),body)
        post('rb_own_unprivileged',primary,identity(actor='boundary-viewer'),body)
        post('rb_cross_privileged',primary,b,body)
        faults={'rb_empty_owner':{'owner_user_id':''},'rb_blank_owner':{'owner_user_id':'   '},
                'rb_long_owner':{'owner_user_id':'x'*65},'rb_owner_control':{'owner_user_id':'owner\nother'},
                'rb_blank_reason':{'reason':' \t\n'},'rb_extreme_expiry':{'expires_at':'9999-12-31T23:59:59-14:00'}}
        for case,change in faults.items():post(case,primary,a,{**body,**change})
        # Invalid inputs on the old product may already have changed the state.
        # Preserve that contamination as a failed control; do not reset via SQL.
        record('ack_before',snapshot(primary));request('rb_ack','POST',f'/api/v1/findings/{primary}/acknowledge',a);record('ack_after',snapshot(primary))
        post('rb_accept_acknowledged',primary,a,body)
        post('rb_repeat_accept',primary,a,{**body,'reason':'attempted terminal rewrite'})
        post('rb_accept_open',open_control,a,body)
        record('resolve_before',snapshot(resolved));request('rb_resolve','POST',f'/api/v1/findings/{resolved}/resolve',a,{'evidence_ref':'ticket:resolved-fixture'});record('resolve_after',snapshot(resolved))
        post('rb_resolved_accept',resolved,a,body)
        request('rb_final_findings','GET','/api/v1/findings',a)
        record('http',{x['case_id']:x for x in rows if x['case_id'].startswith('rb_')})
        for name,passed in evaluate(o).items():check(name,passed,{'source':'risk-observations.json','predicate':name})
    finally:
        write_json(out/'risk-observations.json',o)


def evaluate(o):
    http=o['http'];native=o['native_asset']['id'];other=o['synthetic_asset']['id'];findings=http['rb_findings']['body']
    def valid_control(case,prior):
        before,after=o[case+'_before'],o[case+'_after'];brow=before['finding'][0];row=after['finding'][0]
        audits=[x for x in after['audit'] if x[0] not in {y[0] for y in before['audit']}]
        events=[x for x in after['outbox'] if x[0] not in {y[0] for y in before['outbox']}]
        return brow[1]==prior and row[1]=='risk_accepted' and row[2]=='risk-owner' and row[3]['reason']=='owned acceptance control' and len(audits)==len(events)==1 and audits[0][1]=='finding.accept_risk' and events[0][1]=='agent.finding.resolved.v1'
    results={'rb_actual_rule_subjects':len(findings)==4 and {(x['asset_id'],x['rule_id']) for x in findings}=={(a,r) for a in (native,other) for r in ('no-effective-permissions','unowned-confirmed-agent')},
             'rb_open_control':valid_control('rb_accept_open','open'),
             'rb_acknowledged_control':o['ack_before']['finding'][0][1]=='open' and o['ack_after']['finding'][0][1]=='acknowledged' and valid_control('rb_accept_acknowledged','acknowledged'),
             'rb_resolution_control':o['resolve_before']['finding'][0][1]=='open' and o['resolve_after']['finding'][0][1]=='resolved' and o['resolve_after']['finding'][0][3]['evidence_ref']=='ticket:resolved-fixture'}
    for case in REJECTIONS:
        results[case+'_unchanged']=o[case+'_before']==o[case+'_after']
        if case=='rb_repeat_accept':results[case+'_unchanged'] &= o[case+'_before']['finding'][0][1]=='risk_accepted'
        if case=='rb_resolved_accept':results[case+'_unchanged'] &= o[case+'_before']['finding'][0][1]=='resolved'
    if set(results)!=set(ASSERTIONS):raise ValueError('risk boundary allocation differs')
    return results
