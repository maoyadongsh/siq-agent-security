import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { SkillCard } from './SkillsPage';
import type { SkillInstallation } from '@/api/skillInventory';

const skill: SkillInstallation = {
  installation_id: 'ski_a', locator_sha256: 'a'.repeat(64), environment: { id: 'env_a', name: '<script>unsafe</script>' },
  device: { id: 'edge_a', identity: 'device', revoked: true }, presence: 'observed_not_verified_current',
  relationship_status: 'unresolved', effective_permissions: null, latest_observation: null,
};
it('escapes labels and marks unknown permissions and revoked historical sources', () => {
  const html = renderToStaticMarkup(<SkillCard skill={skill} />);
  expect(html).not.toContain('<script>');
  expect(html).toContain('权限未知');
  expect(html).toContain('凭据已吊销');
  expect(html).toContain('尚未核验');
  expect(html).toContain('尚无关联证据');
  expect(html).toContain('不是整个技能包摘要');
});
it('distinguishes absent declaration from explicit empty declaration', () => {
  for (const present of [true, false]) {
    const html = renderToStaticMarkup(<SkillCard skill={{ ...skill, latest_observation: {
      observation_id: 'smo_a', manifest_sha256: 'b'.repeat(64), parser_version: 'enterprise-skill-manifest/v1',
      parse_status: 'parsed', name: 'skill-name', allowed_tools_present: present, declared_tools: [],
      observed_at: '2026-09-25T00:00:00Z', batch_digest: 'c'.repeat(64),
    } }} />);
    expect(html).toContain(present ? '显式空声明，不代表运行时无权限' : '未声明，不代表不需要权限');
  }
});
