import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request } from './client';
import { deploymentPreviewError } from './deploymentPreview';
afterEach(() => vi.unstubAllGlobals());
describe('FastAPI deployment rejection', () => {
  it('maps a stable detail code to a safe Chinese explanation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'change_not_approved' }), { status: 409, headers: { 'content-type': 'application/json' } })));
    const error = await request('/deployment-preview/submit').catch(e => e);
    if (!(error instanceof ApiError)) throw new Error('Expected API rejection');
    expect(error.code).toBe('change_not_approved');
    expect(deploymentPreviewError(error)).toContain('此变更当前不可部署');
  });
  it('does not expose free-form backend diagnostics as a code or message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'backend failed: private credential' }), { status: 409, headers: { 'content-type': 'application/json' } })));
    const error = await request('/deployment-preview').catch(e => e);
    if (!(error instanceof ApiError)) throw new Error('Expected API rejection');
    expect(error.code).toBeUndefined();
    expect(error.message).not.toContain('private credential');
    expect(deploymentPreviewError(error)).not.toContain('private credential');
  });
});
