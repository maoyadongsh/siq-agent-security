package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"os"
	"testing"
	"time"

	"siq-agent-security/edge/agent/canon"
)

func consentFixture(t *testing.T) (*State, *Task) {
	t.Helper()
	raw, err := os.ReadFile("installplan/testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	digest, err := compactPlanDigest(raw)
	if err != nil {
		t.Fatal(err)
	}
	return &State{DeviceIdentity: "fixture", EnvironmentID: "env-fixture", ControlPlaneURL: "https://security.example.test:8443", DiscoveryPlan: raw, DiscoveryPlanSHA256: digest}, &Task{TaskID: "tsk-consent", TaskType: "scan", EnvironmentID: "env-fixture", Payload: json.RawMessage(`{"connector":"hermes","scope":{"roots":["~/.hermes/profiles/*"],"include":["config.yaml"]}}`)}
}

func TestDiscoveryConsentBounds(t *testing.T) {
	for _, scenario := range []string{"valid", "legacy", "digest", "missing_plan", "environment", "origin", "connector", "root", "file", "empty_scope", "empty_include", "unknown", "default_connector"} {
		t.Run(scenario, func(t *testing.T) {
			s, task := consentFixture(t)
			switch scenario {
			case "legacy":
				s.DiscoveryPlan = nil
				s.DiscoveryPlanSHA256 = ""
			case "digest":
				s.DiscoveryPlanSHA256 = "bad"
			case "missing_plan":
				s.DiscoveryPlan = nil
			case "environment":
				task.EnvironmentID = "other"
			case "origin":
				s.ControlPlaneURL = "https://other.test"
			case "connector":
				task.Payload = []byte(`{"connector":"docker","scope":{"roots":["~/.hermes/profiles/*"],"include":["config.yaml"]}}`)
			case "root":
				task.Payload = []byte(`{"connector":"hermes","scope":{"roots":["/"],"include":["config.yaml"]}}`)
			case "file":
				task.Payload = []byte(`{"connector":"hermes","scope":{"roots":["~/.hermes/profiles/*"],"include":[".env"]}}`)
			case "empty_scope":
				task.Payload = []byte(`{"connector":"hermes","scope":{}}`)
			case "empty_include":
				task.Payload = []byte(`{"connector":"hermes","scope":{"roots":["~/.hermes/profiles/*"]}}`)
			case "unknown":
				task.Payload = []byte(`{"connector":"hermes","override":true,"scope":{"roots":["~/.hermes/profiles/*"],"include":["config.yaml"]}}`)
			case "default_connector":
				task.Payload = []byte(`{"scope":{"roots":["~/.hermes/profiles/*"],"include":["config.yaml"]}}`)
			}
			err := checkDiscoveryConsent(s, task)
			if scenario == "valid" || scenario == "legacy" {
				if err != nil {
					t.Fatal(err)
				}
			} else if err != errDiscoveryConsent {
				t.Fatal("scope escape accepted")
			}
		})
	}
}

func TestSignedOutOfScopeTaskDeniedBeforeExecution(t *testing.T) {
	s, task := consentFixture(t)
	task.Payload = []byte(`{"connector":"hermes","scope":{"roots":["/"],"include":["config.yaml"]}}`)
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
	// No Client or Connector is supplied: reaching either is a test failure.
	rcpt, err := (&Runner{State: s}).Execute(context.Background(), task)
	if err != nil || rcpt.Status != "failed" || rcpt.ErrorCode != "discovery_scope_denied" {
		t.Fatal("signed scope escape not rejected")
	}
}
