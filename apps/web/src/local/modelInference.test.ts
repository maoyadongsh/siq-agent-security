import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isModelInferenceRecord } from './modelInference';
import type { ModelConnection } from './modelConnections';

const sample = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-model-inference-record.json', import.meta.url), 'utf8'));
const item = { id: sample.model_id, fingerprint: sample.fingerprint } as ModelConnection;

describe('model answer observations', () => {
  it('reads the real Go output and preserves historical configuration identity', () => {
    expect(isModelInferenceRecord(sample, item)).toBe(true);
    expect(isModelInferenceRecord(sample, { ...item, fingerprint: 'a'.repeat(64) })).toBe(true);
    expect(isModelInferenceRecord(sample, { ...item, id: `mc-${'b'.repeat(32)}` })).toBe(false);
  });
  it('never turns partial or uncertain results into a passed observation', () => {
    for (const patch of [
      { status: 'uncertain' }, { status: 'running', finished_at: '', expires_at: '' },
      { inference_verified: false }, { business_data_sent: true }, { service_session_only: false },
      { status: 'effective' }, { request_id: 'unbound' }, { fingerprint: '' },
      { started_at: '' }, { expires_at: sample.finished_at }, { finished_at: '' },
    ]) expect(isModelInferenceRecord({ ...sample, ...patch }, item)).toBe(false);
    expect(isModelInferenceRecord({ ...sample, status: 'running', inference_verified: false, finished_at: '', expires_at: '' }, item)).toBe(true);
    expect(isModelInferenceRecord({ ...sample, status: 'uncertain', inference_verified: false }, item)).toBe(true);
  });
});
