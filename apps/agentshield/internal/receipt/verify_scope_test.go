package receipt

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestVerifyDetailedPrefixOKHistoryUnknownWithoutCheckpoint(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	chain, err := OpenChain(dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		r := Receipt{
			Platform: "hermes", SessionID: "s", Tool: "read_file", Action: "allow",
			Reason: "ok", EnforcementMode: "block",
		}
		if err := chain.Append(&r); err != nil {
			t.Fatal(err)
		}
	}
	all, err := chain.Read()
	if err != nil || len(all) != 3 {
		t.Fatalf("%v %d", err, len(all))
	}
	rep := VerifyDetailed(all, key.Public(), nil)
	if !rep.PrefixValid {
		t.Fatalf("prefix must be valid: %+v", rep)
	}
	if rep.HistoryIntegrity != HistoryUnknown {
		t.Fatalf("without independent checkpoint history must be unknown, got %q", rep.HistoryIntegrity)
	}
	if rep.CheckpointConsistent != nil {
		t.Fatal("checkpoint_consistent must be omitted without checkpoint")
	}
}

func TestVerifyDetailedTruncationStillPrefixValidHistoryUnknown(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	chain, err := OpenChain(dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		r := Receipt{
			Platform: "hermes", SessionID: "s", Tool: "read_file", Action: "allow",
			Reason: "ok", EnforcementMode: "block",
		}
		if err := chain.Append(&r); err != nil {
			t.Fatal(err)
		}
	}
	all, err := chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	fullTip := all[2].Hash
	// Truncate the tip (delete last record) — offline verifier cannot detect this.
	truncated := all[:2]
	rep := VerifyDetailed(truncated, key.Public(), nil)
	if !rep.PrefixValid {
		t.Fatalf("truncated prefix of valid records must still verify: %+v", rep)
	}
	if rep.HistoryIntegrity != HistoryUnknown {
		t.Fatalf("truncation without checkpoint must leave history unknown, got %q", rep.HistoryIntegrity)
	}
	if rep.TipHash == fullTip {
		t.Fatal("truncated tip must differ from full tip")
	}
	// Independent checkpoint of the full tip must fail against truncated chain.
	cp := &Checkpoint{MaxSeq: 2, TipHash: fullTip}
	rep2 := VerifyDetailed(truncated, key.Public(), cp)
	if !rep2.PrefixValid {
		t.Fatal("prefix still valid")
	}
	if rep2.HistoryIntegrity != HistoryFailed {
		t.Fatalf("checkpoint mismatch must fail history, got %q", rep2.HistoryIntegrity)
	}
	if rep2.CheckpointConsistent == nil || *rep2.CheckpointConsistent {
		t.Fatal("checkpoint must be inconsistent")
	}
}

func TestVerifyDetailedCheckpointMatchVerified(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{13}, 32))
	if err != nil {
		t.Fatal(err)
	}
	chain, err := OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	r := Receipt{Platform: "hermes", SessionID: "s", Tool: "t", Action: "allow", Reason: "ok", EnforcementMode: "block"}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	all, _ := chain.Read()
	cp := &Checkpoint{MaxSeq: all[0].Seq, TipHash: all[0].Hash}
	rep := VerifyDetailed(all, key.Public(), cp)
	if !rep.PrefixValid || rep.HistoryIntegrity != HistoryVerified {
		t.Fatalf("%+v", rep)
	}
	if rep.CheckpointConsistent == nil || !*rep.CheckpointConsistent {
		t.Fatal("checkpoint must match")
	}
}

func TestVerifyDetailedTamperFailsPrefix(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{15}, 32))
	if err != nil {
		t.Fatal(err)
	}
	chain, err := OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	r := Receipt{Platform: "hermes", SessionID: "s", Tool: "t", Action: "allow", Reason: "ok", EnforcementMode: "block"}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	files, _ := chain.files()
	raw, _ := os.ReadFile(files[0])
	tampered := bytes.Replace(raw, []byte(`"action":"allow"`), []byte(`"action":"deny"`), 1)
	_ = os.WriteFile(files[0], tampered, 0o600)
	all, _ := chain.Read()
	rep := VerifyDetailed(all, key.Public(), nil)
	if rep.PrefixValid || rep.HistoryIntegrity != HistoryFailed {
		t.Fatalf("tamper must fail prefix: %+v", rep)
	}
	if !strings.Contains(rep.Error, "hash mismatch") {
		t.Fatalf("error: %s", rep.Error)
	}
	// colocated HEAD must not be accepted as Checkpoint — callers pass nil or external cp only.
	_ = filepath.Join(chain.dir, "HEAD")
}
