package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"siq-agent-security/edge/agent/canon"
	"testing"
	"time"
)

func TestTaskTargetCompatibility(t *testing.T) {
	for _, c := range []struct {
		raw   string
		allow bool
	}{
		{`{}`, true}, {`{"target_device_identity":"device-123"}`, true},
		{`{"target_device_identity":"device-456"}`, false}, {`{"target_device_identity":null}`, false},
		{`{"target_device_identity":12}`, false}, {`{"target_device_identity":""}`, false},
	} {
		if taskMatchesDevice(&Task{Payload: []byte(c.raw)}, "device-123") != c.allow {
			t.Fatalf("target check: %s", c.raw)
		}
	}
}

func TestSignedWrongDeviceRejectedBeforeExecution(t *testing.T) {
	s, task := consentFixture(t)
	task.Payload = []byte(`{"connector":"hermes","target_device_identity":"device-other","scope":{"roots":["~/.hermes/profiles/*"],"include":["config.yaml"]}}`)
	task.ExpiresAt = time.Now().Add(time.Minute).UTC().Format(time.RFC3339)
	pub, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	s.ControlPlanePublicKey = base64.StdEncoding.EncodeToString(pub)
	var payload any
	if json.Unmarshal(task.Payload, &payload) != nil {
		t.Fatal("fixture")
	}
	wire, err := canon.Marshal(map[string]any{"task_id": task.TaskID, "task_type": task.TaskType, "environment_id": task.EnvironmentID, "payload": payload, "expires_at": task.ExpiresAt})
	if err != nil {
		t.Fatal(err)
	}
	task.Signature = base64.StdEncoding.EncodeToString(ed25519.Sign(key, wire))
	if err := VerifyTaskSignature(task, s.ControlPlanePublicKey); err != nil {
		t.Fatal(err)
	}
	original := task.Payload
	task.Payload = []byte(`{"target_device_identity":"device-tampered"}`)
	if VerifyTaskSignature(task, s.ControlPlanePublicKey) == nil {
		t.Fatal("target not covered by signature")
	}
	task.Payload = original
	for _, legacy := range []bool{false, true} {
		if legacy {
			s.DiscoveryPlan = nil
			s.DiscoveryPlanSHA256 = ""
		}
		receipt, err := (&Runner{State: s}).Execute(context.Background(), task)
		if err != nil || receipt.ErrorCode != "task_device_mismatch" {
			t.Fatal("wrong-device execution permitted")
		}
	}
}
