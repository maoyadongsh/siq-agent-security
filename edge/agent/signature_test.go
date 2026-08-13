package main

// 跨语言规范化一致性测试（威胁 T5）：
// 夹具由控制面 Python 侧（app/signing.py，固定种子 bytes(range(32))）生成；
// Go 侧必须构造出字节级相同的规范信封并验签成功，篡改必须失败。

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"testing"
)

const (
	fixturePublicKey = "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="
	fixtureSignature = "SzOyUikO4TPYEmTPgSgxfKydYcqgNiMNPdTbY9391hjRIlJ8Qhq8KvFAJYrz3FE62Qtcwr80V755QenL4nRiDg=="
	fixtureCanonical = `{"environment_id":"env_fixture","expires_at":"2026-08-13T12:00:00.123456","payload":{"scope":{"connector":"hermes"}},"task_id":"tsk_fixture","task_type":"scan"}`
)

func fixtureTask() *Task {
	payload, _ := json.Marshal(map[string]any{"scope": map[string]any{"connector": "hermes"}})
	return &Task{
		TaskID:        "tsk_fixture",
		TaskType:      "scan",
		EnvironmentID: "env_fixture",
		Payload:       payload,
		ExpiresAt:     "2026-08-13T12:00:00.123456",
		Signature:     fixtureSignature,
	}
}

func TestCanonicalEnvelopeMatchesPython(t *testing.T) {
	task := fixtureTask()
	var payload any
	if err := json.Unmarshal(task.Payload, &payload); err != nil {
		t.Fatal(err)
	}
	envelope := map[string]any{
		"task_id":        task.TaskID,
		"task_type":      task.TaskType,
		"environment_id": task.EnvironmentID,
		"payload":        payload,
		"expires_at":     task.ExpiresAt,
	}
	canonical, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if string(canonical) != fixtureCanonical {
		t.Fatalf("canonical mismatch:\n got %s\nwant %s", canonical, fixtureCanonical)
	}
}

func TestVerifyFixtureSignature(t *testing.T) {
	if err := VerifyTaskSignature(fixtureTask(), fixturePublicKey); err != nil {
		t.Fatalf("valid fixture rejected: %v", err)
	}
}

func TestVerifyTamperedPayloadFails(t *testing.T) {
	task := fixtureTask()
	tampered, _ := json.Marshal(map[string]any{"scope": map[string]any{"connector": "EVIL"}})
	task.Payload = tampered
	if err := VerifyTaskSignature(task, fixturePublicKey); err == nil {
		t.Fatal("tampered task accepted")
	}
}

func TestVerifyUnsignedTaskFails(t *testing.T) {
	task := fixtureTask()
	task.Signature = ""
	if err := VerifyTaskSignature(task, fixturePublicKey); err == nil {
		t.Fatal("unsigned task accepted")
	}
}

func TestVerifyForeignKeyFails(t *testing.T) {
	_, _, foreignPub := newTestKeyPair(t)
	if err := VerifyTaskSignature(fixtureTask(), foreignPub); err == nil {
		t.Fatal("foreign-key signature accepted")
	}
}

func newTestKeyPair(t *testing.T) (pubB64, privB64, _ string) {
	t.Helper()
	pubKey, privKey, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	return base64.StdEncoding.EncodeToString(pubKey), base64.StdEncoding.EncodeToString(privKey), ""
}
