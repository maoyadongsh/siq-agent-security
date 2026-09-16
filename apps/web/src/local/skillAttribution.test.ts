import { describe, expect, it } from 'vitest';
import { skillAttributionLabel } from './skillAttribution';

describe('skillAttributionLabel', () => {
  it('shows nothing for unattributed calls', () => {
    expect(skillAttributionLabel(undefined)).toEqual({ text: '—', trusted: false });
  });
  it('shows task-level trusted attribution with its context', () => {
    const label = skillAttributionLabel({
      status: 'verified',
      skill_id: 'marketplace:skill:report-gen@0a1b2c3d4e5f',
      evidence_level: 'controlled_task',
      context_id: 'sec-' + 'a'.repeat(32),
    });
    expect(label.trusted).toBe(true);
    expect(label.text).toContain('任务级可信');
    expect(label.detail).toContain('sec-');
  });
  it('marks session-level granularity honestly', () => {
    const label = skillAttributionLabel({
      status: 'verified',
      skill_id: 's',
      evidence_level: 'controlled_session',
      context_id: 'sec-' + 'b'.repeat(32),
    });
    expect(label.trusted).toBe(true);
    expect(label.text).toContain('不含逐调用因果');
  });
  it('never upgrades a verified status missing its evidence level or context', () => {
    expect(skillAttributionLabel({ status: 'verified', skill_id: 's' }).trusted).toBe(false);
    expect(
      skillAttributionLabel({ status: 'verified', skill_id: 's', evidence_level: 'controlled_task' }).trusted,
    ).toBe(false);
  });
  it('renders mismatch and unknown as untrusted', () => {
    expect(skillAttributionLabel({ status: 'mismatch', skill_id: 's' }).text).toBe('不匹配');
    expect(skillAttributionLabel({ status: 'unknown', skill_id: 's' }).text).toBe('未验证');
  });
});
