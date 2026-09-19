import type { FilesystemConfirmation, Grant, RuntimeIdentity } from './types';

export type DisplayFilesystemProfile = 'posix/v1' | 'windows-local-drive/v1' | 'unsupported';
export const windowsFilesystemProfile = 'windows-local-drive/v1' as const;

export function grantFilesystemProfile(grant: Grant): DisplayFilesystemProfile {
  if (grant.schema_version === undefined && grant.filesystem_profile === undefined && grant.filesystem_bindings === undefined) return 'posix/v1';
  if (grant.schema_version === 'grant/v2' && grant.filesystem_profile === windowsFilesystemProfile
    && grant.filesystem_bindings !== null && typeof grant.filesystem_bindings === 'object' && !Array.isArray(grant.filesystem_bindings)) return windowsFilesystemProfile;
  return 'unsupported';
}

export function identityFilesystemProfile(identity: RuntimeIdentity): DisplayFilesystemProfile {
  if (identity.filesystem_profile === undefined && identity.grant_ref?.permission_digest_schema === undefined) return 'posix/v1';
  if (identity.filesystem_profile === windowsFilesystemProfile && identity.grant_ref?.permission_digest_schema === 'grant-permissions/v2') return windowsFilesystemProfile;
  return 'unsupported';
}

export function filesystemProfileLabel(profile: DisplayFilesystemProfile): string {
  return profile === windowsFilesystemProfile ? 'Windows 本地盘符路径（windows-local-drive/v1）'
    : profile === 'posix/v1' ? '原有 POSIX 路径解释' : '无法识别的路径解释，请检查服务版本';
}

// A blank line is a separator, but whitespace within a path is caller input.
// In particular, never turn a rejected trailing-space alias into a valid path.
export const windowsPathLines = (text: string): string[] => text.split(/\r?\n/).filter((line) => line !== '');

// Enforce the choice again at submission, independently of disabled controls.
export function resourceFilesystemConfirmation(grant: Grant, selected: DisplayFilesystemProfile, confirmed: boolean): FilesystemConfirmation | null {
  const current = grantFilesystemProfile(grant);
  if (current === 'unsupported' || selected === 'unsupported' || (current === windowsFilesystemProfile && selected !== current)) return null;
  if (selected === 'posix/v1') return { profile: 'posix/v1' };
  if (selected !== windowsFilesystemProfile || !confirmed || grant.subject.type !== 'agent_instance' || !supportsWindowsGrantResources(grant) || !['hermes', 'openclaw', 'workbuddy'].includes(grant.platform)) return null;
  return { profile: windowsFilesystemProfile, confirmed: true };
}

export function identityFilesystemReviewKey(platform: string, instanceId: string, grant: Grant | undefined): string {
  if (!instanceId || !grant || grant.platform !== platform || !Number.isSafeInteger(grant.state_revision)
    || (grant.state_revision ?? 0) < 1 || grantFilesystemProfile(grant) === 'unsupported') return '';
  return JSON.stringify([platform, instanceId, grant.grant_id, grant.state_revision, grantFilesystemProfile(grant)]);
}

export function identityFilesystemConfirmation(platform: string, instanceId: string, grant: Grant | undefined, reviewedKey: string): FilesystemConfirmation | null {
  const key = identityFilesystemReviewKey(platform, instanceId, grant);
  if (!key || !grant) return null;
  if (grantFilesystemProfile(grant) === 'posix/v1') return platform === 'workbuddy' ? null : { profile: 'posix/v1' };
  return reviewedKey === key ? { profile: windowsFilesystemProfile, confirmed: true } : null;
}

// This only enables the editor. The server still verifies the persisted import and fixed copy.
export function supportsWindowsGrantResources(grant: Grant): boolean {
  if (grant.subject.type !== 'agent_instance' || !['hermes', 'openclaw', 'workbuddy'].includes(grant.platform)) return false;
  const imported = /^adm-si-[a-f0-9]{64}$/.test(grant.admission_id);
  if (!imported) return !grant.skill && !grant.admission_id.startsWith('adm-si-');
  const skill = grant.skill;
  return /^hri-[a-f0-9]{32}$/.test(grant.subject.id) && !!skill && typeof skill === 'object' && !Array.isArray(skill) &&
    Object.keys(skill).every((key) => ['skill_id', 'version', 'content_hash'].includes(key)) &&
    typeof skill.skill_id === 'string' && skill.skill_id.length > 0 && skill.skill_id.length <= 128 &&
    typeof skill.content_hash === 'string' && /^[a-f0-9]{64}$/.test(skill.content_hash) &&
    (skill.version === undefined || typeof skill.version === 'string' && skill.version.length <= 64);
}
export function grantWireVersion(value: unknown): 1 | 2 | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const grant = value as Grant;
  const profile = grantFilesystemProfile(grant);
  if (profile === 'posix/v1') return 1;
  if (profile !== windowsFilesystemProfile || Object.keys(grant.filesystem_bindings ?? {}).length > 128 || !Object.values(grant.filesystem_bindings ?? {}).every((identity) => typeof identity === 'string' && /^[a-f0-9]{64}$/.test(identity))) return null;
  return 2;
}
