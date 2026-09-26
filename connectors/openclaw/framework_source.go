package main

import (
	"encoding/json"

	"siq-agent-security/edge/agent/protocol"
)

func frameworkSource(root, configHash, evidenceID string) string {
	identity, _ := json.Marshal([]string{"enterprise-openclaw-config-instance/v1", root})
	value, _ := json.Marshal(map[string]string{
		"schema_version": "enterprise-framework-source/v1", "framework": "openclaw",
		"instance_key": protocol.ContentHash(identity), "config_sha256": configHash,
		"evidence_id": evidenceID,
	})
	return string(value)
}
