import { describe, expect, it } from 'vitest';
import { resultPresentation, effectTypeLabel } from './resultPresentation';

describe('result facts remain distinct from task execution', () => {
  it('never promotes a missing or self-reported result to running, failed, or successful', () => {
    expect(resultPresentation('incomplete', 'effect_evidence_missing').label).toBe('结果待核验');
    expect(resultPresentation('unknown', 'effect_evidence_insufficient').label).toBe('结果无法确认');
    expect(resultPresentation('unknown', 'not_required').label).toBe('未设置结果核验');
    expect(resultPresentation('unknown', 'effects_verified').label).toBe('结果无法确认');
  });
  it('distinguishes observed failures, conflicts and verified requirements', () => {
    expect(resultPresentation('incomplete', 'effect_failed').label).toBe('观测到执行失败');
    expect(resultPresentation('conflicting', 'task_security_incident').explanation).toContain('安全事件');
    expect(resultPresentation('verified', 'effects_verified').label).toBe('结果核验通过');
  });
  it('keeps unknown codes out of business text and does not guess an effect', () => {
    expect(JSON.stringify(resultPresentation('unknown', 'PRIVATE-NEW-CODE'))).not.toContain('PRIVATE');
    expect(effectTypeLabel('custom.report.completed')).toBe('其他效果类型');
    expect(effectTypeLabel('file.write')).toBe('文件写入');
  });
});
