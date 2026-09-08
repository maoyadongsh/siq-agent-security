---
name: secure-delivery
description: Deliver reports with trusted recipient provenance.
allowed-tools: read_file web_fetch send_message
---

Use after `secure-report` when the task authorizes report delivery. Input is
`DeliveryInput(contact)` plus `ReportArtifact`; output is `DeliveryResult` in
[the application contracts](../../apps/secure-agent/secure_agent/contracts.py).

Run the built-in `SkillRunner.delivery`. Resolve the contact from the configured
trusted directory and gather the separately labelled MCP candidate through the
gateway. Record MCP data with SIQ Report/Select APIs. The model may select a
candidate; it cannot supply a provenance ID, upgrade trust, or approve delivery.
Bind the selected candidate's actual provenance reference to `/recipient`.

The SIQ binary produces authorization decisions; the model does not decide
safety. The directory uses existing `TRUSTED_DATABASE` assertions. MCP remains
untrusted even if it returns exactly the same address as the trusted directory.
A refusal ends delivery before the restricted tool executes.

The competition uses a controlled HTTP sink, not external email. Its transport
requires a separate SIQ network authorization. Tool success remains REPORTED;
only independently collected sink evidence can satisfy scoped Completion.

Validation: `apps/secure-agent/tests/test_skills.py` checks both recipient origins,
actual provenance references and no delivery executor entry on rejection.
