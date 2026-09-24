import { get } from './client';

export type BusinessNavigation = { schema_version: 'siq.business-event-navigation/v1'; configured: boolean; items: { evidence_id: string; event_id: string; href: string }[] };
export function parseNavigation(value: BusinessNavigation): BusinessNavigation {
  if (!value || value.schema_version !== 'siq.business-event-navigation/v1' || typeof value.configured !== 'boolean'
    || !Array.isArray(value.items) || value.items.length > 200 || (!value.configured && value.items.length)) throw new Error('invalid_navigation');
  const seen = new Set<string>();
  for (const item of value.items) {
    if (!item || typeof item.evidence_id !== 'string' || !item.evidence_id || seen.has(item.evidence_id)
      || typeof item.event_id !== 'string' || !/^sev_[0-9a-f]{64}$/.test(item.event_id)
      || typeof item.href !== 'string') throw new Error('invalid_navigation');
    const url = new URL(item.href);
    if (url.username || url.password || url.hash || !['http:', 'https:'].includes(url.protocol)
      || (url.protocol === 'http:' && !['127.0.0.1', '[::1]'].includes(url.hostname))
      || item.href !== `${url.origin}/analysis/security-event?event_id=${item.event_id}`) throw new Error('invalid_navigation');
    seen.add(item.evidence_id);
  }
  return value;
}
export async function businessNavigation(assetId: string) {
  return parseNavigation(await get<BusinessNavigation>(`/agents/${encodeURIComponent(assetId)}/business-navigation`));
}
