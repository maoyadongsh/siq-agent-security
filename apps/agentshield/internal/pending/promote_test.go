package pending

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPromoteIdempotentAndCursor(t *testing.T) {
	dir := t.TempDir()
	if err := Append(dir, Record{
		Platform: "hermes", Tool: "exec", SessionID: "s1",
		EnforcementMode: "block", Outcome: "deny", Reason: "decision service unavailable",
	}); err != nil {
		t.Fatal(err)
	}
	if err := Append(dir, Record{
		Platform: "codebuddy", Tool: "Bash",
		EnforcementMode: "warn", Outcome: "allow", Reason: "decision service unavailable",
	}); err != nil {
		t.Fatal(err)
	}

	var got []Record
	n, err := Promote(dir, func(r Record) error {
		got = append(got, r)
		return nil
	})
	if err != nil || n != 2 || len(got) != 2 {
		t.Fatalf("first promote: n=%d len=%d err=%v", n, len(got), err)
	}
	if got[0].Outcome != "deny" || got[1].Outcome != "allow" {
		t.Fatalf("outcomes: %+v", got)
	}

	n, err = Promote(dir, func(r Record) error {
		t.Fatal("second promote must not re-append")
		return nil
	})
	if err != nil || n != 0 {
		t.Fatalf("idempotent promote: n=%d err=%v", n, err)
	}

	raw, err := os.ReadFile(filepath.Join(dir, "pending", cursorFile))
	if err != nil || string(raw) != "2\n" {
		t.Fatalf("cursor=%q err=%v", raw, err)
	}
}

func TestPromoteCorruptLineStops(t *testing.T) {
	dir := t.TempDir()
	pend := filepath.Join(dir, "pending")
	if err := os.MkdirAll(pend, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(pend, "decisions.jsonl"), []byte("{\"schema\":\"pending_decision/v1\",\"signed\":false,\"outcome\":\"deny\",\"enforcement_mode\":\"block\",\"platform\":\"hermes\",\"reason\":\"ok\"}\nNOT-JSON\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var nOK int
	n, err := Promote(dir, func(r Record) error {
		nOK++
		return nil
	})
	if err == nil || n != 1 || nOK != 1 {
		t.Fatalf("corrupt must stop after first: n=%d nOK=%d err=%v", n, nOK, err)
	}
}
