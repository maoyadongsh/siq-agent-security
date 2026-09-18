package signing

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestMissingIdentityRejectsExistingHistoryWithoutNewSeed(t *testing.T) {
	for _, name := range []string{"receipts/local/chain.jsonl", "grants/g.json", "commits/txn.json", "service.json", "keys/unknown", "unknown-state.json"} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			k, err := Load(dir)
			if err != nil || k == nil {
				t.Fatal(err)
			}
			p := filepath.Join(dir, name)
			if err = os.MkdirAll(filepath.Dir(p), 0700); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(p, []byte("historical evidence"), 0600); err != nil {
				t.Fatal(err)
			}
			seed := filepath.Join(dir, "keys/signing.seed")
			if err = os.Remove(seed); err != nil {
				t.Fatal(err)
			}
			if _, err = Load(dir); !errors.Is(err, ErrIdentityMissing) {
				t.Fatalf("history accepted: %v", err)
			}
			if _, err = os.Lstat(seed); !os.IsNotExist(err) {
				t.Fatal("seed recreated")
			}
			b, err := os.ReadFile(p)
			if err != nil || string(b) != "historical evidence" {
				t.Fatal("history modified")
			}
		})
	}
}
func TestFirstIdentityAllowsBootstrapAndEmptySkeleton(t *testing.T) {
	dir := t.TempDir()
	for _, d := range []string{"keys", "receipts/local", "grants"} {
		if err := os.MkdirAll(filepath.Join(dir, d), 0700); err != nil {
			t.Fatal(err)
		}
	}
	for _, n := range []string{"config.json", "local-instance.json", "state-format.json", "serve.lock"} {
		if n == "state-format.json" {
			continue
		}
		if err := os.WriteFile(filepath.Join(dir, n), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := Load(dir); err != nil {
		t.Fatal(err)
	}
}
func TestMissingIdentityRejectsDanglingSeedLink(t *testing.T) {
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, "keys"), 0700); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "missing")
	if err := os.Symlink(outside, filepath.Join(dir, "keys/signing.seed")); err != nil {
		t.Skip(err)
	}
	if _, err := Load(dir); !errors.Is(err, ErrIdentityMissing) {
		t.Fatal(err)
	}
	if _, err := os.Lstat(outside); !os.IsNotExist(err) {
		t.Fatal("followed seed link")
	}
}
