---
name: FinReport_Helper
description: ""
---

# Frontmatter mismatch fixture

The body is harmless. The frontmatter violates the agentskills.io spec in two
ways: the name uses uppercase and underscores and does not match the directory
name, and the description is empty. Admission must fail closed on spec
violations even though no threat pattern is present.
