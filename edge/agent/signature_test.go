package main

// Cross-language task-signature vectors (threat T5 / DEV09):
// Producer: packages/contracts/fixtures/task_signature_vectors_v1.json
// (independent CPython json.dumps + Ed25519; not Go canon).
// Consumer under test: VerifyTaskSignature via edge/agent/canon.

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/edge/agent/canon"
)

type taskSigVector struct {
	Name          string         `json:"name"`
	PublicKeyB64  string         `json:"public_key_b64"`
	Envelope      map[string]any `json:"envelope"`
	PayloadJSON   string         `json:"payload_json"`
	CanonicalUTF8 string         `json:"canonical_utf8"`
	SignatureB64  string         `json:"signature_b64"`
}

type taskSigFixtureFile struct {
	Schema  string          `json:"schema"`
	Vectors []taskSigVector `json:"vectors"`
}

func loadTaskSigFixtures(t *testing.T) taskSigFixtureFile {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	path := filepath.Clean(filepath.Join(filepath.Dir(thisFile), "..", "..", "packages", "contracts", "fixtures", "task_signature_vectors_v1.json"))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixtures %s: %v", path, err)
	}
	var doc taskSigFixtureFile
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Vectors) == 0 {
		t.Fatal("empty task signature fixture set")
	}
	return doc
}

func taskFromVector(t *testing.T, v taskSigVector) *Task {
	t.Helper()
	env := v.Envelope
	return &Task{
		TaskID:        env["task_id"].(string),
		TaskType:      env["task_type"].(string),
		EnvironmentID: env["environment_id"].(string),
		Payload:       []byte(v.PayloadJSON),
		ExpiresAt:     env["expires_at"].(string),
		Signature:     v.SignatureB64,
	}
}

func TestTaskSignatureVectorsVerify(t *testing.T) {
	doc := loadTaskSigFixtures(t)
	for _, v := range doc.Vectors {
		t.Run(v.Name, func(t *testing.T) {
			payload, err := canon.Decode([]byte(v.PayloadJSON))
			if err != nil {
				t.Fatal(err)
			}
			envelope := map[string]any{
				"task_id":        v.Envelope["task_id"],
				"task_type":      v.Envelope["task_type"],
				"environment_id": v.Envelope["environment_id"],
				"payload":        payload,
				"expires_at":     v.Envelope["expires_at"],
			}
			got, err := canon.Marshal(envelope)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != v.CanonicalUTF8 {
				t.Fatalf("canon mismatch\n got %s\nwant %s", got, v.CanonicalUTF8)
			}
			if err := VerifyTaskSignature(taskFromVector(t, v), v.PublicKeyB64); err != nil {
				t.Fatalf("valid vector rejected: %v", err)
			}
		})
	}
}

func TestTaskSignatureVectorsTamperFails(t *testing.T) {
	doc := loadTaskSigFixtures(t)
	task := taskFromVector(t, doc.Vectors[0])
	task.Payload = []byte(`{"scope":{"connector":"EVIL"}}`)
	if err := VerifyTaskSignature(task, doc.Vectors[0].PublicKeyB64); err == nil {
		t.Fatal("tampered task accepted")
	}
}

func TestVerifyUnsignedTaskFails(t *testing.T) {
	doc := loadTaskSigFixtures(t)
	task := taskFromVector(t, doc.Vectors[0])
	task.Signature = ""
	if err := VerifyTaskSignature(task, doc.Vectors[0].PublicKeyB64); err == nil {
		t.Fatal("unsigned task accepted")
	}
}

func TestVerifyForeignKeyFails(t *testing.T) {
	doc := loadTaskSigFixtures(t)
	pub, _, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	foreign := base64.StdEncoding.EncodeToString(pub)
	if err := VerifyTaskSignature(taskFromVector(t, doc.Vectors[0]), foreign); err == nil {
		t.Fatal("foreign-key signature accepted")
	}
}

func TestGoDefaultMarshalBreaksChineseHTMLVector(t *testing.T) {
	// encoding/json.Marshal HTML-escapes "<" → "\u003c", diverging from CPython
	// task signing (ensure_ascii=True leaves "<" literal).
	doc := loadTaskSigFixtures(t)
	var v *taskSigVector
	for i := range doc.Vectors {
		if doc.Vectors[i].Name == "chinese_html_float" {
			v = &doc.Vectors[i]
			break
		}
	}
	if v == nil {
		t.Fatal("missing chinese_html_float vector")
	}
	payload, err := canon.Decode([]byte(v.PayloadJSON))
	if err != nil {
		t.Fatal(err)
	}
	envelope := map[string]any{
		"task_id":        v.Envelope["task_id"],
		"task_type":      v.Envelope["task_type"],
		"environment_id": v.Envelope["environment_id"],
		"payload":        payload,
		"expires_at":     v.Envelope["expires_at"],
	}
	broken, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if string(broken) == v.CanonicalUTF8 {
		t.Fatal("expected encoding/json.Marshal to diverge on HTML/unicode task envelope")
	}
	good, err := canon.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if string(good) != v.CanonicalUTF8 {
		t.Fatalf("canon should match producer\n got %s\nwant %s", good, v.CanonicalUTF8)
	}
}
