//go:build linux

package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func TestRotateCredentialCommandRecovery(t *testing.T) {
	for _, mode := range []string{"success", "lost-response", "uncommitted", "activated-before-cleanup"} {
		t.Run(mode, func(t *testing.T) {
			state := journalFixture(t)
			active := rotationHash(state.Secret)
			calls, commits := 0, 0
			var exact CredentialRotationRequest
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "POST" || r.URL.Path != "/edge/v1/credential-rotation" {
					t.Error("unexpected request")
				}
				journal, err := readRotationJournal(state)
				if err != nil {
					t.Error("request sent before durable journal")
					w.WriteHeader(500)
					return
				}
				var body CredentialRotationRequest
				if json.NewDecoder(r.Body).Decode(&body) != nil || body != journal.Request {
					t.Error("not the durable request")
				}
				if calls == 1 {
					exact = body
				} else if body != exact {
					t.Error("recovery changed request")
				}
				secret := state.Secret
				if r.Header.Get("Authorization") == "Bearer "+journal.NewSecret {
					secret = journal.NewSecret
				} else if r.Header.Get("Authorization") != "Bearer "+state.Secret {
					t.Error("unexpected credential")
				}
				if rotationHash(secret) != active {
					w.WriteHeader(401)
					return
				}
				if mode == "uncommitted" && calls == 1 {
					w.WriteHeader(503)
					return
				}
				if active == body.ExpectedHash {
					active = body.NewHash
					commits++
				}
				if mode == "lost-response" && calls == 1 {
					w.WriteHeader(503)
					return
				}
				_ = json.NewEncoder(w).Encode(rotationResponse(body))
			}))
			defer server.Close()
			state.ControlPlaneURL = server.URL
			if err := state.Save(); err != nil {
				t.Fatal(err)
			}
			args := []string{"--confirm-device", state.DeviceIdentity}
			if mode == "activated-before-cleanup" {
				journal, err := prepareRotationJournal(state)
				if err != nil {
					t.Fatal(err)
				}
				state.Secret = journal.NewSecret
				active = journal.Request.NewHash
				if err := state.Save(); err != nil {
					t.Fatal(err)
				}
				args = append(args, "--resume")
			}
			err := cmdRotateCredential(context.Background(), args)
			if mode == "lost-response" || mode == "uncommitted" {
				if err == nil {
					t.Fatal("unknown result reported success")
				}
				loaded, readErr := LoadState()
				if readErr != nil || loaded.Secret != state.Secret {
					t.Fatal("unknown result activated")
				}
				if cmdRotateCredential(context.Background(), args) == nil || calls != 1 {
					t.Fatal("pending request replaced or resent implicitly")
				}
				err = cmdRotateCredential(context.Background(), append(args, "--resume"))
			}
			if err != nil {
				t.Fatal(err)
			}
			loaded, err := LoadState()
			if err != nil || rotationHash(loaded.Secret) != active {
				t.Fatal("activation mismatch")
			}
			path, _ := rotationJournalPath()
			if _, err := os.Lstat(path); !os.IsNotExist(err) {
				t.Fatal("completed journal retained")
			}
			expectedCalls := map[string]int{"success": 1, "lost-response": 2, "uncommitted": 3, "activated-before-cleanup": 1}[mode]
			if calls != expectedCalls || (mode != "activated-before-cleanup" && commits != 1) {
				t.Fatal("unexpected retries or duplicate commit")
			}
		})
	}
}

func TestRotateCredentialCommandLocalRefusals(t *testing.T) {
	state := journalFixture(t)
	for _, args := range [][]string{nil, {"--confirm-device", "foreign"}, {"--confirm-device", state.DeviceIdentity, "extra"}, {"--secret", "must-not-echo"}} {
		if err := cmdRotateCredential(context.Background(), args); err != errRotation {
			t.Fatal("unsafe arguments accepted or leaked")
		}
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	if cmdRotateCredential(context.Background(), []string{"--confirm-device", state.DeviceIdentity}) == nil {
		t.Fatal("task lock bypass")
	}
	unlock()
	path, _ := StateFilePath()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if json.Unmarshal(raw, &fields) != nil {
		t.Fatal("fixture")
	}
	fields["future_version_field"] = true
	raw, _ = json.Marshal(fields)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if cmdRotateCredential(context.Background(), []string{"--confirm-device", state.DeviceIdentity}) == nil {
		t.Fatal("unknown state field dropped")
	}
	journalPath, _ := rotationJournalPath()
	if _, err := os.Lstat(journalPath); !os.IsNotExist(err) {
		t.Fatal("refusal created a journal")
	}
}

func TestRotateCredentialResumeUnknownDoesNotFallback(t *testing.T) {
	state := journalFixture(t)
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; w.WriteHeader(503) }))
	defer server.Close()
	state.ControlPlaneURL = server.URL
	if err := state.Save(); err != nil {
		t.Fatal(err)
	}
	journal, err := prepareRotationJournal(state)
	if err != nil {
		t.Fatal(err)
	}
	if cmdRotateCredential(context.Background(), []string{"--confirm-device", state.DeviceIdentity, "--resume"}) == nil || calls != 1 {
		t.Fatal("unknown recovery fell back")
	}
	loaded, err := readRotationJournal(state)
	if err != nil || *loaded != *journal {
		t.Fatal("pending journal changed")
	}
}

func TestRotateCredentialDoesNotOverwriteConcurrentStateDrift(t *testing.T) {
	state := journalFixture(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body CredentialRotationRequest
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Error("fixture request")
			w.WriteHeader(500)
			return
		}
		changed := *state
		changed.EnvironmentID = "changed-during-request"
		if err := changed.Save(); err != nil {
			t.Error(err)
			w.WriteHeader(500)
			return
		}
		_ = json.NewEncoder(w).Encode(rotationResponse(body))
	}))
	defer server.Close()
	state.ControlPlaneURL = server.URL
	if err := state.Save(); err != nil {
		t.Fatal(err)
	}
	if cmdRotateCredential(context.Background(), []string{"--confirm-device", state.DeviceIdentity}) == nil {
		t.Fatal("state drift accepted")
	}
	current, err := LoadState()
	if err != nil || current.EnvironmentID != "changed-during-request" || current.Secret != state.Secret {
		t.Fatal("concurrent state overwritten")
	}
	if _, err := readRotationJournal(state); err != nil {
		t.Fatal("pending recovery record removed")
	}
}
