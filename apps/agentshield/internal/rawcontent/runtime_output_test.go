package rawcontent

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestRuntimeEnvelopeFixture(t *testing.T) {
	oldRandom := random
	random = bytes.NewReader(bytes.Repeat([]byte{7}, 60))
	t.Cleanup(func() { random = oldRandom })
	store, err := Initialize(t.TempDir(), Limits{Retention: DefaultRetention, Budget: DefaultBudget})
	if err != nil {
		t.Fatal(err)
	}
	content, _ := Prepare("output", []Field{{Path: "/result", Value: "fixture runtime output"}})
	source, _ := runtimeSource("fixture-identity", "fixture-session", "fixture-binding")
	envelope, err := store.writeFromRuntime("fixture-task", content, DefaultRetention, time.Date(2026, 9, 23, 0, 0, 0, 0, time.UTC), &source)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.MarshalIndent(envelope, "", "  ")
	raw = append(raw, '\n')
	path := "../../testdata/contracts/local-raw-task-content-envelope-v2.json"
	if os.Getenv("SIQ_UPDATE_CONTRACT_FIXTURE") == "1" {
		if err := os.WriteFile(path, raw, 0644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(raw, want) {
		t.Fatal("cross-language runtime envelope differs", err)
	}
}

func TestRuntimeOutputsSeparateSessionsAndLegacyRecords(t *testing.T) {
	dir, store, authority, _ := testAuthority(t, DefaultRetention)
	now := time.Date(2026, 9, 23, 10, 0, 0, 0, time.UTC)
	grant, err := authority.Issue("task", []string{"input", "output"}, "operator", time.Hour, time.Hour, 4096, now)
	if err != nil {
		t.Fatal(err)
	}
	capture := func(identity, session, binding, kind string) Envelope {
		t.Helper()
		permit, err := authority.IssueCapturePermit(grant.GrantID, grant.Signature, identity, session, binding, "task", kind, now.Add(time.Hour), time.Minute, now)
		if err != nil {
			t.Fatal(err)
		}
		content, err := Prepare(kind, []Field{{Path: "/result", Value: "scoped report text"}, {Path: "/api_key", Value: "must be omitted"}})
		if err != nil {
			t.Fatal(err)
		}
		e, err := authority.CaptureWithPermit(permit, identity, session, binding, "task", content, now)
		if err != nil {
			t.Fatal(err)
		}
		return e
	}
	wanted := capture("identity", "session", "binding", "output")
	otherSession := capture("identity", "other-session", "binding", "output")
	otherIdentity := capture("other-identity", "session", "binding", "output")
	otherBinding := capture("identity", "session", "other-binding", "output")
	input := capture("identity", "session", "binding", "input")
	prepared, _ := Prepare("output", []Field{{Path: "/result", Value: "legacy unscoped"}})
	legacy, err := store.write("task", prepared, time.Hour, now)
	if err != nil {
		t.Fatal(err)
	}
	// Reopen rather than relying on process memory or the issuing authority.
	store, err = OpenExisting(dir, Limits{Retention: DefaultRetention, Budget: DefaultBudget})
	if err != nil {
		t.Fatal(err)
	}
	rows, err := store.ListRuntimeOutputs("task", "identity", "session", "binding", now)
	if err != nil || len(rows) != 1 || rows[0].RecordID != wanted.RecordID {
		t.Fatal("runtime attribution", rows, err)
	}
	fields, envelope, err := store.ReadRuntimeOutput("task", "identity", "session", "binding", wanted.RecordID, now)
	if err != nil || len(fields) != 1 || fields[0].Value != "scoped report text" || envelope.OmittedCount != 1 {
		t.Fatal("runtime read", fields, err)
	}
	for _, e := range []Envelope{otherSession, otherIdentity, otherBinding, input, legacy} {
		if fields, _, err := store.ReadRuntimeOutput("task", "identity", "session", "binding", e.RecordID, now); !errors.Is(err, ErrDenied) || len(fields) != 0 {
			t.Fatal("borrowed record accepted", err)
		}
	}
	if fields, _, err := store.ReadRuntimeOutput("other-task", "identity", "session", "binding", wanted.RecordID, now); err == nil || len(fields) != 0 {
		t.Fatal("cross-task read")
	}
	rows, err = store.ListMetadata("task", now)
	if err != nil || len(rows) != 6 {
		t.Fatal("legacy task listing changed", err)
	}
	if _, _, err := store.Read("task", legacy.RecordID, now); err != nil {
		t.Fatal("legacy read lost", err)
	}
	rows, err = store.ListRuntimeOutputs("task", "identity", "session", "binding", now.Add(time.Hour))
	if err != nil || len(rows) != 1 || rows[0].Status != "expired" {
		t.Fatal("expiry metadata", rows, err)
	}
	if fields, _, err := store.ReadRuntimeOutput("task", "identity", "session", "binding", wanted.RecordID, now.Add(time.Hour)); !errors.Is(err, ErrExpired) || len(fields) != 0 {
		t.Fatal("expired output readable", err)
	}
	if err := store.Delete("task", wanted.RecordID); err != nil {
		t.Fatal(err)
	}
	rows, err = store.ListRuntimeOutputs("task", "identity", "session", "binding", now)
	if err != nil || len(rows) != 0 {
		t.Fatal("deleted output returned", err)
	}
}

func TestRuntimeOutputSourceAuthenticatedAndNotGuessable(t *testing.T) {
	for _, mutation := range []string{"session", "identity", "binding", "missing", "downgrade"} {
		t.Run(mutation, func(t *testing.T) {
			dir, store, authority, _ := testAuthority(t, DefaultRetention)
			now := time.Now().UTC()
			grant, err := authority.Issue("private-task", []string{"output"}, "operator", time.Hour, time.Hour, 4096, now)
			if err != nil {
				t.Fatal(err)
			}
			permit, err := authority.IssueCapturePermit(grant.GrantID, grant.Signature, "private-identity", "private-session", "private-binding", "private-task", "output", now.Add(time.Hour), time.Minute, now)
			if err != nil {
				t.Fatal(err)
			}
			content, _ := Prepare("output", []Field{{Path: "/result", Value: "private-result"}})
			e, err := authority.CaptureWithPermit(permit, "private-identity", "private-session", "private-binding", "private-task", content, now)
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, "raw-task-content", e.RecordID+".json")
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if bytes.Contains(raw, []byte("private-")) {
				t.Fatal("source or content leaked")
			}
			switch mutation {
			case "session":
				e.Source.SessionRef = "sha256:" + strings.Repeat("a", 64)
			case "identity":
				e.Source.RuntimeIdentityRef = "sha256:" + strings.Repeat("b", 64)
			case "binding":
				e.Source.BindingRef = "sha256:" + strings.Repeat("c", 64)
			case "missing":
				e.Source = nil
			case "downgrade":
				e.Source = nil
				e.Schema = "local-raw-task-content-envelope/v1"
			}
			tampered, _ := json.Marshal(e)
			if err := os.WriteFile(path, tampered, 0600); err != nil {
				t.Fatal(err)
			}
			if fields, _, err := store.Read("private-task", e.RecordID, now); !errors.Is(err, ErrState) || len(fields) != 0 {
				t.Fatal("source tamper accepted", err)
			}
			if rows, err := store.ListRuntimeOutputs("private-task", "private-identity", "private-session", "private-binding", now); !errors.Is(err, ErrState) || rows != nil {
				t.Fatal("tamper silently filtered", err)
			}
		})
	}
}
