import { describe, expect, it } from 'vitest';
import { backendOrigin } from './localProxy';

describe('local development proxy Origin boundary', () => {
  it('translates only the exact dev server origin', () => {
    expect(backendOrigin('http://127.0.0.1:5174', '127.0.0.1:5174')).toBe('http://127.0.0.1:47611');
    expect(backendOrigin('http://localhost:5174', 'localhost:5174')).toBe('http://127.0.0.1:47611');
  });
  it('preserves foreign origins, null and absent Origin for backend checks', () => {
    for (const origin of ['http://evil.example', 'http://127.0.0.1:9999', 'null', undefined]) {
      expect(backendOrigin(origin, '127.0.0.1:5174')).toBe(origin);
    }
  });
});
