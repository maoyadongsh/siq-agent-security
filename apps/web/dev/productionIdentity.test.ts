import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('actual Vite configuration build guard', () => {
  it.each([
    { command: 'build', mode: 'production', app: '', flag: 'true', rejected: true },
    { command: 'build', mode: 'development', app: 'agentshield', flag: 'true', rejected: true },
    { command: 'build', mode: 'custom', app: '', flag: 'true', rejected: true },
    { command: 'build', mode: 'production', app: '', flag: 'false', rejected: false },
    { command: 'build', mode: 'production', app: 'agentshield', flag: undefined, rejected: false },
    { command: 'serve', mode: 'development', app: '', flag: 'true', rejected: false },
  ])('$command/$mode/$app/$flag', ({ command, mode, app, flag, rejected }) => {
    // Use a private empty envDir, never the developer's .env.local.
    const envDir = mkdtempSync(join(tmpdir(), 'siq-build-env-'));
    try {
      const env = { ...process.env, VITE_APP: app, NODE_ENV: 'production' };
      delete env.VITE_DEV_MODE;
      if (flag !== undefined) env.VITE_DEV_MODE = flag;
      const script = `import {resolveConfig} from 'vite'; await resolveConfig(${JSON.stringify({ envDir, mode })}, ${JSON.stringify(command)});`;
      const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { env, encoding: 'utf8', timeout: 20000 });
      expect(result.error).toBeUndefined();
      if (rejected) {
        expect(result.status).not.toBe(0);
        expect(result.stderr).toContain('SIQ build refuses VITE_DEV_MODE=true');
      } else {
        expect(result.stderr).not.toContain('SIQ build refuses');
        expect(result.status).toBe(0);
      }
    } finally { rmSync(envDir, { recursive: true, force: true }); }
  }, 25000);
});
