package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func TestRegistrationUnknownOutcomePreservesIdentity(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		var request RegisterRequest
		if json.NewDecoder(r.Body).Decode(&request) != nil {
			t.Error("invalid request")
		}
		raw, err := os.ReadFile(filepath.Join(dir, "registration-pending.json"))
		if err != nil {
			t.Error("identity not durable before request")
		}
		var pending map[string]string
		if json.Unmarshal(raw, &pending) != nil || pending["device_identity"] != request.DeviceIdentity || pending["public_key_pem"] != request.PublicKeyPEM || pending["signer_seed"] == "" {
			t.Error("pending identity mismatch")
		}
		if strings.Contains(string(raw), "enr-sensitive-fixture") {
			t.Error("code persisted")
		}
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte("sensitive-server-error"))
	}))
	defer server.Close()
	args := []string{"--control-plane", server.URL, "--enrollment-code", "enr-sensitive-fixture"}
	err := cmdRegister(context.Background(), args)
	if err == nil || strings.Contains(err.Error(), "sensitive") || calls.Load() != 1 {
		t.Fatal("registration retried or leaked response")
	}
	path := filepath.Join(dir, "registration-pending.json")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal("missing journal")
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("unsafe journal mode")
	}
	if err := cmdRegister(context.Background(), args); err != errRegistrationPending {
		t.Fatal("ambiguous retry not blocked")
	}
	after, err := os.ReadFile(path)
	if err != nil || string(before) != string(after) || calls.Load() != 1 {
		t.Fatal("identity overwritten or request replayed")
	}
	if _, err := os.Stat(filepath.Join(dir, "state.json")); !os.IsNotExist(err) {
		t.Fatal("ambiguous attempt marked registered")
	}
}

func TestRegistrationJournalExclusiveAndUnsafeDirectory(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	var success atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if beginRegistration(&State{DeviceIdentity: "fixture"}) == nil {
				success.Add(1)
			}
		}()
	}
	wg.Wait()
	if success.Load() != 1 {
		t.Fatal("multiple local registrars acquired identity")
	}
	unsafe := filepath.Join(t.TempDir(), "wide")
	if os.Mkdir(unsafe, 0755) != nil {
		t.Fatal("fixture directory")
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", unsafe)
	if beginRegistration(&State{}) != errRegistrationPending {
		t.Fatal("wide directory accepted")
	}
}
