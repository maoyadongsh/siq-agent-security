import { defineConfig } from 'vitest/config';

// ENT-019-AUDIT-WIRE：独立消费者契约检查配置，不并入标准单测 glob、不改依赖。
export default defineConfig({
  test: { environment: 'node', include: ['dev/audit-query-wire.check.ts'] },
});
