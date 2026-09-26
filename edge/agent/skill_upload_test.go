package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/canon"
	"siq-agent-security/edge/agent/protocol"
)

func skillUploadFixture() protocol.SkillCollection {
	return protocol.SkillCollection{SchemaVersion: "enterprise-skill-collection/v1", Observations: []protocol.SkillObservation{{
		LocatorSHA256: strings.Repeat("a", 64), ManifestSHA256: strings.Repeat("b", 64), ParserVersion: "enterprise-skill-manifest/v1",
		ParseStatus: "parsed", Name: "sample", AllowedToolsPresent: true, DeclaredTools: []string{"read_file"}, ObservedAt: time.Now().UTC().Format(time.RFC3339Nano),
	}}}
}

func TestSkillUploadWireSignatureAndReadback(t *testing.T) {
	for _, scenario := range []string{"success", "replay", "wrong_task", "wrong_digest", "missing_flag", "wrong_count", "http_failure", "local_tamper"} {
		t.Run(scenario, func(t *testing.T) {
			signer, _ := NewSigner()
			pub, _ := signer.PublicKeyPEM()
			body, digest, err := prepareSkillUpload("tsk_fixture", json.RawMessage(`{"roots":["/fixture/skills"],"include":["SKILL.md"]}`), skillUploadFixture(), signer)
			if err != nil {
				t.Fatal(err)
			}
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "POST" || r.URL.Path != "/edge/v1/skill-batches" {
					t.Error("wrong route")
				}
				decoder := json.NewDecoder(r.Body)
				decoder.UseNumber()
				var value map[string]any
				if err := decoder.Decode(&value); err != nil {
					t.Error(err)
					return
				}
				signature, _ := value["signature"].(string)
				delete(value, "signature")
				signed, _ := canon.MarshalUTF8(value)
				if VerifySignature(pub, signed, signature) != nil {
					t.Error("invalid native signature")
				}
				sum := sha256.Sum256(signed)
				if hex.EncodeToString(sum[:]) != digest {
					t.Error("wire digest mismatch")
				}
				if scenario == "http_failure" {
					w.WriteHeader(503)
					return
				}
				response := map[string]any{"schema_version": "enterprise-skill-upload-result/v1", "task_id": "tsk_fixture", "batch_digest": digest, "observations": 1, "idempotent": false}
				switch scenario {
				case "replay":
					response["observations"], response["idempotent"] = 0, true
				case "wrong_task":
					response["task_id"] = "tsk_other"
				case "wrong_digest":
					response["batch_digest"] = strings.Repeat("0", 64)
				case "missing_flag":
					delete(response, "idempotent")
				case "wrong_count":
					response["observations"] = 0
				}
				w.Header().Set("Content-Type", "application/json")
				json.NewEncoder(w).Encode(response)
			}))
			defer server.Close()
			if scenario == "local_tamper" {
				body = json.RawMessage(strings.Replace(string(body), "sample", "changed", 1))
			}
			err = NewClient(ClientConfig{ControlPlaneURL: server.URL}).UploadSkills(context.Background(), body, digest)
			wantSuccess := scenario == "success" || scenario == "replay"
			if (err == nil) != wantSuccess {
				t.Fatalf("unexpected result: %v", err)
			}
			wantCalls := 1
			if scenario == "local_tamper" {
				wantCalls = 0
			}
			if calls != wantCalls {
				t.Fatalf("calls=%d want=%d; implicit retry or corruption", calls, wantCalls)
			}
		})
	}
}

func TestSkillUploadPreparationRejectsIncompleteCollections(t *testing.T) {
	signer, _ := NewSigner()
	for _, mutation := range []string{"truncated", "issue", "partial", "duplicate", "secret", "bad_scope"} {
		collection := skillUploadFixture()
		scope := json.RawMessage(`{"roots":["/fixture"],"include":["SKILL.md"]}`)
		switch mutation {
		case "truncated":
			collection.Truncated = true
		case "issue":
			collection.Issues = []protocol.SkillCollectionIssue{{Status: "size_limit"}}
		case "partial":
			collection.Observations[0].ParseStatus = "unsupported"
		case "duplicate":
			collection.Observations = append(collection.Observations, collection.Observations[0])
		case "secret":
			collection.Observations[0].Name = "sk-synthetic-secret-1234567890"
		case "bad_scope":
			scope = json.RawMessage(`{"roots":["/fixture"],"include":[".env"]}`)
		}
		if _, _, err := prepareSkillUpload("tsk_fixture", scope, collection, signer); err == nil {
			t.Fatalf("accepted %s", mutation)
		}
	}
	collection := protocol.SkillCollection{SchemaVersion: "enterprise-skill-collection/v1"}
	body, _, err := prepareSkillUpload("tsk_empty", json.RawMessage(`{"roots":["/fixture"],"include":["SKILL.md"]}`), collection, signer)
	if err != nil || !strings.Contains(string(body), `"observations":[]`) {
		t.Fatal("empty complete collection not represented")
	}
}
