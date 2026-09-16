# OpenShell capability evidence v3

Additive client contract. Historical `capabilities`/booleans are documentation,
not proof of current enforcement. `configuration_capabilities` describes this
adapter's ability to express a configuration; compilers use this explicit map,
never a legacy boolean alone. Missing entries fail closed. Configuration support
does not grant execution authority. CLI apply retains O01/O02 full live readback
and current authorization requirements. There is no CLI enforcement attestation.

Capability rows identify evidence level, observation date and scope. Handshake
means a protocol-shaped response through the configured CLI, not independent
cryptographic authentication or kernel isolation. Gateway and CLI versions stay
separate. `behavior_verified` is reserved, with no implemented producer.

Only explicit CLI/endpoint selection has a reusable observation fingerprint;
it includes TLS mode and CLI file identity. PATH-selected gateways and env.sh
may change their destination indirectly: their handshake caches are never reused.
Configuration is compared before/after probing; drift invalidates that result.
Failed refresh clears cached capabilities. No credentials appear in fingerprints.

Doctor without a target reports configuration/handshake status only. Target
readback requires an explicit CLI/endpoint pair and authenticated target query and reports a fresh
revision plus full policy digest, never behavior_verified. Expired observation
is shown as expired by consumers rather than silently retaining a ready label.

Performance format agentshield.perf_baseline.v2 encodes unavailable RSS as null with source=unavailable;
runtime.MemStats.Sys stays separately named. Historical reports are unchanged.
Go bounded command pipe drainage uses at most 200ms, reduced to the configured
command timeout when it is smaller; all stdout/stderr limits remain enforced.
