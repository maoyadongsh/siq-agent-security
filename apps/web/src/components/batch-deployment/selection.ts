import type { DeploymentSelection } from '@/api/deploymentPreview';

/** getRandomValues also works for the user's HTTP LAN console; no Math.random fallback. */
export function batchRequestKey(random: Pick<Crypto, 'getRandomValues'> = globalThis.crypto): string {
  const bytes = random.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function addBatchSelection(current: readonly DeploymentSelection[], next: DeploymentSelection): DeploymentSelection[] {
  if (current.length >= 20) throw new Error('每批最多 20 项。');
  if (current.some(item => item.change_request_id === next.change_request_id)) throw new Error('该变更已在批次中。');
  if (current.some(item => item.binding_id === next.binding_id)) throw new Error('同一绑定每批只能选择一次。');
  return [...current, next];
}
