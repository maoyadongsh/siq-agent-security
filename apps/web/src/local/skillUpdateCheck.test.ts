import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isCurrentSkillUpdateRequest, isSkillUpdateCheckResult, isSkillUpdateScheduleView, planSkillUpdateSourceToggle, updateCheckErrorText } from './skillUpdateCheck';
const sample = () => JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-skill-update-check-result.json', import.meta.url), 'utf8'));
const scheduleSample = () => JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-skill-update-schedule-view.json', import.meta.url), 'utf8'));
describe('upstream checks never authorize an update', () => {
  it('accepts the Go contract sample and binds it to the installation', () => {
    const v = sample(); expect(isSkillUpdateCheckResult(v, v.install_id)).toBe(true);
    expect(isSkillUpdateCheckResult(v, 'sin-' + 'e'.repeat(64))).toBe(false);
    expect(isSkillUpdateCheckResult({ ...v, status: 'up_to_date', content_changes: [], content_changes_total: 0, requires_confirmation: false }, v.install_id)).toBe(true);
  });
  it('rejects inconsistent, oversized or malformed evidence', () => {
    const v = sample();
    for (const patch of [{ requires_confirmation: false }, { checked_at: 'now' }, { content_changes_total: 4 }, { content_changes_truncated: true },
      { content_changes: [{ ...v.content_changes[0], before: null, after: null }] }, { permission_comparison: 'approved' }, { raw_url: 'private' },
      { upstream_commit_sha: 'a'.repeat(40) }, { content_changes: Array(201).fill(v.content_changes[0]) }]) expect(isSkillUpdateCheckResult({ ...v, ...patch }, v.install_id)).toBe(false);
    expect(isSkillUpdateCheckResult({ ...v, content_changes: Array(200).fill(v.content_changes[0]), content_changes_total: 201, content_changes_truncated: true }, v.install_id)).toBe(true);
  });
  it('does not echo raw transport diagnostics and distinguishes unavailable from changed', () => {
    expect(updateCheckErrorText(new Error('private-token'))).not.toContain('private-token');
    expect(updateCheckErrorText(new Error('skill_install_unavailable'))).toContain('未完成检查');
    expect(updateCheckErrorText(new Error('skill_install_changed'))).toContain('不一致');
  });
});
describe('update schedule view never leaks the saved locator or scheduling internals', () => {
  it('accepts the Go contract sample and binds it to the installation', () => {
    const v = scheduleSample();
    expect(isSkillUpdateScheduleView(v, v.install_id)).toBe(true);
    expect(isSkillUpdateScheduleView(v, 'sin-' + 'e'.repeat(64))).toBe(false);
  });
  it('rejects locator leakage, wrong vocabularies and inconsistent optional fields', () => {
    const v = scheduleSample();
    for (const patch of [
      { display: 'https://git.example.com/org/skill.git?token=secret' },
      { display: 'https://user:pass@git.example.com/org/skill.git' },
      { display: 'https://git.example.com/org/skill.git#fragment' },
      { display: 'file:///etc/skills' },
      { source_state: 'stale' }, { source_state: 'needs_source', display: '', enabled: false },
      { status: 'unknown' }, { source_kind: 'local_zip', display: '', enabled: false },
      { enabled: 'yes' }, { next_check_at: 'now' },
      { next_check_at: '2026-09-14T12:00:00Z', source_state: 'needs_source', display: '', enabled: false },
      { locator: 'https://git.example.com/org/skill.git' }, { signature: 'x'.repeat(64) },
      { failure_category: '' }, { failure_category: 'x'.repeat(65) },
    ]) expect(isSkillUpdateScheduleView({ ...v, ...patch }, v.install_id)).toBe(false);
    // A saved, currently disabled source keeps its display but drops timestamps;
    // a last failed attempt may carry a bounded failure_category.
    const { next_check_at: _drop, ...withoutNext } = v;
    expect(isSkillUpdateScheduleView({ ...withoutNext, enabled: false }, v.install_id)).toBe(true);
    expect(isSkillUpdateScheduleView({ ...withoutNext, failure_category: 'source_unavailable' }, v.install_id)).toBe(true);
    // Local kinds are never "saved": no display, no optional fields, not enabled.
    const local = { ...withoutNext, source_kind: 'local_dir', display: '', enabled: false, source_state: 'unsupported', status: 'unsupported' };
    expect(isSkillUpdateScheduleView(local, v.install_id)).toBe(true);
    expect(isSkillUpdateScheduleView({ ...local, display: v.display }, v.install_id)).toBe(false);
  });
  it('plans URL-free disable while retaining explicit enable binding rules', () => {
    const v = scheduleSample();
    expect(planSkillUpdateSourceToggle({ ...v, source_kind: 'https_zip', enabled: true }, '')).toEqual({ kind: 'disable' });
    expect(planSkillUpdateSourceToggle({ ...v, enabled: false }, '')).toEqual({ kind: 'save', remoteURL: '' });
    expect(planSkillUpdateSourceToggle({ ...v, source_kind: 'git', source_state: 'needs_source', display: '', enabled: false }, '')).toEqual({ kind: 'save', remoteURL: '' });
    expect(planSkillUpdateSourceToggle({ ...v, source_kind: 'https_zip', enabled: false }, '')).toMatchObject({ kind: 'error' });
    expect(planSkillUpdateSourceToggle({ ...v, source_kind: 'https_zip', enabled: false }, '  https://download.example/skill.zip  ')).toEqual({ kind: 'save', remoteURL: 'https://download.example/skill.zip' });
    expect(planSkillUpdateSourceToggle({ ...v, source_state: 'stale', display: '', enabled: false }, 'https://download.example/skill.zip')).toMatchObject({ kind: 'error' });
    expect(planSkillUpdateSourceToggle({ ...v, source_kind: 'local_dir', source_state: 'unsupported', display: '', enabled: false, status: 'unsupported' }, '')).toMatchObject({ kind: 'error' });
  });
  it('rejects a late result after the installation identity changes', async () => {
    let current = 'install-a/session-a';
    let release: (value: string) => void = () => {};
    const owner = current;
    const pending = new Promise<string>((resolve) => { release = resolve; }).then((value) =>
      isCurrentSkillUpdateRequest(owner, current, false) ? value : undefined);
    current = 'install-b/session-a';
    release('old-view');
    await expect(pending).resolves.toBeUndefined();
    expect(isCurrentSkillUpdateRequest(current, current, false)).toBe(true);
    expect(isCurrentSkillUpdateRequest(current, current, true)).toBe(false);
  });
});
