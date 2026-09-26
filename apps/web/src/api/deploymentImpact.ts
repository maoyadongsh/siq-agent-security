import { post } from './client';
import { parseDeploymentPreview, type DeploymentPreview } from './deploymentPreview';

export interface DeploymentImpact {
  schema_version: 'enterprise-deployment-impact/v1';
  preview: DeploymentPreview;
  registered_subject: { binding_id: string; environment_id: string; asset_id: string; agent_instance_id: string };
  coverage: 'registered_binding_only';
  shared_runtime_occupants: 'unknown';
  skill_isolation: 'not_established';
  execution_confirmation_supported: false;
  impact_digest: string;
}
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const id = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 64;

export function parseDeploymentImpact(value: unknown, expected: DeploymentPreview): DeploymentImpact {
  const keys = ['schema_version', 'preview', 'registered_subject', 'coverage', 'shared_runtime_occupants', 'skill_isolation', 'execution_confirmation_supported', 'impact_digest'];
  if (!object(value) || !exact(value, keys) || value.schema_version !== 'enterprise-deployment-impact/v1'
    || value.coverage !== 'registered_binding_only' || value.shared_runtime_occupants !== 'unknown'
    || value.skill_isolation !== 'not_established' || value.execution_confirmation_supported !== false
    || typeof value.impact_digest !== 'string' || !/^[a-f0-9]{64}$/.test(value.impact_digest)) throw new Error('影响响应不完整');
  const preview = parseDeploymentPreview(value.preview, { change_request_id: expected.change_id, environment_id: expected.environment_id, binding_id: expected.binding_id });
  if (!(Object.keys(expected) as (keyof DeploymentPreview)[]).every(key => preview[key] === expected[key])) throw new Error('影响预览已变化');
  const subject = value.registered_subject;
  if (!object(subject) || !exact(subject, ['binding_id', 'environment_id', 'asset_id', 'agent_instance_id'])
    || !Object.values(subject).every(id) || subject.binding_id !== expected.binding_id
    || subject.environment_id !== expected.environment_id) throw new Error('影响目标不匹配');
  return value as unknown as DeploymentImpact;
}

/** A read-only POST/preflight; never approves or executes the preview. */
export async function readDeploymentImpact(item: DeploymentPreview): Promise<DeploymentImpact> {
  return parseDeploymentImpact(await post<unknown>('/deployment-preview/impact', {
    schema_version: 'enterprise-deployment-impact-request/v1', change_request_id: item.change_id,
    environment_id: item.environment_id, binding_id: item.binding_id, preview_digest: item.preview_digest,
  }, { timeoutMs: 60000 }), item);
}
