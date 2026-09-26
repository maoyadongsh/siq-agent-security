package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"

	"siq-agent-security/edge/agent/installplan"
	"siq-agent-security/edge/agent/protocol"
)

var errDiscoveryConsent = errors.New("discovery_scope_denied")

func compactPlanDigest(raw []byte) (string, error) {
	var compact bytes.Buffer
	if json.Compact(&compact, raw) != nil {
		return "", errDiscoveryConsent
	}
	h := sha256.Sum256(compact.Bytes())
	return hex.EncodeToString(h[:]), nil
}

func strictDiscoveryJSON(raw []byte, target any) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(target) != nil || d.Decode(new(any)) != io.EOF {
		return errDiscoveryConsent
	}
	return nil
}

func checkDiscoveryConsent(state *State, task *Task) error {
	if len(state.DiscoveryPlan) == 0 && state.DiscoveryPlanSHA256 == "" {
		return nil
	} // Legacy, not verified consent.
	digest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digest != state.DiscoveryPlanSHA256 {
		return errDiscoveryConsent
	}
	p, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil || p.EnvironmentID != state.EnvironmentID || p.ControlPlaneOrigin != state.ControlPlaneURL || task.EnvironmentID != state.EnvironmentID || task.TaskType != "scan" {
		return errDiscoveryConsent
	}
	var request ScanRequest
	if strictDiscoveryJSON(task.Payload, &request) != nil || request.Connector == "" {
		return errDiscoveryConsent
	}
	var scope protocol.Scope
	if strictDiscoveryJSON(request.Scope, &scope) != nil || len(scope.Roots) == 0 || len(scope.Include) == 0 || len(scope.Exclude) != 0 {
		return errDiscoveryConsent
	}
	for _, connector := range p.Connectors {
		if connector.ID == request.Connector {
			if !membersOnly(scope.Roots, connector.Scope.Roots) || !membersOnly(scope.Include, connector.Scope.Include) {
				return errDiscoveryConsent
			}
			return nil
		}
	}
	return errDiscoveryConsent
}

func membersOnly(requested, allowed []string) bool {
	set := map[string]bool{}
	for _, value := range allowed {
		set[value] = true
	}
	for _, value := range requested {
		if !set[value] {
			return false
		}
	}
	return true
}
