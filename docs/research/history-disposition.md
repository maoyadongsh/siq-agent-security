# Historical key disposition

Owner confirmation on 2026-09-08: the old Control API signing key was used only for local development, never deployed externally or delivered to others. Treat its public historical bytes as exposed, never as a usable secret or official publisher identity.

The targeted local check in [credential-remediation-summary.json](evidence/credential-remediation-summary.json) derived only the old public fingerprint in memory and compared key bytes without exporting them. Current task/release seed environment variables were absent. The current default local development signing key was present and different. No external provider or remote service was contacted with the old material.

Based on the owner's usage statement and current local mismatch, there is no identified relying external deployment to revoke or notify. External revocation is not applicable. Historical local profiles were not exhaustively inspected; if one is intentionally restored, generate a fresh private development key and re-enroll its disposable clients rather than reusing this exposed key.

No credential was declared safe merely because the scanner passed. No claim is made that an Ed25519 key has a central revocation service or that deletion itself revoked it.
