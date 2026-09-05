# Statement JSON format

```json
{
  "company": "SYNTHETIC-A",
  "period": "FY2025",
  "unit": "CNY",
  "items": [
    {"name": "revenue", "current": "1250.5", "previous": "1100"},
    {"name": "net_profit", "current": "88.2", "previous": "91.0"}
  ]
}
```

Amounts are strings so they can be parsed as exact decimals.
