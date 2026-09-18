import { describe, expect, it } from 'vitest';
import type { Grant, RuntimeIdentity } from './types';
import {
  grantFilesystemProfile, identityFilesystemConfirmation, identityFilesystemProfile,
  identityFilesystemReviewKey, resourceFilesystemConfirmation, windowsPathLines, type DisplayFilesystemProfile,
} from './filesystemProfile';

const legacy: Grant = {
  grant_id: 'gr-test', admission_id: 'adm-test', platform: 'hermes', status: 'pending_approval',
  subject: { type: 'agent_instance', id: 'hri-test' }, enforcement_mode: 'block',
  created_at: '2026-09-18T00:00:00Z', state_revision: 3,
};
const windows: Grant = { ...legacy, schema_version: 'grant/v2', filesystem_profile: 'windows-local-drive/v1', filesystem_bindings: {} };

describe('filesystem interpretation submission boundaries', () => {
  it('preserves rejected Windows aliases for the backend instead of silently repairing them', () => {
    const raw = 'C:\\Reports \\Sub  \r\n\r\n D:\\资料\\尾点.\n \nE:\\Case\\Report\r';
    expect(windowsPathLines(raw)).toEqual(['C:\\Reports \\Sub  ', ' D:\\资料\\尾点.', ' ', 'E:\\Case\\Report\r']);
    expect(windowsPathLines('')).toEqual([]);
  });

  it('keeps an existing drive-looking resource under legacy interpretation until separately confirmed', () => {
    const driveText: Grant = { ...legacy, facts: [{ fact_id: 'f-test', domain: 'filesystem', action: 'fs.read',
      state: 'declared', effect: 'allow', resource: { type: 'path', value: 'C:\\Reports' } }] };
    expect(grantFilesystemProfile(driveText)).toBe('posix/v1');
    expect(resourceFilesystemConfirmation(driveText, 'posix/v1', false)).toEqual({ profile: 'posix/v1' });
    expect(resourceFilesystemConfirmation(driveText, 'windows-local-drive/v1', false)).toBeNull();
    expect(resourceFilesystemConfirmation(driveText, 'windows-local-drive/v1', true)).toEqual({ profile: 'windows-local-drive/v1', confirmed: true });
  });

  it('requires confirmation again for a Windows revision and refuses a downgrade in the submit path', () => {
    expect(resourceFilesystemConfirmation(windows, 'windows-local-drive/v1', false)).toBeNull();
    expect(resourceFilesystemConfirmation(windows, 'windows-local-drive/v1', true)).toEqual({ profile: 'windows-local-drive/v1', confirmed: true });
    expect(resourceFilesystemConfirmation(windows, 'posix/v1', true)).toBeNull();
    expect(resourceFilesystemConfirmation(windows, 'posix/v1', false)).toBeNull();
    expect(resourceFilesystemConfirmation(legacy, 'windows-local-drive/v2' as DisplayFilesystemProfile, true)).toBeNull();
  });

  it.each([
    { platform: 'codebuddy' },
    { subject: { type: 'skill', id: 'skill-test' } },
    { skill: { skill_id: 'skill-test' } },
  ])('does not upgrade an unsupported managed subject: %j', (fields) => {
    expect(resourceFilesystemConfirmation({ ...legacy, ...fields }, 'windows-local-drive/v1', true)).toBeNull();
  });

  it.each([
    { schema_version: 'grant/v3' },
    { schema_version: 'grant/v2' },
    { filesystem_profile: 'windows-local-drive/v1' },
    { filesystem_bindings: {} },
    { ...windows, filesystem_profile: 'posix/v1' },
    { ...windows, filesystem_bindings: null },
    { ...windows, filesystem_bindings: [] },
  ])('rejects partial or unknown signed profile metadata without treating it as legacy: %j', (fields) => {
    const malformed = { ...legacy, ...fields } as unknown as Grant;
    expect(grantFilesystemProfile(malformed)).toBe('unsupported');
    expect(resourceFilesystemConfirmation(malformed, 'posix/v1', true)).toBeNull();
    expect(resourceFilesystemConfirmation(malformed, 'windows-local-drive/v1', true)).toBeNull();
    expect(identityFilesystemConfirmation('hermes', 'hi-test', malformed, '')).toBeNull();
  });
});

describe('independent identity filesystem review', () => {
  const reviewed = identityFilesystemReviewKey('hermes', 'hi-test', windows);

  it('allows WorkBuddy only after separate Windows resource and identity confirmations', () => {
    const oldWorkBuddy = { ...legacy, platform: 'workbuddy' };
    expect(grantFilesystemProfile(oldWorkBuddy)).toBe('posix/v1');
    expect(resourceFilesystemConfirmation(oldWorkBuddy, 'windows-local-drive/v1', false)).toBeNull();
    expect(resourceFilesystemConfirmation(oldWorkBuddy, 'windows-local-drive/v1', true)).toEqual({ profile: 'windows-local-drive/v1', confirmed: true });
    expect(identityFilesystemConfirmation('workbuddy', 'hi-test', oldWorkBuddy, '')).toBeNull();
    const newWorkBuddy = { ...windows, platform: 'workbuddy' };
    const workBuddyReview = identityFilesystemReviewKey('workbuddy', 'hi-test', newWorkBuddy);
    expect(identityFilesystemConfirmation('workbuddy', 'hi-test', newWorkBuddy, reviewed)).toBeNull();
    expect(identityFilesystemConfirmation('workbuddy', 'hi-test', newWorkBuddy, '')).toBeNull();
    expect(identityFilesystemConfirmation('workbuddy', 'hi-test', newWorkBuddy, workBuddyReview)).toEqual({ profile: 'windows-local-drive/v1', confirmed: true });
    expect(identityFilesystemConfirmation('workbuddy', 'hi-test', { ...newWorkBuddy, state_revision: 4 }, workBuddyReview)).toBeNull();
  });

  it('requires its own review instead of accepting a grant resource or ordinary permission confirmation', () => {
    expect(reviewed).not.toBe('');
    expect(resourceFilesystemConfirmation(windows, 'windows-local-drive/v1', true)).not.toBeNull();
    for (const otherConfirmation of ['', 'true', `${windows.grant_id}:${windows.state_revision}`]) {
      expect(identityFilesystemConfirmation('hermes', 'hi-test', windows, otherConfirmation)).toBeNull();
    }
    expect(identityFilesystemConfirmation('hermes', 'hi-test', windows, reviewed)).toEqual({ profile: 'windows-local-drive/v1', confirmed: true });
  });

  it.each([
    ['hermes', 'hi-other', windows],
    ['hermes', 'hi-test', { ...windows, grant_id: 'gr-other' }],
    ['hermes', 'hi-test', { ...windows, state_revision: 4 }],
    ['openclaw', 'hi-test', { ...windows, platform: 'openclaw' }],
  ] as const)('invalidates an old review when the selection changes (%s, %s, %j)', (platform, instance, grant) => {
    expect(identityFilesystemReviewKey(platform, instance, grant)).not.toBe(reviewed);
    expect(identityFilesystemConfirmation(platform, instance, grant, reviewed)).toBeNull();
  });

  it.each([undefined, 0, -1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1])('cannot review a missing or invalid revision %s', (revision) => {
    const grant = { ...windows, state_revision: revision };
    expect(identityFilesystemReviewKey('hermes', 'hi-test', grant)).toBe('');
    expect(identityFilesystemConfirmation('hermes', 'hi-test', grant, '')).toBeNull();
  });

  it('requires an instance and matching platform, while legacy creation remains v1', () => {
    expect(identityFilesystemConfirmation('hermes', '', windows, reviewed)).toBeNull();
    expect(identityFilesystemConfirmation('openclaw', 'hi-test', windows, reviewed)).toBeNull();
    expect(identityFilesystemConfirmation('hermes', 'hi-test', undefined, reviewed)).toBeNull();
    expect(identityFilesystemConfirmation('hermes', 'hi-test', legacy, '')).toEqual({ profile: 'posix/v1' });
    expect(identityFilesystemConfirmation('hermes', 'hi-test', legacy, reviewed)).toEqual({ profile: 'posix/v1' });
  });

  it('requires both new identity metadata fields before displaying a Windows identity', () => {
    const identity = { grant_ref: { grant_id: 'gr-test' } } as RuntimeIdentity;
    expect(identityFilesystemProfile(identity)).toBe('posix/v1');
    expect(identityFilesystemProfile({ ...identity, filesystem_profile: 'windows-local-drive/v1' })).toBe('unsupported');
    expect(identityFilesystemProfile({ ...identity, grant_ref: { ...identity.grant_ref, permission_digest_schema: 'grant-permissions/v2' } })).toBe('unsupported');
    expect(identityFilesystemProfile({ ...identity, filesystem_profile: 'windows-local-drive/v1',
      grant_ref: { ...identity.grant_ref, permission_digest_schema: 'grant-permissions/v2' } })).toBe('windows-local-drive/v1');
  });
});
