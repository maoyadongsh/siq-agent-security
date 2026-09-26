import { expect, it } from 'vitest';
import { frameworkTreeQuery } from './frameworkTreeNavigation';

it('retains only framework view and exact environment/device filters', () => {
  const result = new URLSearchParams(frameworkTreeQuery(new URLSearchParams({
    view: 'candidates', environment_id: 'env+a &b', device_id: 'edge-one',
    tenant_id: 'foreign', redirect: 'https://example.invalid', cursor: 'agt_old',
  })));
  expect([...result.entries()]).toEqual([
    ['view', 'framework'], ['environment_id', 'env+a &b'], ['device_id', 'edge-one'],
  ]);
});

it('does not invent absent filters', () => {
  expect(frameworkTreeQuery(new URLSearchParams())).toBe('view=framework');
});
