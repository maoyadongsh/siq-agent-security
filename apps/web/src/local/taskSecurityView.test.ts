import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isTaskSecurityView } from './taskSecurityView';

const sample = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-task-security-view.json', import.meta.url), 'utf8'));
const validate = (value: unknown) => isTaskSecurityView(value, sample.activity, 'tasks', sample.snapshot);

describe('task security view response boundary', () => {
  it('accepts the server fixture and preserves separate authorization, result, and release states', () => {
    expect(validate(sample)).toBe(true);
    expect(sample.authorization.status).toBe('mixed');
    expect(sample.actual_result.status).toBe('unknown');
    expect(sample.release_assurance.status).toBe('not_evaluated');
  });

  it('rejects optimistic status upgrades and plaintext destinations', () => {
    const changes = [
      { ...sample, authorization: { ...sample.authorization, status: 'authorized' } },
      { ...sample, actual_result: { ...sample.actual_result, status: 'verified' } },
      { ...sample, release_assurance: { status: 'passed', reason_code: 'native_candidate_verified' } },
      { ...sample, data_destinations: { ...sample.data_destinations, plaintext_exposed: true } },
      { ...sample, data_destinations: { ...sample.data_destinations, destinations: [{ ...sample.data_destinations.destinations[0], host: 'private.example' }] } },
      { ...sample, business_object: { ...sample.business_object, display_label_status: 'available', display_label: 'invented customer' } },
      { ...sample, run_mode: { ...sample.run_mode, mode_status: 'unknown' } },
      { ...sample, run_mode: { ...sample.run_mode, model_status: 'unknown' } },
      { ...sample, run_mode: { ...sample.run_mode, model_keys: ['valid', 'bad\nmodel'] } },
      { ...sample, run_mode: { ...sample.run_mode, execution_context: 'mixed' } },
      { ...sample, activity: { ...sample.activity, binding: { ...sample.activity.binding, task_id: 'other-task' } } },
    ];
    for (const value of changes) expect(validate(value)).toBe(false);
  });

  it('requires evidence for any verified effect result', () => {
    const result = { ...sample.actual_result.result, status: 'verified', reason_code: 'effects_verified', requirements: [] };
    expect(validate({ ...sample, actual_result: { ...sample.actual_result, status: 'verified', reason_code: 'effects_verified', result } })).toBe(false);
  });
});
