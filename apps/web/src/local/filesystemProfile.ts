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
  if (selected !== windowsFilesystemProfile || !confirmed || grant.subject.type !== 'agent_instance' || grant.skill || !['hermes', 'openclaw'].includes(grant.platform)) return null;
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
  if (grantFilesystemProfile(grant) === 'posix/v1') return { profile: 'posix/v1' };
  return reviewedKey === key ? { profile: windowsFilesystemProfile, confirmed: true } : null;
}
