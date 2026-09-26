//go:build linux

package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/canon"
)

func skillJournalFixture(t *testing.T) (*State, *Task, json.RawMessage, string) {
	t.Helper()
	stateDir := t.TempDir()
	if err := os.Chmod(stateDir, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", stateDir)
	signer, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	control, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	scope := json.RawMessage(`{"roots":["/fixture/skills"],"include":["SKILL.md"]}`)
	payload := map[string]any{"connector": "directory", "inventory_kind": "skills", "target_device_identity": "device-fixture", "scope": map[string]any{"roots": []any{"/fixture/skills"}, "include": []any{"SKILL.md"}}}
	raw, _ := json.Marshal(payload)
	task := &Task{TaskID: "tsk_fixture", TaskType: "skill_scan", EnvironmentID: "env-fixture", Payload: raw, ExpiresAt: time.Now().Add(time.Hour).UTC().Format(time.RFC3339)}
	envelope, _ := canon.Marshal(map[string]any{"task_id": task.TaskID, "task_type": task.TaskType, "environment_id": task.EnvironmentID, "payload": payload, "expires_at": task.ExpiresAt})
	task.Signature = base64.StdEncoding.EncodeToString(ed25519.Sign(key, envelope))
	state := &State{ControlPlaneURL: "https://fixture.invalid", DeviceIdentity: "device-fixture", EnvironmentID: task.EnvironmentID, PublicKeyPEM: pub, ControlPlanePublicKey: base64.StdEncoding.EncodeToString(control), Secret: "secret-not-in-journal", SignerSeed: signer.SeedB64(), DiscoveryPlanSHA256: strings.Repeat("c", 64)}
	body, digest, err := prepareSkillUpload(task.TaskID, scope, skillUploadFixture(), signer)
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyTaskSignature(task, state.ControlPlanePublicKey); err != nil {
		t.Fatal("fixture task signature:", err)
	}
	if _, _, err := skillRecordContext(state, task); err != nil {
		t.Fatal("fixture context:", err)
	}
	return state, task, body, digest
}

func TestSkillUploadJournalRoundTripAndNoOverwrite(t *testing.T) {
	state, task, body, digest := skillJournalFixture(t)
	if got, err := loadSkillUpload(state, task); err != nil || got != nil {
		t.Fatal("missing is not absent", err)
	}
	if err := saveSkillUpload(state, task, body, digest); err != nil {
		t.Fatal(err)
	}
	dir, _ := StateDir()
	path := filepath.Join(dir, "skill_uploads", task.TaskID+".json")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(before), state.Secret) || strings.Contains(string(before), state.SignerSeed) {
		t.Fatal("credentials stored in upload journal")
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0600 {
		t.Fatal("not private")
	}
	if err := saveSkillUpload(state, task, body, digest); err != nil {
		t.Fatal(err)
	}
	got, err := loadSkillUpload(state, task)
	if err != nil || got == nil || string(got.Body) != string(body) || got.BatchDigest != digest {
		t.Fatal("replay bytes changed", err)
	}
	mutated := json.RawMessage(strings.Replace(string(body), "sample", "changed", 1))
	if saveSkillUpload(state, task, mutated, digest) == nil {
		t.Fatal("tamper saved")
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("existing journal overwritten")
	}
	signer, err := NewSignerFromSeed(state.SignerSeed)
	if err != nil {
		t.Fatal(err)
	}
	changed := skillUploadFixture()
	changed.Observations[0].ManifestSHA256 = strings.Repeat("e", 64)
	newBody, newDigest, err := prepareSkillUpload(task.TaskID, json.RawMessage(`{"roots":["/fixture/skills"],"include":["SKILL.md"]}`), changed, signer)
	if err != nil {
		t.Fatal(err)
	}
	if saveSkillUpload(state, task, newBody, newDigest) == nil {
		t.Fatal("valid but different signed batch replaced original")
	}
	after, _ = os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("original signed bytes lost")
	}
	// Rotated bearer credential does not replace signing identity or discovery consent.
	state.Secret = "rotated-secret"
	if _, err := loadSkillUpload(state, task); err != nil {
		t.Fatal("credential rotation lost signed batch")
	}
	state.DiscoveryPlanSHA256 = strings.Repeat("d", 64)
	if _, err := loadSkillUpload(state, task); err == nil {
		t.Fatal("different consent reused batch")
	}
}

func TestSkillUploadJournalUnsafeRecordsFailClosed(t *testing.T) {
	for _, scenario := range []string{"partial", "symlink", "hardlink", "wide_file", "wide_directory", "different_device", "changed_task", "ancestor_link"} {
		t.Run(scenario, func(t *testing.T) {
			state, task, body, digest := skillJournalFixture(t)
			dir, _ := StateDir()
			journal := filepath.Join(dir, "skill_uploads")
			path := filepath.Join(journal, task.TaskID+".json")
			if scenario == "partial" || scenario == "symlink" {
				if err := os.Mkdir(journal, 0700); err != nil {
					t.Fatal(err)
				}
				if scenario == "partial" {
					if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
						t.Fatal(err)
					}
				} else {
					target := filepath.Join(dir, "unrelated")
					if err := os.WriteFile(target, []byte("preserve"), 0600); err != nil {
						t.Fatal(err)
					}
					if err := os.Symlink(target, path); err != nil {
						t.Fatal(err)
					}
				}
			} else {
				if err := saveSkillUpload(state, task, body, digest); err != nil {
					t.Fatal(err)
				}
				switch scenario {
				case "hardlink":
					if err := os.Link(path, filepath.Join(dir, "extra-link")); err != nil {
						t.Fatal(err)
					}
				case "wide_file":
					if err := os.Chmod(path, 0644); err != nil {
						t.Fatal(err)
					}
				case "wide_directory":
					if err := os.Chmod(journal, 0755); err != nil {
						t.Fatal(err)
					}
				case "different_device":
					state.DeviceIdentity = "other-device"
				case "changed_task":
					task.Payload = json.RawMessage(`{}`)
				case "ancestor_link":
					link := filepath.Join(t.TempDir(), "linked-state")
					if err := os.Symlink(dir, link); err != nil {
						t.Fatal(err)
					}
					t.Setenv("SIQ_EDGE_STATE_DIR", link)
				}
			}
			if _, err := loadSkillUpload(state, task); err == nil {
				t.Fatal("unsafe record read as absent or valid")
			}
			if saveSkillUpload(state, task, body, digest) == nil {
				t.Fatal("unsafe record overwritten")
			}
		})
	}
}
