package modelconfig

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestRegisteredPrivateFileCredentialAndRotation(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "credentials.json")
	write := func(raw string) {
		t.Helper()
		if os.WriteFile(path, []byte(raw), 0600) != nil {
			t.Fatal("fixture")
		}
	}
	write(`{"keys":{"step/key":"private-one"}}`)
	providers := map[string]any{"registered": map[string]any{"source": "file", "mode": "json", "path": path, "maxBytes": float64(1024)}}
	ref := map[string]any{"source": "file", "provider": "registered", "id": "/keys/step~1key"}
	key, state := fileCredential(ref, providers)
	if key != "private-one" || state != "present" {
		t.Fatal("registered file reference unreadable")
	}
	s := Source{ID: "hi-11111111111111111111111111111111", Root: root, Platform: "openclaw", Name: "default", secretProviders: providers}
	cfg := map[string]any{"baseUrl": "https://example.com/v1", "api": "openai-completions", "apiKey": ref}
	a := build(s, []byte("fixture"), "primary", "model", "step", cfg)
	write(`{"keys":{"step/key":"private-two"}}`)
	b := build(s, []byte("fixture"), "primary", "model", "step", cfg)
	if !a.Item.CanCheck || !b.Item.CanCheck || a.Item.Fingerprint == b.Item.Fingerprint {
		t.Fatal("credential rotation did not invalidate selection")
	}
	for _, pointer := range []string{"relative", "/keys/step~2key", "/keys"} {
		ref["id"] = pointer
		if _, state := fileCredential(ref, providers); state != "unsupported" {
			t.Fatal("invalid pointer resolved")
		}
	}
	ref["id"] = "/keys/step~1key"
	write(`{"keys":{"step/key":"one","step/key":"two"}}`)
	if _, state := fileCredential(ref, providers); state != "unsupported" {
		t.Fatal("duplicate credential key accepted")
	}
	write(`{"keys":{"step/key":"private-two"}}`)
	if runtime.GOOS != "windows" {
		if os.Chmod(path, 0644) != nil {
			t.Fatal("fixture")
		}
		if _, state := fileCredential(ref, providers); state != "unsupported" {
			t.Fatal("broad secret permissions accepted")
		}
		_ = os.Chmod(path, 0600)
	}
	if os.Remove(path) != nil {
		t.Fatal("fixture")
	}
	if _, state := fileCredential(ref, providers); state != "missing" {
		t.Fatal("missing credential mislabeled")
	}
}
