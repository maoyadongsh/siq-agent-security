package skillinstall

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func installedInspection(t *testing.T) (fixture, *Operation) {
	t.Helper()
	f, _, req := readyInstall(t)
	op, err := f.store.Apply(nil, req)
	if err != nil {
		t.Fatal(err)
	}
	return f, op
}
func TestInspectionSeparatesHistoricalRecordAndCurrentContents(t *testing.T) {
	for _, kind := range []string{"matched", "modified", "removed", "type_changed", "ownership_changed", "unknown_directory", "source_corrupt", "missing", "owner_missing"} {
		t.Run(kind, func(t *testing.T) {
			f, op := installedInspection(t)
			s := f.store
			target := filepath.Join(f.root, "skills", "example")
			entry := filepath.Join(target, "SKILL.md")
			wantState, wantChange := "changed", kind
			switch kind {
			case "matched":
				wantState = "matched"
			case "modified":
				write(t, entry, "changed")
			case "removed":
				if err := os.Remove(entry); err != nil {
					t.Fatal(err)
				}
			case "type_changed":
				if err := os.Remove(entry); err != nil {
					t.Fatal(err)
				}
				outside := filepath.Join(t.TempDir(), "outside")
				write(t, outside, "external content")
				if err := os.Symlink(outside, entry); err != nil {
					t.Fatal(err)
				}
			case "ownership_changed":
				raw, err := os.ReadFile(entry)
				if err != nil {
					t.Fatal(err)
				}
				if err := os.Remove(entry); err != nil {
					t.Fatal(err)
				}
				write(t, entry, string(raw))
			case "unknown_directory":
				write(t, filepath.Join(target, "untracked", "nested", "payload.sh"), "exit 77\n")
				wantChange = "added"
			case "source_corrupt":
				write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"), "bad source")
				wantState = "matched"
			case "missing":
				if err := os.Rename(target, target+"-retained"); err != nil {
					t.Fatal(err)
				}
				wantState = "missing"
				wantChange = "removed"
			case "owner_missing":
				if err := os.Remove(filepath.Join(target, ownerName)); err != nil {
					t.Fatal(err)
				}
				wantChange = "ownership_changed"
			}
			list, err := s.Catalog(nil)
			if err != nil || len(list.Items) != 1 || len(list.Issues) != 0 || list.Items[0].RecordedStatus != "installed_unverified" {
				t.Fatal(list, err)
			}
			beforeGrant, revision, err := s.authority.GetGrantWithSeq(f.request.GrantID)
			if err != nil {
				t.Fatal(err)
			}
			result, err := s.Inspect(nil, op.InstallID)
			if err != nil || result.TargetState != wantState || !result.ComparisonComplete || result.PlatformChanges || result.IssueCode != nil {
				t.Fatal(result, err)
			}
			if wantState == "matched" {
				if result.ChangesTotal != 0 || len(result.Changes) != 0 {
					t.Fatal(result)
				}
			} else {
				if result.ChangesTotal != 1 || len(result.Changes) != 1 || result.Changes[0].Change != wantChange {
					t.Fatal(result)
				}
			}
			afterGrant, afterRevision, err := s.authority.GetGrantWithSeq(f.request.GrantID)
			if err != nil || afterRevision != revision || afterGrant.Signature != beforeGrant.Signature {
				t.Fatal("inspection mutated authority", err)
			}
			if kind != "matched" && kind != "source_corrupt" {
				if _, err := s.ReadOperation(nil, op.InstallID); err == nil {
					t.Fatal("inspection weakened runtime target check")
				}
			}
		})
	}
}
func TestCatalogReportsCorruptAndOrphanRecordsWithoutTrustingBody(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	if err := os.Remove(s.operationPath(op.InstallID, "result")); err != nil {
		t.Fatal(err)
	}
	list, err := s.Catalog(nil)
	if err != nil || list.Items[0].RecordedStatus != "recovery_required" || list.Items[0].Operation != nil {
		t.Fatal(list, err)
	}
	write(t, s.operationPath(op.InstallID, "result"), `{"target_display":"untrusted"}`)
	list, err = s.Catalog(nil)
	if err != nil || len(list.Items) != 0 || len(list.Issues) != 1 || *list.Issues[0].InstallID != op.InstallID {
		t.Fatal(list, err)
	}
	if err := os.Remove(s.operationPath(op.InstallID, "claim")); err != nil {
		t.Fatal(err)
	}
	list, err = s.Catalog(nil)
	if err != nil || len(list.Items) != 0 || len(list.Issues) != 1 {
		t.Fatal("orphan hidden", list, err)
	}
	if _, err := s.Inspect(nil, op.InstallID); err == nil {
		t.Fatal("untrusted history accepted")
	}
	for i := 0; i < 64; i++ {
		write(t, s.operationPath(fmt.Sprintf("sin-%064x", i), "result"), "{}")
	}
	if _, err := s.Catalog(nil); !errors.Is(err, ErrLimit) {
		t.Fatal("catalog overflow", err)
	}
}
func TestInspectionBudgetsTruncationAndEscapedNames(t *testing.T) {
	f, op := installedInspection(t)
	target := filepath.Join(f.root, "skills", "example")
	for i := 0; i < maxInspectionEntries-3; i++ {
		write(t, filepath.Join(target, fmt.Sprintf("extra-%05d", i)), "")
	}
	r, err := f.store.Inspect(nil, op.InstallID)
	if err != nil || r.TargetState != "changed" || !r.ComparisonComplete || !r.ChangesTruncated || len(r.Changes) != maxInspectionChanges || r.ChangesTotal != maxInspectionEntries-3 {
		t.Fatal(r, err)
	}
	write(t, filepath.Join(target, "one-more"), "")
	r, err = f.store.Inspect(nil, op.InstallID)
	if err != nil || r.TargetState != "unavailable" || r.ComparisonComplete || r.IssueCode == nil || *r.IssueCode != "comparison_budget_exceeded" {
		t.Fatal(r, err)
	}
	escaped := Inspection{Changes: []ContentChange{}}
	escaped.add("line\nbreak", "file", "added")
	if strings.Contains(escaped.Changes[0].PathDisplay, "\n") || escaped.Changes[0].PathDigest != hash([]byte("line\nbreak")) {
		t.Fatal(escaped)
	}
	escaped.add(strings.Repeat("x", 1200), "file", "added")
	if len([]rune(escaped.Changes[1].PathDisplay)) > 1024 {
		t.Fatal("unbounded display")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.store.Inspect(ctx, op.InstallID); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if _, err := f.store.Catalog(ctx); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
}
func TestInstallationInspectionContractSamples(t *testing.T) {
	f, op := installedInspection(t)
	f.store.now = func() time.Time { return time.Date(2026, 9, 11, 4, 0, 0, 0, time.UTC) }
	list, err := f.store.Catalog(nil)
	if err != nil {
		t.Fatal(err)
	}
	inspection, err := f.store.Inspect(nil, op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-install-view.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var view View
	if err := json.Unmarshal(raw, &view); err != nil {
		t.Fatal(err)
	}
	// Reuse the signed synthetic historical record; real target comparison was
	// performed above and its matched result is retained without extra claims.
	record := Record{"local-skill-install-record/v1", view.InstallID, view.Plan, view.ClaimSignature, view.Status, view.Operation}
	list.Items = []Record{record}
	inspection.Record = record
	for name, value := range map[string]any{"record": record, "catalog": list, "inspection": inspection} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/local-skill-install-" + name + ".v1.sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(expected) != string(raw) {
			t.Fatal("inspection sample differs", name, err)
		}
	}
}
