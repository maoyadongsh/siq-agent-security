package state

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestUserServiceIntentRecoveryAndDrift(t *testing.T) {
	dir := t.TempDir()
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	unit := []byte("[Service]\nExecStart=/test serve\n")
	r, err := s.PrepareUserService(w, key, unit)
	if err != nil {
		t.Fatal(err)
	}
	if !signing.VerifyCanonical(key.Public(), r.unsigned(), r.Signature) {
		t.Fatal("unsigned intent")
	}
	path := filepath.Join(dir, r.UnitName)
	if err = os.Remove(path); err != nil {
		t.Fatal(err)
	} // Interrupted before unit publication.
	again, err := s.PrepareUserService(w, key, unit)
	if err != nil || r != again {
		t.Fatalf("recovery: %v", err)
	}
	if _, err = s.PrepareUserService(w, key, []byte("changed")); err == nil {
		t.Fatal("changed input adopted")
	}
	if err = os.WriteFile(path, []byte("user data"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.PrepareUserService(w, key, unit); err == nil {
		t.Fatal("drift overwritten")
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "user data" {
		t.Fatal("unknown file changed")
	}
	if _, err = s.PrepareUserService(nil, key, unit); err == nil {
		t.Fatal("missing writer accepted")
	}
}

func TestUserServiceRefusesUnknownFileAndInvalidRecord(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	init, err := s.Initialize(w, 0)
	if err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(make([]byte, 32))
	unit := []byte("unit")
	path := filepath.Join(s.Dir, "siq-agent-security-"+init.InstanceID[:32]+".service")
	if err = os.WriteFile(path, unit, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.PrepareUserService(w, key, unit); err == nil {
		t.Fatal("unowned identical file adopted")
	}
	if _, err = os.Stat(filepath.Join(s.Dir, "user-service.json")); !os.IsNotExist(err) {
		t.Fatal("created intent over unknown file")
	}
	if err = os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err = s.PrepareUserService(w, key, unit); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(s.Dir, "user-service.json"), []byte(`{"signature":"invalid"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.PrepareUserService(w, key, unit); err == nil {
		t.Fatal("corrupt record accepted")
	}
}

func TestUserServiceContractFixture(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(make([]byte, 32))
	r, err := s.PrepareUserService(w, key, []byte("[Service]\nExecStart=/test serve\n"))
	if err != nil {
		t.Fatal(err)
	}
	// Normalize random instance and machine-local directory, then re-sign.
	r.InstanceID = strings.Repeat("a", 64)
	r.DirectoryID = strings.Repeat("b", 64)
	r.UnitName = "siq-agent-security-" + r.InstanceID[:32] + ".service"
	r.Signature, err = key.SignCanonical(r.unsigned())
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	path := "../../testdata/contracts/local-user-service-record.json"
	if os.Getenv("SIQ_UPDATE_USER_SERVICE_FIXTURE") == "1" {
		if err = os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(raw, expected) {
		t.Fatal("service contract fixture drift")
	}
	otherSeed := bytes.Repeat([]byte{1}, 32)
	other, _ := signing.FromSeed(otherSeed)
	if _, err = s.PrepareUserService(w, other, []byte("[Service]\nExecStart=/test serve\n")); err == nil {
		t.Fatal("different signing identity accepted")
	}
}

func TestVerifyUserServiceReadOnlyWhileWriterHeld(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(make([]byte, 32))
	unit := []byte("unit")
	r, err := s.PrepareUserService(w, key, unit)
	if err != nil {
		t.Fatal(err)
	}
	got, err := s.VerifyUserService(key, unit)
	if err != nil || got != r {
		t.Fatal("read blocked by writer", err)
	}
	path := filepath.Join(s.Dir, r.UnitName)
	if err = os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err = s.VerifyUserService(key, unit); err == nil {
		t.Fatal("missing unit accepted")
	}
	if _, err = os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("read repaired unit")
	}
}
