import { describe, expect, it } from 'vitest';
import { frameworkGroups } from './assetKinds';

describe('framework discovery from explicit configuration evidence', () => {
  it('shows Hermes when inventory supplies only profiles and combines its installations', () => {
    expect(frameworkGroups([
      { framework: 'hermes', source_type: 'hermes_profile' },
      { framework: 'hermes', source_type: 'hermes_profile' },
    ])).toEqual([{ framework: 'hermes', configurationRecords: 2, roleCount: 2 }]);
  });

  it('does not treat a Skill, MCP entry, or unknown framework as framework configuration', () => {
    expect(frameworkGroups([
      { framework: 'hermes', source_type: 'skill_dir' },
      { framework: 'openclaw', source_type: 'mcp_server' },
      { framework: 'unknown', source_type: 'platform_config' },
      { framework: '', source_type: 'hermes_profile' },
    ])).toEqual([]);
  });

  it('counts configured roles separately from their framework configuration', () => {
    expect(frameworkGroups([
      { framework: 'openclaw', source_type: 'platform_config' },
      { framework: 'openclaw', source_type: 'openclaw_agent' },
      { framework: 'openclaw', source_type: 'skill_dir' },
    ])).toEqual([{ framework: 'openclaw', configurationRecords: 2, roleCount: 1 }]);
  });
});
