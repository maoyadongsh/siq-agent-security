# Historical credential review

The calibrated Gitleaks scanner found no additional findings in fetched local Git refs (`--all`) or the extracted V5 RC. Exact scope, ref hashes, scanner calibration and limitations are in [history-scan-summary.json](evidence/history-scan-summary.json). This does not establish that every secret is detected.

A separate path-history check confirmed `apps/control-api/signing-key.seed` was added in `364dade` and deleted in `145e53f`. The base64 seed is task-signing private material, not a release publisher key. Its bytes are not reproduced here. The public record includes only its digest and provenance. A deletion from the current tree does not remove the public historical blob or revoke any relying deployment.

The current configuration requires production signing material from the environment and generates development keys outside the repository. This prevents accidental use of the old in-tree default, but does not demonstrate that an external deployment revoked an old key. External deployment usage was asked of the owner separately and is recorded in history-disposition.md.

Fetched branches/tags are covered; inaccessible forks, mirrors and historical release asset binaries were not scanned. Those are explicit limits, not passed checks. No history rewrite, forced push, user-state deletion or credential-use attempt was performed.
