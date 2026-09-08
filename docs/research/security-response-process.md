# Security response process

Owner: @maoyadongsh, sole maintainer. Private entry and its API readback are linked in SECURITY.md. The owner's direct repository-operation instruction authorizes configuring that owner's reporting channel; no test vulnerability was sent. Notification delivery and an actual response have not been exercised.

1. Receive a private report; acknowledge when available. The proposed three/ten-working-day targets have not been accepted as a staffed SLA.
2. Reproduce against an exact SHA in a disposable environment. Separate secrets, user data and controlled fixtures. Preserve a restricted original and publish only sanitized evidence.
3. Determine impact, including whether credential material was used in an external system. Revoke/replace confirmed active credentials through that system's owner; history deletion is insufficient.
4. Prepare a scoped fix and negative regression test. Verify authorization, receipt and effect invariants and applicable CI.
5. Coordinate disclosure, affected versions, upgrade instructions and reporter credit. Do not automatically publish a private advisory or contact third parties without authorization.
6. Publish a correction linked to the affected artifact; retain historical research identities. Close only after readback of the relevant remediation.
