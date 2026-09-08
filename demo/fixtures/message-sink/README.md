# Controlled delivery sink

Started by the isolated Secure Agent fixture service. `POST /messages/<routing
value SHA256>` accepts report bytes; `GET /messages` lists observed recipient,
payload digest, action ID and received time. The sink resolves the opaque route
using its separately loaded trusted directory. No external email is sent.

The request target and report bytes are precommitted to SIQ before execution.
A message authorization must precede the separate HTTP authorization. Using an
opaque route keeps mail routing metadata separate from report payload; it does
not conceal report bytes from SIQ's network request scan.
