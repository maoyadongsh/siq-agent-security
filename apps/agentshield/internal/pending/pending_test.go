package pending

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestAppendWritesUnsignedJSONL(t *testing.T) {
	dir := t.TempDir()
	if err := Append(dir, Record{
		Platform: "codebuddy", Tool: "Bash", SessionID: "s1",
		EnforcementMode: "block", Outcome: OutcomeForMode("block"),
		Reason: "decision service unavailable",
	}); err != nil {
		t.Fatal(err)
	}
	if err := Append(dir, Record{
		Platform: "hermes", Tool: "exec",
		EnforcementMode: "audit_only", Outcome: OutcomeForMode("audit_only"),
		Reason: "decision service unavailable",
	}); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "pending", "decisions.jsonl")
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	var n int
	for sc.Scan() {
		var rec Record
		if err := json.Unmarshal(sc.Bytes(), &rec); err != nil {
			t.Fatal(err)
		}
		if rec.Schema != SchemaID || rec.Signed {
			t.Fatalf("bad record: %+v", rec)
		}
		n++
	}
	if n != 2 {
		t.Fatalf("want 2 lines, got %d", n)
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("pending log must be 0600, got %o", info.Mode().Perm())
	}
}

func TestOutcomeForMode(t *testing.T) {
	if OutcomeForMode("block") != "deny" || OutcomeForMode("warn") != "allow" || OutcomeForMode("audit_only") != "allow" {
		t.Fatal("outcome table mismatch")
	}
}
