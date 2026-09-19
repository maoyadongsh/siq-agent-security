import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isInstalledContext, isSkillContextManagement } from './skillContextManagement';
const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-install-${name}.v2.sample.json`, import.meta.url), 'utf8'));
const view = sample('view'), ready = sample('runtime-readiness');
const context = {
  schema_version: 'skill-execution-context/v1', context_id: 'sec-'+'a'.repeat(32), issuer_id: 'local-admin',
  subject: { platform: view.plan.platform, instance_id: view.plan.instance_id, agent_id: ready.grant.subject.id, session_id: 'enrolled-session' },
  skill: ready.grant.skill, install: { install_id: view.install_id, claim_signature: view.claim_signature },
  authority: { grant_id: view.plan.grant_id, grant_digest: 'b'.repeat(64) }, evidence_level: 'controlled_session',
  issued_at: '2026-09-19T00:00:00Z', expires_at: '2026-09-19T01:00:00Z', signing_schema: 'local_canonical/v1', signature: 'c'.repeat(128),
};
const catalog = () => ({ schema_version: 'local-skill-context-management/v1', install_id: view.install_id, instance_id: view.plan.instance_id,
  sessions: [{ session_id: context.subject.session_id, expires_at: context.expires_at }], contexts: [{ context: structuredClone(context), revoked: false }] });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('installed Skill session management', () => {
  it('reads exact historical records, including expired or revoked records without calling them effective', () => {
    expect(isInstalledContext(context,view,ready)).toBe(true);
    const value=catalog(); value.contexts[0].revoked=true;
    expect(isSkillContextManagement(value,view,ready)).toBe(true);
  });
  it('rejects cross-install, instance, claim, Grant, Skill and duplicate results', () => {
    for (const change of [
      (v: ReturnType<typeof catalog>) => { v.install_id='other'; },
      (v: ReturnType<typeof catalog>) => { v.contexts[0].context.subject.instance_id='hi-'+'f'.repeat(32); },
      (v: ReturnType<typeof catalog>) => { v.contexts[0].context.install.claim_signature='f'.repeat(128); },
      (v: ReturnType<typeof catalog>) => { v.contexts[0].context.authority.grant_id='other'; },
      (v: ReturnType<typeof catalog>) => { v.contexts[0].context.skill={...ready.grant.skill,content_hash:'f'.repeat(64)}; },
      (v: ReturnType<typeof catalog>) => { v.sessions.push(v.sessions[0]); },
      (v: ReturnType<typeof catalog>) => { v.contexts.push(v.contexts[0]); },
    ]) { const value=catalog(); change(value); expect(isSkillContextManagement(value,view,ready)).toBe(false); }
  });
  it('uses only existing management request fields, pins revocation, and never retries lost writes', async () => {
    vi.stubGlobal('fetch',vi.fn()); const {localApi}=await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(context),{status:201}));
    await localApi.issueSkillSession(view,ready,context.subject.session_id,'human');
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual({schema_version:'local-skill-execution-context-issue/v1',instance_id:view.plan.instance_id,install_id:view.install_id,session_id:context.subject.session_id,task_id:'',ttl_seconds:3600,actor_id:'human',confirm_issue:true});
    vi.mocked(fetch).mockRejectedValueOnce(new Error('response lost'));
    await expect(localApi.issueSkillSession(view,ready,context.subject.session_id,'human')).rejects.toThrow();
    expect(fetch).toHaveBeenCalledTimes(2);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({schema_version:'skill-execution-context-revocation/v1',context_id:context.context_id,issuer_id:'local-admin',revoked_at:context.expires_at,signing_schema:'local_canonical/v1',signature:'d'.repeat(128)}),{status:200}));
    await localApi.revokeSkillSession(context as Parameters<typeof localApi.revokeSkillSession>[0],'human');
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[2][1]?.body)).expected_context_signature).toBe(context.signature);
  });
});
