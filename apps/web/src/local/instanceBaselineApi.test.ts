import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import type { Grant } from './types';

const instance = `hi-${'1'.repeat(32)}`;
const requestId = `gid-${'2'.repeat(32)}`;
const grant: Grant = { grant_id: `grt-id-${'3'.repeat(64)}`, admission_id: 'adm-real-skill', platform: 'hermes',
  subject: { type: 'agent_instance', id: `hri-${'1'.repeat(32)}` }, status: 'pending_approval',
  enforcement_mode: 'block', created_at: '2026-09-18T00:00:00Z' };
const result = { schema_version: 'grant-instance-draft-created/v1', instance_id: instance, grant, state_revision: 0, reused: false };
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 201, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('explicit instance baseline draft', () => {
  it('accepts the actual Go HTTP contract sample with its initial revision zero', async () => {
    const { localApi } = await import('./api');
    const sample = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/grant-instance-draft-created.json', import.meta.url), 'utf8'));
    vi.mocked(fetch).mockResolvedValueOnce(response(sample));
    await expect(localApi.createInstanceDraft(sample.instance_id, sample.grant.admission_id, 'operator', requestId, true, 'hermes')).resolves.toEqual(sample);
    expect(sample.state_revision).toBe(0);
  });

  it('uses the confirmed instance endpoint without client-selected platform or subject', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(result));
    await expect(localApi.createInstanceDraft(instance, grant.admission_id, 'operator', requestId, true, 'hermes')).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/v1/grants/instance-drafts');
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual({
      schema_version: 'grant-instance-draft-create/v1', instance_id: instance, admission_id: grant.admission_id,
      actor_id: 'operator', request_id: requestId, confirm_instance_scope: true,
    });
  });

  it('does not send a missing scope confirmation', async () => {
    const { localApi } = await import('./api');
    await expect(localApi.createInstanceDraft(instance, grant.admission_id, 'operator', requestId, false, 'hermes')).rejects.toMatchObject({ status: 400 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('keeps a valid replay instead of demanding that the server reset an edited grant', async () => {
    const { localApi } = await import('./api');
    const replay = { ...result, reused: true, state_revision: 3, grant: { ...grant, status: 'approved' } };
    vi.mocked(fetch).mockResolvedValueOnce(response(replay));
    await expect(localApi.createInstanceDraft(instance, grant.admission_id, 'operator', requestId, true, 'hermes')).resolves.toEqual(replay);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { schema_version: 'grant-instance-draft-created/v2' },
    { instance_id: 'hi-other' },
    { state_revision: -1 },
    { state_revision: 1.5 },
    { reused: 'false' },
    { grant: { ...grant, admission_id: 'adm-other' } },
    { grant: { ...grant, grant_id: 'grt-skill' } },
    { grant: { ...grant, platform: 'workbuddy' } },
    { grant: { ...grant, skill: { skill_id: 'real-skill' } } },
    { grant: { ...grant, subject: { type: 'agent_instance', id: 'hri-other' } } },
    { grant: { ...grant, subject: { type: 'skill', id: grant.subject.id } } },
    { grant: { ...grant, status: 'effective' } },
    { grant: null },
  ])('rejects substituted or auto-approved authority without retrying: %j', async (bad) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...result, ...bad }));
    await expect(localApi.createInstanceDraft(instance, grant.admission_id, 'operator', requestId, true, 'hermes')).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
