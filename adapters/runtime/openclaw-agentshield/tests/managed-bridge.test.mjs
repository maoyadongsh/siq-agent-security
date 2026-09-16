// Test entry: each scenario runs in a child process because the plugin reads
// its config and credential once at import time. Run with:
//   node --experimental-strip-types --test tests/managed-bridge.test.mjs
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const SCENARIOS = [
  "legacy-no-enrollment-no-capture",
  "managed-allow-enrolls-and-captures-params",
  "managed-ignores-host-agent-id",
  "managed-enroll-failure-fails-closed",
  "managed-foreign-platform-enrollment-rejected",
  "managed-legacy-token-rejected",
  "managed-observe-with-reference-captures-output",
  "managed-output-capture-skips-undefined-leaves",
  "managed-capture-timeout-is-best-effort",
  "managed-deny-blocks-with-receipt",
  ...["block", "warn", "audit_only"].flatMap(mode =>
    ["enroll", "decide", "missing-reference", "bad-identity", "bad-config", "no-session", "remote", "credentials-url", "query-url", "redirect", "expired"].map(failure => `boundary-${mode}-${failure}`)),
  ...[
    "duplicate-post",
    "duplicate-pre",
    "blocked-hold",
    "approved-hold",
    "reserve-rejected",
    "reserve-malformed",
    "reserve-response-loss",
  ].map(flow => `correlation-${flow}`),
];

for (const name of SCENARIOS) {
  test(name, () => {
    const result = spawnSync(
      process.execPath,
      ["--experimental-strip-types", new URL("./scenarios.mjs", import.meta.url).pathname, name],
      { encoding: "utf8", timeout: 30_000 },
    );
    if (result.status !== 0) {
      throw new Error(`scenario ${name} failed\n${result.stdout}\n${result.stderr}`);
    }
  });
}
