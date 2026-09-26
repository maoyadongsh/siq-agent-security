import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { RoleSkillHistoryDetails, SelectionDescription } from './RoleSkillSelectionPanel';
import type { RoleSkillHistory, RoleSkillSelection } from '@/api/roleSkillSelections';

const selection: RoleSkillSelection = { schema_version: 'enterprise-openclaw-skill-selection/v1', source: 'agent', status: 'declared_list', names: [] };
describe('role skill presentation', () => {
  it('distinguishes explicit empty, absent filter and unsupported configuration', () => {
    expect(renderToStaticMarkup(<SelectionDescription selection={selection} />)).toContain('不代表技能已卸载');
    expect(renderToStaticMarkup(<SelectionDescription selection={{ ...selection, source: 'none', status: 'unconfigured' }} />)).toContain('未配置技能范围筛选');
    expect(renderToStaticMarkup(<SelectionDescription selection={{ ...selection, status: 'unsupported' }} />)).toContain('不回退到默认范围');
  });
  it('escapes text instead of interpreting skill content', () => {
    const html = renderToStaticMarkup(<SelectionDescription selection={{ ...selection, names: ['<script>bad()</script>'] }} />);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });
  it('does not turn missing history into no installed skills', () => {
    const history: RoleSkillHistory = { schema_version: 'enterprise-role-skill-observations/v1', asset_id: 'asset',
      status: 'no_recorded_declaration', relationship_status: 'unresolved', effective_permissions: null,
      observations: [], observations_truncated: false };
    const html = renderToStaticMarkup(<MemoryRouter><RoleSkillHistoryDetails history={history} /></MemoryRouter>);
    expect(html).toContain('这不代表此角色没有安装技能');
  });
});
