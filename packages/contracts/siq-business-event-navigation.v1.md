# SIQ business event navigation v1

The existing `siq.business-security-event/v1` export and connector stay unchanged.
`siq://business-security-event/sev_<64 lowercase hex>` is a locator, never authority.

Control API `GET /api/v1/agents/{asset_id}/business-navigation` requires the current
tenant's asset and `agent:read`. It returns `{schema_version:
"siq.business-event-navigation/v1", configured: boolean, items: [{evidence_id,
event_id, href}]}`. Only gateway evidence linked to that asset qualifies. The
origin comes exclusively from the administrator's JSON map
`SIQ_AS_BUSINESS_WEB_ORIGINS` keyed by verified security tenant ID. Unconfigured
tenants receive an empty list. Origins permit HTTPS, or HTTP on literal loopback
hosts only; credentials, paths, query, fragment and control characters are refused.
The only generated destination is `/analysis/security-event?event_id=sev_…`.
No security credentials or raw business identifiers cross that link.

Research API `GET /api/analysis/chat/result/from-security-event?event_id=sev_…`
requires its own authenticated business account. The producer keeps a private,
immutable `.navigation/{event_id}.json` index beside its export. Index v1 contains
only `schema_version: siq.business-event-index/v1`, `event_id`, `result_id` (the
existing retained-result SHA256 primary key). It is not ingested by the connector.
Only terminal, confidential `siq_analysis` runs receive an index. No index means
unavailable; historical events are not guessed from names or URLs.

The resolver uses bounded no-follow file reads, queries the result by primary key
AND current business tenant/user/profile, validates the stored result and current
business scope, and returns `{schema_version: siq.business-event-result/v1,
event_id, session_id, run_id}`. It returns no body. Missing/foreign records yield
404; denied/revoked scope yields 403; malformed request yields 400. All responses
are no-store. The browser constructs the existing same-origin result route, which
rechecks permission before metadata/content reads. A security administrator has
no implicit business read permission. Navigation does not create a session, run,
grant, approval, or report publication.
