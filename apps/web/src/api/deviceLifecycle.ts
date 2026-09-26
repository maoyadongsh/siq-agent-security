import { get, post } from './client';

export interface DeviceCredentialStatus {
  schema_version: 'enterprise-device-credential-status/v1';
  environment_id: string;
  device_id: string;
  status: 'active' | 'revoked';
  revoked_at: string | null;
  runtime_permissions_changed: false;
}

const fields = ['schema_version', 'environment_id', 'device_id', 'status', 'revoked_at', 'runtime_permissions_changed'];
function validId(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 64 && /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(value);
}
function path(environmentId: string, deviceId: string) {
  if (!validId(environmentId) || !validId(deviceId)) throw new Error('环境或设备标识无效');
  return `/environments/${encodeURIComponent(environmentId)}/devices/${encodeURIComponent(deviceId)}`;
}

export function parseDeviceCredentialStatus(value: unknown, environmentId: string, deviceId: string): DeviceCredentialStatus {
  path(environmentId, deviceId);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('设备凭据状态待核对');
  const row = value as Record<string, unknown>;
  const timestamp = row.revoked_at;
  const revokedTime = typeof timestamp === 'string' && timestamp.length <= 40
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.test(timestamp)
    && Number.isFinite(Date.parse(timestamp));
  if (Object.keys(row).length !== fields.length || !fields.every(field => Object.hasOwn(row, field))
    || row.schema_version !== 'enterprise-device-credential-status/v1'
    || row.environment_id !== environmentId || row.device_id !== deviceId
    || row.runtime_permissions_changed !== false
    || !(row.status === 'active' && timestamp === null || row.status === 'revoked' && revokedTime)) {
    throw new Error('设备凭据状态待核对');
  }
  return { schema_version: 'enterprise-device-credential-status/v1', environment_id: environmentId,
    device_id: deviceId, status: row.status as 'active' | 'revoked', revoked_at: timestamp as string | null,
    runtime_permissions_changed: false };
}

/** Readback only: active is not proof of liveness, protection, or absence of an in-flight revoke. */
export async function readDeviceCredentialStatus(environmentId: string, deviceId: string) {
  const endpoint = path(environmentId, deviceId);
  return parseDeviceCredentialStatus(await get<unknown>(`${endpoint}/credential-status`), environmentId, deviceId);
}

/** One explicit write, never an automatic retry. Any failure requires readback before another decision. */
export async function revokeDeviceCredential(environmentId: string, deviceId: string, confirmedDeviceId: string) {
  const endpoint = path(environmentId, deviceId);
  if (confirmedDeviceId !== deviceId) throw new Error('请核对并确认目标设备');
  const result = parseDeviceCredentialStatus(await post<unknown>(`${endpoint}/revoke`, {
    schema_version: 'enterprise-device-revoke/v1', confirm_device_id: deviceId,
  }), environmentId, deviceId);
  if (result.status !== 'revoked') throw new Error('吊销结果未确认，请查询原设备状态');
  return result;
}
