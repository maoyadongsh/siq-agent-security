# Recompute reported results

Run the commands in REPRODUCIBILITY.md track B. `benchmarks/hackathon/verify.py` authenticates receipt-chain consistency, checks effect bindings, recomputes summaries and rejects inconsistent reports. Use the exact verifier SHA from the run identity. It does not establish an external publisher identity from a key embedded in the same report.

The new local development report is [controls.json](evidence/reproduction-b/controls.json); [verification.json](evidence/reproduction-b/verification.json) contains its SHA256, 318 verified receipts, 20 effect envelopes and all metric denominators. It records a dirty development worktree and is not a clean release acceptance. All 23 expectations passed; benign completion is 5/5, unsafe materialization 0/13. The original V5 report and earlier model failures remain separate.

To verify existing data without rerunning inference:

```bash
apps/control-api/.venv/bin/python benchmarks/hackathon/verify.py \
  docs/research/evidence/reproduction-b/controls.json \
  --out .tmp/research-controls-reverified.json
```

If the output already exists, choose a new filename. Publish a correction with the old and new report digests if a metric was wrong; never silently change a signed report to match a desired table.
