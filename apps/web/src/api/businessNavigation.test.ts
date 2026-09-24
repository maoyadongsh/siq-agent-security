import { describe, expect, it } from 'vitest';
import { parseNavigation } from './businessNavigation';

const event_id = 'sev_' + 'a'.repeat(64);
const value = (origin = 'https://research.example.com') => ({ schema_version: 'siq.business-event-navigation/v1' as const, configured: true,
  items: [{ evidence_id: 'ev:test', event_id, href: `${origin}/analysis/security-event?event_id=${event_id}` }] });
describe('business navigation', () => {
  it('accepts only the fixed result resolver and safe schemes', () => {
    for (const origin of ['https://research.example.com', 'http://127.0.0.1:15173', 'http://[::1]:15173']) expect(parseNavigation(value(origin))).toEqual(value(origin));
  });
  it.each(['javascript:alert(1)', 'http://evil.example', 'https://user:password@research.example.com', '//research.example.com'])('rejects %s', origin => {
    expect(() => parseNavigation(value(origin))).toThrow();
  });
  it.each(['#leak', '&redirect=https://evil.example', '&event_id=other'])('rejects extra URL components %s', suffix => {
    const data = value(); data.items[0].href += suffix;
    expect(() => parseNavigation(data)).toThrow();
  });
  it('rejects duplicate evidence and unavailable config claiming links', () => {
    const data = value(); data.items.push(data.items[0]);
    expect(() => parseNavigation(data)).toThrow();
    expect(() => parseNavigation({ ...value(), configured: false })).toThrow();
  });
});
