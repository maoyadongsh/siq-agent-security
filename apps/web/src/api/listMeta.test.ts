import { describe, expect, it } from 'vitest';
import { formatListCoverage, parseListMeta } from './listMeta';

describe('DEV13-D list meta', () => {
  it('parses truncation headers', () => {
    const h = new Headers({
      'X-SIQ-List-Limit': '50',
      'X-SIQ-List-Returned': '50',
      'X-SIQ-List-Truncated': '1',
      'X-SIQ-Next-Cursor': 'c1',
    });
    const meta = parseListMeta(h);
    expect(meta.truncated).toBe(true);
    expect(meta.nextCursor).toBe('c1');
    expect(meta.total).toBeNull();
    expect(formatListCoverage(meta, 50)).toMatch(/不是全量/);
  });

  it('never treats page size as total when total header absent', () => {
    const h = new Headers({
      'X-SIQ-List-Returned': '2',
      'X-SIQ-List-Truncated': '1',
      'X-SIQ-List-Total': '9',
    });
    const meta = parseListMeta(h);
    expect(formatListCoverage(meta, 2)).toMatch(/共 9 条/);
    expect(formatListCoverage(meta, 2)).not.toMatch(/共 2 条$/);
  });
});
