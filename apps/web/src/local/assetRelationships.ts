import type { LedgerAsset } from './types';

/** Only join explicit discovery edges, never names, adjacent paths or framework labels. */
export function assetRelationships(rows: LedgerAsset[]) {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const sourcesBySkill = new Map<string, Set<string>>();
  const skillsBySource = new Map<string, Set<string>>();
  for (const row of rows) for (const edge of row.relationships ?? []) {
    const source = byId.get(edge.source_id);
    if (edge.state !== 'inferred' || !edge.evidence_ids?.length || !source || source.source_type === 'skill_dir'
      || byId.get(edge.skill_id)?.source_type !== 'skill_dir') continue;
    const sources = sourcesBySkill.get(edge.skill_id) ?? new Set<string>();
    sources.add(edge.source_id); sourcesBySkill.set(edge.skill_id, sources);
    const skills = skillsBySource.get(edge.source_id) ?? new Set<string>();
    skills.add(edge.skill_id); skillsBySource.set(edge.source_id, skills);
  }
  return { sourcesBySkill, skillsBySource };
}
