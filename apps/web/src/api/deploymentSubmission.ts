import { ApiError, get, post } from './client';
import type { DeploymentPreview, DeploymentSelection } from './deploymentPreview';
export interface DeploymentSubmission {
  schema_version: 'deployment-submission/v1'; id: string; change_id: string; deployment_id: string;
  state: 'unconfirmed' | 'recorded' | 'needs_attention';
  deployment_status: 'pending' | 'sent' | 'effective' | 'failed' | 'rolled_back';
  preview_digest: string; created_at: string;
}
export function parseDeploymentSubmission(value: unknown, changeId: string): DeploymentSubmission {
  const v = value as Partial<DeploymentSubmission> | null;
  const keys = ['schema_version', 'id', 'change_id', 'deployment_id', 'state', 'deployment_status', 'preview_digest', 'created_at'];
  const id = (x: unknown) => typeof x === 'string' && x.length > 0 && x.length <= 64;
  const expected = { pending: 'unconfirmed', sent: 'recorded', effective: 'recorded', failed: 'needs_attention', rolled_back: 'needs_attention' };
  if (!v || typeof v !== 'object' || Object.keys(v).length !== keys.length || !keys.every(k => k in v) || v.schema_version !== 'deployment-submission/v1' || !id(v.id) || !id(v.change_id) || v.change_id !== changeId || !id(v.deployment_id) || typeof v.deployment_status !== 'string' || !v.deployment_status || !Object.hasOwn(expected, v.deployment_status) || expected[v.deployment_status] !== v.state || typeof v.preview_digest !== 'string' || !/^[a-f0-9]{64}$/.test(v.preview_digest) || typeof v.created_at !== 'string' || !v.created_at.endsWith('Z') || !Number.isFinite(Date.parse(v.created_at))) throw new Error('部署请求记录无效');
  return v as DeploymentSubmission;
}
export async function readDeploymentSubmission(changeId: string): Promise<DeploymentSubmission | null> {
  try { return parseDeploymentSubmission(await get<unknown>(`/change-requests/${encodeURIComponent(changeId)}/deployment-submission`), changeId); }
  catch (error) { if (error instanceof ApiError && error.status === 404 && error.code === 'deployment_submission_not_found') return null; throw error; }
}
export async function createDeploymentSubmission(selection: DeploymentSelection, preview: DeploymentPreview, key: string) {
  const value = await post<unknown>('/deployment-submissions', { schema_version: 'deployment-submission-create/v1', request_key: key, ...selection, preview_digest: preview.preview_digest }, { timeoutMs: 60000 });
  return parseDeploymentSubmission(value, selection.change_request_id);
}
