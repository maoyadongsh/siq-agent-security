package main

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"siq-agent-security/edge/agent/installplan"
	"siq-agent-security/edge/agent/protocol"
)

var errSkillExecution = errors.New("skill_execution_unconfirmed; preserve original journal")

type skillScanRequest struct {
	Connector string          `json:"connector"`
	Kind      string          `json:"inventory_kind"`
	Target    string          `json:"target_device_identity"`
	Scope     json.RawMessage `json:"scope"`
}

type skillUploadOutcome struct {
	Digest       string
	Observations int
}

func confirmedSkillRequest(state *State, task *Task) (*skillScanRequest, error) {
	if state == nil || task == nil || task.TaskType != "skill_scan" || len(state.DiscoveryPlan) == 0 || task.EnvironmentID != state.EnvironmentID {
		return nil, errDiscoveryConsent
	}
	digest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digest != state.DiscoveryPlanSHA256 {
		return nil, errDiscoveryConsent
	}
	plan, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil || plan.EnvironmentID != state.EnvironmentID || plan.ControlPlaneOrigin != state.ControlPlaneURL {
		return nil, errDiscoveryConsent
	}
	var request skillScanRequest
	if strictDiscoveryJSON(task.Payload, &request) != nil || request.Connector != "directory" || request.Kind != "skills" || request.Target != state.DeviceIdentity || request.Target == "" {
		return nil, errDiscoveryConsent
	}
	var scope protocol.Scope
	if strictDiscoveryJSON(request.Scope, &scope) != nil || len(scope.Roots) == 0 || len(scope.Roots) > 16 || len(scope.Include) != 1 || scope.Include[0] != "SKILL.md" || len(scope.Exclude) != 0 {
		return nil, errDiscoveryConsent
	}
	for _, connector := range plan.Connectors {
		if connector.ID == "directory" && membersOnly(scope.Roots, connector.Scope.Roots) && membersOnly(scope.Include, connector.Scope.Include) {
			return &request, nil
		}
	}
	return nil, errDiscoveryConsent
}

// executeSkillUpload composes consent, immutable journal and HTTP upload. The
// owner must hold the task lock and handle the final control-plane receipt.
// Neither an uncertain upload nor a journal error becomes a completed task.
func executeSkillUpload(ctx context.Context, state *State, task *Task,
	collect func(context.Context, json.RawMessage) (protocol.SkillCollection, error),
	upload func(context.Context, json.RawMessage, string) error) (*skillUploadOutcome, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	request, err := confirmedSkillRequest(state, task)
	if err != nil {
		return nil, err
	}
	if VerifyTaskSignature(task, state.ControlPlanePublicKey) != nil || task.ExpiryError(time.Now()) != nil {
		return nil, errSkillExecution
	}
	record, err := loadSkillUpload(state, task)
	if err != nil {
		return nil, err
	}
	if record == nil {
		if collect == nil {
			return nil, errSkillExecution
		}
		collection, err := collect(ctx, request.Scope)
		if err != nil {
			return nil, errSkillExecution
		}
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if _, err := confirmedSkillRequest(state, task); err != nil {
			return nil, err
		}
		// Never generate a new device identity in order to sign a scan result.
		signer, err := NewSignerFromSeed(state.SignerSeed)
		if err != nil {
			return nil, errSkillExecution
		}
		pub, err := signer.PublicKeyPEM()
		if err != nil || pub != state.PublicKeyPEM {
			return nil, errSkillExecution
		}
		body, digest, err := prepareSkillUpload(task.TaskID, request.Scope, collection, signer)
		if err != nil {
			return nil, err
		}
		if err := saveSkillUpload(state, task, body, digest); err != nil {
			return nil, err
		}
		record, err = loadSkillUpload(state, task)
		if err != nil || record == nil {
			return nil, errSkillJournal
		}
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if _, err := confirmedSkillRequest(state, task); err != nil {
		return nil, err
	}
	if upload == nil || upload(ctx, record.Body, record.BatchDigest) != nil {
		return nil, errSkillUpload
	}
	var body struct {
		Observations []protocol.SkillObservation `json:"observations"`
	}
	if json.Unmarshal(record.Body, &body) != nil {
		return nil, errSkillJournal
	}
	return &skillUploadOutcome{Digest: record.BatchDigest, Observations: len(body.Observations)}, nil
}
