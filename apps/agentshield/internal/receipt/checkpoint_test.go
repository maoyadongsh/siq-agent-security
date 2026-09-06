package receipt

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestManagedCheckpointDetectsTruncation(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	if err != nil {
		t.Fatal(err)
	}
	state := t.TempDir()
	store, err := OpenCheckpointStore(state, key)
	if err != nil {
		t.Fatal(err)
	}
	chain, err := OpenChain(state, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	chain.AttachCheckpointStore(store)
	for i := 0; i < 3; i++ {
		r := Receipt{
			Platform: "hermes", SessionID: "s", Tool: "read_file", Action: "allow",
			Reason: "ok", EnforcementMode: "block",
		}
		if err := chain.Append(&r); err != nil {
			t.Fatal(err)
		}
	}
	cp, err := store.Load("local")
	if err != nil {
		t.Fatal(err)
	}
	all, err := chain.Read()
	if err != nil || len(all) != 3 {
		t.Fatalf("%v len=%d", err, len(all))
	}
	rep := VerifyDetailed(all, key.Public(), cp)
	if rep.HistoryIntegrity != HistoryVerified || !rep.PrefixValid {
		t.Fatalf("want verified, got %+v", rep)
	}

	// Truncate chain files but leave managed checkpoint at tip=2.
	dayFiles, _ := filepath.Glob(filepath.Join(state, "receipts", "local", "*.jsonl"))
	if len(dayFiles) == 0 {
		t.Fatal("missing jsonl")
	}
	raw, _ := os.ReadFile(dayFiles[0])
	lines := bytes.Split(bytes.TrimSpace(raw), []byte("\n"))
	if len(lines) < 3 {
		t.Fatalf("lines %d", len(lines))
	}
	truncated := append(bytes.Join(lines[:2], []byte("\n")), '\n')
	if err := os.WriteFile(dayFiles[0], truncated, 0o600); err != nil {
		t.Fatal(err)
	}
	c2, err := OpenChain(state, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	got, err := c2.Read()
	if err != nil || len(got) != 2 {
		t.Fatalf("truncated read: %v %d", err, len(got))
	}
	cp2, err := store.Load("local")
	if err != nil {
		t.Fatal(err)
	}
	rep2 := VerifyDetailed(got, key.Public(), cp2)
	if rep2.HistoryIntegrity != HistoryFailed {
		t.Fatalf("truncation vs managed checkpoint must fail history, got %+v", rep2)
	}
}

func TestCheckpointStoreRejectsReceiptsColocation(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	if err != nil {
		t.Fatal(err)
	}
	state := t.TempDir()
	bad := filepath.Join(state, "receipts", "local")
	_ = os.MkdirAll(bad, 0o700)
	if _, err := OpenCheckpointStoreAt(bad, key); !errors.Is(err, ErrCheckpointColocated) {
		t.Fatalf("want ErrCheckpointColocated, got %v", err)
	}
	if _, err := RejectColocatedHEAD(filepath.Join(bad, "HEAD")); err == nil {
		t.Fatal("HEAD must be rejected as checkpoint")
	}
}

func TestCheckpointTamperFailsLoad(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	if err != nil {
		t.Fatal(err)
	}
	state := t.TempDir()
	store, err := OpenCheckpointStore(state, key)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Publish("local", 0, "abc"); err != nil {
		t.Fatal(err)
	}
	path := store.Path("local")
	raw, _ := os.ReadFile(path)
	raw = bytes.Replace(raw, []byte(`"max_seq": 0`), []byte(`"max_seq": 99`), 1)
	_ = os.WriteFile(path, raw, 0o600)
	if _, err := store.Load("local"); !errors.Is(err, ErrCheckpointBadSig) {
		t.Fatalf("want ErrCheckpointBadSig, got %v", err)
	}
}

func TestLoadOptionalMissing(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	if err != nil {
		t.Fatal(err)
	}
	store, err := OpenCheckpointStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	cp, err := store.LoadOptional("local")
	if err != nil || cp != nil {
		t.Fatalf("missing optional: %v %#v", err, cp)
	}
}
