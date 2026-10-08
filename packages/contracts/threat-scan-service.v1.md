# Threat scan service transport v1

Private Linux AF_UNIX/SOCK_STREAM protocol for ADR-060. This adds a transport;
the immutable `threat-scan-worker.v1.schema.json` request and success result stay v1.
One connection carries one request. No authorization credentials, retry or queue IDs.

## Framing

All integers are unsigned big-endian. Both directions start with the exact eight
bytes `SIQSCAN1`. The next byte is status, followed by four bytes of body length.

| Direction/status | Body |
| --- | --- |
| request 0 | Existing worker v1 JSON request, 1–4,194,304 bytes |
| response 0 | Existing worker v1 JSON result, 1–2,097,152 bytes |
| response 1 | Empty body: service busy |
| response 2 | Empty body: worker failed / isolation unavailable |
| response 3 | Empty body: invalid request / transport failure |

Any other status, nonzero failure length, bad magic, excessive length, truncated
or trailing bytes is a failure. Request writer shuts down its write half after
the frame; response writer closes after the frame. EOF is part of the protocol.
Request ID and all semantic bindings are checked by the existing parent; a
second result cannot be consumed on the same connection. Fresh API invocations
create fresh random task IDs. This is not a durable exactly-once queue.

## Authentication and budgets

Before sending content the client checks socket ownership/ancestor protection and
server SO_PEERCRED.uid against configured nonzero service UID. Before reading
content the service checks SO_PEERCRED.uid against its single configured nonzero
client UID. Deployment uses different service and API UIDs. A group may access
the socket but cannot substitute for the exact peer UID. No authentication by
client-provided fields. Root/user-namespace mapping is an operator prerequisite.

Absolute connection deadline is 8 seconds including frame reads/writes and EOF;
worker deadline is min(5 seconds, remaining connection budget). Service concurrent
tasks are bounded (default 2, range 1–8), with no application wait queue. An
unauthorized peer is disconnected without reading content. Busy reply is best
effort within 0.2 seconds. No payload or peer failure detail is logged.

Client failures raise fixed ScanFailure categories; no result may be persisted
as clean. Worker error response deliberately coalesces internal details. Parent
result validation remains mandatory, including task/scope/input/rule/version.
