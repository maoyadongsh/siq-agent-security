# Enterprise user service status v1

Linux `edge-agent user-service-status` reads only the current user's fixed
siq-edge-discovery.service through /usr/bin/systemctl --user show --no-pager
--property=LoadState,ActiveState,UnitFileState. No shell, arbitrary unit argument,
state-file read, registration, heartbeat, scan, reload, enable or restart.
Command timeout is 20 seconds, stdout is bounded to 4096 bytes, stderr discarded.
Manager unavailable, malformed output and duplicate/missing/extra properties
return a fixed error, not a fabricated inactive service. Unknown property values
become `unknown`; raw diagnostics, unit paths and environment are never returned.

JSON: schema_version=enterprise-user-service-status/v1, unit, load_state,
active_state, unit_file_state. heartbeat_verified, discovery_verified and
protection_verified are always false. Active is service-manager state, not proof
of control-plane connectivity, completed discovery or runtime protection.
No caller-selected unit, host, system scope or bus is exposed as a CLI option.
The current user session/system manager environment remains an OS trust boundary.
This diagnostic is not installation ownership or binary-integrity verification.

Other operating systems return an unsupported error. No lifecycle mutation or
automatic remediation follows from reading status. Missing installation or an
unavailable user manager requires explicit installation/session diagnosis.
