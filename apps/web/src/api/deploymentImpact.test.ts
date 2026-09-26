import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DeploymentPreview } from './deploymentPreview';
import { parseDeploymentImpact, readDeploymentImpact } from './deploymentImpact';
const post = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ post, ApiError: class extends Error {} }));
const preview: DeploymentPreview = { schema_version: 'deployment-preview/v1', change_id: 'c1', policy_id: 'p1', policy_name: 'Policy', policy_version: 1, enforcement_mode: 'block', environment_id: 'e1', environment_name: 'Fixture', binding_id: 'b1', target: 'sandbox', backend: 'fake', action: 'development_task', base_revision: null, preview_digest: 'a'.repeat(64) };
const fixture = () => ({ schema_version: 'enterprise-deployment-impact/v1', preview: { ...preview }, registered_subject: { binding_id: 'b1', environment_id: 'e1', asset_id: 'a1', agent_instance_id: 'i1' }, coverage: 'registered_binding_only', shared_runtime_occupants: 'unknown', skill_isolation: 'not_established', execution_confirmation_supported: false, impact_digest: 'b'.repeat(64) });
beforeEach(() => { post.mockReset(); });
describe('deployment impact protocol', () => {
  it('retains unknown coverage and no execution confirmation', () => {
    expect(parseDeploymentImpact(fixture(), preview).execution_confirmation_supported).toBe(false);
  });
  it.each([{ coverage: 'complete' }, { shared_runtime_occupants: [] }, { skill_isolation: 'supported' }, { execution_confirmation_supported: true }, { impact_digest: 'x' }, { raw_attestation: {} }])('rejects unrecognised authority or extra data %j', patch => {
    expect(() => parseDeploymentImpact({ ...fixture(), ...patch }, preview)).toThrow();
  });
  it.each([{ binding_id: 'other' }, { environment_id: 'other' }, { asset_id: '' }, { agent_instance_id: null }, { extra: 'field' }])('rejects invalid subject %j', patch => {
    const value = fixture();
    expect(() => parseDeploymentImpact({ ...value, registered_subject: { ...value.registered_subject, ...patch } }, preview)).toThrow();
  });
  it.each([{ preview_digest: 'c'.repeat(64) }, { policy_version: 2 }, { target: 'other' }])('rejects preview changes %j', patch => {
    expect(() => parseDeploymentImpact({ ...fixture(), preview: { ...preview, ...patch } }, preview)).toThrow();
  });
  it('sends only the bound preflight request', async () => {
    post.mockResolvedValue(fixture());
    await readDeploymentImpact(preview);
    expect(post).toHaveBeenCalledExactlyOnceWith('/deployment-preview/impact', {
      schema_version: 'enterprise-deployment-impact-request/v1', change_request_id: 'c1',
      environment_id: 'e1', binding_id: 'b1', preview_digest: preview.preview_digest,
    }, { timeoutMs: 60000 });
  });
  it('does not retry a failed preflight or return fake coverage', async () => {
    post.mockRejectedValue(new Error('forbidden'));
    await expect(readDeploymentImpact(preview)).rejects.toThrow('forbidden');
    expect(post).toHaveBeenCalledTimes(1);
  });
});
