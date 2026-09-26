package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"

	"siq-agent-security/edge/agent/canon"
)

var errSkillJournal = errors.New("skill_upload_journal_unavailable; preserve original state and signed batch")

type skillUploadRecord struct {
	Schema        string          `json:"schema_version"`
	TaskDigest    string          `json:"task_digest"`
	ContextDigest string          `json:"context_digest"`
	BatchDigest   string          `json:"batch_digest"`
	Body          json.RawMessage `json:"body"`
}

func skillRecordContext(state *State, task *Task) (string, string, error) {
	if state == nil || task == nil || !initialTaskID.MatchString(task.TaskID) || task.TaskType != "skill_scan" || task.EnvironmentID != state.EnvironmentID || state.EnvironmentID == "" || state.DeviceIdentity == "" || state.ControlPlaneURL == "" || VerifyTaskSignature(task, state.ControlPlanePublicKey) != nil {
		return "", "", errSkillJournal
	}
	taskDigest, err := TaskContentDigest(task)
	if err != nil {
		return "", "", errSkillJournal
	}
	wire, err := canon.MarshalUTF8(map[string]any{"origin": state.ControlPlaneURL, "environment": state.EnvironmentID,
		"device": state.DeviceIdentity, "public_key": state.PublicKeyPEM, "control_key": state.ControlPlanePublicKey,
		"consent_digest": state.DiscoveryPlanSHA256})
	if err != nil {
		return "", "", errSkillJournal
	}
	sum := sha256.Sum256(wire)
	return taskDigest, hex.EncodeToString(sum[:]), nil
}

func validateSkillRecord(record *skillUploadRecord, state *State, task *Task) error {
	taskDigest, contextDigest, err := skillRecordContext(state, task)
	if err != nil || record.Schema != "edge-skill-upload-journal/v1" || record.TaskDigest != taskDigest || record.ContextDigest != contextDigest {
		return errSkillJournal
	}
	wire, err := canon.Decode(record.Body)
	if err != nil {
		return errSkillJournal
	}
	body, ok := wire.(map[string]any)
	if !ok || (body["schema_version"] != "enterprise-skill-upload/v1" && body["schema_version"] != "enterprise-skill-upload/v2") || body["task_id"] != task.TaskID {
		return errSkillJournal
	}
	signature, ok := body["signature"].(string)
	if !ok {
		return errSkillJournal
	}
	delete(body, "signature")
	signed, err := canon.MarshalUTF8(body)
	if err != nil || VerifySignature(state.PublicKeyPEM, signed, signature) != nil {
		return errSkillJournal
	}
	sum := sha256.Sum256(signed)
	if record.BatchDigest != hex.EncodeToString(sum[:]) {
		return errSkillJournal
	}
	payload, err := canon.Decode(task.Payload)
	if err != nil {
		return errSkillJournal
	}
	object, ok := payload.(map[string]any)
	if !ok || object["scope"] == nil || object["target_device_identity"] != state.DeviceIdentity {
		return errSkillJournal
	}
	scope, err := canon.MarshalUTF8(object["scope"])
	if err != nil {
		return errSkillJournal
	}
	scopeSum := sha256.Sum256(scope)
	if body["scope_digest"] != hex.EncodeToString(scopeSum[:]) {
		return errSkillJournal
	}
	return nil
}
