import type { RuntimeIdentity } from './types';

// Metadata consistency only: this is not a grant or proof of a running host.
export function identityNativePolicy(identity: RuntimeIdentity): 'legacy' | 'required' | 'unsupported' {
  const keys = Object.keys(identity);
  if (keys.some((key) => key.toLowerCase() === 'native_skill_policy' && key !== 'native_skill_policy')) return 'unsupported';
  if (!Object.prototype.hasOwnProperty.call(identity, 'native_skill_policy')) return 'legacy';
  const policy = identity.native_skill_policy;
  if (!policy || typeof policy !== 'object' || Array.isArray(policy)
    || Object.keys(policy).length !== 2 || policy.mode !== 'required'
    || typeof policy.runtime_artifact_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(policy.runtime_artifact_sha256)
    || identity.platform !== 'hermes' || Object.prototype.hasOwnProperty.call(identity, 'filesystem_profile')
    || Object.prototype.hasOwnProperty.call(identity.grant_ref ?? {}, 'permission_digest_schema')
    || identity.runtime_state !== 'unverified') return 'unsupported';
  return 'required';
}
