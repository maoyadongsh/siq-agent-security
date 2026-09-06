package controlsync

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestPushSkippedWithoutCreds(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	res, err := Push(&inventory.Report{}, key, Creds{ControlAPI: "http://127.0.0.1:8600"}, time.Now().UTC(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Skipped {
		t.Fatalf("%+v", res)
	}
}

func TestPushHTTPErrorLeavesLocalUnchanged(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	rep := miniRep()
	var payload map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/edge/v1/batches" {
			t.Errorf("path %s", r.URL.Path)
		}
		if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") {
			t.Error("missing bearer")
		}
		if r.Header.Get("X-Edge-Identity") != "edge-as" {
			t.Error("missing identity")
		}
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &payload)
		w.WriteHeader(401)
		_, _ = w.Write([]byte(`{"detail":"edge_untrusted"}`))
	}))
	defer srv.Close()

	res, err := Push(rep, key, Creds{ControlAPI: srv.URL, Identity: "edge-as", Secret: "secret-value", TaskID: "tsk-1"}, time.Date(2026, 9, 5, 12, 0, 0, 0, time.UTC), srv.Client())
	if err == nil {
		t.Fatal("401 must fail")
	}
	if !strings.Contains(err.Error(), "local decisions unchanged") {
		t.Fatalf("error must say local unchanged: %v", err)
	}
	if res.StatusCode != 401 {
		t.Fatalf("status %d", res.StatusCode)
	}
	if payload["task_id"] != "tsk-1" {
		t.Fatalf("task %v", payload["task_id"])
	}
	cands, _ := payload["candidates"].([]any)
	if len(cands) == 0 {
		t.Fatal("expected candidates")
	}
	facts, _ := payload["permission_facts"].([]any)
	if len(facts) != 0 {
		t.Fatalf("must not send permission_facts: %v", facts)
	}
	evs, _ := payload["evidence"].([]any)
	if len(evs) == 0 {
		t.Fatal("expected evidence")
	}
	row := evs[0].(map[string]any)
	if row["collector_id"] != "edge-as" {
		t.Fatalf("collector rewrite: %v", row["collector_id"])
	}
}

func TestPushOK(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"candidates":1,"evidence":1}`))
	}))
	defer srv.Close()
	res, err := Push(miniRep(), key, Creds{ControlAPI: srv.URL, Identity: "edge-as", Secret: "s", TaskID: "tsk-1"}, time.Now().UTC(), srv.Client())
	if err != nil {
		t.Fatal(err)
	}
	if res.Skipped || res.Candidates == 0 {
		t.Fatalf("%+v", res)
	}
}

func miniRep() *inventory.Report {
	return &inventory.Report{
		Candidates: []inventory.Candidate{{
			CandidateID: "platform:hermes", SourceType: "platform_config", SourceLocator: "hermes://config",
			DiscoveredAt: "2026-09-05T00:00:00Z", Name: "hermes", Framework: "hermes",
			EvidenceIDs: []string{"ev-1"}, Confidence: 1, Status: "candidate",
		}},
		Evidence: []admission.Evidence{{
			EvidenceID: "ev-1", SourceType: "platform_config", SourceLocator: "hermes://config",
			ObservedAt: "2026-09-05T00:00:00Z", CollectedAt: "2026-09-05T00:00:00Z",
			CollectorID: "agentshield-local", ConnectorVersion: "test",
			ContentHash: strings.Repeat("ab", 32), RedactionProfile: "siq.redaction.v1",
			Classification: "internal", Signature: strings.Repeat("f", 128),
		}},
	}
}
