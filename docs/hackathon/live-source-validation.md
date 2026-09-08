> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Live GitHub validation status — 2026-09-08

The earlier anonymous GitHub request exhausted the API quota. A later read of
`https://api.github.com/repos/pallets/flask/commits/HEAD`, requesting the SHA-only
media type, returned HTTP 200, revision
`d318b683471101618febed18996405ad26462110`, and 25 remaining requests.
This proves that endpoint was reachable at the probe time; it is not an Agent
task completion or a permanent assertion about HEAD.

The subsequent [actual ornith task attempt](evidence/live-github-ornith-20260908.json)
was configured for `pallets/flask`, path `src/flask/signals.py`, and the live
GitHub endpoint. Its first planning call failed as `model_request_failed` after
about 60.06 seconds, consistent with the configured 60-second client timeout.
The archived diagnostic does not retain the underlying exception subtype. It produced zero
tool actions and zero effects. At that checkpoint live-source Agent completion
was unverified. The record's `source_mode` is the configured mode; it does
not claim files were fetched in this failed attempt. No fixture fallback or
automatic retry was used.

The existing model checkpoint CLI now accepts repository, scope and live endpoint
arguments and retains failure evidence:

```bash
SIQ_MODEL_PROVIDER=ornith SIQ_ORNITH_ENDPOINT=http://127.0.0.1:8006/v1 \
SIQ_ORNITH_MODEL=Ornith-1.5-35B-A3B-NVFP4 \
apps/control-api/.venv/bin/python scripts/hackathon/model-checkpoint.py \
  --binary .tmp/hackathon-bin/siq-agent-security \
  --state-dir .tmp/hackathon-runs/new-live-github \
  --out .tmp/new-live-github.json \
  --github-endpoint https://api.github.com \
  --repository pallets/flask --scope src/flask/signals.py
```

The subsequent [schema-constrained ornith run](evidence/live-github-structured-20260908.json)
completed the same live-source task in **21.90 seconds**: three accepted model
calls, actual pinned GitHub source reads, 22 verified signed receipts and two
SIQ effect readbacks for report and delivery. Its source mode is `live_github`.
This is one successful live-source checkpoint, not a GitHub availability SLA or
proof of semantic review accuracy. It used the schema-only generation profile;
the later direct-output profile has a separate controlled-source utility cohort.
Contacts and delivery still use the controlled local receiver. No external email
was sent, and the earlier rate-limit/transport failures remain archived.
