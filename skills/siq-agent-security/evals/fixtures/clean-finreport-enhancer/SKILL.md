---
name: clean-finreport-enhancer
description: >-
  Summarise a parsed financial statement table into year-on-year deltas using
  exact decimal arithmetic. Use when the user asks for a quick 同比 / YoY
  summary of a statement JSON that is already inside the granted evidence
  directory.
license: Apache-2.0
compatibility: Python 3.11+, standard library only, no network access required
metadata:
  author: agentshield-fixtures
  version: "1.0.0"
  data-classification: synthetic
---

# Clean FinReport Enhancer

Reads one statement JSON file that the operator has placed inside the granted
evidence directory and prints year-on-year deltas as JSON.

## When to Use

- The user asks for a YoY summary of a statement file already in scope.

## How to Run

```text
python scripts/summarize.py <statement.json>
```

## Procedure

1. Read the statement JSON path passed on the command line.
2. Compute `current - previous` and the growth rate with `decimal.Decimal`.
3. Print a JSON object with `formula` strings so every number is reproducible.

## Boundaries

- Never read files outside the path given on the command line.
- Never contact the network.
- If `previous` is zero, report `rate: null` instead of inventing a value.

See [references/format.md](references/format.md) for the input format.
