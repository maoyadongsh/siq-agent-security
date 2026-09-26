import { describe, expect, it } from 'vitest';
import { assetRelationships } from './assetRelationships';
import type { DiscoveryRelationship, LedgerAsset } from './types';

const edge = (source: string, skill: string): DiscoveryRelationship => ({
  relationship_id: `${source}-${skill}`, source_id: source, skill_id: skill, state: 'inferred',
  basis: 'profile_directory', evidence_ids: ['evidence'],
});
const asset = (id: string, source_type: string, relationships: DiscoveryRelationship[] = []): LedgerAsset => ({
  id, source_type, name: 'same-name', framework: 'hermes', status: 'discovered', source_locator: '/same/path', evidence_ids: [], relationships,
});
describe('explicit configuration hierarchy', () => {
  it('deduplicates shared edges without inventing a runtime skill attribution', () => {
    const result = assetRelationships([asset('role1', 'hermes_profile', [edge('role1', 'skill')]),
      asset('role2', 'hermes_profile', [edge('role2', 'skill')]), asset('skill', 'skill_dir', [edge('role1', 'skill')])]);
    expect([...result.sourcesBySkill.get('skill')!]).toEqual(['role1', 'role2']);
    expect([...result.skillsBySource.get('role1')!]).toEqual(['skill']);
  });
  it('leaves names and paths unassociated without evidence, and drops dangling edges', () => {
    const result = assetRelationships([asset('role', 'hermes_profile', [edge('missing', 'skill'),
      { ...edge('role', 'skill'), evidence_ids: [] }]), asset('skill', 'skill_dir')]);
    expect(result.sourcesBySkill.size).toBe(0);
    expect(result.skillsBySource.size).toBe(0);
  });
});
