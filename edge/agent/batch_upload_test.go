package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"siq-agent-security/edge/agent/canon"
	"siq-agent-security/edge/agent/protocol"
)

func TestUploadTypedBatchSignsWireAndRejectsTamper(t *testing.T) {
	signer, _ := NewSigner()
	pub, _ := signer.PublicKeyPEM()
	called := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		if r.URL.Path != "/edge/v1/batches" {
			t.Error("wrong endpoint")
		}
		decoder := json.NewDecoder(r.Body)
		decoder.UseNumber()
		var body map[string]any
		if err := decoder.Decode(&body); err != nil {
			t.Error(err)
			w.WriteHeader(400)
			return
		}
		signature, ok := body["signature"].(string)
		if !ok {
			t.Error("missing signature")
			w.WriteHeader(400)
			return
		}
		delete(body, "signature")
		payload, err := canon.MarshalUTF8(body)
		if err != nil || VerifySignature(pub, payload, signature) != nil {
			t.Error("wire batch signature rejected", err)
		}
		if len(body["candidates"].([]any)) != 1 || len(body["evidence"].([]any)) != 1 {
			t.Error("typed objects lost")
		}
		body["task_id"] = "another-task"
		altered, _ := canon.MarshalUTF8(body)
		if VerifySignature(pub, altered, signature) == nil {
			t.Error("changed task accepted")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true}`))
	}))
	defer server.Close()
	candidate := &protocol.Candidate{CandidateID: "candidate-1", Name: "测试<报告>", EvidenceIDs: []string{"ev-1"}, Attributes: map[string]string{"profile": "fixture"}}
	evidence := &protocol.Evidence{EvidenceID: "ev-1", SourceType: "hermes_profile", SourceLocator: "fixture", ContentHash: "hash"}
	if err := SealEvidence(evidence, signer, "device-1"); err != nil {
		t.Fatal(err)
	}
	client := NewClient(ClientConfig{ControlPlaneURL: server.URL})
	if err := client.UploadBatch(context.Background(), "task-1", []*protocol.Candidate{candidate}, []*protocol.Evidence{evidence}, nil, signer); err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("typed batch never reached HTTP server")
	}
}
